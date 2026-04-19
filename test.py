"""
Poll Zalo Mini Bot (bot.zapps.me) và gọi API local (upload + poll /result).

Chạy:
  export ZALO_BOT_TOKEN=...
  export API_BASE_URL=http://localhost:8080   # optional
  python test.py

Lệnh user gửi qua Zalo (text):
  health          — kiểm tra API /health
  poll <uuid>     — chỉ poll GET /result/<uuid> đến khi xong hoặc timeout
  <URL ảnh http>  — tải ảnh, POST /upload (kèm condition/size/price từ env), rồi poll /result

Biến env tùy chọn (mặc định cho upload):
  UPLOAD_CONDITION, UPLOAD_SIZE, UPLOAD_PRICE
  POLL_INTERVAL_SEC (mặc định 2), POLL_TIMEOUT_SEC (mặc định 120)
  ZALO_HTTP_RETRIES (mặc định 5), ZALO_HTTP_BACKOFF_SEC (mặc định 3)

Lỗi HTTP 500 từ https://bot.zapps.me/api/getUpdates: do phía máy chủ Zalo hoặc token/sản phẩm OA
không hợp lệ — script chỉ retry và in body phản hồi để bạn đối chiếu tài liệu Zalo Mini Bot.
"""

from __future__ import annotations

import os
import re
import time

import dotenv
import httpx

dotenv.load_dotenv()

TOKEN = os.getenv("ZALO_BOT_TOKEN")
if not TOKEN:
    raise SystemExit("Thiếu ZALO_BOT_TOKEN trong .env hoặc môi trường")

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8080").rstrip("/")
SEND_API = "https://bot.zapps.me/api/sendMessage"
GET_UPDATES = "https://bot.zapps.me/api/getUpdates"

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL_SEC", "2"))
POLL_TIMEOUT = float(os.getenv("POLL_TIMEOUT_SEC", "120"))
ZALO_HTTP_RETRIES = int(os.getenv("ZALO_HTTP_RETRIES", "5"))
ZALO_HTTP_BACKOFF = float(os.getenv("ZALO_HTTP_BACKOFF_SEC", "3"))

DEFAULT_CONDITION = os.getenv("UPLOAD_CONDITION", "90%")
DEFAULT_SIZE = os.getenv("UPLOAD_SIZE", "40x55cm")
DEFAULT_PRICE = os.getenv("UPLOAD_PRICE", "60000 VND")

# N8N webhook cũ — chỉ dùng nếu bật USE_N8N_WEBHOOK=1
N8N_WEBHOOK = os.getenv("N8N_WEBHOOK_URL", "")
USE_N8N = os.getenv("USE_N8N_WEBHOOK", "").lower() in ("1", "true", "yes")


def get_updates(offset: int | None = None) -> dict:
    """Gọi API Zalo. HTTP 5xx thường là lỗi phía bot.zapps.me hoặc token / cấu hình OA."""
    params = {"token": TOKEN}
    if offset is not None:
        params["offset"] = offset

    backoff = ZALO_HTTP_BACKOFF
    last_detail = ""

    for attempt in range(1, ZALO_HTTP_RETRIES + 1):
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.get(GET_UPDATES, params=params)
                last_detail = f"HTTP {r.status_code} body={r.text[:800]!r}"

                if 500 <= r.status_code < 600:
                    print(
                        f"[getUpdates] lỗi server Zalo ({r.status_code}), "
                        f"lần {attempt}/{ZALO_HTTP_RETRIES}: {r.text[:400]!r}"
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 1.5, 60.0)
                    continue

                r.raise_for_status()
                return r.json()
        except httpx.RequestError as exc:
            last_detail = str(exc)
            print(f"[getUpdates] lỗi mạng lần {attempt}/{ZALO_HTTP_RETRIES}: {exc}")
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)

    print(
        "[getUpdates] hết số lần thử. Kiểm tra: token Zalo OA đúng chưa, "
        "dịch vụ bot.zapps.me có đang lỗi không, token có bị thừa khoảng trắng/xuống dòng không.\n"
        f"Chi tiết cuối: {last_detail}"
    )
    return {"result": []}


def send_message(chat_id: str | int, text: str) -> None:
    with httpx.Client(timeout=30.0) as client:
        client.post(
            SEND_API,
            json={"token": TOKEN, "chat_id": chat_id, "text": text[:4000]},
        )


def api_health() -> str:
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{API_BASE}/health")
        return f"HTTP {r.status_code}: {r.text[:500]}"


def poll_result(request_id: str) -> str:
    deadline = time.monotonic() + POLL_TIMEOUT
    with httpx.Client(timeout=30.0) as client:
        while time.monotonic() < deadline:
            r = client.get(f"{API_BASE}/result/{request_id}")
            if r.status_code == 404:
                return f"404: {r.text[:500]}"

            try:
                data = r.json()
            except Exception:
                return f"HTTP {r.status_code}: {r.text[:1000]}"

            if r.status_code == 200 and "product_name" in data:
                return str(data)

            if r.status_code == 202:
                if data.get("status") == "needs_input":
                    return str(data)
                if data.get("status") == "processing":
                    time.sleep(POLL_INTERVAL)
                    continue

            return f"HTTP {r.status_code}: {r.text[:1000]}"

    return f"Timeout sau {POLL_TIMEOUT}s khi poll result/{request_id}"


def upload_image_bytes(image_bytes: bytes, filename: str = "image.jpg") -> str:
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            f"{API_BASE}/upload",
            files={"file": (filename, image_bytes, "image/jpeg")},
            data={
                "condition": DEFAULT_CONDITION,
                "size": DEFAULT_SIZE,
                "price": DEFAULT_PRICE,
            },
        )
        r.raise_for_status()
        body = r.json()
        rid = body.get("request_id")
        if not rid:
            return f"Lỗi upload: {body}"
        if body.get("status") == "needs_input":
            return f"needs_input: {body.get('missing_fields')} — bổ sung qua POST /input/{{id}}"
        return poll_result(rid)


def download_image(url: str) -> tuple[bytes, str]:
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        name = "image.jpg"
        cd = r.headers.get("content-disposition", "")
        m = re.search(r'filename="?([^";]+)"?', cd)
        if m:
            name = m.group(1)[:200]
        return r.content, name


def try_image_url(text: str) -> str | None:
    text = text.strip()
    if not text.startswith("http"):
        return None
    if not re.match(r"^https?://", text, re.I):
        return None
    try:
        data, name = download_image(text)
        return upload_image_bytes(data, filename=name)
    except Exception as e:
        return f"Tải/upload ảnh lỗi: {e}"


def handle_n8n(chat_id: str | int, text: str | None) -> str:
    if not N8N_WEBHOOK:
        return "Chưa cấu hình N8N_WEBHOOK_URL"
    with httpx.Client(timeout=30.0) as client:
        r = client.post(N8N_WEBHOOK, json={"chat_id": chat_id, "text": text})
        try:
            return r.json().get("reply", r.text[:500])
        except Exception:
            return r.text[:500]


def handle_text(chat_id: str | int, text: str | None) -> str:
    if not text or not text.strip():
        return "Gửi: health | poll <request_id> | URL ảnh (http...)"

    t = text.strip()

    if t.lower() == "health":
        return api_health()

    if t.lower().startswith("poll "):
        rid = t[5:].strip()
        if not rid:
            return "Dùng: poll <request_id>"
        return poll_result(rid)

    img_reply = try_image_url(t)
    if img_reply is not None:
        return img_reply

    if USE_N8N:
        return handle_n8n(chat_id, text)

    return (
        "Không hiểu lệnh. Gửi:\n"
        "- health\n"
        "- poll <request_id>\n"
        "- URL ảnh trực tiếp (http...)\n"
        f"(upload dùng condition={DEFAULT_CONDITION}, size={DEFAULT_SIZE}, price={DEFAULT_PRICE})"
    )


def main() -> None:
    last_update_id: int | None = None

    while True:
        try:
            data = get_updates(last_update_id)

            for item in data.get("result", []):
                update_id = item.get("update_id")
                message = item.get("message") or {}
                chat_id = (message.get("chat") or {}).get("id")
                text = message.get("text")

                if chat_id is None:
                    continue

                print("Update:", update_id, "chat:", chat_id, "text:", text)

                try:
                    response_text = handle_text(chat_id, text)
                except Exception as e:
                    response_text = f"Lỗi: {e}"

                send_message(chat_id, response_text)

                if update_id is not None:
                    last_update_id = int(update_id) + 1

        except Exception as e:
            print("Error:", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

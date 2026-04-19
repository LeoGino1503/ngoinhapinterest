import json
import os
import uuid
import base64
from io import BytesIO
from typing import Optional

import httpx
import redis
import yaml
from fastapi import HTTPException, UploadFile
from minio import Minio
from PIL import Image

from src.schemas import AnalyzeRequest, AnalyzeResponse, CallbackPayload, UploadResponse, UserInputPayload


def load_config():
    config_path = os.getenv("APP_CONFIG_PATH", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


config = load_config()
redis_client = redis.Redis(
    host=config["redis"]["host"],
    port=config["redis"]["port"],
    db=config["redis"]["db"],
)
minio_client = Minio(
    endpoint=config["storage"]["endpoint"].replace("http://", "").replace("https://", ""),
    access_key=os.getenv("MINIO_ROOT_USER"),
    secret_key=os.getenv("MINIO_ROOT_PASSWORD"),
    secure=config["storage"]["endpoint"].startswith("https"),
)
bucket_name = config["storage"]["bucket"]
result_ttl = config["redis"]["ttl_seconds"]


def healthcheck() -> dict:
    try:
        redis_client.ping()
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def ensure_bucket() -> None:
    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)


def normalize_user_input(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def missing_input_fields(data: dict) -> list[str]:
    required_fields = ("condition", "size", "price")
    return [field for field in required_fields if not data.get(field)]


async def trigger_n8n(payload: dict) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{config['app']['base_url'].replace('api:8080', 'n8n:5678')}/webhook/ngoinha-process",
            json=payload,
            timeout=10.0,
        )


def resolve_ai_provider() -> str:
    ai_config = config.get("ai", {})
    openai_enabled = ai_config.get("openai", {}).get("enabled", False)
    gemini_enabled = ai_config.get("gemini", {}).get("enabled", False)

    if openai_enabled and gemini_enabled:
        raise HTTPException(status_code=500, detail="Only one AI provider can be enabled at a time")
    if openai_enabled:
        return "openai"
    if gemini_enabled:
        return "gemini"
    raise HTTPException(status_code=500, detail="No API provider enabled. Enable openai or gemini in config.yaml")


def describe_colors(pil_image: Image.Image) -> list[str]:
    def rgb_to_name(color):
        r, g, b = color
        if r > 200 and g > 200 and b > 200:
            return "white"
        if r < 60 and g < 60 and b < 60:
            return "black"
        if r > g and r > b:
            return "red"
        if g > r and g > b:
            return "green"
        if b > r and b > g:
            return "blue"
        if r > 180 and g > 180:
            return "yellow"
        return "pink"

    rgb_image = pil_image.convert("RGB")
    small_image = rgb_image.resize((120, 120))
    quantized = small_image.quantize(colors=5, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()
    dominant = sorted(quantized.getcolors(), reverse=True) if quantized.getcolors() else []

    names = []
    for _, color_idx in dominant:
        base = color_idx * 3
        rgb = tuple(palette[base : base + 3])
        name = rgb_to_name(rgb)
        if name not in names:
            names.append(name)
    return names[:2]


async def generate_caption_openai(image_bytes: bytes) -> str:
    openai_cfg = config.get("ai", {}).get("openai", {})
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is missing")

    endpoint = openai_cfg.get("endpoint", "https://api.openai.com/v1/responses")
    model = openai_cfg.get("model", "gpt-4o-mini")
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Describe this product image for resale caption."},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_b64}"},
                ],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(endpoint, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {resp.text}")
    data = resp.json()
    try:
        return data["output"][0]["content"][0]["text"]
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid response format from OpenAI")


async def generate_caption_gemini(image_bytes: bytes) -> str:
    gemini_cfg = config.get("ai", {}).get("gemini", {})
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is missing")

    endpoint = gemini_cfg.get(
        "endpoint",
        "https://generativelanguage.googleapis.com/v1beta/models",
    )
    model = gemini_cfg.get("model", "gemini-2.5-flash")
    url = f"{endpoint}/{model}:generateContent?key={api_key}"
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": "Describe this product image for resale caption."},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                ]
            }
        ]
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Gemini error: {resp.text}")
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid response format from Gemini")


async def generate_caption_from_provider(image_bytes: bytes) -> str:
    provider = resolve_ai_provider()
    if provider == "openai":
        return await generate_caption_openai(image_bytes)
    if provider == "gemini":
        return await generate_caption_gemini(image_bytes)
    raise HTTPException(status_code=500, detail="Unsupported AI provider")


async def analyze_image(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        response = minio_client.get_object(bucket_name=req.bucket, object_name=req.object_name)
        data = response.read()
        response.close()
        response.release_conn()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch image from MinIO: {exc}")

    try:
        pil_image = Image.open(BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image data: {exc}")

    colors = describe_colors(pil_image)
    caption_text = await generate_caption_from_provider(data)

    caption = (
        f"{caption_text}\n"
        f"Colors: {', '.join(colors)}\n"
        f"Condition: {req.condition}\n"
        f"Size: {req.size}\n"
        f"Price: {req.price}"
    )
    return AnalyzeResponse(object=caption_text, colors=colors, confidence=0.0, captionDraft=caption)


async def create_upload(file: UploadFile, condition: Optional[str], size: Optional[str], price: Optional[str]) -> UploadResponse:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    ensure_bucket()
    request_id = str(uuid.uuid4())
    object_name = f"uploads/{request_id}_{file.filename}"
    file_bytes = await file.read()
    data_stream = BytesIO(file_bytes)
    minio_client.put_object(
        bucket_name=bucket_name,
        object_name=object_name,
        data=data_stream,
        length=len(file_bytes),
        content_type=file.content_type,
    )

    payload = {
        "request_id": request_id,
        "bucket": bucket_name,
        "object_name": object_name,
        "condition": normalize_user_input(condition),
        "size": normalize_user_input(size),
        "price": normalize_user_input(price),
    }
    missing_fields = missing_input_fields(payload)
    redis_client.setex(f"input:{request_id}", result_ttl, json.dumps(payload))
    if missing_fields:
        redis_client.setex(f"status:{request_id}", result_ttl, "needs_input")
        return UploadResponse(request_id=request_id, status="needs_input", missing_fields=missing_fields)

    try:
        await trigger_n8n(payload)
        redis_client.setex(f"status:{request_id}", result_ttl, "processing")
    except Exception:
        redis_client.setex(f"status:{request_id}", result_ttl, "orchestration_failed")
        raise HTTPException(status_code=502, detail="Failed to trigger workflow")

    return UploadResponse(request_id=request_id, status="processing", missing_fields=[])


def get_result_or_status(request_id: str):
    status = redis_client.get(f"status:{request_id}")
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown request_id")

    current_status = status.decode()
    if current_status == "done":
        raw = redis_client.get(f"result:{request_id}")
        if raw is None:
            raise HTTPException(status_code=404, detail="Result missing")
        return {"done": True, "data": json.loads(raw)}
    if current_status == "needs_input":
        raw_input = redis_client.get(f"input:{request_id}")
        current_input = json.loads(raw_input) if raw_input else {}
        return {
            "done": False,
            "status": "needs_input",
            "missing_fields": missing_input_fields(current_input),
            "message": "Please provide missing product info: condition, size, price",
        }
    return {"done": False, "status": current_status}


async def provide_missing_input(request_id: str, payload: UserInputPayload) -> dict:
    status = redis_client.get(f"status:{request_id}")
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown request_id")
    if status.decode() == "done":
        return {"status": "done", "message": "Request already processed"}

    raw_input = redis_client.get(f"input:{request_id}")
    if raw_input is None:
        raise HTTPException(status_code=404, detail="Input context missing")

    current_input = json.loads(raw_input)
    for key, value in payload.dict().items():
        normalized = normalize_user_input(value)
        if normalized is not None:
            current_input[key] = normalized

    missing_fields = missing_input_fields(current_input)
    redis_client.setex(f"input:{request_id}", result_ttl, json.dumps(current_input))
    if missing_fields:
        redis_client.setex(f"status:{request_id}", result_ttl, "needs_input")
        return {"status": "needs_input", "missing_fields": missing_fields}

    try:
        await trigger_n8n(current_input)
        redis_client.setex(f"status:{request_id}", result_ttl, "processing")
    except Exception:
        redis_client.setex(f"status:{request_id}", result_ttl, "orchestration_failed")
        raise HTTPException(status_code=502, detail="Failed to trigger workflow")

    return {"status": "processing", "request_id": request_id}


def save_callback(payload: CallbackPayload) -> dict:
    redis_client.setex(f"status:{payload.request_id}", result_ttl, "done")
    redis_client.setex(f"result:{payload.request_id}", result_ttl, json.dumps(payload.dict()))
    return {"ok": True}

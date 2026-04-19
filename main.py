import os
import secrets

from fastapi import FastAPI, File, Form, Request, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from src.schemas import AnalyzeRequest, AnalyzeResponse, CallbackPayload, ResultResponse, UploadResponse, UserInputPayload
from src.services import analyze_image, create_upload, get_result_or_status, healthcheck, provide_missing_input, save_callback
from src.handler.handler import *
from src.services import config
app = FastAPI(title="Ngoinha API")

@app.post("/webhooks/zalo/incoming")
async def zalo_incoming(request: Request):
    """
    Webhook Zalo Bot Platform (setWebhook).
    Khi gọi setWebhook với secret_token, mọi request tới URL này kèm header:
    X-Bot-Api-Secret-Token: <secret_token>
    So khớp với biến môi trường ZALO_WEBHOOK_SECRET (ví dụ mykey-abcyxz).
    """
    if not config["features"]["enable_zalo_webhooks"]:
        raise HTTPException(status_code=404, detail="Zalo disabled")

    expected = (os.getenv("ZALO_WEBHOOK_SECRET") or "").strip()
    if expected:
        token = request.headers.get("x-bot-api-secret-token") or request.headers.get(
            "X-Bot-Api-Secret-Token"
        )
        if not token or not secrets.compare_digest(token.strip(), expected):
            raise HTTPException(status_code=403, detail="Invalid or missing X-Bot-Api-Secret-Token")

    try:
        body = await request.json()
        handle_zalo_incoming(body)
    except Exception:
        body = {}

    return {"ok": True, "received": body}


@app.post("/webhooks/zalo/outgoing")
async def zalo_outgoing(request: Request):
    if not config["features"]["enable_zalo_webhooks"]:
        raise HTTPException(status_code=404, detail="Zalo disabled")

    expected = (os.getenv("ZALO_WEBHOOK_SECRET") or "").strip()
    if expected:
        token = request.headers.get("x-bot-api-secret-token") or request.headers.get(
            "X-Bot-Api-Secret-Token"
        )
        if not token or not secrets.compare_digest(token.strip(), expected):
            raise HTTPException(status_code=403, detail="Invalid or missing X-Bot-Api-Secret-Token")

    try:
        body = await request.json()
    except Exception:
        body = {}

    return {"ok": True, "echo": body}


@app.get("/health", tags=["Monitoring"])
def health():
    return healthcheck()


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    return await analyze_image(req)


@app.post("/upload", response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    condition: str | None = Form(default=None),
    size: str | None = Form(default=None),
    price: str | None = Form(default=None),
):
    return await create_upload(file=file, condition=condition, size=size, price=price)


@app.get("/result/{request_id}", response_model=ResultResponse | None)
def get_result(request_id: str):
    result = get_result_or_status(request_id)
    if result.get("done"):
        return ResultResponse(**result["data"])
    if result.get("status") == "needs_input":
        return JSONResponse(
            {
                "status": "needs_input",
                "missing_fields": result["missing_fields"],
                "message": result["message"],
            },
            status_code=202,
        )
    return JSONResponse({"status": result["status"]}, status_code=202)


@app.post("/input/{request_id}")
async def provide_input(request_id: str, payload: UserInputPayload):
    return await provide_missing_input(request_id=request_id, payload=payload)


@app.post("/callback/result")
def callback_result(payload: CallbackPayload):
    return save_callback(payload)



from typing import List, Optional

from pydantic import BaseModel


class UploadResponse(BaseModel):
    request_id: str
    status: str
    missing_fields: list[str] = []


class ResultResponse(BaseModel):
    product_name: str
    condition: str
    size: str
    price: str
    colors: list[str]
    caption: str


class AnalyzeRequest(BaseModel):
    bucket: str
    object_name: str
    request_id: str
    condition: str
    size: str
    price: str


class AnalyzeResponse(BaseModel):
    object: str
    colors: List[str]
    confidence: float
    captionDraft: str


class UserInputPayload(BaseModel):
    condition: Optional[str] = None
    size: Optional[str] = None
    price: Optional[str] = None


class CallbackPayload(BaseModel):
    request_id: str
    product_name: str
    condition: str
    size: str
    price: str
    colors: list[str]
    caption: str

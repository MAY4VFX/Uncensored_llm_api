import uuid
from datetime import datetime

from pydantic import BaseModel


class ModelResponse(BaseModel):
    id: uuid.UUID
    slug: str
    display_name: str
    hf_repo: str
    params_b: float
    quantization: str
    gpu_type: str
    gpu_count: int = 1
    max_context_length: int
    status: str
    cost_per_1m_input: float
    cost_per_1m_output: float
    description: str | None
    system_prompt: str | None = None
    hf_downloads: int | None = None
    hf_likes: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateModelRequest(BaseModel):
    slug: str
    display_name: str
    hf_repo: str
    params_b: float
    quantization: str = "Q4"
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0
    description: str | None = None


class AddFromHfRequest(BaseModel):
    hf_repo: str


class UpdateModelRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    gpu_type: str | None = None
    gpu_count: int | None = None
    max_context_length: int | None = None
    system_prompt: str | None = None


class UpdateModelStatusRequest(BaseModel):
    status: str

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
    status: str
    cost_per_1m_input: float
    cost_per_1m_output: float
    description: str | None
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


class UpdateModelStatusRequest(BaseModel):
    status: str

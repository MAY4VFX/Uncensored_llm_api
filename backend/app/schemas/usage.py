from datetime import datetime

from pydantic import BaseModel


class UsageLogEntry(BaseModel):
    model_slug: str
    tokens_in: int
    tokens_out: int
    gpu_seconds: float = 0.0
    cost: float
    created_at: datetime


class UsageSummary(BaseModel):
    total_tokens_in: int
    total_tokens_out: int
    total_gpu_seconds: float
    total_cost: float
    credits_remaining: float
    recent_usage: list[UsageLogEntry]

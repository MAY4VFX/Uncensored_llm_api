from datetime import datetime

from pydantic import BaseModel


class UsageLogEntry(BaseModel):
    model_slug: str
    tokens_in: int
    tokens_out: int
    cost: float
    created_at: datetime


class UsageSummary(BaseModel):
    total_tokens_in: int
    total_tokens_out: int
    total_cost: float
    credits_remaining: float
    recent_usage: list[UsageLogEntry]

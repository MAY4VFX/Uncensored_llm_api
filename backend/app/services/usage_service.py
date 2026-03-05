import uuid

import tiktoken
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage_log import UsageLog


def count_tokens(text: str, model: str = "gpt-4") -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def count_message_tokens(messages: list[dict], model: str = "gpt-4") -> int:
    total = 0
    for msg in messages:
        total += 4  # message overhead
        total += count_tokens(msg.get("content", ""), model)
        total += count_tokens(msg.get("role", ""), model)
    total += 2  # reply priming
    return total


def calculate_cost(
    tokens_in: int, tokens_out: int, cost_per_1m_input: float, cost_per_1m_output: float
) -> float:
    """Legacy token-based cost calculation (kept for backward compat)."""
    return (tokens_in / 1_000_000 * cost_per_1m_input) + (tokens_out / 1_000_000 * cost_per_1m_output)


def calculate_gpu_cost(
    gpu_seconds: float, gpu_hourly_cost: float, margin_multiplier: float = 1.5
) -> float:
    """Calculate cost based on actual GPU time.

    cost = gpu_seconds * (gpu_hourly_cost / 3600) * margin_multiplier
    """
    if gpu_seconds <= 0 or gpu_hourly_cost <= 0:
        return 0.0
    return gpu_seconds * (gpu_hourly_cost / 3600.0) * margin_multiplier


def estimate_max_cost(
    max_tokens: int, gpu_hourly_cost: float, margin_multiplier: float = 1.5,
    tokens_per_second: float = 30.0,
) -> float:
    """Estimate maximum possible cost for pre-authorization.

    Conservative estimate: assumes model generates all max_tokens at given throughput.
    """
    if max_tokens <= 0 or gpu_hourly_cost <= 0:
        return 0.0
    estimated_seconds = max_tokens / tokens_per_second
    return calculate_gpu_cost(estimated_seconds, gpu_hourly_cost, margin_multiplier)


async def log_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    api_key_id: uuid.UUID | None,
    model_id: uuid.UUID,
    tokens_in: int,
    tokens_out: int,
    cost: float,
    gpu_seconds: float = 0.0,
) -> UsageLog:
    log = UsageLog(
        user_id=user_id,
        api_key_id=api_key_id,
        model_id=model_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        gpu_seconds=gpu_seconds,
        cost=cost,
    )
    db.add(log)
    await db.commit()
    return log

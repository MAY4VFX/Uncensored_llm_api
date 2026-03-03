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
    return (tokens_in / 1_000_000 * cost_per_1m_input) + (tokens_out / 1_000_000 * cost_per_1m_output)


async def log_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    api_key_id: uuid.UUID,
    model_id: uuid.UUID,
    tokens_in: int,
    tokens_out: int,
    cost: float,
) -> UsageLog:
    log = UsageLog(
        user_id=user_id,
        api_key_id=api_key_id,
        model_id=model_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
    )
    db.add(log)
    await db.commit()
    return log

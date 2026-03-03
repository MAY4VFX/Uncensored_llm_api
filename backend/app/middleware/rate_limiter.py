import time

import redis.asyncio as redis

from app.config import settings

_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


TIER_LIMITS = {
    "free": settings.rate_limit_free,
    "starter": settings.rate_limit_starter,
    "pro": settings.rate_limit_pro,
    "business": settings.rate_limit_business,
}


async def check_rate_limit(api_key_id: str, tier: str) -> tuple[bool, int]:
    """
    Sliding window rate limiter using Redis sorted sets.
    Returns (allowed: bool, retry_after_seconds: int).
    """
    r = await get_redis()
    limit = TIER_LIMITS.get(tier, settings.rate_limit_free)
    window = 60  # 1 minute
    now = time.time()
    key = f"ratelimit:{api_key_id}"

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window)
    results = await pipe.execute()

    count = results[2]
    if count > limit:
        # Calculate retry-after
        oldest = await r.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = int(window - (now - oldest[0][1])) + 1
        else:
            retry_after = window
        return False, retry_after

    return True, 0

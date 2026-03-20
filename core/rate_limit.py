import time

from redis.asyncio import Redis


async def check_rate_limit(
    redis: Redis,
    key: str,
    limit: int,
    window_seconds: int = 60,
) -> bool:
    """Sliding window using a Redis sorted set. Safe for distributed deployments."""
    now = time.time()
    window_start = now - window_seconds
    full_key = f"rl:{key}"

    pipe = redis.pipeline()
    pipe.zremrangebyscore(full_key, 0, window_start)
    pipe.zcard(full_key)
    # member must be unique; use microsecond timestamp as both score and member
    pipe.zadd(full_key, {str(now): now})
    pipe.expire(full_key, window_seconds + 1)
    results = await pipe.execute()

    count = results[1]
    return count < limit


async def rate_limit_remaining(
    redis: Redis,
    key: str,
    limit: int,
    window_seconds: int = 60,
) -> int:
    now = time.time()
    window_start = now - window_seconds
    full_key = f"rl:{key}"
    await redis.zremrangebyscore(full_key, 0, window_start)
    count = await redis.zcard(full_key)
    return max(0, limit - count)


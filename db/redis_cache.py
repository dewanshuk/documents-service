import json
import os
import time
from typing import Any

_redis = None
_memory_cache: dict[str, tuple[float, Any]] = {}


async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None

    try:
        import redis.asyncio as redis

        _redis = redis.from_url(redis_url, decode_responses=True)
        await _redis.ping()
        return _redis
    except Exception:
        _redis = None
        return None


async def cache_set(key: str, value: dict, ttl: int = 3600):
    client = await _get_redis()
    if client:
        await client.set(key, json.dumps(value, default=str), ex=ttl)
        return

    _memory_cache[key] = (time.time() + ttl, value)


async def cache_get(key: str):
    client = await _get_redis()
    if client:
        raw = await client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    entry = _memory_cache.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        _memory_cache.pop(key, None)
        return None
    return value


async def cache_delete(key: str):
    client = await _get_redis()
    if client:
        await client.delete(key)
    _memory_cache.pop(key, None)


async def cache_delete_pattern(prefix: str):
    client = await _get_redis()
    if client:
        keys = [key async for key in client.scan_iter(match=f"{prefix}*")]
        if keys:
            await client.delete(*keys)

    to_remove = [k for k in _memory_cache if k.startswith(prefix)]
    for key in to_remove:
        _memory_cache.pop(key, None)


async def close_redis():
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
    _memory_cache.clear()

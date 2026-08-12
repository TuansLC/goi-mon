"""Async Redis client dependency for FastAPI.

Provides a request-scoped Redis connection via ``get_redis()``.
The connection pool is shared process-wide and created lazily on first use.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from qorder_api.config import get_settings

_pool: aioredis.ConnectionPool | None = None


def _get_pool() -> aioredis.ConnectionPool:
    """Return or create the process-wide connection pool."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency yielding an async Redis client scoped to a request."""
    client = aioredis.Redis(connection_pool=_get_pool())
    try:
        yield client
    finally:
        await client.aclose()

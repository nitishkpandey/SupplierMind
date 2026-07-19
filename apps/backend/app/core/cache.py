"""Redis-compatible async cache abstraction with in-memory fallback.

USAGE:
    from app.core.cache import get_cache
    cache = get_cache()

    await cache.set("my_key", "my_value", ttl=3600)  # expires in 1 hour
    value = await cache.get("my_key")                # returns "my_value" or None
    await cache.delete("my_key")
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseCache(ABC):
    """Abstract cache interface — same API for Redis and in-memory."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Get a value. Returns None if not found or expired."""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set a value with TTL in seconds."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a key."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        ...


class InMemoryCache(BaseCache):
    """Process-local cache used when Redis is unavailable or LITE_MODE is on."""

    def __init__(self) -> None:
        # {key: (value, expiry_timestamp)}
        self._store: dict[str, tuple[Any, float]] = {}
        logger.info("Using in-memory cache (no Redis)")

    def _is_expired(self, key: str) -> bool:
        if key not in self._store:
            return True
        _, expiry = self._store[key]
        return time.time() > expiry

    async def get(self, key: str) -> Any | None:
        if self._is_expired(key):
            self._store.pop(key, None)
            return None
        value, _ = self._store[key]
        return value

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        self._store[key] = (value, time.time() + ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return not self._is_expired(key)


class RedisCache(BaseCache):
    """Redis-backed cache shared across backend processes."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client
        logger.info("Using Redis cache")

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning("Redis GET failed for key=%s: %s", key, e)
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        try:
            await self._redis.setex(key, ttl, json.dumps(value))
        except Exception as e:
            logger.warning("Redis SET failed for key=%s: %s", key, e)

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception as e:
            logger.warning("Redis DELETE failed for key=%s: %s", key, e)

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self._redis.exists(key))
        except Exception:
            return False


# Module-level cache instance (initialized in main.py lifespan)
_cache_instance: BaseCache | None = None


def set_cache_instance(cache: BaseCache) -> None:
    """Called during app startup to set the cache implementation."""
    global _cache_instance
    _cache_instance = cache


def get_cache() -> BaseCache:
    """
    Returns the active cache instance.
    Raises if called before app startup (cache not initialized).
    """
    if _cache_instance is None:
        raise RuntimeError(
            "Cache not initialized. "
            "This should be called after app startup."
        )
    return _cache_instance

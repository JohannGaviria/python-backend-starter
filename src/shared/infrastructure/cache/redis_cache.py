import json
from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis, RedisError

from src.shared.domain.exceptions.exception import (
    CacheException,
    CacheUnavailableException,
)
from src.shared.infrastructure.logging.structlog_logger import StructlogLogger

_logger = StructlogLogger(__name__)


class RedisCache[CacheValueType]:
    """Stores dictionaries in Redis and rebuilds them into domain objects.

    The Redis client and the deserialization factory are injected, so the same
    adapter works in development and in tests. Because the factory is fixed per
    instance, create one instance per cached type.

    Usage::

        redis_cache = RedisCache(redis_client=redis_client.client, factory=Book.from_dict)
        book = await redis_cache.get("book:1")
        await redis_cache.set("book:1", {"id": "1", "title": "Dune"}, ttl_seconds=60)
        await redis_cache.delete("book:catalog")
    """

    def __init__(
        self,
        redis_client: Redis,
        factory: Callable[[dict[str, Any]], CacheValueType],
    ) -> None:
        """Initialize the cache adapter.

        Args:
            redis_client (Redis): The Redis client used for cache operations.
            factory (Callable[[dict[str, Any]], CacheValueType]): Rebuilds a
                dictionary coming from Redis into an instance of CacheValueType.
        """
        self._redis_client = redis_client
        self._factory = factory

    async def get(self, key: str) -> CacheValueType | None:
        """Retrieve a cache entry from Redis.

        Args:
            key (str): The cache key of the entry to retrieve.

        Returns:
            CacheValueType | None: The value associated with the cache key if
                found, otherwise None.

        Raises:
            CacheException: If the stored value is not valid JSON, if Redis fails,
                or if the value cannot be rebuilt into CacheValueType.
        """
        try:
            value = await self._redis_client.get(key)
            if value is None:
                _logger.debug("Cache entry not found.", key=key)
                return None

            cache_value = self._factory(json.loads(value))

            _logger.debug("Cache entry retrieved.", key=key)

            return cache_value
        except json.JSONDecodeError as exc:
            _logger.error("Cache entry is not valid JSON.", key=key, exc_info=True)
            raise CacheException(
                detail=f"Cache entry is not valid JSON. Original error: {exc}",
                key=key,
            ) from exc
        except RedisError as exc:
            _logger.error(
                "Redis error while reading cache entry.", key=key, exc_info=True
            )
            raise CacheUnavailableException(
                detail=f"Redis error while reading cache entry. Original error: {exc}",
                key=key,
            ) from exc
        except CacheException:
            raise
        except Exception as exc:
            _logger.error(
                "Unexpected error while reading cache entry.", key=key, exc_info=True
            )
            raise CacheException(
                detail=(
                    f"Unexpected error while reading cache entry. Original error: {exc}"
                ),
                key=key,
            ) from exc

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        """Store a cache entry in Redis with the given time to live.

        Args:
            key (str): The cache key of the entry to store.
            value (dict[str, Any]): The value to serialize as JSON.
            ttl_seconds (int): Seconds until the entry expires.

        Raises:
            CacheException: If the value is not JSON-serializable, if Redis fails,
                or if any unexpected error occurs.
        """
        try:
            await self._redis_client.set(
                name=key,
                value=json.dumps(value),
                ex=ttl_seconds,
            )
            _logger.debug("Cache entry stored.", key=key, ttl_seconds=ttl_seconds)
        except (TypeError, ValueError) as exc:
            _logger.error(
                "Cache value is not JSON-serializable.", key=key, exc_info=True
            )
            raise CacheException(
                detail=(f"Cache value is not JSON-serializable. Original error: {exc}"),
                key=key,
            ) from exc
        except RedisError as exc:
            _logger.error(
                "Redis error while writing cache entry.", key=key, exc_info=True
            )
            raise CacheUnavailableException(
                detail=f"Redis error while writing cache entry. Original error: {exc}",
                key=key,
            ) from exc

    async def delete(self, key: str) -> None:
        """Delete one or multiple cache entries from Redis.

        If the provided key represents a cache namespace (for example,
        ``cache:books:catalog``), all cache entries with that prefix are removed.
        Otherwise, only the exact cache key is deleted.

        Args:
            key (str): The cache key or namespace prefix of the entries to delete.

        Raises:
            CacheException: If Redis fails or if any unexpected error occurs.
        """
        try:
            # Delete the exact key first.
            deleted_keys = await self._redis_client.delete(key)

            # Delete all derived keys under the namespace.
            keys = [k async for k in self._redis_client.scan_iter(match=f"{key}:*")]

            if keys:
                deleted_keys += await self._redis_client.delete(*keys)

            _logger.info(
                "Cache entries deleted.",
                key=key,
                deleted_keys=deleted_keys,
            )
        except RedisError as exc:
            _logger.error(
                "Redis error while deleting cache entries.", key=key, exc_info=True
            )
            raise CacheUnavailableException(
                detail=f"Redis error while deleting cache entries. Original error: {exc}",
                key=key,
            ) from exc
        except Exception as exc:
            _logger.error(
                "Unexpected error while deleting cache entries.", key=key, exc_info=True
            )
            raise CacheException(
                detail=(
                    f"Unexpected error while deleting cache entries. "
                    f"Original error: {exc}"
                ),
                key=key,
            ) from exc

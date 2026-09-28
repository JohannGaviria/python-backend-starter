"""Integration tests for the RedisCache adapter against a real Redis."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import redis.asyncio as redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from src.shared.domain.exceptions.exception import (
    CacheException,
    CacheUnavailableException,
)
from src.shared.infrastructure.cache.redis_cache import RedisCache
from src.shared.infrastructure.cache.redis_client import redis_client

pytestmark = pytest.mark.db

# Every key used here lives under this prefix so the cleanup fixture can wipe
# them without touching anything else in the database.
NAMESPACE = "test:redis-cache"


class FakeEntity:
    def __init__(self, entity_id: str, name: str) -> None:
        self.id = entity_id
        self.name = name

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FakeEntity":
        return cls(entity_id=str(data["id"]), name=str(data["name"]))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FakeEntity)
            and self.id == other.id
            and self.name == other.name
        )

    def __repr__(self) -> str:
        return f"FakeEntity(id={self.id!r}, name={self.name!r})"


@pytest.fixture
async def connection() -> AsyncIterator[Any]:
    """Open the shared Redis client and close it after the test.

    Yields:
        Any: The live Redis client.
    """
    redis_client.connect()
    yield redis_client.client
    await redis_client.disconnect()


@pytest.fixture
async def cache(connection: Any) -> AsyncIterator[RedisCache[FakeEntity]]:
    """Provide a RedisCache and wipe its namespace afterwards.

    Yields:
        RedisCache[FakeEntity]: The adapter under test.
    """
    adapter: RedisCache[FakeEntity] = RedisCache(
        redis_client=connection,
        factory=FakeEntity.from_dict,
    )
    yield adapter

    leftovers = [key async for key in connection.scan_iter(match=f"{NAMESPACE}*")]
    if leftovers:
        await connection.delete(*leftovers)


class TestGet:
    async def test_should_return_none_when_the_key_is_absent(
        self, cache: RedisCache[FakeEntity]
    ):
        assert await cache.get(f"{NAMESPACE}:absent") is None

    async def test_should_rebuild_the_domain_object_after_a_set(
        self, cache: RedisCache[FakeEntity]
    ):
        await cache.set(f"{NAMESPACE}:entity:1", {"id": "1", "name": "alpha"}, 60)

        assert await cache.get(f"{NAMESPACE}:entity:1") == FakeEntity(
            entity_id="1", name="alpha"
        )

    async def test_should_return_none_after_the_ttl_expires(
        self, cache: RedisCache[FakeEntity]
    ):
        key = f"{NAMESPACE}:entity:expiring"
        await cache.set(key, {"id": "1", "name": "alpha"}, 1)

        await asyncio.sleep(1.2)

        assert await cache.get(key) is None

    async def test_should_raise_cache_exception_when_the_entry_is_not_json(
        self, cache: RedisCache[FakeEntity], connection: Any
    ):
        # Written straight to Redis to simulate an entry corrupted by something
        # other than this adapter, such as a deploy with a different schema.
        await connection.set(f"{NAMESPACE}:corrupted", "}{ not json")

        with pytest.raises(CacheException) as exc_info:
            await cache.get(f"{NAMESPACE}:corrupted")

        assert exc_info.value.key == f"{NAMESPACE}:corrupted"

    async def test_should_raise_cache_exception_when_the_factory_fails(
        self, cache: RedisCache[FakeEntity]
    ):
        await cache.set(f"{NAMESPACE}:entity:2", {"unexpected": True}, 60)

        with pytest.raises(CacheException, match="Unexpected error"):
            await cache.get(f"{NAMESPACE}:entity:2")


class TestSet:
    async def test_should_store_the_value_as_json(
        self, cache: RedisCache[FakeEntity], connection: Any
    ):
        await cache.set(f"{NAMESPACE}:entity:3", {"id": "3", "name": "beta"}, 60)

        stored = await connection.get(f"{NAMESPACE}:entity:3")

        assert stored in (
            '{"id": "3", "name": "beta"}',
            b'{"id": "3", "name": "beta"}',
        )

    async def test_should_apply_the_given_ttl(
        self, cache: RedisCache[FakeEntity], connection: Any
    ):
        await cache.set(f"{NAMESPACE}:entity:4", {"id": "4", "name": "gamma"}, 120)

        ttl = await connection.ttl(f"{NAMESPACE}:entity:4")

        assert 0 < ttl <= 120

    async def test_should_raise_cache_exception_when_the_value_is_not_serializable(
        self, cache: RedisCache[FakeEntity]
    ):
        with pytest.raises(CacheException, match="not JSON-serializable"):
            await cache.set(f"{NAMESPACE}:entity:5", {"id": object()}, 60)

    async def test_should_not_store_anything_when_serialization_fails(
        self, cache: RedisCache[FakeEntity], connection: Any
    ):
        with pytest.raises(CacheException):
            await cache.set(f"{NAMESPACE}:entity:6", {"id": object()}, 60)

        assert await connection.get(f"{NAMESPACE}:entity:6") is None


class TestDelete:
    async def test_should_delete_the_exact_key(
        self, cache: RedisCache[FakeEntity], connection: Any
    ):
        await cache.set(f"{NAMESPACE}:entity:7", {"id": "7", "name": "delta"}, 60)

        await cache.delete(f"{NAMESPACE}:entity:7")

        assert await connection.get(f"{NAMESPACE}:entity:7") is None

    async def test_should_delete_every_key_under_the_namespace(
        self, cache: RedisCache[FakeEntity], connection: Any
    ):
        catalog = f"{NAMESPACE}:catalog"
        await cache.set(catalog, {"total": 0}, 60)
        await cache.set(f"{catalog}:1", {"id": "1"}, 60)
        await cache.set(f"{catalog}:2", {"id": "2"}, 60)
        await cache.set(f"{NAMESPACE}:unrelated", {"id": "9"}, 60)

        await cache.delete(catalog)

        assert await connection.get(catalog) is None
        assert await connection.get(f"{catalog}:1") is None
        assert await connection.get(f"{catalog}:2") is None
        assert await connection.get(f"{NAMESPACE}:unrelated") is not None

    async def test_should_not_fail_when_the_namespace_does_not_exist(
        self, cache: RedisCache[FakeEntity]
    ):
        await cache.delete(f"{NAMESPACE}:never-created")

    async def test_should_allow_repopulating_the_namespace_after_a_delete(
        self, cache: RedisCache[FakeEntity]
    ):
        key = f"{NAMESPACE}:entity:8"
        await cache.set(key, {"id": "8", "name": "epsilon"}, 60)
        await cache.delete(key)

        await cache.set(key, {"id": "8", "name": "epsilon"}, 60)

        assert await cache.get(key) == FakeEntity(entity_id="8", name="epsilon")


class TestUnreachableRedis:
    async def test_should_raise_cache_unavailable_when_redis_is_unreachable(self):
        unreachable = redis.Redis(
            host="127.0.0.1",
            port=1,
            socket_connect_timeout=1,
            retry=Retry(NoBackoff(), 0),
        )
        cache: RedisCache[FakeEntity] = RedisCache(
            redis_client=unreachable,
            factory=FakeEntity.from_dict,
        )

        with pytest.raises(CacheUnavailableException, match="Redis error"):
            await cache.get(f"{NAMESPACE}:unreachable")

    async def test_should_raise_cache_unavailable_when_writing_to_an_unreachable_redis(
        self,
    ):
        unreachable = redis.Redis(
            host="127.0.0.1",
            port=1,
            socket_connect_timeout=1,
            retry=Retry(NoBackoff(), 0),
        )
        cache: RedisCache[FakeEntity] = RedisCache(
            redis_client=unreachable,
            factory=FakeEntity.from_dict,
        )

        with pytest.raises(CacheUnavailableException, match="Redis error"):
            await cache.set(f"{NAMESPACE}:unreachable", {"id": "1"}, 60)

    async def test_should_raise_cache_unavailable_when_deleting_from_an_unreachable_redis(
        self,
    ):
        unreachable = redis.Redis(
            host="127.0.0.1",
            port=1,
            socket_connect_timeout=1,
            retry=Retry(NoBackoff(), 0),
        )
        cache: RedisCache[FakeEntity] = RedisCache(
            redis_client=unreachable,
            factory=FakeEntity.from_dict,
        )

        with pytest.raises(CacheUnavailableException, match="Redis error"):
            await cache.delete(f"{NAMESPACE}:unreachable")

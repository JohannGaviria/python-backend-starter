"""Unit tests for the RedisCache adapter, with a fake redis client instead of Redis."""

from typing import Any, Callable

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from src.shared.domain.exceptions.exception import (
    CacheException,
    CacheUnavailableException,
)
from src.shared.infrastructure.cache.redis_cache import RedisCache


class FakeEntity:
    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FakeEntity":
        return cls(id=str(data["id"]), name=str(data["name"]))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FakeEntity)
            and self.id == other.id
            and self.name == other.name
        )


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int]] = []
        self.deleted: list[Any] = []
        self.get_error: Exception | None = None
        self.set_error: Exception | None = None
        self.delete_error: Exception | None = None

    async def get(self, key: str) -> str | None:
        if self.get_error is not None:
            raise self.get_error
        return self.store.get(key)

    async def set(self, name: str, value: str, ex: int) -> bool:
        if self.set_error is not None:
            raise self.set_error
        self.set_calls.append((name, value, ex))
        self.store[name] = value
        return True

    async def delete(self, *keys: str) -> int:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(keys)
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed

    async def scan_iter(self, match: str) -> Any:
        prefix = match.rstrip("*")
        for key in list(self.store):
            if key.startswith(prefix):
                yield key


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


def build_cache(
    fake_redis: FakeRedis,
    factory: Callable[[dict[str, Any]], FakeEntity],
) -> RedisCache[FakeEntity]:
    """Build a RedisCache backed by the fake client.

    Args:
        fake_redis: The fake Redis client.
        factory: The factory that rebuilds a FakeEntity from a stored dictionary.

    Returns:
        RedisCache[FakeEntity]: The adapter under test.
    """
    cache: RedisCache[FakeEntity] = RedisCache(
        redis_client=fake_redis,  # type: ignore[arg-type]
        factory=factory,
    )
    return cache


@pytest.fixture
def cache(fake_redis: FakeRedis) -> RedisCache[FakeEntity]:
    return build_cache(fake_redis, FakeEntity.from_dict)


class TestGet:
    async def test_should_return_none_when_the_key_is_missing(
        self, cache: RedisCache[FakeEntity]
    ):
        assert await cache.get("entity:1") is None

    async def test_should_rebuild_the_domain_object_from_the_stored_json(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.store["entity:1"] = '{"id": "1", "name": "alpha"}'

        result = await cache.get("entity:1")

        assert result == FakeEntity(id="1", name="alpha")

    async def test_should_raise_cache_exception_when_the_entry_is_not_json(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.store["entity:1"] = "not json"

        with pytest.raises(CacheException) as exc_info:
            await cache.get("entity:1")

        assert exc_info.value.key == "entity:1"

    async def test_should_raise_cache_exception_when_the_factory_fails(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.store["entity:1"] = '{"unexpected": true}'

        with pytest.raises(CacheException, match="Unexpected error"):
            await cache.get("entity:1")

    async def test_should_propagate_a_cache_exception_raised_by_the_factory(
        self, fake_redis: FakeRedis
    ):
        original = CacheException(
            detail="the factory rejected the payload", key="entity:1"
        )

        def factory(_: dict[str, Any]) -> FakeEntity:
            raise original

        cache = build_cache(fake_redis, factory)
        fake_redis.store["entity:1"] = '{"id": "1", "name": "alpha"}'

        with pytest.raises(CacheException) as exc_info:
            await cache.get("entity:1")

        assert exc_info.value is original

    async def test_should_raise_cache_unavailable_when_redis_fails(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.get_error = RedisConnectionError("connection refused")

        with pytest.raises(CacheUnavailableException, match="Redis error"):
            await cache.get("entity:1")

    async def test_should_raise_cache_exception_when_an_unexpected_error_happens(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.get_error = ValueError("something else entirely")

        with pytest.raises(CacheException, match="Unexpected error"):
            await cache.get("entity:1")


class TestSet:
    async def test_should_store_the_value_as_json_with_the_given_ttl(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        await cache.set("entity:1", {"id": "1", "name": "alpha"}, ttl_seconds=60)

        assert fake_redis.set_calls == [
            ("entity:1", '{"id": "1", "name": "alpha"}', 60)
        ]

    async def test_should_raise_cache_exception_when_the_value_is_not_serializable(
        self, cache: RedisCache[FakeEntity]
    ):
        with pytest.raises(CacheException, match="not JSON-serializable"):
            await cache.set("entity:1", {"id": object()}, ttl_seconds=60)

    async def test_should_raise_cache_unavailable_when_redis_fails(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.set_error = RedisConnectionError("connection refused")

        with pytest.raises(CacheUnavailableException, match="Redis error"):
            await cache.set("entity:1", {"id": "1"}, ttl_seconds=60)


class TestDelete:
    async def test_should_delete_the_exact_key(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.store["entity:1"] = "{}"

        await cache.delete("entity:1")

        assert "entity:1" not in fake_redis.store

    async def test_should_delete_every_key_under_the_namespace(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.store["cache:entities:catalog"] = "{}"
        fake_redis.store["cache:entities:catalog:1"] = "{}"
        fake_redis.store["cache:entities:catalog:2"] = "{}"
        fake_redis.store["unrelated:1"] = "{}"

        await cache.delete("cache:entities:catalog")

        assert "cache:entities:catalog" not in fake_redis.store
        assert "cache:entities:catalog:1" not in fake_redis.store
        assert "cache:entities:catalog:2" not in fake_redis.store
        assert "unrelated:1" in fake_redis.store

    async def test_should_not_fail_when_the_key_does_not_exist(
        self, cache: RedisCache[FakeEntity]
    ):
        await cache.delete("entity:missing")

    async def test_should_raise_cache_unavailable_when_redis_fails(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.delete_error = RedisConnectionError("connection refused")

        with pytest.raises(CacheUnavailableException, match="Redis error"):
            await cache.delete("entity:1")

    async def test_should_raise_cache_exception_when_an_unexpected_error_happens(
        self, cache: RedisCache[FakeEntity], fake_redis: FakeRedis
    ):
        fake_redis.delete_error = ValueError("something else entirely")

        with pytest.raises(CacheException, match="Unexpected error"):
            await cache.delete("entity:1")

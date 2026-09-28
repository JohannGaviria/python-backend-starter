"""Unit tests for the RedisClient adapter, with a fake redis client instead of Redis."""

from collections.abc import Iterator
from typing import Any

import pytest
import redis.asyncio as redis_asyncio

from src.config import settings
from src.shared.infrastructure.cache.redis_client import RedisClient


class FakeRedis:
    def __init__(self, ping_result: Any = True) -> None:
        self.ping_result = ping_result
        self.closed = False

    async def ping(self) -> Any:
        if isinstance(self.ping_result, Exception):
            raise self.ping_result
        return self.ping_result

    async def aclose(self) -> None:
        self.closed = True


class FakeConnectionPool:
    def __init__(self) -> None:
        self.disconnected = False

    async def disconnect(self) -> None:
        self.disconnected = True


class Harness:
    """A RedisClient wired to fake pool and client factories.

    Attributes:
        client: The instance under test.
        pool: The fake pool returned by the patched factory.
        redis: The fake client returned by the patched factory.
        pool_kwargs: The keyword args the pool factory was called with.
    """

    def __init__(self, ping_result: Any = True) -> None:
        self.client = RedisClient()
        self.pool = FakeConnectionPool()
        self.redis = FakeRedis(ping_result)
        self.pool_kwargs: dict[str, Any] = {}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from_url_calls: list[tuple[Any, ...]] = []

        def from_url(*args: Any, **kwargs: Any) -> FakeConnectionPool:
            from_url_calls.append(args)
            self.pool_kwargs = kwargs
            return self.pool

        def build_client(*args: Any, **kwargs: Any) -> FakeRedis:
            return self.redis

        monkeypatch.setattr(redis_asyncio.ConnectionPool, "from_url", from_url)
        monkeypatch.setattr(redis_asyncio, "Redis", build_client)
        self.from_url_calls = from_url_calls

    @property
    def built_clients(self) -> list[Any]:
        return self.from_url_calls


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    built = Harness()
    built.install(monkeypatch)
    yield built


class TestConnect:
    def test_should_build_the_pool_from_the_settings(self, harness: Harness):
        harness.client.connect()

        assert harness.pool_kwargs["max_connections"] == settings.REDIS_MAX_CONNECTIONS
        assert (
            harness.pool_kwargs["decode_responses"] == settings.REDIS_DECODE_RESPONSES
        )

    def test_should_build_the_pool_from_the_configured_url(self, harness: Harness):
        harness.client.connect()

        assert harness.built_clients == [(settings.REDIS_URL,)]

    def test_should_expose_the_client_once_connected(self, harness: Harness):
        harness.client.connect()

        assert harness.client.client is harness.redis

    def test_should_be_idempotent_when_connect_is_called_twice(self, harness: Harness):
        harness.client.connect()
        first = harness.client.client

        harness.client.connect()

        assert harness.client.client is first
        assert len(harness.built_clients) == 1


class TestDisconnect:
    async def test_should_close_the_client_and_the_pool(self, harness: Harness):
        harness.client.connect()

        await harness.client.disconnect()

        assert harness.redis.closed is True
        assert harness.pool.disconnected is True

    async def test_should_reset_internal_state_when_disconnect_is_called(
        self, harness: Harness
    ):
        harness.client.connect()

        await harness.client.disconnect()

        with pytest.raises(RuntimeError, match="not connected"):
            _ = harness.client.client

    async def test_should_be_idempotent_when_disconnect_is_called_without_connect(
        self, harness: Harness
    ):
        await harness.client.disconnect()

        assert harness.pool.disconnected is False

    async def test_should_allow_reconnect_when_connect_is_called_after_disconnect(
        self, harness: Harness
    ):
        harness.client.connect()
        await harness.client.disconnect()

        harness.client.connect()

        assert await harness.client.ping() is True


class TestClientProperty:
    def test_should_raise_runtime_error_when_client_accessed_before_connect(
        self, harness: Harness
    ):
        with pytest.raises(RuntimeError, match="not connected"):
            _ = harness.client.client


class TestPing:
    async def test_should_return_true_when_ping_succeeds(self, harness: Harness):
        harness.client.connect()

        assert await harness.client.ping() is True

    async def test_should_return_false_when_ping_answers_false(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        built = Harness(ping_result=False)
        built.install(monkeypatch)
        built.client.connect()

        assert await built.client.ping() is False

    async def test_should_propagate_when_ping_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        built = Harness(ping_result=ConnectionError("redis is down"))
        built.install(monkeypatch)
        built.client.connect()

        with pytest.raises(ConnectionError):
            await built.client.ping()

    async def test_should_raise_runtime_error_when_ping_is_called_before_connect(
        self, harness: Harness
    ):
        with pytest.raises(RuntimeError, match="not connected"):
            await harness.client.ping()

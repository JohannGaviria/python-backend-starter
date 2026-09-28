"""Unit tests for the application wiring in src/main.py."""

from collections.abc import Iterator
from typing import Any

import pytest

from src import main as main_module
from src.main import _is_reachable, app, lifespan


class FakeDependency:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.disconnect_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1

    async def disconnect(self) -> None:
        self.disconnect_calls += 1

    async def ping(self) -> bool:
        return True


@pytest.fixture
def dependencies(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Any]]:
    """Replace the database and Redis singletons with fakes.

    Yields:
        tuple: The fake database and the fake Redis client.
    """
    fake_db = FakeDependency()
    fake_redis = FakeDependency()
    monkeypatch.setattr(main_module, "db", fake_db)
    monkeypatch.setattr(main_module, "redis_client", fake_redis)
    yield fake_db, fake_redis


class TestIsReachable:
    async def test_should_return_true_when_the_ping_answers_true(self) -> None:
        async def ping() -> bool:
            return True

        assert await _is_reachable(ping) is True

    async def test_should_return_false_when_the_ping_answers_false(self) -> None:
        async def ping() -> bool:
            return False

        assert await _is_reachable(ping) is False

    async def test_should_swallow_the_error_when_the_ping_raises(self) -> None:
        async def ping() -> bool:
            raise ConnectionError("the dependency is down")

        assert await _is_reachable(ping) is False


class TestLifespan:
    async def test_should_connect_on_startup_and_disconnect_on_shutdown(
        self, dependencies: tuple[Any, Any]
    ) -> None:
        fake_db, fake_redis = dependencies

        async with lifespan(app):
            assert fake_db.connect_calls == 1
            assert fake_redis.connect_calls == 1
            assert fake_db.disconnect_calls == 0

        assert fake_db.disconnect_calls == 1
        assert fake_redis.disconnect_calls == 1

    async def test_should_disconnect_even_when_the_body_raises(
        self, dependencies: tuple[Any, Any]
    ) -> None:
        fake_db, fake_redis = dependencies

        with pytest.raises(ValueError, match="boom"):
            async with lifespan(app):
                raise ValueError("boom")

        assert fake_db.disconnect_calls == 1
        assert fake_redis.disconnect_calls == 1

    async def test_should_disconnect_even_when_startup_fails_part_way(
        self, dependencies: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_db, fake_redis = dependencies

        def exploding_connect() -> None:
            fake_db.connect_calls += 1
            raise RuntimeError("could not reach the database")

        monkeypatch.setattr(fake_db, "connect", exploding_connect)

        with pytest.raises(RuntimeError, match="could not reach"):
            async with lifespan(app):
                pass

        assert fake_db.disconnect_calls == 1
        assert fake_redis.disconnect_calls == 1


class TestAppWiring:
    def test_should_expose_the_application_metadata(self) -> None:
        assert app.title
        assert app.version

    def test_should_register_the_health_routes(self) -> None:
        paths = {getattr(route, "path", None) for route in app.routes}

        assert "/health" in paths
        assert "/health/ready" in paths

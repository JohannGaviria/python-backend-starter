"""Unit tests for the Database adapter, with a fake engine instead of PostgreSQL."""

from collections.abc import Iterator
from typing import Any

import pytest

from src.config import settings
from src.shared.infrastructure.persistence.database import database as database_module
from src.shared.infrastructure.persistence.database.database import Database


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute(self, statement: Any) -> Any:
        self.executed.append(str(statement))
        return None


class FakeConnectContext:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self._connection

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.disposed = False

    def connect(self) -> FakeConnectContext:
        return FakeConnectContext(self.connection)

    async def dispose(self) -> None:
        self.disposed = True


class FakeSession:
    def __init__(self) -> None:
        self.rolled_back = False
        self.closed = False

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        await self._session.close()
        return None


class FakeSessionMaker:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSessionContext:
        session = FakeSession()
        self.sessions.append(session)
        return FakeSessionContext(session)


class Harness:
    """A Database wired to fake engine and sessionmaker factories.

    Attributes:
        database: The instance under test.
        engine: The fake engine returned by the patched factory.
        sessionmaker: The fake sessionmaker returned by the patched factory.
        engine_args: The positional args the engine factory was called with.
        engine_kwargs: The keyword args the engine factory was called with.
        sessionmaker_kwargs: The keyword args the sessionmaker factory got.
    """

    def __init__(self) -> None:
        self.database = Database()
        self.engine = FakeEngine()
        self.sessionmaker = FakeSessionMaker()
        self.engine_args: tuple[Any, ...] = ()
        self.engine_kwargs: dict[str, Any] = {}
        self.sessionmaker_kwargs: dict[str, Any] = {}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def create_engine(*args: Any, **kwargs: Any) -> FakeEngine:
            self.engine_args = args
            self.engine_kwargs = kwargs
            return self.engine

        def create_sessionmaker(**kwargs: Any) -> FakeSessionMaker:
            self.sessionmaker_kwargs = kwargs
            return self.sessionmaker

        monkeypatch.setattr(database_module, "create_async_engine", create_engine)
        monkeypatch.setattr(database_module, "async_sessionmaker", create_sessionmaker)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    built = Harness()
    built.install(monkeypatch)
    yield built


class TestConnect:
    def test_should_build_the_engine_from_the_settings(self, harness: Harness):
        harness.database.connect()

        assert harness.engine_args == (settings.DATABASE_URL,)
        assert harness.engine_kwargs["echo"] == settings.DB_ECHO
        assert harness.engine_kwargs["pool_size"] == settings.DB_POOL_SIZE
        assert harness.engine_kwargs["max_overflow"] == settings.DB_MAX_OVERFLOW
        assert harness.engine_kwargs["pool_timeout"] == settings.DB_POOL_TIMEOUT
        assert harness.engine_kwargs["pool_pre_ping"] is True

    def test_should_configure_the_sessionmaker_without_autoflush(
        self, harness: Harness
    ):
        harness.database.connect()

        assert harness.sessionmaker_kwargs["bind"] is harness.engine
        assert harness.sessionmaker_kwargs["expire_on_commit"] is False
        assert harness.sessionmaker_kwargs["autoflush"] is False

    def test_should_be_idempotent_when_connect_is_called_twice(self, harness: Harness):
        harness.database.connect()
        first = harness.database.session_factory()

        harness.database.connect()

        assert harness.database.session_factory() is first

    async def test_should_dispose_the_engine_when_disconnect_is_called(
        self, harness: Harness
    ):
        harness.database.connect()

        await harness.database.disconnect()

        assert harness.engine.disposed is True

    async def test_should_reset_internal_state_when_disconnect_is_called(
        self, harness: Harness
    ):
        harness.database.connect()

        await harness.database.disconnect()

        with pytest.raises(RuntimeError):
            harness.database.session_factory()

    async def test_should_be_idempotent_when_disconnect_is_called_without_connect(
        self, harness: Harness
    ):
        await harness.database.disconnect()

        assert harness.engine.disposed is False

    async def test_should_allow_reconnect_when_connect_is_called_after_disconnect(
        self, harness: Harness
    ):
        harness.database.connect()
        await harness.database.disconnect()

        harness.database.connect()

        assert await harness.database.ping() is True


class TestPing:
    async def test_should_run_a_select_one_when_ping_is_called(self, harness: Harness):
        harness.database.connect()

        assert await harness.database.ping() is True
        assert harness.engine.connection.executed == ["SELECT 1"]

    async def test_should_raise_runtime_error_when_ping_is_called_before_connect(
        self, harness: Harness
    ):
        with pytest.raises(RuntimeError, match="not connected"):
            await harness.database.ping()


class TestSession:
    async def test_should_raise_runtime_error_when_session_is_used_before_connect(
        self, harness: Harness
    ):
        with pytest.raises(RuntimeError, match="not connected"):
            async with harness.database.session():
                pass

    async def test_should_yield_a_session_and_close_it(self, harness: Harness):
        harness.database.connect()

        async with harness.database.session() as session:
            assert isinstance(session, FakeSession)

        assert harness.sessionmaker.sessions[0].closed is True

    async def test_should_not_rollback_when_the_block_succeeds(self, harness: Harness):
        harness.database.connect()

        async with harness.database.session():
            pass

        assert harness.sessionmaker.sessions[0].rolled_back is False

    async def test_should_rollback_and_reraise_when_the_block_raises(
        self, harness: Harness
    ):
        harness.database.connect()

        with pytest.raises(ValueError, match="boom"):
            async with harness.database.session():
                raise ValueError("boom")

        assert harness.sessionmaker.sessions[0].rolled_back is True

    def test_should_raise_runtime_error_when_session_factory_is_used_before_connect(
        self, harness: Harness
    ):
        with pytest.raises(RuntimeError, match="not connected"):
            harness.database.session_factory()

    def test_should_return_the_sessionmaker_when_connected(self, harness: Harness):
        harness.database.connect()

        assert harness.database.session_factory() is harness.sessionmaker

"""Unit tests for the CorrelationIdMiddleware."""

from collections.abc import Iterator
from uuid import UUID

import pytest
import structlog
from starlette.requests import Request
from starlette.responses import Response

from src.shared.presentation.middleware.correlation_id_middleware import (
    CorrelationIdMiddleware,
)


@pytest.fixture(autouse=True)
def clear_contextvars() -> Iterator[None]:
    """Drop the contextvars between tests so ids do not leak across them.

    Yields:
        None: Control passes to the test with a clean context.
    """
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def build_request(correlation_id: str | None = None) -> Request:
    """Build a minimal GET request, optionally carrying the header.

    The raw header name is lowercased because the ASGI spec requires servers to
    send header names in lowercase, and Starlette looks them up that way.

    Args:
        correlation_id: The value for the header, or None to omit it.

    Returns:
        Request: The request to pass to the middleware.
    """
    headers = []
    if correlation_id is not None:
        headers.append(
            (
                CorrelationIdMiddleware.HEADER_NAME.lower().encode(),
                correlation_id.encode(),
            )
        )

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
        }
    )


async def call_next(_: Request) -> Response:
    return Response(status_code=200)


class TestCorrelationId:
    async def test_should_echo_the_incoming_correlation_id(self) -> None:
        middleware = CorrelationIdMiddleware(app=None)  # type: ignore[arg-type]

        response = await middleware.dispatch(
            build_request("incoming-id"),
            call_next,
        )

        assert response.headers[CorrelationIdMiddleware.HEADER_NAME] == "incoming-id"

    async def test_should_generate_a_uuid_when_the_header_is_absent(self) -> None:
        middleware = CorrelationIdMiddleware(app=None)  # type: ignore[arg-type]

        response = await middleware.dispatch(build_request(), call_next)

        generated = response.headers[CorrelationIdMiddleware.HEADER_NAME]
        assert UUID(generated).version == 4

    async def test_should_generate_a_different_id_per_request(self) -> None:
        middleware = CorrelationIdMiddleware(app=None)  # type: ignore[arg-type]

        first = await middleware.dispatch(build_request(), call_next)
        second = await middleware.dispatch(build_request(), call_next)

        assert (
            first.headers[CorrelationIdMiddleware.HEADER_NAME]
            != second.headers[CorrelationIdMiddleware.HEADER_NAME]
        )

    async def test_should_bind_the_correlation_id_to_the_contextvars(self) -> None:
        middleware = CorrelationIdMiddleware(app=None)  # type: ignore[arg-type]

        await middleware.dispatch(build_request("incoming-id"), call_next)

        assert (
            structlog.contextvars.get_contextvars()["correlation_id"] == "incoming-id"
        )

    async def test_should_replace_the_contextvars_of_the_previous_request(
        self,
    ) -> None:
        middleware = CorrelationIdMiddleware(app=None)  # type: ignore[arg-type]
        structlog.contextvars.bind_contextvars(correlation_id="stale-id", user="42")

        await middleware.dispatch(build_request("incoming-id"), call_next)

        context = structlog.contextvars.get_contextvars()
        assert context["correlation_id"] == "incoming-id"
        assert "user" not in context

    async def test_should_return_the_response_from_the_next_handler(self) -> None:
        middleware = CorrelationIdMiddleware(app=None)  # type: ignore[arg-type]

        response = await middleware.dispatch(build_request(), call_next)

        assert response.status_code == 200

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from src.shared.domain.exceptions.exception import (
    CacheException,
    CacheUnavailableException,
)
from src.shared.infrastructure.logging.structlog_logger import StructlogLogger
from src.shared.presentation.schemas.schema import ErrorsResponseSchema

_logger = StructlogLogger(__name__)


def exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CacheUnavailableException)
    async def cache_unavailable_exception_handler(
        request: Request,
        exc: CacheUnavailableException,
    ) -> JSONResponse:
        """Handle a cache backend that could not be reached.

        The cache is a dependency, so the request cannot be served. The detail
        and the key go to the log only: returning them would expose the Redis
        host and the connection error to the client.

        Args:
            request (Request): The request object.
            exc (CacheUnavailableException): The cache failure.

        Returns:
            JSONResponse: The 503 response with a generic message.
        """
        _logger.error(
            "Cache backend unavailable while processing request.",
            request_method=request.method,
            request_path=request.url.path,
            cache_key=exc.key,
            exception_detail=exc.detail,
            exc_info=True,
        )

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=jsonable_encoder(
                ErrorsResponseSchema(
                    message="The cache is temporarily unavailable.",
                ),
                exclude_none=True,
            ),
        )

    @app.exception_handler(CacheException)
    async def cache_exception_handler(
        request: Request,
        exc: CacheException,
    ) -> JSONResponse:
        """Handle a cache failure caused by the request or by a bug.

        Args:
            request (Request): The request object.
            exc (CacheException): The cache failure.

        Returns:
            JSONResponse: The 500 response with a generic message.
        """
        _logger.error(
            "Cache error while processing request.",
            request_method=request.method,
            request_path=request.url.path,
            cache_key=exc.key,
            exception_detail=exc.detail,
            exc_info=True,
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=jsonable_encoder(
                ErrorsResponseSchema(
                    message="An error occurred while accessing the cache.",
                ),
                exclude_none=True,
            ),
        )

    @app.exception_handler(Exception)
    async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle an exception that no specific handler claimed.

        The message is generic on purpose. The text of an unexpected exception
        can carry SQL, connection strings, file paths or upstream payloads, so
        it is logged and never returned to the client.

        There is no debug escape hatch here on purpose: with DEBUG enabled
        FastAPI serves the full traceback itself and this handler is never
        reached, so adding one would be dead code.

        Args:
            request (Request): The request object.
            exc (Exception): The exception.

        Returns:
            JSONResponse: The JSON response with a generic 500 message.
        """
        _logger.error(
            "Unhandled exception while processing request.",
            request_method=request.method,
            request_path=request.url.path,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            exc_info=True,
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=jsonable_encoder(
                ErrorsResponseSchema(
                    message="An unexpected error occurred while processing the request.",
                ),
                exclude_none=True,
            ),
        )

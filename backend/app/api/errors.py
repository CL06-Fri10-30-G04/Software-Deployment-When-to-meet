import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..db.exceptions import (
    ConcurrencyError,
    DuplicateEmailError,
    NotFound,
    ParticipantsUnavailable,
    PermissionDenied,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Repository exception -> (status, error code). Order matters only for subclasses.
_REPOSITORY_ERRORS: dict[type[Exception], tuple[int, str]] = {
    DuplicateEmailError: (409, "duplicate_email"),
    PermissionDenied: (403, "forbidden"),
    NotFound: (404, "not_found"),
    ParticipantsUnavailable: (409, "participants_unavailable"),
    ConcurrencyError: (409, "concurrency_conflict"),
    ValidationError: (400, "validation_error"),
}

_HTTP_ERROR_CODES = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
}


class ApiError(Exception):
    """An error raised by a route with an explicit status and error code."""

    def __init__(self, status_code: int, error: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message


def error_response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, "message": message})


def _validation_message(error: RequestValidationError) -> str:
    details = error.errors()
    if not details:
        return "Request body is invalid."
    first = details[0]
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = first.get("msg", "is invalid")
    return f"{location}: {message}" if location else message


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        return error_response(error.status_code, error.error, error.message)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return error_response(400, "validation_error", _validation_message(error))

    for exception_type, (status_code, code) in _REPOSITORY_ERRORS.items():

        async def handle_repository_error(
            _request: Request,
            error: Exception,
            status_code: int = status_code,
            code: str = code,
        ) -> JSONResponse:
            return error_response(status_code, code, str(error))

        app.add_exception_handler(exception_type, handle_repository_error)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        code = _HTTP_ERROR_CODES.get(error.status_code, "request_failed")
        return error_response(error.status_code, code, str(error.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=error)
        return error_response(500, "internal_error", "An unexpected error occurred.")

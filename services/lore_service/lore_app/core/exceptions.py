from fastapi import Request
from fastapi.responses import JSONResponse


class LoreServiceException(Exception):
    def __init__(self, title: str, detail: str, status_code: int = 400):
        self.title = title
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ResourceNotFoundException(LoreServiceException):
    def __init__(self, resource: str, resource_id: str | int):
        super().__init__(
            title="Resource Not Found",
            detail=f"{resource} with id '{resource_id}' was not found.",
            status_code=404,
        )


class ConflictException(LoreServiceException):
    def __init__(self, detail: str):
        super().__init__(
            title="Conflict Error",
            detail=detail,
            status_code=409,
        )


async def problem_details_handler(request: Request, exc: LoreServiceException) -> JSONResponse:
    """RFC 7807 problem details error response as required by ENSI API guide."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "title": exc.title,
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": str(request.url),
        },
    )

from fastapi import Request
from fastapi.responses import JSONResponse


class StoryServiceException(Exception):
    def __init__(self, title: str, detail: str, status_code: int = 400):
        self.title = title
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ResourceNotFoundException(StoryServiceException):
    def __init__(self, resource: str, resource_id: str | int):
        super().__init__(
            title="Resource Not Found",
            detail=f"{resource} with id '{resource_id}' was not found.",
            status_code=404,
        )


class ConflictException(StoryServiceException):
    def __init__(self, detail: str):
        super().__init__(
            title="Conflict Error",
            detail=detail,
            status_code=409,
        )


class UpstreamServiceException(StoryServiceException):
    def __init__(self, service: str, detail: str):
        super().__init__(
            title="Upstream Service Error",
            detail=f"Error communicating with {service}: {detail}",
            status_code=502,
        )


async def problem_details_handler(request: Request, exc: StoryServiceException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "title": exc.title,
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": str(request.url),
        },
    )

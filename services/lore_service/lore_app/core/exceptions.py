from fastapi import Request
from fastapi.responses import JSONResponse


class LoreServiceException(Exception):
    """Base application error serialized using the ENSI response envelope."""

    def __init__(
        self,
        title: str,
        detail: str,
        status_code: int = 400,
        code: str = "BadRequestHttpException",
        meta: dict | None = None,
    ):
        self.title = title
        self.detail = detail
        self.status_code = status_code
        self.code = code
        self.meta = meta
        super().__init__(detail)


class ResourceNotFoundException(LoreServiceException):
    def __init__(self, resource: str, resource_id: str | int):
        super().__init__(
            title="Resource Not Found",
            detail=f"{resource} with id '{resource_id}' was not found.",
            status_code=404,
            code="NotFoundHttpException",
        )


class ConflictException(LoreServiceException):
    def __init__(self, detail: str):
        # ENSI allows only 200, 201, 400, 401, 403, 404 and 500.
        super().__init__(
            title="Conflict Error",
            detail=detail,
            status_code=400,
            code="ConflictHttpException",
        )


async def problem_details_handler(_request: Request, exc: LoreServiceException) -> JSONResponse:
    """Return the common ENSI API error envelope."""
    error: dict[str, object] = {"code": exc.code, "message": exc.detail}
    if exc.meta is not None:
        error["meta"] = exc.meta
    return JSONResponse(
        status_code=exc.status_code,
        content={"data": None, "errors": [error]},
    )

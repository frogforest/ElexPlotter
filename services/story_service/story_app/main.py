from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from story_app.api.v1.stories import router as stories_router
from story_app.core.config import settings
from story_app.core.database import Base, engine
from story_app.core.ensi_middleware import EnsiResponseMiddleware
from story_app.core.exceptions import StoryServiceException, problem_details_handler
from story_app.core.trace_context import TraceContextMiddleware


async def ensi_http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    status_code = exc.status_code if exc.status_code in {401, 403, 404, 500} else 400
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "errors": [
                {
                    "code": (
                        "NotFoundHttpException" if status_code == 404 else "BadRequestHttpException"
                    ),
                    "message": str(exc.detail),
                }
            ],
        },
    )


async def ensi_validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {"location": list(error.get("loc", ())), "message": error.get("msg", "Invalid value")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=400,
        content={
            "data": None,
            "errors": [
                {
                    "code": "ValidationHttpException",
                    "message": "Request validation failed.",
                    "meta": {"fields": details},
                }
            ],
        },
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Story Service",
    description="Microservice managing story texts, file storage, indexing, and lore consistency integration.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(TraceContextMiddleware)
app.add_middleware(EnsiResponseMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handler for RFC 7807 problem details
app.add_exception_handler(StoryServiceException, problem_details_handler)  # type: ignore[arg-type]
app.add_exception_handler(HTTPException, ensi_http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, ensi_validation_exception_handler)  # type: ignore[arg-type]

# Register API v1 router
app.include_router(stories_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "story_service"}

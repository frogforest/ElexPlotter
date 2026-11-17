from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from lore_app.api.v1.canon import router as canon_router
from lore_app.api.v1.characters import router as characters_router
from lore_app.api.v1.world_events import router as events_router
from lore_app.core.config import settings
from lore_app.core.database import Base, engine
from lore_app.core.ensi_middleware import EnsiResponseMiddleware
from lore_app.core.exceptions import LoreServiceException, problem_details_handler
from lore_app.core.trace_context import TraceContextMiddleware


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
    # Initialize DB tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Lore Service (Canon Engine)",
    description="Microservice managing world canon, characters, events DAG, and narrative consistency.",
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
app.add_exception_handler(LoreServiceException, problem_details_handler)  # type: ignore[arg-type]
app.add_exception_handler(HTTPException, ensi_http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, ensi_validation_exception_handler)  # type: ignore[arg-type]

# Register API v1 routers
app.include_router(characters_router, prefix=settings.API_V1_STR)
app.include_router(events_router, prefix=settings.API_V1_STR)
app.include_router(canon_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "lore_service"}

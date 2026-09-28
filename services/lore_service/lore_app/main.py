from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from lore_app.api.v1.canon import router as canon_router
from lore_app.api.v1.characters import router as characters_router
from lore_app.api.v1.world_events import router as events_router
from lore_app.core.config import settings
from lore_app.core.database import Base, engine
from lore_app.core.exceptions import LoreServiceException, problem_details_handler


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handler for RFC 7807 problem details
app.add_exception_handler(LoreServiceException, problem_details_handler)  # type: ignore[arg-type]

# Register API v1 routers
app.include_router(characters_router, prefix=settings.API_V1_STR)
app.include_router(events_router, prefix=settings.API_V1_STR)
app.include_router(canon_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "lore_service"}

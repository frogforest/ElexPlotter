from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from story_app.api.v1.stories import router as stories_router
from story_app.core.config import settings
from story_app.core.database import Base, engine
from story_app.core.exceptions import StoryServiceException, problem_details_handler


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

# Exception handler for RFC 7807 problem details
app.add_exception_handler(StoryServiceException, problem_details_handler)  # type: ignore[arg-type]

# Register API v1 router
app.include_router(stories_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "story_service"}

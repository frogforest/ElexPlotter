from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from story_app.core.database import get_db
from story_app.core.exceptions import ResourceNotFoundException
from story_app.models.entities import EventRole
from story_app.schemas.dto import (
    MetaPagination,
    PaginatedResponse,
    StoryCreate,
    StoryDetailResponse,
    StoryResponse,
)
from story_app.services.search_engine import SearchEngine
from story_app.services.story_manager import StoryManager

router = APIRouter(prefix="/stories", tags=["Stories"])


def get_story_manager(db: AsyncSession = Depends(get_db)) -> StoryManager:
    return StoryManager(session=db)


@router.post("", response_model=StoryResponse, status_code=status.HTTP_201_CREATED)
async def create_story(
    payload: StoryCreate,
    manager: StoryManager = Depends(get_story_manager),
) -> StoryResponse:
    return await manager.create_story(payload)


@router.get("", response_model=PaginatedResponse[StoryResponse])
async def list_stories(
    character_id: int | None = Query(default=None, alias="filter[character_id]"),
    event_id: int | None = Query(default=None, alias="filter[event_id]"),
    event_role: EventRole | None = Query(default=None, alias="filter[role]"),
    search: str | None = Query(default=None, alias="filter[q]"),
    page: int = Query(default=1, ge=1, alias="page[number]"),
    per_page: int = Query(default=20, ge=1, le=100, alias="page[size]"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[StoryResponse]:
    search_engine = SearchEngine(session=db)
    stories, total = await search_engine.search_stories(
        character_id=character_id,
        event_id=event_id,
        event_role=event_role,
        query_text=search,
        page=page,
        per_page=per_page,
    )
    return PaginatedResponse(
        data=stories,
        meta=MetaPagination(current_page=page, per_page=per_page, total=total),
    )


@router.get("/{story_id}", response_model=StoryDetailResponse)
async def get_story_by_id(story_id: int, db: AsyncSession = Depends(get_db)) -> StoryDetailResponse:
    manager = StoryManager(session=db)
    story = await manager.get_story_detail(story_id)
    if not story:
        raise ResourceNotFoundException("Story", story_id)
    return story

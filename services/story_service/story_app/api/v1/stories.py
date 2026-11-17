from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from story_app.core.database import get_db
from story_app.core.exceptions import ConflictException, ResourceNotFoundException
from story_app.models.entities import EventRole
from story_app.schemas.dto import (
    MetaPagination,
    PaginatedResponse,
    SearchRequest,
    StoryCreate,
    StoryDetailResponse,
    StoryResponse,
    StoryUpdate,
)
from story_app.services.search_engine import SearchEngine
from story_app.services.story_manager import StoryManager

router = APIRouter(prefix="/stories", tags=["Stories"])


def get_story_manager(db: AsyncSession = Depends(get_db)) -> StoryManager:
    return StoryManager(session=db)


@router.post("", response_model=StoryResponse, status_code=status.HTTP_200_OK)
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


@router.post(":search", response_model=PaginatedResponse[StoryResponse])
async def search_stories(
    payload: SearchRequest, db: AsyncSession = Depends(get_db)
) -> PaginatedResponse[StoryResponse]:
    """Search stories using ENSI filter and offset pagination."""
    filters = payload.filter
    character_id = (
        int(str(filters["character_id"])) if filters.get("character_id") is not None else None
    )
    event_id = int(str(filters["event_id"])) if filters.get("event_id") is not None else None
    event_role = EventRole(filters["role"]) if filters.get("role") else None
    search = str(filters["q"]) if filters.get("q") is not None else None
    supported_includes: set[str] = set()
    unsupported_includes = set(payload.include) - supported_includes
    if unsupported_includes:
        raise ConflictException(
            f"Unsupported include values: {', '.join(sorted(unsupported_includes))}"
        )
    supported_sorts = {"id", "title", "created_at", "sort_order"}
    invalid_sorts = {
        item.lstrip("-") for item in payload.sort if item.lstrip("-") not in supported_sorts
    }
    if invalid_sorts:
        raise ConflictException(f"Unsupported sort fields: {', '.join(sorted(invalid_sorts))}")
    offset = payload.pagination.offset
    limit = payload.pagination.limit
    page_size = 1_000_000 if limit < 0 else limit
    page = (offset // page_size + 1) if page_size > 0 else 1
    search_engine = SearchEngine(session=db)
    stories, total = await search_engine.search_stories(
        character_id=character_id,
        event_id=event_id,
        event_role=event_role,
        query_text=search,
        page=page,
        per_page=page_size,
        offset=offset,
        sort=payload.sort,
    )
    return PaginatedResponse(
        data=stories,
        meta=MetaPagination(current_page=page, per_page=page_size, total=total),
    )


@router.get("/{story_id}", response_model=StoryDetailResponse)
async def get_story_by_id(story_id: int, db: AsyncSession = Depends(get_db)) -> StoryDetailResponse:
    manager = StoryManager(session=db)
    story = await manager.get_story_detail(story_id)
    if not story:
        raise ResourceNotFoundException("Story", story_id)
    return story


@router.patch("/{story_id}", response_model=StoryResponse)
async def update_story_by_id(
    story_id: int,
    payload: StoryUpdate,
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    manager = StoryManager(session=db)
    updated = await manager.update_story(story_id, payload)
    if not updated:
        raise ResourceNotFoundException("Story", story_id)
    return updated


@router.delete("/{story_id}", status_code=status.HTTP_200_OK)
async def delete_story_by_id(story_id: int, db: AsyncSession = Depends(get_db)) -> None:
    manager = StoryManager(session=db)
    # ENSI deletion is idempotent: a missing story is already in the desired state.
    await manager.delete_story(story_id)

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from story_app.models.entities import EventRole

T = TypeVar("T")


class StoryEventInput(BaseModel):
    event_id: int
    role: EventRole = Field(default=EventRole.REFERENCES)


class StoryEventResponse(BaseModel):
    event_id: int
    role: EventRole
    model_config = ConfigDict(from_attributes=True)


class StoryBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: str | None = Field(default=None)


class StoryCreate(StoryBase):
    character_ids: list[int] = Field(default_factory=list)
    events: list[StoryEventInput] = Field(default_factory=list)
    primary_event_id: int | None = Field(
        default=None, description="Key canon milestone under which this story takes place"
    )
    sort_order: int = Field(default=0, description="Order index of this story within the milestone")
    content: str | None = Field(default=None, description="Story text content to save as txt file")


class StoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = None
    content: str | None = None
    primary_event_id: int | None = None
    sort_order: int | None = None
    character_ids: list[int] | None = None
    events: list[StoryEventInput] | None = None


class ConsistencyWarningDTO(BaseModel):
    code: str
    event_id: int | None = None
    event_title: str | None = None
    character_id: int | None = None
    message: str
    missing_prerequisites: list[str] = Field(default_factory=list)


class StoryResponse(StoryBase):
    id: int
    created_at: datetime
    file_path: str | None = None
    primary_event_id: int | None = None
    sort_order: int = 0
    character_ids: list[int] = Field(default_factory=list)
    events: list[StoryEventResponse] = Field(default_factory=list)
    search_excerpt: str | None = Field(
        default=None, description="Text fragment matching the search query"
    )
    warnings: list[ConsistencyWarningDTO] = Field(
        default_factory=list,
        description="Canon consistency warnings returned by Lore Service",
    )
    model_config = ConfigDict(from_attributes=True)


class StoryDetailResponse(StoryResponse):
    content: str | None = Field(default=None, description="Loaded text content if txt file exists")


class SearchPagination(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=-1, le=1000)


class SearchRequest(BaseModel):
    filter: dict[str, object] = Field(default_factory=dict)
    sort: list[str] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)
    pagination: SearchPagination = Field(default_factory=SearchPagination)


class MetaPagination(BaseModel):
    current_page: int
    per_page: int
    total: int
    offset: int | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: MetaPagination

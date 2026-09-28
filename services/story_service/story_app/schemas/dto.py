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
    content: str | None = Field(default=None, description="Story text content to save as txt file")


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
    character_ids: list[int] = Field(default_factory=list)
    events: list[StoryEventResponse] = Field(default_factory=list)
    warnings: list[ConsistencyWarningDTO] = Field(
        default_factory=list,
        description="Canon consistency warnings returned by Lore Service",
    )
    model_config = ConfigDict(from_attributes=True)


class StoryDetailResponse(StoryResponse):
    content: str | None = Field(default=None, description="Loaded text content if txt file exists")


class MetaPagination(BaseModel):
    current_page: int
    per_page: int
    total: int


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: MetaPagination

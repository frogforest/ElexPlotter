from datetime import datetime
from typing import Generic, TypeVar

from lore_app.models.entities import CharacterType, EventType, ParticipantRole
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# Base schemas
class CharacterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Unique character name")
    type: CharacterType = Field(default=CharacterType.COMPANION)
    description: str | None = Field(default=None, max_length=500)


class CharacterCreate(CharacterBase):
    pass


class CharacterResponse(CharacterBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ParticipantInput(BaseModel):
    character_id: int
    role: ParticipantRole = Field(default=ParticipantRole.PARTICIPANT)


class ParticipantResponse(BaseModel):
    character_id: int
    character_name: str
    role: ParticipantRole
    model_config = ConfigDict(from_attributes=True)


class WorldEventBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Unique event title")
    type: EventType = Field(default=EventType.PLOT_MILESTONE)
    description: str | None = Field(default=None, max_length=1000)


class WorldEventCreate(WorldEventBase):
    parent_ids: list[int] = Field(default_factory=list, description="IDs of prerequisite events")
    participants: list[ParticipantInput] = Field(
        default_factory=list, description="Participating characters"
    )


class WorldEventResponse(WorldEventBase):
    id: int
    created_at: datetime
    parent_ids: list[int] = Field(default_factory=list)
    child_ids: list[int] = Field(default_factory=list)
    participants: list[ParticipantResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class DependencyCreate(BaseModel):
    parent_id: int = Field(..., description="ID of the prerequisite event")
    child_id: int = Field(..., description="ID of the event that depends on parent")


class DependencyResponse(BaseModel):
    id: int
    parent_id: int
    child_id: int
    model_config = ConfigDict(from_attributes=True)


# Consistency Check schemas
class ConsistencyCheckRequest(BaseModel):
    requires: list[int] = Field(
        default_factory=list, description="Event IDs that must be true prior to story"
    )
    creates: list[int] = Field(
        default_factory=list, description="Event IDs that this story establishes/creates"
    )
    participating_character_ids: list[int] = Field(
        default_factory=list, description="Characters participating in this story"
    )


class ConsistencyWarning(BaseModel):
    code: str
    event_id: int | None = None
    event_title: str | None = None
    character_id: int | None = None
    message: str
    missing_prerequisites: list[str] = Field(default_factory=list)


class ConsistencyCheckResponse(BaseModel):
    valid: bool
    warnings: list[ConsistencyWarning] = Field(default_factory=list)
    timeline_order: list[int] = Field(
        default_factory=list,
        description="Topologically sorted sequence of relevant events",
    )


# Pagination response wrapper in ENSI API Guide format
class MetaPagination(BaseModel):
    current_page: int
    per_page: int
    total: int


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: MetaPagination

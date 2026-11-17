from typing import Any

from fastapi import APIRouter, Depends, Query, status
from lore_app.core.database import get_db
from lore_app.core.exceptions import ConflictException, ResourceNotFoundException
from lore_app.models.entities import Character, CharacterType, EventParticipant
from lore_app.schemas.dto import (
    CharacterCreate,
    CharacterResponse,
    CharacterUpdate,
    MetaPagination,
    PaginatedResponse,
    SearchRequest,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

router = APIRouter(prefix="/characters", tags=["Characters"])


@router.post("", response_model=CharacterResponse, status_code=status.HTTP_200_OK)
async def create_character(
    payload: CharacterCreate, db: AsyncSession = Depends(get_db)
) -> CharacterResponse:
    existing = await db.execute(select(Character).where(Character.name == payload.name))
    if existing.scalar_one_or_none():
        raise ConflictException(f"Character with name '{payload.name}' already exists.")

    character = Character(
        name=payload.name,
        type=payload.type,
        description=payload.description,
    )
    db.add(character)
    await db.flush()
    await db.refresh(character)
    return CharacterResponse.model_validate(character)


@router.get("", response_model=PaginatedResponse[CharacterResponse])
async def list_characters(
    character_type: CharacterType | None = Query(default=None, alias="filter[type]"),
    page: int = Query(default=1, ge=1, alias="page[number]"),
    per_page: int = Query(default=20, ge=1, le=100, alias="page[size]"),
    db: AsyncSession = Depends(get_db),
    offset: int | None = None,
) -> PaginatedResponse[CharacterResponse]:
    query = select(Character)
    if character_type:
        query = query.where(Character.type == character_type)

    total_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(total_query)
    total = total_res.scalar_one()

    query = (
        query.order_by(Character.id)
        .offset(offset if offset is not None else (page - 1) * per_page)
        .limit(per_page)
    )
    res = await db.execute(query)
    characters = res.scalars().all()

    return PaginatedResponse(
        data=[CharacterResponse.model_validate(c) for c in characters],
        meta=MetaPagination(current_page=page, per_page=per_page, total=total),
    )


@router.post(":search", response_model=PaginatedResponse[CharacterResponse])
async def search_characters(
    payload: SearchRequest, db: AsyncSession = Depends(get_db)
) -> PaginatedResponse[CharacterResponse]:
    """ENSI search with deterministic sorting and offset pagination."""
    raw_type = payload.filter.get("type")
    character_type = CharacterType(raw_type) if raw_type else None
    query = select(Character)
    if character_type is not None:
        query = query.where(Character.type == character_type)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar_one()

    sort_columns = {"id": Character.id, "name": Character.name, "type": Character.type}
    order_by: list[ColumnElement[Any]] = []
    for item in payload.sort:
        descending = item.startswith("-")
        field = item[1:] if descending else item
        column = sort_columns.get(field)
        if column is None:
            raise ConflictException(f"Unsupported sort field: {field}")
        order_by.append(column.desc() if descending else column.asc())
    if not order_by:
        order_by = [Character.id.asc()]
    query = query.order_by(*order_by)

    offset = payload.pagination.offset
    limit = payload.pagination.limit
    query = query.offset(offset)
    if limit >= 0:
        query = query.limit(limit)
    result = await db.execute(query)
    characters = result.scalars().all()
    page = (offset // limit + 1) if limit > 0 else 1
    return PaginatedResponse(
        data=[CharacterResponse.model_validate(c) for c in characters],
        meta=MetaPagination(current_page=page, per_page=limit, total=total, offset=offset),
    )


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(character_id: int, db: AsyncSession = Depends(get_db)) -> CharacterResponse:
    res = await db.execute(select(Character).where(Character.id == character_id))
    character = res.scalar_one_or_none()
    if not character:
        raise ResourceNotFoundException("Character", character_id)
    return CharacterResponse.model_validate(character)


@router.patch("/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: int,
    payload: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
) -> CharacterResponse:
    """Update a character's editable fields."""
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    if character is None:
        raise ResourceNotFoundException("Character", character_id)

    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != character.name:
        existing = await db.execute(
            select(Character).where(
                Character.name == changes["name"],
                Character.id != character_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictException(f"Character with name '{changes['name']}' already exists.")

    for field, value in changes.items():
        setattr(character, field, value)

    await db.flush()
    await db.commit()
    await db.refresh(character)
    return CharacterResponse.model_validate(character)


@router.delete("/{character_id}", status_code=status.HTTP_200_OK)
async def delete_character(
    character_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a character and its event-participation links.

    Event records and their DAG dependencies are deliberately preserved.
    Repeated deletion is idempotent under the ENSI API contract.
    """
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    if character is None:
        return

    participations = await db.execute(
        select(EventParticipant).where(EventParticipant.character_id == character_id)
    )
    for participation in participations.scalars().all():
        await db.delete(participation)

    await db.delete(character)
    await db.flush()
    await db.commit()

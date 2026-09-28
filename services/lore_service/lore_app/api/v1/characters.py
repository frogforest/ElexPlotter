from fastapi import APIRouter, Depends, Query, status
from lore_app.core.database import get_db
from lore_app.core.exceptions import ConflictException, ResourceNotFoundException
from lore_app.models.entities import Character, CharacterType
from lore_app.schemas.dto import (
    CharacterCreate,
    CharacterResponse,
    MetaPagination,
    PaginatedResponse,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/characters", tags=["Characters"])


@router.post("", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED)
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
) -> PaginatedResponse[CharacterResponse]:
    query = select(Character)
    if character_type:
        query = query.where(Character.type == character_type)

    total_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(total_query)
    total = total_res.scalar_one()

    query = query.order_by(Character.id).offset((page - 1) * per_page).limit(per_page)
    res = await db.execute(query)
    characters = res.scalars().all()

    return PaginatedResponse(
        data=[CharacterResponse.model_validate(c) for c in characters],
        meta=MetaPagination(current_page=page, per_page=per_page, total=total),
    )


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(character_id: int, db: AsyncSession = Depends(get_db)) -> CharacterResponse:
    res = await db.execute(select(Character).where(Character.id == character_id))
    character = res.scalar_one_or_none()
    if not character:
        raise ResourceNotFoundException("Character", character_id)
    return CharacterResponse.model_validate(character)

from fastapi import APIRouter, Depends, Query, status
from lore_app.core.database import get_db
from lore_app.core.exceptions import ConflictException, ResourceNotFoundException
from lore_app.models.entities import (
    Character,
    EventDependency,
    EventParticipant,
    EventType,
    WorldEvent,
)
from lore_app.schemas.dto import (
    DependencyCreate,
    DependencyResponse,
    MetaPagination,
    PaginatedResponse,
    ParticipantResponse,
    WorldEventCreate,
    WorldEventResponse,
)
from lore_app.services.graph_manager import DependencyGraphManager
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/world-events", tags=["World Events"])


def _to_event_response(event: WorldEvent) -> WorldEventResponse:
    participants = [
        ParticipantResponse(
            character_id=p.character_id,
            character_name=p.character.name if p.character else "",
            role=p.role,
        )
        for p in event.participants
    ]
    parent_ids = [e.parent_id for e in event.parent_edges]
    child_ids = [e.child_id for e in event.child_edges]

    return WorldEventResponse(
        id=event.id,
        title=event.title,
        type=event.type,
        description=event.description,
        created_at=event.created_at,
        parent_ids=parent_ids,
        child_ids=child_ids,
        participants=participants,
    )


@router.post("", response_model=WorldEventResponse, status_code=status.HTTP_201_CREATED)
async def create_world_event(
    payload: WorldEventCreate, db: AsyncSession = Depends(get_db)
) -> WorldEventResponse:
    existing = await db.execute(select(WorldEvent).where(WorldEvent.title == payload.title))
    if existing.scalar_one_or_none():
        raise ConflictException(f"WorldEvent with title '{payload.title}' already exists.")

    # Validate parent existence
    if payload.parent_ids:
        parents_res = await db.execute(
            select(WorldEvent).where(WorldEvent.id.in_(payload.parent_ids))
        )
        found_parent_ids = {p.id for p in parents_res.scalars().all()}
        for pid in payload.parent_ids:
            if pid not in found_parent_ids:
                raise ResourceNotFoundException("Parent WorldEvent", pid)

    # Validate participants existence
    if payload.participants:
        p_cids = [p.character_id for p in payload.participants]
        chars_res = await db.execute(select(Character).where(Character.id.in_(p_cids)))
        found_cids = {c.id for c in chars_res.scalars().all()}
        for cid in p_cids:
            if cid not in found_cids:
                raise ResourceNotFoundException("Character", cid)

    event = WorldEvent(
        title=payload.title,
        type=payload.type,
        description=payload.description,
    )
    db.add(event)
    await db.flush()

    for pid in payload.parent_ids:
        db.add(EventDependency(parent_id=pid, child_id=event.id))

    for p in payload.participants:
        db.add(EventParticipant(event_id=event.id, character_id=p.character_id, role=p.role))

    await db.flush()

    # Re-fetch full object with relations
    res = await db.execute(
        select(WorldEvent)
        .options(
            selectinload(WorldEvent.participants).selectinload(EventParticipant.character),
            selectinload(WorldEvent.parent_edges),
            selectinload(WorldEvent.child_edges),
        )
        .where(WorldEvent.id == event.id)
    )
    saved_event = res.scalar_one()
    return _to_event_response(saved_event)


@router.get("", response_model=PaginatedResponse[WorldEventResponse])
async def list_world_events(
    event_type: EventType | None = Query(default=None, alias="filter[type]"),
    character_id: int | None = Query(default=None, alias="filter[character_id]"),
    page: int = Query(default=1, ge=1, alias="page[number]"),
    per_page: int = Query(default=20, ge=1, le=100, alias="page[size]"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[WorldEventResponse]:
    query = (
        select(WorldEvent)
        .options(
            selectinload(WorldEvent.participants).selectinload(EventParticipant.character),
            selectinload(WorldEvent.parent_edges),
            selectinload(WorldEvent.child_edges),
        )
        .distinct()
    )

    if event_type:
        query = query.where(WorldEvent.type == event_type)
    if character_id:
        query = query.join(WorldEvent.participants).where(
            EventParticipant.character_id == character_id
        )

    total_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(total_query)
    total = total_res.scalar_one()

    query = query.order_by(WorldEvent.id).offset((page - 1) * per_page).limit(per_page)
    res = await db.execute(query)
    events = res.scalars().all()

    return PaginatedResponse(
        data=[_to_event_response(e) for e in events],
        meta=MetaPagination(current_page=page, per_page=per_page, total=total),
    )


@router.post(
    "/dependencies", response_model=DependencyResponse, status_code=status.HTTP_201_CREATED
)
async def add_dependency(
    payload: DependencyCreate, db: AsyncSession = Depends(get_db)
) -> DependencyResponse:
    if payload.parent_id == payload.child_id:
        raise ConflictException("An event cannot depend on itself.")

    parent = await db.execute(select(WorldEvent).where(WorldEvent.id == payload.parent_id))
    if not parent.scalar_one_or_none():
        raise ResourceNotFoundException("Parent WorldEvent", payload.parent_id)

    child = await db.execute(select(WorldEvent).where(WorldEvent.id == payload.child_id))
    if not child.scalar_one_or_none():
        raise ResourceNotFoundException("Child WorldEvent", payload.child_id)

    # Check for existing dependency
    existing = await db.execute(
        select(EventDependency).where(
            EventDependency.parent_id == payload.parent_id,
            EventDependency.child_id == payload.child_id,
        )
    )
    existing_dep = existing.scalar_one_or_none()
    if existing_dep:
        return DependencyResponse.model_validate(existing_dep)

    # Cycle check via DAG
    all_events_res = await db.execute(select(WorldEvent.id))
    all_event_ids = [r[0] for r in all_events_res.all()]
    all_deps_res = await db.execute(select(EventDependency.parent_id, EventDependency.child_id))
    all_deps = [(r[0], r[1]) for r in all_deps_res.all()]

    graph_mgr = DependencyGraphManager()
    graph_mgr.build_from_dependencies(all_event_ids, all_deps)
    graph_mgr.validate_new_edge(payload.parent_id, payload.child_id)

    dependency = EventDependency(parent_id=payload.parent_id, child_id=payload.child_id)
    db.add(dependency)
    await db.flush()
    await db.refresh(dependency)
    return DependencyResponse.model_validate(dependency)

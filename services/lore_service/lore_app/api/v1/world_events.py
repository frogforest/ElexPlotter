from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
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
    ReorderEventsRequest,
    SearchRequest,
    WorldEventCreate,
    WorldEventResponse,
    WorldEventUpdate,
)
from lore_app.services.graph_manager import DependencyGraphManager
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

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
        sort_order=event.sort_order,
        created_at=event.created_at,
        parent_ids=parent_ids,
        child_ids=child_ids,
        participants=participants,
    )


@router.post("", response_model=WorldEventResponse, status_code=status.HTTP_200_OK)
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
    offset: int | None = None,
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

    query = (
        query.order_by(WorldEvent.sort_order, WorldEvent.id)
        .offset(offset if offset is not None else (page - 1) * per_page)
        .limit(per_page)
    )
    res = await db.execute(query)
    events = res.scalars().all()

    return PaginatedResponse(
        data=[_to_event_response(e) for e in events],
        meta=MetaPagination(current_page=page, per_page=per_page, total=total),
    )


@router.post(":search", response_model=PaginatedResponse[WorldEventResponse])
async def search_world_events(
    payload: SearchRequest, db: AsyncSession = Depends(get_db)
) -> PaginatedResponse[WorldEventResponse]:
    """ENSI search with deterministic sorting and offset pagination."""
    raw_type = payload.filter.get("type")
    event_type = EventType(raw_type) if raw_type else None
    raw_character_id = payload.filter.get("character_id")
    character_id = int(str(raw_character_id)) if raw_character_id is not None else None

    query = (
        select(WorldEvent)
        .options(
            selectinload(WorldEvent.participants).selectinload(EventParticipant.character),
            selectinload(WorldEvent.parent_edges),
            selectinload(WorldEvent.child_edges),
        )
        .distinct()
    )
    if event_type is not None:
        query = query.where(WorldEvent.type == event_type)
    if character_id is not None:
        query = query.join(WorldEvent.participants).where(
            EventParticipant.character_id == character_id
        )

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar_one()

    sort_columns = {
        "id": WorldEvent.id,
        "title": WorldEvent.title,
        "type": WorldEvent.type,
        "sort_order": WorldEvent.sort_order,
        "created_at": WorldEvent.created_at,
    }
    order_by: list[ColumnElement[Any]] = []
    for item in payload.sort:
        descending = item.startswith("-")
        field = item[1:] if descending else item
        column = sort_columns.get(field)
        if column is None:
            raise ConflictException(f"Unsupported sort field: {field}")
        order_by.append(column.desc() if descending else column.asc())
    if not order_by:
        order_by = [WorldEvent.sort_order.asc(), WorldEvent.id.asc()]
    query = query.order_by(*order_by).offset(payload.pagination.offset)
    if payload.pagination.limit >= 0:
        query = query.limit(payload.pagination.limit)

    result = await db.execute(query)
    events = result.scalars().unique().all()
    limit = payload.pagination.limit
    offset = payload.pagination.offset
    page = (offset // limit + 1) if limit > 0 else 1
    return PaginatedResponse(
        data=[_to_event_response(event) for event in events],
        meta=MetaPagination(current_page=page, per_page=limit, total=total, offset=offset),
    )


@router.get("/{event_id}", response_model=WorldEventResponse)
async def get_world_event(event_id: int, db: AsyncSession = Depends(get_db)) -> WorldEventResponse:
    res = await db.execute(
        select(WorldEvent)
        .options(
            selectinload(WorldEvent.participants).selectinload(EventParticipant.character),
            selectinload(WorldEvent.parent_edges),
            selectinload(WorldEvent.child_edges),
        )
        .where(WorldEvent.id == event_id)
    )
    event = res.scalar_one_or_none()
    if not event:
        raise ResourceNotFoundException("WorldEvent", event_id)
    return _to_event_response(event)


@router.patch("/{event_id}", response_model=WorldEventResponse)
async def update_world_event(
    event_id: int, payload: WorldEventUpdate, db: AsyncSession = Depends(get_db)
) -> WorldEventResponse:
    res = await db.execute(
        select(WorldEvent)
        .options(
            selectinload(WorldEvent.participants).selectinload(EventParticipant.character),
            selectinload(WorldEvent.parent_edges),
            selectinload(WorldEvent.child_edges),
        )
        .where(WorldEvent.id == event_id)
    )
    event = res.scalar_one_or_none()
    if not event:
        raise ResourceNotFoundException("WorldEvent", event_id)

    if payload.title is not None and payload.title != event.title:
        existing = await db.execute(
            select(WorldEvent).where(WorldEvent.title == payload.title, WorldEvent.id != event_id)
        )
        if existing.scalar_one_or_none():
            raise ConflictException(f"WorldEvent with title '{payload.title}' already exists.")
        event.title = payload.title

    if payload.type is not None:
        event.type = payload.type
    if payload.description is not None:
        event.description = payload.description

    # Update participants if provided
    if payload.participants is not None:
        del_parts = await db.execute(
            select(EventParticipant).where(EventParticipant.event_id == event_id)
        )
        for p in del_parts.scalars().all():
            await db.delete(p)
        await db.flush()

        for part_input in payload.participants:
            db.add(
                EventParticipant(
                    event_id=event.id,
                    character_id=part_input.character_id,
                    role=part_input.role,
                )
            )

    # Update parent_ids if provided
    if payload.parent_ids is not None:
        clean_parent_ids = [pid for pid in payload.parent_ids if pid != event_id]
        if clean_parent_ids:
            parents_res = await db.execute(
                select(WorldEvent).where(WorldEvent.id.in_(clean_parent_ids))
            )
            found_parent_ids = {p.id for p in parents_res.scalars().all()}
            for pid in clean_parent_ids:
                if pid not in found_parent_ids:
                    raise ResourceNotFoundException("Parent WorldEvent", pid)

        # Validate DAG cycles with proposed edges
        all_events_res = await db.execute(select(WorldEvent.id))
        all_event_ids = [r[0] for r in all_events_res.all()]
        other_deps_res = await db.execute(
            select(EventDependency.parent_id, EventDependency.child_id).where(
                EventDependency.child_id != event_id
            )
        )
        simulated_deps = [(r[0], r[1]) for r in other_deps_res.all()]
        for pid in clean_parent_ids:
            simulated_deps.append((pid, event_id))

        graph_mgr = DependencyGraphManager()
        graph_mgr.build_from_dependencies(all_event_ids, simulated_deps)

        # Ensure child's sort_order is after all parents
        if clean_parent_ids:
            parents_sort_res = await db.execute(
                select(func.max(WorldEvent.sort_order)).where(WorldEvent.id.in_(clean_parent_ids))
            )
            max_parent_sort = parents_sort_res.scalar()
            if max_parent_sort is not None and event.sort_order <= max_parent_sort:
                event.sort_order = max_parent_sort + 1

        del_deps = await db.execute(
            select(EventDependency).where(EventDependency.child_id == event_id)
        )
        for d in del_deps.scalars().all():
            await db.delete(d)
        await db.flush()

        for pid in clean_parent_ids:
            db.add(EventDependency(parent_id=pid, child_id=event.id))

    await db.flush()
    await db.commit()
    db.expire_all()

    # Re-fetch
    res = await db.execute(
        select(WorldEvent)
        .options(
            selectinload(WorldEvent.participants).selectinload(EventParticipant.character),
            selectinload(WorldEvent.parent_edges),
            selectinload(WorldEvent.child_edges),
        )
        .where(WorldEvent.id == event_id)
    )
    updated = res.scalar_one()
    return _to_event_response(updated)


@router.delete("/{event_id}", status_code=status.HTTP_200_OK)
async def delete_world_event(event_id: int, db: AsyncSession = Depends(get_db)) -> None:
    res = await db.execute(select(WorldEvent).where(WorldEvent.id == event_id))
    event = res.scalar_one_or_none()
    # ENSI deletion is idempotent: deleting an already absent resource succeeds.
    if not event:
        return

    # Delete participants
    parts = await db.execute(select(EventParticipant).where(EventParticipant.event_id == event_id))
    for p in parts.scalars().all():
        await db.delete(p)

    # Delete dependencies (where this event is parent or child)
    deps = await db.execute(
        select(EventDependency).where(
            (EventDependency.parent_id == event_id) | (EventDependency.child_id == event_id)
        )
    )
    for d in deps.scalars().all():
        await db.delete(d)

    await db.delete(event)
    await db.flush()
    await db.commit()


@router.post("/dependencies", response_model=DependencyResponse, status_code=status.HTTP_200_OK)
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


@router.delete("/dependencies", status_code=status.HTTP_200_OK)
async def delete_dependency(
    parent_id: int = Query(...),
    child_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    res = await db.execute(
        select(EventDependency).where(
            EventDependency.parent_id == parent_id,
            EventDependency.child_id == child_id,
        )
    )
    dep = res.scalar_one_or_none()
    if dep:
        await db.delete(dep)
        await db.flush()


@router.post(
    ":reorder",
    response_model=list[WorldEventResponse],
)
async def reorder_world_events(
    payload: ReorderEventsRequest,
    db: AsyncSession = Depends(get_db),
) -> list[WorldEventResponse] | JSONResponse:
    """Reorder events, asking for explicit confirmation before deleting edges.

    First request:
        Send ``items`` without ``confirmed_dependency_ids``. If the proposed
        order contradicts existing dependencies, the endpoint returns 400 and
        lists the exact dependency IDs that would be removed.

    Confirmation request:
        Repeat the same ``items`` and send those IDs in
        ``confirmed_dependency_ids``. The operation is applied only if the
        current set of conflicting dependencies exactly matches the confirmed
        set. This prevents a stale confirmation from deleting unseen edges.
    """
    event_ids = [item.event_id for item in payload.items]

    if not event_ids:
        raise ConflictException("At least one event must be provided for reordering.")

    if len(event_ids) != len(set(event_ids)):
        raise ConflictException("The reorder request contains duplicate event IDs.")

    confirmed_ids = set(payload.confirmed_dependency_ids)
    if len(payload.confirmed_dependency_ids) != len(confirmed_ids):
        raise ConflictException("The confirmation contains duplicate dependency IDs.")

    # Load all events so dependencies involving events outside the submitted
    # reorder subset are checked as well.
    events_result = await db.execute(select(WorldEvent))
    all_events = events_result.scalars().all()
    events_by_id = {event.id: event for event in all_events}

    missing_event_ids = set(event_ids) - events_by_id.keys()
    if missing_event_ids:
        missing_id = min(missing_event_ids)
        raise ResourceNotFoundException("WorldEvent", missing_id)

    # Build the proposed timeline without mutating ORM objects yet.
    proposed_order = {event.id: event.sort_order for event in all_events}
    for item in payload.items:
        proposed_order[item.event_id] = item.sort_order

    # A dependency is violated when its parent is not earlier than its child.
    dependencies_result = await db.execute(
        select(EventDependency).where(
            or_(
                EventDependency.parent_id.in_(event_ids),
                EventDependency.child_id.in_(event_ids),
            )
        )
    )
    dependencies = dependencies_result.scalars().all()

    conflicting_dependencies = []
    conflicting_ids = set()

    for dependency in dependencies:
        parent = events_by_id[dependency.parent_id]
        child = events_by_id[dependency.child_id]

        if proposed_order[parent.id] >= proposed_order[child.id]:
            conflicting_ids.add(dependency.id)
            conflicting_dependencies.append(
                {
                    "dependency_id": dependency.id,
                    "parent_id": parent.id,
                    "parent_title": parent.title,
                    "child_id": child.id,
                    "child_title": child.title,
                }
            )

    # Never accept a confirmation that does not exactly match the current
    # conflicts. The client must show the updated warning and ask again.
    if confirmed_ids != conflicting_ids:
        if conflicting_ids:
            code = (
                "STALE_CONFIRMATION"
                if confirmed_ids
                else "DEPENDENCY_REMOVAL_CONFIRMATION_REQUIRED"
            )
            detail = (
                "The dependency graph changed after the previous warning. "
                "Review the current conflicts and confirm them again."
                if confirmed_ids
                else (
                    "The proposed order contradicts existing cause-and-effect "
                    "dependencies. Removing these links may change the meaning "
                    "of the canon and affect related stories."
                )
            )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "data": None,
                    "errors": [
                        {
                            "code": code,
                            "message": detail,
                            "meta": {
                                "confirmation_required": True,
                                "dependencies": conflicting_dependencies,
                                "required_confirmation_ids": sorted(conflicting_ids),
                            },
                        }
                    ],
                },
            )

        if confirmed_ids:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "data": None,
                    "errors": [
                        {
                            "code": "STALE_CONFIRMATION",
                            "message": (
                                "The previously confirmed dependencies no longer "
                                "conflict with this order. Submit the reorder request "
                                "again without confirmed_dependency_ids."
                            ),
                            "meta": {
                                "confirmation_required": False,
                                "dependencies": [],
                                "required_confirmation_ids": [],
                            },
                        }
                    ],
                },
            )

    # All validation is complete. Apply order changes and remove only the
    # exact dependencies explicitly confirmed by the user.
    try:
        for item in payload.items:
            events_by_id[item.event_id].sort_order = item.sort_order

        for dependency in dependencies:
            if dependency.id in confirmed_ids:
                await db.delete(dependency)

        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # Re-fetch the submitted events with fresh relationship data so the
    # response reflects the updated dependency graph.
    updated_result = await db.execute(
        select(WorldEvent)
        .options(
            selectinload(WorldEvent.participants).selectinload(EventParticipant.character),
            selectinload(WorldEvent.parent_edges),
            selectinload(WorldEvent.child_edges),
        )
        .where(WorldEvent.id.in_(event_ids))
        .execution_options(populate_existing=True)
    )
    updated_events = updated_result.scalars().all()
    ordered_events = sorted(
        updated_events,
        key=lambda event: (event.sort_order, event.id),
    )
    return [_to_event_response(event) for event in ordered_events]

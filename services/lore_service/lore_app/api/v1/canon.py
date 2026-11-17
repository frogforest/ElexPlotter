from fastapi import APIRouter, Depends
from lore_app.api.v1.world_events import _to_event_response
from lore_app.core.database import get_db
from lore_app.schemas.dto import (
    ConsistencyCheckRequest,
    ConsistencyCheckResponse,
    WorldEventResponse,
)
from lore_app.services.consistency_checker import ConsistencyChecker
from lore_app.services.timeline_builder import TimelineBuilder
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["Canon Engine"])


@router.post(
    "/canon:check-consistency",
    response_model=ConsistencyCheckResponse,
    operation_id="check_canon_consistency",
)
async def check_consistency(
    payload: ConsistencyCheckRequest, db: AsyncSession = Depends(get_db)
) -> ConsistencyCheckResponse:
    """Evaluates narrative canon consistency, missing prerequisites, and participant logic."""
    checker = ConsistencyChecker(db)
    return await checker.check(payload)


@router.get("/timeline", response_model=list[WorldEventResponse])
async def get_chronological_timeline(
    db: AsyncSession = Depends(get_db),
) -> list[WorldEventResponse]:
    """Returns all canon world events in topologically sorted chronological order."""
    builder = TimelineBuilder(db)
    events = await builder.get_chronological_events()
    return [_to_event_response(e) for e in events]

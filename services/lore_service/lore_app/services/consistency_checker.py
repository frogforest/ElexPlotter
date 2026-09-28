from lore_app.models.entities import Character, EventDependency, EventParticipant, WorldEvent
from lore_app.schemas.dto import (
    ConsistencyCheckRequest,
    ConsistencyCheckResponse,
    ConsistencyWarning,
)
from lore_app.services.graph_manager import DependencyGraphManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


class ConsistencyChecker:
    """Validates narrative canon consistency, missing prerequisites, and participant logic."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def check(self, request: ConsistencyCheckRequest) -> ConsistencyCheckResponse:
        # 1. Fetch all events and their dependencies from DB
        events_res = await self.session.execute(
            select(WorldEvent).options(
                selectinload(WorldEvent.participants).selectinload(EventParticipant.character)
            )
        )
        all_events = {e.id: e for e in events_res.scalars().all()}

        deps_res = await self.session.execute(select(EventDependency))
        all_deps = [(d.parent_id, d.child_id) for d in deps_res.scalars().all()]

        # 2. Build DAG
        graph_mgr = DependencyGraphManager()
        graph_mgr.build_from_dependencies(list(all_events.keys()), all_deps)

        warnings: list[ConsistencyWarning] = []
        satisfied_events = set(request.requires)

        # Check missing requires existence
        for req_id in request.requires:
            if req_id not in all_events:
                warnings.append(
                    ConsistencyWarning(
                        code="MISSING_REQUIRE_EVENT",
                        event_id=req_id,
                        message=f"Required event ID {req_id} does not exist in canon database.",
                    )
                )

        # 3. For each created event, check if its prerequisite DAG ancestors are in requires
        for create_id in request.creates:
            event = all_events.get(create_id)
            if not event:
                warnings.append(
                    ConsistencyWarning(
                        code="UNKNOWN_CREATED_EVENT",
                        event_id=create_id,
                        message=f"Created event ID {create_id} does not exist in canon database.",
                    )
                )
                continue

            ancestors = graph_mgr.get_prerequisites(create_id)
            missing = ancestors - satisfied_events

            if missing:
                missing_titles = [all_events[m].title for m in missing if m in all_events]
                warnings.append(
                    ConsistencyWarning(
                        code="MISSING_PREREQUISITES",
                        event_id=create_id,
                        event_title=event.title,
                        message=(
                            f"For event '{event.title}', the following canon prerequisites "
                            f"are not satisfied in requirements: {', '.join(missing_titles)}"
                        ),
                        missing_prerequisites=missing_titles,
                    )
                )

        # 4. Check participating characters
        if request.participating_character_ids:
            chars_res = await self.session.execute(
                select(Character).where(Character.id.in_(request.participating_character_ids))
            )
            existing_char_ids = {c.id for c in chars_res.scalars().all()}
            for cid in request.participating_character_ids:
                if cid not in existing_char_ids:
                    warnings.append(
                        ConsistencyWarning(
                            code="UNKNOWN_CHARACTER",
                            character_id=cid,
                            message=f"Participating character ID {cid} does not exist in canon.",
                        )
                    )

            # Check if created events involve characters not declared in story participants
            for create_id in request.creates:
                event = all_events.get(create_id)
                if not event:
                    continue
                for participant in event.participants:
                    if participant.character_id not in request.participating_character_ids:
                        char_name = (
                            participant.character.name
                            if participant.character
                            else str(participant.character_id)
                        )
                        warnings.append(
                            ConsistencyWarning(
                                code="UNMENTIONED_EVENT_PARTICIPANT",
                                event_id=create_id,
                                event_title=event.title,
                                character_id=participant.character_id,
                                message=(
                                    f"Event '{event.title}' involves character '{char_name}', "
                                    f"but this character is not marked as participating in this story."
                                ),
                            )
                        )

        # 5. Build timeline order of all relevant events (requires + creates)
        relevant_event_ids = list(set(request.requires + request.creates))
        timeline_order: list[int] = []
        try:
            timeline_order = graph_mgr.topological_sort(relevant_event_ids)
        except Exception:
            timeline_order = relevant_event_ids

        return ConsistencyCheckResponse(
            valid=len(warnings) == 0,
            warnings=warnings,
            timeline_order=timeline_order,
        )

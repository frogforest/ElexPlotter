from lore_app.models.entities import (
    Character,
    EventDependency,
    EventParticipant,
    EventType,
    WorldEvent,
)
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
    """Validate event prerequisites and character presence/life status."""

    INTRODUCTION_TYPES = (EventType.COMPANION_JOIN, EventType.NPC_APPEAR)

    def __init__(self, session: AsyncSession):
        self.session = session

    async def check(self, request: ConsistencyCheckRequest) -> ConsistencyCheckResponse:
        events_result = await self.session.execute(
            select(WorldEvent).options(
                selectinload(WorldEvent.participants).selectinload(EventParticipant.character)
            )
        )
        all_events = {event.id: event for event in events_result.scalars().all()}

        deps_result = await self.session.execute(select(EventDependency))
        dependencies = [(dep.parent_id, dep.child_id) for dep in deps_result.scalars().all()]

        graph = DependencyGraphManager()
        graph.build_from_dependencies(list(all_events), dependencies)

        warnings: list[ConsistencyWarning] = []
        required_ids = set(request.requires)
        created_ids = set(request.creates)
        relevant_ids = list(required_ids | created_ids)

        for event_id in request.requires:
            if event_id not in all_events:
                warnings.append(
                    ConsistencyWarning(
                        code="MISSING_REQUIRE_EVENT",
                        event_id=event_id,
                        message=f"Required event ID {event_id} does not exist in canon database.",
                    )
                )

        for event_id in request.creates:
            event = all_events.get(event_id)
            if event is None:
                warnings.append(
                    ConsistencyWarning(
                        code="UNKNOWN_CREATED_EVENT",
                        event_id=event_id,
                        message=f"Created event ID {event_id} does not exist in canon database.",
                    )
                )
                continue
            missing = graph.get_prerequisites(event_id) - required_ids
            if missing:
                titles = [all_events[item].title for item in sorted(missing) if item in all_events]
                warnings.append(
                    ConsistencyWarning(
                        code="MISSING_PREREQUISITES",
                        event_id=event_id,
                        event_title=event.title,
                        message=(
                            f"For event '{event.title}', the following canon prerequisites "
                            f"are not satisfied in requirements: {', '.join(titles)}"
                        ),
                        missing_prerequisites=titles,
                    )
                )

        # Build a position map for the complete canon, not just request.requires.
        # DAG constraints always win; sort_order breaks ties between unrelated events.
        sort_keys = {event_id: event.sort_order for event_id, event in all_events.items()}
        try:
            global_timeline = graph.topological_sort(list(all_events), sort_keys=sort_keys)
        except Exception:
            global_timeline = sorted(all_events, key=lambda eid: (all_events[eid].sort_order, eid))
        position = {event_id: index for index, event_id in enumerate(global_timeline)}

        # The story starts after all required events. Events listed in creates happen
        # during this story and therefore are not treated as already completed.
        required_positions = [position[eid] for eid in required_ids if eid in position]
        story_start = max(required_positions, default=-1)

        character_ids = set(request.participating_character_ids)
        if character_ids:
            chars_result = await self.session.execute(
                select(Character).where(Character.id.in_(character_ids))
            )
            characters = {character.id: character for character in chars_result.scalars().all()}

            for character_id in sorted(character_ids):
                character = characters.get(character_id)
                if character is None:
                    warnings.append(
                        ConsistencyWarning(
                            code="UNKNOWN_CHARACTER",
                            character_id=character_id,
                            message=f"Participating character ID {character_id} does not exist in canon.",
                        )
                    )
                    continue

                character_events = [
                    event
                    for event in all_events.values()
                    if any(part.character_id == character_id for part in event.participants)
                ]
                introductions = [e for e in character_events if e.type in self.INTRODUCTION_TYPES]
                if introductions:
                    first_intro = min(
                        introductions, key=lambda e: (position.get(e.id, 10**12), e.id)
                    )
                    if (
                        position.get(first_intro.id, 10**12) > story_start
                        and first_intro.id not in created_ids
                    ):
                        warnings.append(
                            ConsistencyWarning(
                                code="CHARACTER_NOT_YET_PRESENT",
                                character_id=character_id,
                                event_id=first_intro.id,
                                event_title=first_intro.title,
                                message=(
                                    f"Персонаж '{character.name}' участвует в истории до своего "
                                    f"появления/присоединения: событие '{first_intro.title}' "
                                    f"ещё не произошло."
                                ),
                            )
                        )

                deaths = [e for e in character_events if e.type == EventType.CHARACTER_DEATH]
                prior_deaths = [
                    event for event in deaths if position.get(event.id, 10**12) <= story_start
                ]
                if prior_deaths:
                    last_death = max(prior_deaths, key=lambda e: (position.get(e.id, -1), e.id))
                    warnings.append(
                        ConsistencyWarning(
                            code="CHARACTER_ALREADY_DEAD",
                            character_id=character_id,
                            event_id=last_death.id,
                            event_title=last_death.title,
                            message=(
                                f"Персонаж '{character.name}' участвует в истории, хотя по канону "
                                f"уже погиб в событии '{last_death.title}'."
                            ),
                        )
                    )

            # Events created by this story must not silently introduce undeclared participants.
            for event_id in created_ids:
                event = all_events.get(event_id)
                if event is None:
                    continue
                for participant in event.participants:
                    if participant.character_id not in character_ids:
                        name = (
                            participant.character.name
                            if participant.character
                            else str(participant.character_id)
                        )
                        warnings.append(
                            ConsistencyWarning(
                                code="UNMENTIONED_EVENT_PARTICIPANT",
                                event_id=event_id,
                                event_title=event.title,
                                character_id=participant.character_id,
                                message=(
                                    f"Event '{event.title}' involves character '{name}', "
                                    "but this character is not marked as participating in this story."
                                ),
                            )
                        )

        try:
            timeline_order = graph.topological_sort(relevant_ids, sort_keys=sort_keys)
        except Exception:
            timeline_order = sorted(relevant_ids, key=lambda eid: (sort_keys.get(eid, 0), eid))

        return ConsistencyCheckResponse(
            valid=not warnings, warnings=warnings, timeline_order=timeline_order
        )

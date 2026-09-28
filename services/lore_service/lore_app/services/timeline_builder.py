from lore_app.models.entities import EventDependency, WorldEvent
from lore_app.services.graph_manager import DependencyGraphManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


class TimelineBuilder:
    """Calculates ordered canonical event sequences from the dependency graph."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_chronological_events(self) -> list[WorldEvent]:
        events_res = await self.session.execute(
            select(WorldEvent).options(
                selectinload(WorldEvent.participants),
                selectinload(WorldEvent.parent_edges),
                selectinload(WorldEvent.child_edges),
            )
        )
        all_events = {e.id: e for e in events_res.scalars().all()}

        deps_res = await self.session.execute(select(EventDependency))
        all_deps = [(d.parent_id, d.child_id) for d in deps_res.scalars().all()]

        graph_mgr = DependencyGraphManager()
        graph_mgr.build_from_dependencies(list(all_events.keys()), all_deps)

        ordered_ids = graph_mgr.topological_sort()
        return [all_events[eid] for eid in ordered_ids if eid in all_events]

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from story_app.models.entities import EventRole, Story, StoryCharacter, StoryEvent
from story_app.schemas.dto import StoryEventResponse, StoryResponse


class SearchEngine:
    """Provides querying and filtering over stored narrative texts."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search_stories(
        self,
        character_id: int | None = None,
        event_id: int | None = None,
        event_role: EventRole | None = None,
        query_text: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[StoryResponse], int]:
        base_query = (
            select(Story)
            .options(
                selectinload(Story.characters),
                selectinload(Story.events),
            )
            .distinct()
        )

        if character_id is not None:
            base_query = base_query.join(Story.characters).where(
                StoryCharacter.character_id == character_id
            )

        if event_id is not None or event_role is not None:
            base_query = base_query.join(Story.events)
            if event_id is not None:
                base_query = base_query.where(StoryEvent.event_id == event_id)
            if event_role is not None:
                base_query = base_query.where(StoryEvent.role == event_role)

        if query_text:
            base_query = base_query.where(
                Story.title.ilike(f"%{query_text}%") | Story.summary.ilike(f"%{query_text}%")
            )

        total_res = await self.session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = total_res.scalar_one()

        paginated_query = (
            base_query.order_by(Story.id.desc()).offset((page - 1) * per_page).limit(per_page)
        )
        res = await self.session.execute(paginated_query)
        stories = res.scalars().all()

        results = [
            StoryResponse(
                id=s.id,
                title=s.title,
                summary=s.summary,
                created_at=s.created_at,
                file_path=s.file_path,
                character_ids=[c.character_id for c in s.characters],
                events=[StoryEventResponse(event_id=e.event_id, role=e.role) for e in s.events],
                warnings=[],
            )
            for s in stories
        ]
        return results, total

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from story_app.models.entities import EventRole, Story, StoryCharacter, StoryEvent
from story_app.schemas.dto import StoryEventResponse, StoryResponse
from story_app.services.file_storage import FileStorageManager


class SearchEngine:
    """Search story metadata and the full text of stored .txt files."""

    def __init__(self, session: AsyncSession, storage: FileStorageManager | None = None) -> None:
        self.session = session
        self.storage = storage or FileStorageManager()

    @staticmethod
    def _make_excerpt(content: str, terms: list[str], radius: int = 90) -> str:
        folded = content.casefold()
        positions = [folded.find(term) for term in terms if folded.find(term) >= 0]
        if not positions:
            return ""
        start = max(0, min(positions) - radius)
        end = min(len(content), max(positions) + radius + max(map(len, terms)))
        excerpt = content[start:end].replace("\r", " ").replace("\n", " ")
        return ("…" if start else "") + excerpt.strip() + ("…" if end < len(content) else "")

    async def search_stories(
        self,
        character_id: int | None = None,
        event_id: int | None = None,
        event_role: EventRole | None = None,
        query_text: str | None = None,
        page: int = 1,
        per_page: int = 20,
        offset: int | None = None,
        sort: list[str] | None = None,
    ) -> tuple[list[StoryResponse], int]:
        base_query = (
            select(Story)
            .options(selectinload(Story.characters), selectinload(Story.events))
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

        sort_columns = {
            "id": Story.id,
            "title": Story.title,
            "created_at": Story.created_at,
            "sort_order": Story.sort_order,
        }
        order_clauses: list[Any] = []
        for item in sort or []:
            descending = item.startswith("-")
            field = item[1:] if descending else item
            column = sort_columns.get(field)
            if column is not None:
                order_clauses.append(column.desc() if descending else column.asc())
        if not order_clauses:
            order_clauses = [Story.sort_order.asc(), Story.id.asc()]

        stories: list[Story]

        # Text search must inspect files before pagination, otherwise matches in
        # later pages would be missed and the total count would be incorrect.
        if query_text and query_text.strip():
            terms = [part.casefold() for part in query_text.split() if part.strip()]
            total_res = await self.session.execute(
                select(func.count()).select_from(base_query.subquery())
            )
            candidate_count = total_res.scalar_one()
            candidates_res = await self.session.execute(
                base_query.order_by(*order_clauses).limit(candidate_count)
            )
            candidates = candidates_res.scalars().unique().all()
            matched: list[tuple[Story, str | None]] = []
            for story in candidates:
                metadata = f"{story.title or ''} {story.summary or ''}".casefold()
                content = (
                    await self.storage.read_story_text(story.file_path) if story.file_path else None
                )
                searchable = f"{metadata} {content or ''}".casefold()
                if all(term in searchable for term in terms):
                    excerpt = self._make_excerpt(content or "", terms) if content else None
                    matched.append((story, excerpt))
            total = len(matched)
            start = offset if offset is not None else (page - 1) * per_page
            page_items = matched[start : start + per_page]
            stories = [item[0] for item in page_items]
            excerpts = {item[0].id: item[1] for item in page_items}
        else:
            total_res = await self.session.execute(
                select(func.count()).select_from(base_query.subquery())
            )
            total = total_res.scalar_one()
            result = await self.session.execute(
                base_query.order_by(Story.sort_order, Story.id.asc())
                .offset(offset if offset is not None else (page - 1) * per_page)
                .limit(per_page)
            )
            stories = list(result.scalars().unique().all())
            excerpts = {}

        results = [
            StoryResponse(
                id=s.id,
                title=s.title,
                summary=s.summary,
                created_at=s.created_at,
                file_path=s.file_path,
                primary_event_id=s.primary_event_id,
                sort_order=s.sort_order,
                character_ids=[c.character_id for c in s.characters],
                events=[StoryEventResponse(event_id=e.event_id, role=e.role) for e in s.events],
                warnings=[],
                search_excerpt=excerpts.get(s.id),
            )
            for s in stories
        ]
        return results, total

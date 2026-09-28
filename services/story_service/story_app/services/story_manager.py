from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from story_app.clients.lore_client import LoreServiceClient
from story_app.models.entities import EventRole, Story, StoryCharacter, StoryEvent
from story_app.schemas.dto import (
    ConsistencyWarningDTO,
    StoryCreate,
    StoryDetailResponse,
    StoryEventResponse,
    StoryResponse,
)
from story_app.services.file_storage import FileStorageManager


class StoryManager:
    """Orchestrates story creation, file storage, and canon consistency checking."""

    def __init__(
        self,
        session: AsyncSession,
        lore_client: LoreServiceClient | None = None,
        storage: FileStorageManager | None = None,
    ):
        self.session = session
        self.lore_client = lore_client or LoreServiceClient()
        self.storage = storage or FileStorageManager()

    async def create_story(self, payload: StoryCreate) -> StoryResponse:
        requires = [e.event_id for e in payload.events if e.role == EventRole.REQUIRES]
        creates = [e.event_id for e in payload.events if e.role == EventRole.CREATES]

        warnings: list[ConsistencyWarningDTO] = []

        # 1. Ask Lore Service for canon consistency
        if self.lore_client:
            try:
                check_result = await self.lore_client.check_consistency(
                    requires=requires,
                    creates=creates,
                    character_ids=payload.character_ids,
                )
                for w in check_result.get("warnings", []):
                    warnings.append(
                        ConsistencyWarningDTO(
                            code=w.get("code", "WARNING"),
                            event_id=w.get("event_id"),
                            event_title=w.get("event_title"),
                            character_id=w.get("character_id"),
                            message=w.get("message", ""),
                            missing_prerequisites=w.get("missing_prerequisites", []),
                        )
                    )
            except Exception:
                # If Lore Service is temporarily down, we log/warn rather than block the author completely
                warnings.append(
                    ConsistencyWarningDTO(
                        code="LORE_SERVICE_OFFLINE",
                        message="Lore Service was unreachable. Canon consistency could not be verified.",
                    )
                )

        # 2. Persist Story Entity
        story = Story(
            title=payload.title,
            summary=payload.summary,
        )
        self.session.add(story)
        await self.session.flush()

        # 3. Save text file if provided
        if payload.content is not None:
            file_path = await self.storage.save_story_text(story.id, payload.content)
            story.file_path = file_path

        # 4. Associate characters and events
        for cid in payload.character_ids:
            self.session.add(StoryCharacter(story_id=story.id, character_id=cid))

        for ev in payload.events:
            self.session.add(StoryEvent(story_id=story.id, event_id=ev.event_id, role=ev.role))

        await self.session.flush()

        return StoryResponse(
            id=story.id,
            title=story.title,
            summary=story.summary,
            created_at=story.created_at,
            file_path=story.file_path,
            character_ids=payload.character_ids,
            events=[StoryEventResponse(event_id=e.event_id, role=e.role) for e in payload.events],
            warnings=warnings,
        )

    async def get_story_detail(self, story_id: int) -> StoryDetailResponse | None:
        query = (
            select(Story)
            .options(
                selectinload(Story.characters),
                selectinload(Story.events),
            )
            .where(Story.id == story_id)
        )
        res = await self.session.execute(query)
        story = res.scalar_one_or_none()
        if not story:
            return None

        content = None
        if story.file_path:
            content = await self.storage.read_story_text(story.file_path)

        return StoryDetailResponse(
            id=story.id,
            title=story.title,
            summary=story.summary,
            created_at=story.created_at,
            file_path=story.file_path,
            character_ids=[c.character_id for c in story.characters],
            events=[StoryEventResponse(event_id=e.event_id, role=e.role) for e in story.events],
            content=content,
            warnings=[],
        )

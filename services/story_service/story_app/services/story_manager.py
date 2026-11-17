from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from story_app.clients.lore_client import LoreServiceClient
from story_app.core.exceptions import UpstreamServiceException
from story_app.models.entities import EventRole, Story, StoryCharacter, StoryEvent
from story_app.schemas.dto import (
    ConsistencyWarningDTO,
    StoryCreate,
    StoryDetailResponse,
    StoryEventResponse,
    StoryResponse,
    StoryUpdate,
)
from story_app.services.file_storage import FileStorageManager


class StoryManager:
    """Orchestrates story persistence, file storage and canon validation."""

    def __init__(
        self,
        session: AsyncSession,
        lore_client: LoreServiceClient | None = None,
        storage: FileStorageManager | None = None,
    ):
        self.session = session
        self.lore_client = lore_client or LoreServiceClient()
        self.storage = storage or FileStorageManager()

    @staticmethod
    def _build_consistency_inputs(
        events: list[StoryEventResponse] | list,
        primary_event_id: int | None,
    ) -> tuple[list[int], list[int]]:
        """Build Lore DTO inputs, including implicit primary_event_id as REQUIRES."""
        requires = [e.event_id for e in events if e.role == EventRole.REQUIRES]
        creates = [e.event_id for e in events if e.role == EventRole.CREATES]

        if primary_event_id is not None and primary_event_id not in {e.event_id for e in events}:
            requires.append(primary_event_id)

        # Avoid duplicate IDs while preserving order.
        return list(dict.fromkeys(requires)), list(dict.fromkeys(creates))

    @staticmethod
    def _warnings_from_result(check_result: dict) -> list[ConsistencyWarningDTO]:
        return [
            ConsistencyWarningDTO(
                code=w.get("code", "WARNING"),
                event_id=w.get("event_id"),
                event_title=w.get("event_title"),
                character_id=w.get("character_id"),
                message=w.get("message", ""),
                missing_prerequisites=w.get("missing_prerequisites", []),
            )
            for w in check_result.get("warnings", [])
        ]

    async def _validate_canon(
        self,
        *,
        requires: list[int],
        creates: list[int],
        character_ids: list[int],
    ) -> list[ConsistencyWarningDTO]:
        """Reject canon conflicts; keep the existing offline-warning behavior."""
        try:
            result = await self.lore_client.check_consistency(
                requires=requires,
                creates=creates,
                character_ids=character_ids,
            )
        except UpstreamServiceException:
            # The original project explicitly allowed graceful degradation when Lore is offline.
            return [
                ConsistencyWarningDTO(
                    code="LORE_SERVICE_OFFLINE",
                    message=(
                        "Lore Service was unreachable. Canon consistency " "could not be verified."
                    ),
                )
            ]

        # Canon inconsistencies are warnings, not a reason to reject a story.
        # The author must be able to save a draft and see what needs fixing.
        return self._warnings_from_result(result)

    @staticmethod
    def _story_response(
        story: Story,
        warnings: list[ConsistencyWarningDTO] | None = None,
    ) -> StoryResponse:
        return StoryResponse(
            id=story.id,
            title=story.title,
            summary=story.summary,
            created_at=story.created_at,
            file_path=story.file_path,
            primary_event_id=story.primary_event_id,
            sort_order=story.sort_order,
            character_ids=[c.character_id for c in story.characters],
            events=[StoryEventResponse(event_id=e.event_id, role=e.role) for e in story.events],
            warnings=warnings or [],
        )

    async def create_story(self, payload: StoryCreate) -> StoryResponse:
        requires, creates = self._build_consistency_inputs(payload.events, payload.primary_event_id)
        warnings = await self._validate_canon(
            requires=requires,
            creates=creates,
            character_ids=list(dict.fromkeys(payload.character_ids)),
        )

        story = Story(
            title=payload.title,
            summary=payload.summary,
            primary_event_id=payload.primary_event_id,
            sort_order=payload.sort_order,
            # Initialize collections explicitly: appending to an unloaded async
            # relationship can trigger forbidden implicit IO (MissingGreenlet).
            characters=[],
            events=[],
        )
        self.session.add(story)
        try:
            await self.session.flush()

            if payload.content is not None:
                file_path = await self.storage.save_story_text(story.id, payload.content)
                story.file_path = file_path

            for cid in set(payload.character_ids):
                self.session.add(StoryCharacter(story_id=story.id, character_id=cid))

            for ev in payload.events:
                self.session.add(StoryEvent(story_id=story.id, event_id=ev.event_id, role=ev.role))

            if payload.primary_event_id is not None and payload.primary_event_id not in {
                e.event_id for e in payload.events
            }:
                self.session.add(
                    StoryEvent(
                        story_id=story.id,
                        event_id=payload.primary_event_id,
                        role=EventRole.REQUIRES,
                    )
                )

            await self.session.flush()
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        query = (
            select(Story)
            .options(selectinload(Story.characters), selectinload(Story.events))
            .where(Story.id == story.id)
            # The Story instance is already in the identity map and its
            # collections were initialized as empty before direct association
            # inserts. Force SQLAlchemy to refresh those collections from DB.
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        saved_story = result.scalar_one()
        return self._story_response(saved_story, warnings)

    async def get_story_detail(self, story_id: int) -> StoryDetailResponse | None:
        query = (
            select(Story)
            .options(selectinload(Story.characters), selectinload(Story.events))
            .where(Story.id == story_id)
        )
        result = await self.session.execute(query)
        story = result.scalar_one_or_none()
        if story is None:
            return None

        content = None
        if story.file_path:
            content = await self.storage.read_story_text(story.file_path)

        response = self._story_response(story)
        return StoryDetailResponse(**response.model_dump(), content=content)

    async def update_story(self, story_id: int, payload: StoryUpdate) -> StoryResponse | None:
        query = (
            select(Story)
            .options(selectinload(Story.characters), selectinload(Story.events))
            .where(Story.id == story_id)
        )
        result = await self.session.execute(query)
        story = result.scalar_one_or_none()
        if story is None:
            return None

        # Construct the complete post-update state before changing anything.
        effective_character_ids = (
            list(dict.fromkeys(payload.character_ids))
            if payload.character_ids is not None
            else [c.character_id for c in story.characters]
        )
        effective_primary_event_id = (
            payload.primary_event_id
            if payload.primary_event_id is not None
            else story.primary_event_id
        )
        effective_events = (
            payload.events
            if payload.events is not None
            else [StoryEventResponse(event_id=e.event_id, role=e.role) for e in story.events]
        )

        # Validate every update against the resulting relationships, even if only
        # one of the canon-relevant fields was changed.
        requires, creates = self._build_consistency_inputs(
            effective_events,
            effective_primary_event_id,
        )
        warnings = await self._validate_canon(
            requires=requires,
            creates=creates,
            character_ids=effective_character_ids,
        )

        old_file_path = story.file_path
        new_file_path: str | None = None
        try:
            if payload.title is not None:
                story.title = payload.title
            if payload.summary is not None:
                story.summary = payload.summary
            if payload.primary_event_id is not None:
                story.primary_event_id = payload.primary_event_id
            if payload.sort_order is not None:
                story.sort_order = payload.sort_order

            if payload.content is not None:
                new_file_path = await self.storage.save_story_text(story.id, payload.content)
                story.file_path = new_file_path

            if payload.character_ids is not None:
                from sqlalchemy import delete

                await self.session.execute(
                    delete(StoryCharacter).where(StoryCharacter.story_id == story.id)
                )
                for cid in effective_character_ids:
                    self.session.add(StoryCharacter(story_id=story.id, character_id=cid))

            if payload.events is not None or payload.primary_event_id is not None:
                from sqlalchemy import delete

                await self.session.execute(
                    delete(StoryEvent).where(StoryEvent.story_id == story.id)
                )
                for event in effective_events:
                    self.session.add(
                        StoryEvent(
                            story_id=story.id,
                            event_id=event.event_id,
                            role=event.role,
                        )
                    )

                if effective_primary_event_id is not None and effective_primary_event_id not in {
                    event.event_id for event in effective_events
                }:
                    self.session.add(
                        StoryEvent(
                            story_id=story.id,
                            event_id=effective_primary_event_id,
                            role=EventRole.REQUIRES,
                        )
                    )

            await self.session.flush()
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            # If a new text file was written but DB persistence failed, remove it.
            if new_file_path is not None and new_file_path != old_file_path:
                await self.storage.delete_story_text(new_file_path)
            raise

        refreshed = await self.session.execute(
            select(Story)
            .options(selectinload(Story.characters), selectinload(Story.events))
            .where(Story.id == story_id)
            # Bulk DELETE + direct INSERT bypass relationship instrumentation;
            # refresh the already-loaded ORM collections before serializing.
            .execution_options(populate_existing=True)
        )
        updated = refreshed.scalar_one()
        return self._story_response(updated, warnings)

    async def delete_story(self, story_id: int) -> bool:
        result = await self.session.execute(select(Story).where(Story.id == story_id))
        story = result.scalar_one_or_none()
        if story is None:
            return False

        if story.file_path:
            await self.storage.delete_story_text(story.file_path)

        await self.session.delete(story)
        await self.session.flush()
        await self.session.commit()
        return True

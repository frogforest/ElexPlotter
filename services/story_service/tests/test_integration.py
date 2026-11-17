from collections.abc import AsyncGenerator
from typing import Any

import lore_app.core.database as lore_db
import lore_app.models.entities  # noqa: F401 - ensures tables registered with Base.metadata
import pytest
import story_app.core.database as story_db
import story_app.models.entities  # noqa: F401 - ensures tables registered with Base.metadata
from httpx import ASGITransport, AsyncClient, Response
from lore_app.main import app as lore_fastapi_app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from story_app.clients.lore_client import LoreServiceClient
from story_app.main import app as story_fastapi_app
from story_app.services.story_manager import StoryManager

# In-memory DBs for each service
lore_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
lore_session_factory = async_sessionmaker(lore_engine, class_=AsyncSession, expire_on_commit=False)

story_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
story_session_factory = async_sessionmaker(
    story_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_lore_db() -> AsyncGenerator[AsyncSession, None]:
    async with lore_session_factory() as session:
        yield session
        await session.commit()


async def override_story_db() -> AsyncGenerator[AsyncSession, None]:
    async with story_session_factory() as session:
        yield session
        await session.commit()


lore_fastapi_app.dependency_overrides[lore_db.get_db] = override_lore_db
story_fastapi_app.dependency_overrides[story_db.get_db] = override_story_db


@pytest.fixture(autouse=True)
async def setup_databases() -> AsyncGenerator[None, None]:
    async with lore_engine.begin() as conn:
        await conn.run_sync(lore_db.Base.metadata.create_all)
    async with story_engine.begin() as conn:
        await conn.run_sync(story_db.Base.metadata.create_all)
    yield
    async with lore_engine.begin() as conn:
        await conn.run_sync(lore_db.Base.metadata.drop_all)
    async with story_engine.begin() as conn:
        await conn.run_sync(story_db.Base.metadata.drop_all)


def api_body(response: Response) -> Any:
    """Return the raw ENSI response document."""
    return response.json()


def api_data(response: Response) -> Any:
    """Return the payload inside the ENSI data envelope."""
    body = api_body(response)
    return body.get("data") if isinstance(body, dict) and "data" in body else body


class DirectLoreServiceClient(LoreServiceClient):
    """Client for testing that sends requests to lore_fastapi_app directly via httpx."""

    def __init__(self, async_client: AsyncClient):
        super().__init__()
        self._client = async_client

    async def check_consistency(
        self,
        requires: list[int],
        creates: list[int],
        character_ids: list[int],
    ) -> dict:
        res = await self._client.post(
            "/api/v1/canon:check-consistency",
            json={
                "requires": requires,
                "creates": creates,
                "participating_character_ids": character_ids,
            },
        )
        return dict(api_data(res))


async def test_end_to_end_microservices_workflow() -> None:
    """
    Complete scenario:
    1. Lore Service sets up characters: Isaac, Cynda, Falk, Conrad, Arya, Tesak.
    2. Lore Service registers events:
       - 1: Falk joined camp
       - 2: Conrad appeared
       - 3: Falk secret revealed (requires 1, 2)
       - 4: Isaac & Cynda became a couple
    3. Story Service attempts to create story:
       "Arya finds Tesak cheating" -> creates event "Arya angry at cheating"
       Without required prerequisites -> Warning returned!
    4. Story Service adds valid story:
       "Falk origin" -> requires [1, 2], creates [3] -> passes cleanly!
    """
    lore_transport = ASGITransport(app=lore_fastapi_app)
    story_transport = ASGITransport(app=story_fastapi_app)

    async with (
        AsyncClient(transport=lore_transport, base_url="http://lore-test") as lore_client,
        AsyncClient(transport=story_transport, base_url="http://story-test") as story_client,
    ):
        from fastapi import Depends
        from story_app.api.v1.stories import get_story_manager
        from story_app.core.database import get_db

        direct_client = DirectLoreServiceClient(lore_client)

        def override_get_story_manager(
            db: AsyncSession = Depends(get_db),
        ) -> StoryManager:
            return StoryManager(session=db, lore_client=direct_client)

        try:
            story_fastapi_app.dependency_overrides[get_story_manager] = override_get_story_manager
            lore_fastapi_app.dependency_overrides[lore_db.get_db] = override_lore_db
            story_fastapi_app.dependency_overrides[story_db.get_db] = override_story_db

            # 1. Setup characters
            falk_res = await lore_client.post(
                "/api/v1/characters", json={"name": "Falk", "type": "COMPANION"}
            )
            falk = api_data(falk_res)
            konrad_res = await lore_client.post(
                "/api/v1/characters", json={"name": "Konrad", "type": "NPC"}
            )
            konrad = api_data(konrad_res)

            # 2. Setup events
            ev1_res = await lore_client.post(
                "/api/v1/world-events",
                json={
                    "title": "Falk joins camp",
                    "type": "COMPANION_JOIN",
                    "participants": [{"character_id": falk["id"]}],
                },
            )
            ev1 = api_data(ev1_res)

            ev2_res = await lore_client.post(
                "/api/v1/world-events",
                json={
                    "title": "Konrad appeared",
                    "type": "NPC_APPEAR",
                    "participants": [{"character_id": konrad["id"]}],
                },
            )

            ev2 = api_data(ev2_res)

            ev3_res = await lore_client.post(
                "/api/v1/world-events",
                json={
                    "title": "Falk origin revealed",
                    "type": "REVELATION",
                    "parent_ids": [ev1["id"], ev2["id"]],
                    "participants": [
                        {"character_id": falk["id"]},
                        {"character_id": konrad["id"]},
                    ],
                },
            )

            ev3 = api_data(ev3_res)

            # 3. Add story with missing prerequisite
            story_res_invalid = await story_client.post(
                "/api/v1/stories",
                json={
                    "title": "Unprepared Revelation",
                    "character_ids": [falk["id"]],  # missing Konrad
                    "events": [
                        {"event_id": ev1["id"], "role": "REQUIRES"},  # missing ev2
                        {"event_id": ev3["id"], "role": "CREATES"},
                    ],
                },
            )
            assert story_res_invalid.status_code == 200
            invalid_story = api_data(story_res_invalid)
            assert len(invalid_story["warnings"]) > 0
            codes = [w["code"] for w in invalid_story["warnings"]]
            assert "MISSING_PREREQUISITES" in codes
            assert "UNMENTIONED_EVENT_PARTICIPANT" in codes

            # 4. Add valid story
            story_res_valid = await story_client.post(
                "/api/v1/stories",
                json={
                    "title": "Truth about Falk",
                    "content": "Konrad reveals that he constructed Falk.",
                    "character_ids": [falk["id"], konrad["id"]],
                    "events": [
                        {"event_id": ev1["id"], "role": "REQUIRES"},
                        {"event_id": ev2["id"], "role": "REQUIRES"},
                        {"event_id": ev3["id"], "role": "CREATES"},
                    ],
                },
            )
            assert story_res_valid.status_code == 200
            valid_story = api_data(story_res_valid)
            assert len(valid_story["warnings"]) == 0
            assert valid_story["title"] == "Truth about Falk"
        finally:
            story_fastapi_app.dependency_overrides.clear()
            lore_fastapi_app.dependency_overrides.clear()

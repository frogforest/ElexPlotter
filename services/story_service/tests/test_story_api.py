from collections.abc import AsyncGenerator

import pytest
import story_app.models.entities  # noqa: F401
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from story_app.core.database import Base, get_db
from story_app.main import app
from story_app.services.file_storage import FileStorageManager

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture(autouse=True)
async def setup_db() -> AsyncGenerator[None, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_file_storage(tmp_path: pytest.TempPathFactory) -> None:
    storage = FileStorageManager(base_dir=str(tmp_path))
    content = "A night by the campfire with Falk and the camp."
    file_path = await storage.save_story_text(story_id=101, content=content)

    loaded = await storage.read_story_text(file_path)
    assert loaded == content

    await storage.delete_story_text(file_path)
    assert await storage.read_story_text(file_path) is None


async def test_create_and_fetch_story(client: AsyncClient) -> None:
    payload = {
        "title": "A Night by the Fire",
        "summary": "Falk talks about android origins.",
        "content": "Full text of the story goes here...",
        "character_ids": [1, 2],
        "events": [
            {"event_id": 10, "role": "REQUIRES"},
            {"event_id": 12, "role": "CREATES"},
        ],
    }
    create_res = await client.post("/api/v1/stories", json=payload)
    assert create_res.status_code == 201
    story = create_res.json()
    assert story["title"] == payload["title"]
    assert story["character_ids"] == [1, 2]
    story_id = story["id"]

    # Fetch detail
    detail_res = await client.get(f"/api/v1/stories/{story_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["title"] == payload["title"]
    assert detail["content"] == payload["content"]


async def test_search_stories(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/stories",
        json={
            "title": "Campfire Encounter",
            "character_ids": [3],
            "events": [{"event_id": 5, "role": "REQUIRES"}],
        },
    )
    await client.post(
        "/api/v1/stories",
        json={
            "title": "Battle of the East",
            "character_ids": [4],
            "events": [{"event_id": 7, "role": "CREATES"}],
        },
    )

    # Filter by character_id=3
    res_char = await client.get("/api/v1/stories?filter[character_id]=3")
    assert res_char.status_code == 200
    assert len(res_char.json()["data"]) == 1
    assert res_char.json()["data"][0]["title"] == "Campfire Encounter"

    # Filter by search text
    res_search = await client.get("/api/v1/stories?filter[q]=Battle")
    assert res_search.status_code == 200
    assert len(res_search.json()["data"]) == 1
    assert res_search.json()["data"][0]["title"] == "Battle of the East"

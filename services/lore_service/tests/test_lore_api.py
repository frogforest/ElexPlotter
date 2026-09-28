from collections.abc import AsyncGenerator

import lore_app.models.entities  # noqa: F401
import pytest
from httpx import ASGITransport, AsyncClient
from lore_app.core.database import Base, get_db
from lore_app.main import app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# StaticPool ensures that SQLite in-memory database persists across connections in memory
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


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "lore_service"}


async def test_character_crud(client: AsyncClient) -> None:
    # 1. Create character
    create_res = await client.post(
        "/api/v1/characters",
        json={"name": "Falk", "type": "COMPANION", "description": "Android companion"},
    )
    assert create_res.status_code == 201
    char_data = create_res.json()
    assert char_data["name"] == "Falk"
    char_id = char_data["id"]

    # 2. Get character
    get_res = await client.get(f"/api/v1/characters/{char_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Falk"

    # 3. List characters with pagination
    list_res = await client.get("/api/v1/characters?page[number]=1&page[size]=10")
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["meta"]["total"] == 1
    assert len(data["data"]) == 1


async def test_canon_consistency_check_scenario(client: AsyncClient) -> None:
    falk_res = await client.post("/api/v1/characters", json={"name": "Falk", "type": "COMPANION"})
    falk_id = falk_res.json()["id"]

    konrad_res = await client.post("/api/v1/characters", json={"name": "Konrad", "type": "NPC"})
    konrad_id = konrad_res.json()["id"]

    # Create event 1
    e1_res = await client.post(
        "/api/v1/world-events",
        json={
            "title": "Falk joins camp",
            "type": "COMPANION_JOIN",
            "participants": [{"character_id": falk_id, "role": "PARTICIPANT"}],
        },
    )
    e1_id = e1_res.json()["id"]

    # Create event 2
    e2_res = await client.post(
        "/api/v1/world-events",
        json={
            "title": "Konrad appears",
            "type": "NPC_APPEAR",
            "participants": [{"character_id": konrad_id, "role": "PARTICIPANT"}],
        },
    )
    e2_id = e2_res.json()["id"]

    # Create event 3 with parents e1 and e2
    e3_res = await client.post(
        "/api/v1/world-events",
        json={
            "title": "Falk origin revealed",
            "type": "REVELATION",
            "parent_ids": [e1_id, e2_id],
            "participants": [
                {"character_id": falk_id, "role": "PARTICIPANT"},
                {"character_id": konrad_id, "role": "PARTICIPANT"},
            ],
        },
    )
    e3_id = e3_res.json()["id"]

    # 1. Valid case
    valid_check = await client.post(
        "/api/v1/consistency/check",
        json={
            "requires": [e1_id, e2_id],
            "creates": [e3_id],
            "participating_character_ids": [falk_id, konrad_id],
        },
    )
    assert valid_check.status_code == 200
    res_data = valid_check.json()
    assert res_data["valid"] is True
    assert len(res_data["warnings"]) == 0

    # 2. Invalid case: missing prerequisite e2 and character konrad
    invalid_check = await client.post(
        "/api/v1/consistency/check",
        json={
            "requires": [e1_id],
            "creates": [e3_id],
            "participating_character_ids": [falk_id],
        },
    )
    assert invalid_check.status_code == 200
    inv_data = invalid_check.json()
    assert inv_data["valid"] is False
    warning_codes = [w["code"] for w in inv_data["warnings"]]
    assert "MISSING_PREREQUISITES" in warning_codes
    assert "UNMENTIONED_EVENT_PARTICIPANT" in warning_codes

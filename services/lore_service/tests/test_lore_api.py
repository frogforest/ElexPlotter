from collections.abc import AsyncGenerator
from typing import Any

import lore_app.models.entities  # noqa: F401
import pytest
from httpx import ASGITransport, AsyncClient, Response
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


def api_body(response: Response) -> Any:
    """Return the raw ENSI response document."""
    return response.json()


def api_data(response: Response) -> Any:
    """Return the payload inside the ENSI data envelope."""
    body = api_body(response)
    return body.get("data") if isinstance(body, dict) and "data" in body else body


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
    assert create_res.status_code == 200
    char_data = api_data(create_res)
    assert char_data["name"] == "Falk"
    char_id = char_data["id"]

    # 2. Get character
    get_res = await client.get(f"/api/v1/characters/{char_id}")
    assert get_res.status_code == 200
    assert api_data(get_res)["name"] == "Falk"

    # 3. List characters with pagination
    list_res = await client.get("/api/v1/characters?page[number]=1&page[size]=10")
    assert list_res.status_code == 200
    body = api_body(list_res)
    assert body["meta"]["pagination"]["total"] == 1
    assert len(body["data"]) == 1


async def test_canon_consistency_check_scenario(client: AsyncClient) -> None:
    falk_res = await client.post("/api/v1/characters", json={"name": "Falk", "type": "COMPANION"})
    falk_id = api_data(falk_res)["id"]

    konrad_res = await client.post("/api/v1/characters", json={"name": "Konrad", "type": "NPC"})
    konrad_id = api_data(konrad_res)["id"]

    # Create event 1
    e1_res = await client.post(
        "/api/v1/world-events",
        json={
            "title": "Falk joins camp",
            "type": "COMPANION_JOIN",
            "participants": [{"character_id": falk_id, "role": "PARTICIPANT"}],
        },
    )
    e1_id = api_data(e1_res)["id"]

    # Create event 2
    e2_res = await client.post(
        "/api/v1/world-events",
        json={
            "title": "Konrad appears",
            "type": "NPC_APPEAR",
            "participants": [{"character_id": konrad_id, "role": "PARTICIPANT"}],
        },
    )
    e2_id = api_data(e2_res)["id"]

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
    e3_id = api_data(e3_res)["id"]

    # 1. Valid case
    valid_check = await client.post(
        "/api/v1/canon:check-consistency",
        json={
            "requires": [e1_id, e2_id],
            "creates": [e3_id],
            "participating_character_ids": [falk_id, konrad_id],
        },
    )
    assert valid_check.status_code == 200
    res_data = api_data(valid_check)
    assert res_data["valid"] is True
    assert len(res_data["warnings"]) == 0

    # 2. Invalid case: missing prerequisite e2 and character konrad
    invalid_check = await client.post(
        "/api/v1/canon:check-consistency",
        json={
            "requires": [e1_id],
            "creates": [e3_id],
            "participating_character_ids": [falk_id],
        },
    )
    assert invalid_check.status_code == 200
    inv_data = api_data(invalid_check)
    assert inv_data["valid"] is False
    warning_codes = [w["code"] for w in inv_data["warnings"]]
    assert "MISSING_PREREQUISITES" in warning_codes
    assert "UNMENTIONED_EVENT_PARTICIPANT" in warning_codes


@pytest.mark.asyncio
async def test_reorder_world_events(client: AsyncClient) -> None:
    # Create two independent events
    ev1_res = await client.post(
        "/api/v1/world-events",
        json={"title": "First Event", "type": "PLOT_MILESTONE", "sort_order": 1},
    )
    ev1_id = api_data(ev1_res)["id"]

    ev2_res = await client.post(
        "/api/v1/world-events",
        json={"title": "Second Event", "type": "PLOT_MILESTONE", "sort_order": 2},
    )
    ev2_id = api_data(ev2_res)["id"]

    # Reorder so ev2 comes before ev1
    reorder_res = await client.post(
        "/api/v1/world-events:reorder",
        json={
            "items": [
                {"event_id": ev2_id, "sort_order": 1},
                {"event_id": ev1_id, "sort_order": 2},
            ]
        },
    )
    assert reorder_res.status_code == 200
    reordered_list = api_data(reorder_res)

    # Find the positions of ev1 and ev2 in returned list
    ev_map = {item["id"]: item["sort_order"] for item in reordered_list}
    assert ev_map[ev2_id] < ev_map[ev1_id]

    # Check timeline builder respects this order
    timeline_res = await client.get("/api/v1/timeline")
    assert timeline_res.status_code == 200
    timeline_ids = [item["id"] for item in api_data(timeline_res)]
    assert timeline_ids.index(ev2_id) < timeline_ids.index(ev1_id)


@pytest.mark.asyncio
async def test_update_and_delete_world_event(client: AsyncClient) -> None:
    # 1. Create an event
    ev_res = await client.post(
        "/api/v1/world-events",
        json={"title": "Original Event", "type": "PLOT_MILESTONE", "description": "Original Desc"},
    )
    assert ev_res.status_code == 200
    ev_id = api_data(ev_res)["id"]

    # 2. Update it
    patch_res = await client.patch(
        f"/api/v1/world-events/{ev_id}",
        json={"title": "Updated Event Title", "type": "WORLD_STATE", "description": "Updated Desc"},
    )
    assert patch_res.status_code == 200
    patched_data = api_data(patch_res)
    assert patched_data["title"] == "Updated Event Title"
    assert patched_data["type"] == "WORLD_STATE"
    assert patched_data["description"] == "Updated Desc"

    # 3. Get single event
    get_res = await client.get(f"/api/v1/world-events/{ev_id}")
    assert get_res.status_code == 200
    assert api_data(get_res)["title"] == "Updated Event Title"

    # 4. Delete it
    del_res = await client.delete(f"/api/v1/world-events/{ev_id}")
    assert del_res.status_code == 200

    # 5. Verify 404
    get_after_del = await client.get(f"/api/v1/world-events/{ev_id}")
    assert get_after_del.status_code == 404


@pytest.mark.asyncio
async def test_character_backstory_event(client: AsyncClient) -> None:
    c_res = await client.post(
        "/api/v1/characters", json={"name": "Sinda Past", "type": "COMPANION"}
    )
    cid = api_data(c_res)["id"]

    ev_res = await client.post(
        "/api/v1/world-events",
        json={
            "title": "Sinda escapes old academy",
            "type": "CHARACTER_BACKSTORY",
            "description": "События до начала основного похода",
            "participants": [{"character_id": cid, "role": "PARTICIPANT"}],
        },
    )
    assert ev_res.status_code == 200
    ev_data = api_data(ev_res)
    assert ev_data["type"] == "CHARACTER_BACKSTORY"
    assert ev_data["title"] == "Sinda escapes old academy"

    # Filter by type
    filter_res = await client.get("/api/v1/world-events?filter[type]=CHARACTER_BACKSTORY")
    assert filter_res.status_code == 200
    items = api_data(filter_res)
    assert any(i["title"] == "Sinda escapes old academy" for i in items)


@pytest.mark.asyncio
async def test_update_event_parents_and_cycles(client: AsyncClient) -> None:
    # 1. Create two events independently
    res_a = await client.post(
        "/api/v1/world-events",
        json={"title": "Battle of Iron Hill", "type": "PLOT_MILESTONE"},
    )
    assert res_a.status_code == 200
    id_a = api_data(res_a)["id"]

    res_b = await client.post(
        "/api/v1/world-events",
        json={"title": "Signing of Peace Treaty", "type": "WORLD_STATE"},
    )
    assert res_b.status_code == 200
    id_b = api_data(res_b)["id"]

    # 2. Update B so that it depends on A (A is parent of B)
    patch_b = await client.patch(
        f"/api/v1/world-events/{id_b}",
        json={"parent_ids": [id_a]},
    )
    assert patch_b.status_code == 200
    assert api_data(patch_b)["parent_ids"] == [id_a]

    # 3. Attempt to make A depend on B (creates cycle A -> B -> A)
    patch_cycle = await client.patch(
        f"/api/v1/world-events/{id_a}",
        json={"parent_ids": [id_b]},
    )
    assert patch_cycle.status_code == 400

    # 4. Remove parent from B
    patch_clear = await client.patch(
        f"/api/v1/world-events/{id_b}",
        json={"parent_ids": []},
    )
    assert patch_clear.status_code == 200
    assert api_data(patch_clear)["parent_ids"] == []


@pytest.mark.asyncio
async def test_character_update_and_delete(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/characters",
        json={"name": "Before", "type": "COMPANION", "description": "Old"},
    )
    assert created.status_code == 200
    character_id = api_data(created)["id"]

    updated = await client.patch(
        f"/api/v1/characters/{character_id}",
        json={"name": "After", "description": "Updated"},
    )
    assert updated.status_code == 200
    updated_data = api_data(updated)
    assert updated_data["name"] == "After"
    assert updated_data["description"] == "Updated"
    assert updated_data["type"] == "COMPANION"

    deleted = await client.delete(f"/api/v1/characters/{character_id}")
    assert deleted.status_code == 200

    missing = await client.get(f"/api/v1/characters/{character_id}")
    assert missing.status_code == 404

    # ENSI DELETE is idempotent.
    repeated_delete = await client.delete(f"/api/v1/characters/{character_id}")
    assert repeated_delete.status_code == 200


@pytest.mark.asyncio
async def test_character_update_rejects_duplicate_name(client: AsyncClient) -> None:
    first_response = await client.post("/api/v1/characters", json={"name": "First"})
    assert first_response.status_code == 200
    second = await client.post("/api/v1/characters", json={"name": "Second"})
    second_id = api_data(second)["id"]

    response = await client.patch(f"/api/v1/characters/{second_id}", json={"name": "First"})
    assert response.status_code == 400
    still_second = await client.get(f"/api/v1/characters/{second_id}")
    assert api_data(still_second)["name"] == "Second"

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from scout_email.app import app
from scout_email.db.base import Base
from scout_email.db.session import create_engine_and_sessionmaker, get_session


@pytest.fixture
def client(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'campaigns.db'}"
    )

    async def prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    import asyncio

    asyncio.run(prepare())

    async def override_session() -> AsyncIterator:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def test_create_campaign_defaults_to_human_approval(client):
    response = client.post(
        "/campaigns",
        json={
            "name": "Lahore Dentists",
            "searches": ["dentist", "dental clinic"],
            "locations": ["Lahore"],
            "target_leads": 50,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["sending"]["human_approval"] is True
    assert body["sending"]["max_per_day"] == 10
    assert body["follow_up"]["max_followups"] == 1
    assert body["status"] == "ACTIVE"


def test_campaign_custom_policies_round_trip(client):
    payload = {
        "name": "Sialkot Clinics",
        "searches": ["clinic", "cosmetic clinic"],
        "locations": ["Sialkot", "Daska"],
        "target_leads": 25,
        "qualification": {"minimum_rating": 4.0, "exclude_chains": False},
        "sending": {"max_per_day": 7, "human_approval": True},
        "follow_up": {"enabled": False, "max_followups": 0, "delay_days": 5},
    }
    created = client.post("/campaigns", json=payload)
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]

    fetched = client.get(f"/campaigns/{campaign_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["searches"] == payload["searches"]
    assert body["locations"] == payload["locations"]
    assert body["qualification"] == payload["qualification"]
    assert body["sending"] == payload["sending"]
    assert body["follow_up"] == payload["follow_up"]


def test_campaign_rejects_unsafe_or_invalid_values(client):
    base = {
        "name": "Bad Campaign",
        "searches": ["dentist"],
        "locations": ["Lahore"],
        "target_leads": 10,
    }
    cases = [
        {**base, "searches": []},
        {**base, "locations": []},
        {**base, "target_leads": 0},
        {**base, "sending": {"max_per_day": 0, "human_approval": True}},
        {**base, "sending": {"max_per_day": 10, "human_approval": False}},
        {**base, "follow_up": {"enabled": True, "max_followups": 2, "delay_days": 4}},
    ]
    for payload in cases:
        response = client.post("/campaigns", json=payload)
        assert response.status_code == 422, (payload, response.text)


def test_pause_and_resume_campaign(client):
    created = client.post(
        "/campaigns",
        json={
            "name": "Lahore Dentists",
            "searches": ["dentist"],
            "locations": ["Lahore"],
            "target_leads": 10,
        },
    )
    campaign_id = created.json()["id"]

    paused = client.post(f"/campaigns/{campaign_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"
    assert client.get(f"/campaigns/{campaign_id}").json()["status"] == "PAUSED"

    resumed = client.post(f"/campaigns/{campaign_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "ACTIVE"


def test_missing_campaign_returns_404(client):
    assert client.get("/campaigns/999999").status_code == 404

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scout_email.app import app
from scout_email.db.base import Base
from scout_email.db.session import create_engine_and_sessionmaker, get_session


ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_WORKFLOW = ROOT / "n8n" / "workflows" / "campaign-scout.json"
RESEARCH_WORKFLOW = ROOT / "n8n" / "workflows" / "lead-research.json"


@pytest.fixture
def client(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'orchestration.db'}"
    )

    async def prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def override_session() -> AsyncIterator:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _assert_job_ref(value: dict) -> None:
    assert isinstance(value["job_id"], int) and value["job_id"] > 0
    assert value["status_url"] == f"/jobs/{value['job_id']}"
    assert isinstance(value["correlation_id"], str) and value["correlation_id"]


def test_async_job_api_returns_stable_polling_metadata(client):
    payload = {
        "kind": "RESEARCH",
        "payload": {"lead_id": 42},
        "idempotency_key": "research:lead:42",
        "max_attempts": 3,
    }
    first = client.post("/jobs", json=payload)
    second = client.post("/jobs", json=payload)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    first_body = first.json()
    second_body = second.json()
    _assert_job_ref(first_body)
    assert second_body["job_id"] == first_body["job_id"]
    assert second_body["correlation_id"] == first_body["correlation_id"]

    polled = client.get(first_body["status_url"])
    assert polled.status_code == 200
    polled_body = polled.json()
    assert polled_body["job_id"] == first_body["job_id"]
    assert polled_body["correlation_id"] == first_body["correlation_id"]
    assert polled_body["state"] == "PENDING"


def test_campaign_scout_202_response_exposes_pollable_jobs(client):
    created = client.post(
        "/campaigns",
        json={
            "name": "Lahore Dentists",
            "searches": ["dentist", "dental clinic"],
            "locations": ["Lahore"],
            "target_leads": 20,
        },
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]

    response = client.post(f"/campaigns/{campaign_id}/scout")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["campaign_id"] == campaign_id
    assert len(body["jobs"]) == 2
    for job in body["jobs"]:
        _assert_job_ref(job)
    assert body["job_ids"] == [job["job_id"] for job in body["jobs"]]


def _load_workflow(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_domain_logic_nodes(workflow: dict) -> None:
    forbidden = {"n8n-nodes-base.code", "n8n-nodes-base.function", "n8n-nodes-base.functionItem"}
    assert not [node for node in workflow["nodes"] if node["type"] in forbidden]


def test_campaign_scout_workflow_only_routes_backend_job_states():
    workflow = _load_workflow(CAMPAIGN_WORKFLOW)
    assert workflow["active"] is False
    _assert_no_domain_logic_nodes(workflow)
    rendered = json.dumps(workflow)
    assert "/campaigns/" in rendered and "/scout" in rendered
    assert "/jobs/" in rendered
    for state in ("COMPLETE", "RETRY", "FAILED", "SKIPPED"):
        assert state in rendered
    assert "status_url" in rendered
    assert "correlation_id" in rendered


def test_lead_research_workflow_is_backend_driven_and_stops_at_human_review():
    workflow = _load_workflow(RESEARCH_WORKFLOW)
    assert workflow["active"] is False
    _assert_no_domain_logic_nodes(workflow)
    rendered = json.dumps(workflow)
    for kind in (
        "ENRICH",
        "CRAWL_EVIDENCE",
        "RESEARCH",
        "STRATEGY",
        "WRITER_CRITIC",
    ):
        assert kind in rendered
    for state in ("COMPLETE", "RETRY", "FAILED", "SKIPPED"):
        assert state in rendered
    assert "/jobs" in rendered
    assert "/review" in rendered
    assert "status_url" in rendered
    assert "correlation_id" in rendered


def test_campaign_scout_dispatches_each_qualified_lead_to_research_workflow():
    workflow = _load_workflow(CAMPAIGN_WORKFLOW)
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert "Split Qualified Leads" in nodes
    assert "Dispatch Lead Research" in nodes

    split = nodes["Split Qualified Leads"]
    dispatch = nodes["Dispatch Lead Research"]
    assert split["type"] == "n8n-nodes-base.splitOut"
    assert "qualified_lead_ids" in json.dumps(split["parameters"])
    assert dispatch["type"] == "n8n-nodes-base.httpRequest"
    assert dispatch["parameters"]["method"] == "POST"
    assert "lead-research" in json.dumps(dispatch["parameters"])
    assert "lead_id" in json.dumps(dispatch["parameters"])

    complete_targets = workflow["connections"]["Scout COMPLETE"]["main"][0]
    assert any(target["node"] == "Split Qualified Leads" for target in complete_targets)
    split_targets = workflow["connections"]["Split Qualified Leads"]["main"][0]
    assert any(target["node"] == "Dispatch Lead Research" for target in split_targets)


def test_long_running_orchestration_webhooks_acknowledge_immediately():
    campaign = _load_workflow(CAMPAIGN_WORKFLOW)
    research = _load_workflow(RESEARCH_WORKFLOW)
    campaign_trigger = next(node for node in campaign["nodes"] if node["name"] == "Campaign Trigger")
    research_trigger = next(node for node in research["nodes"] if node["name"] == "Lead Research Trigger")

    assert campaign_trigger["parameters"]["responseMode"] == "onReceived"
    assert research_trigger["parameters"]["responseMode"] == "onReceived"

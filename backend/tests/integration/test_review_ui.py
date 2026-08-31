from __future__ import annotations

import json

import httpx
import pytest

from scout_email.approval.models import EmailEditMetadata, HumanApprovalEvent  # noqa: F401
from scout_email.app import app
from scout_email.common.enums import ApprovalState, LeadState
from scout_email.db.base import Base
from scout_email.db.models import (
    AuditFinding,
    Campaign,
    EmailDraft,
    EmailReview,
    Evidence,
    Lead,
    Screenshot,
    Strategy,
)
from scout_email.db.session import create_engine_and_sessionmaker, get_session
from scout_email.jobs.models import JobRuntime  # noqa: F401
from scout_email.writing.models import DraftGenerationMetadata


async def _seed(session):
    campaign = Campaign(
        name="Lahore Dentists",
        status="ACTIVE",
        max_per_day=10,
        human_approval_required=True,
    )
    session.add(campaign)
    await session.flush()
    lead = Lead(
        campaign_id=campaign.id,
        state=LeadState.CONTACTABLE.value,
        name="Acme Dental",
        normalized_name="acme dental",
        category="Dentist",
        city="Lahore",
    )
    session.add(lead)
    await session.flush()
    evidence = Evidence(
        lead_id=lead.id,
        kind="screenshot",
        claim_class="OBSERVED_FACT",
        claim="The mobile booking CTA is difficult to spot.",
        source_type="screenshot",
        source_url="https://example.com/",
        artifact_path="campaigns/1/leads/1/screenshots/homepage-mobile.png",
        confidence=0.95,
    )
    screenshot = Screenshot(
        lead_id=lead.id,
        page_url="https://example.com/",
        viewport="mobile",
        artifact_path="campaigns/1/leads/1/screenshots/homepage-mobile.png",
    )
    session.add_all([evidence, screenshot])
    await session.flush()
    strategy = Strategy(
        lead_id=lead.id,
        decision="CONTACT",
        primary_angle="mobile booking friction",
        persuasion_brief_json=json.dumps({"primary_angle": "mobile booking friction"}),
        score_components_json=json.dumps(
            {
                "severity": 0.8,
                "evidence_confidence": 0.95,
                "business_impact": 0.8,
                "weberaise_fit": 0.9,
                "explainability": 0.9,
                "generic_risk": 0.1,
            }
        ),
        confidence=0.92,
        prompt_version="strategist:v1",
        model_id="fake-strategy",
    )
    session.add(strategy)
    await session.flush()
    session.add(
        AuditFinding(
            lead_id=lead.id,
            problem="The mobile booking CTA is difficult to spot.",
            severity=0.8,
            business_impact=0.8,
            confidence=0.95,
            evidence_ids_json=json.dumps([evidence.id]),
            safe_to_reference=True,
        )
    )
    draft = EmailDraft(
        lead_id=lead.id,
        strategy_id=strategy.id,
        subject="Mobile booking thought",
        body="Your mobile booking action is easy to miss. Would it be useful if I sent one focused idea?",
        writer_prompt_version="writer:v1",
        model_id="fake-writer",
        approval_state=ApprovalState.PENDING.value,
    )
    session.add(draft)
    await session.flush()
    session.add_all(
        [
            EmailReview(
                draft_id=draft.id,
                decision="APPROVE",
                scores_json=json.dumps({"specificity": 92, "genericness": 8}),
                issues_json="[]",
                prompt_version="critic:v1",
                model_id="fake-critic",
            ),
            DraftGenerationMetadata(
                draft_id=draft.id,
                playbook_hash="b" * 64,
                strategy_label="CONVERSION_PROBLEM",
                recent_similarity=0.11,
            ),
        ]
    )
    await session.commit()
    return lead, draft


@pytest.mark.asyncio
async def test_review_queue_and_all_four_actions_are_wired(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'review-ui.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        lead, draft = await _seed(session)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            queue = await client.get("/review")
            assert queue.status_code == 200
            assert "Acme Dental" in queue.text
            assert "Mobile booking thought" in queue.text
            assert "mobile booking friction" in queue.text

            detail = await client.get(f"/review/{draft.id}")
            assert detail.status_code == 200
            assert "The mobile booking CTA is difficult to spot." in detail.text
            assert "homepage-mobile.png" in detail.text
            for action in ("Approve", "Save edit", "Regenerate", "Reject"):
                assert action in detail.text

            edited = await client.post(
                f"/approval/drafts/{draft.id}/edit",
                json={
                    "subject": "Quick mobile booking thought",
                    "body": "The booking action is easy to miss on mobile. Want me to send one focused idea?",
                    "reviewer": "human",
                    "edit_context": "CTA",
                },
            )
            assert edited.status_code == 200
            assert edited.json()["approval_state"] == "PENDING"

            approved = await client.post(
                f"/approval/drafts/{draft.id}/approve", json={"reviewer": "human"}
            )
            assert approved.status_code == 200
            assert approved.json()["approval_state"] == "APPROVED"

            rejected = await client.post(
                f"/approval/drafts/{draft.id}/reject",
                json={"reviewer": "human", "reason": "try a different angle"},
            )
            assert rejected.status_code == 200
            assert rejected.json()["approval_state"] == "REJECTED"

            regenerated = await client.post(
                f"/approval/drafts/{draft.id}/regenerate", json={"reviewer": "human"}
            )
            assert regenerated.status_code == 202
            assert regenerated.json()["job"]["kind"] == "writer_critic"
            assert regenerated.json()["job"]["payload"] == {
                "lead_id": lead.id,
                "source_draft_id": draft.id,
            }
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()

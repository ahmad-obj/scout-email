from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from scout_email.common.enums import LeadState
from scout_email.db.base import Base
from scout_email.db.models import (
    AuditFinding,
    Campaign,
    Contact,
    EmailDraft,
    EmailReview,
    Evidence,
    Lead,
    ResearchReport,
    Strategy,
)
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.schemas import ProviderResult
from scout_email.writing.critic import CriticService
from scout_email.writing.playbook import load_playbook
from scout_email.writing.quality import WriterCriticQualityLoop
from scout_email.writing.writer import WriterService


PLAYBOOK_DIR = Path(__file__).parents[3] / "config" / "weberaise"


class FakeProvider:
    def __init__(self, *, name: str, model: str, payloads: list[str]) -> None:
        self.name = name
        self.model = model
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    async def generate_json(self, *, system: str, user: str, schema: dict) -> ProviderResult:
        self.calls.append({"system": system, "user": user, "schema": schema})
        return ProviderResult(
            provider=self.name,
            model=self.model,
            text=self.payloads.pop(0),
        )


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'quality-loop.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed_lead(session):
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
        canonical_domain="example.com",
    )
    session.add(lead)
    await session.flush()
    contact = Contact(
        lead_id=lead.id,
        email="hello@example.com",
        normalized_email="hello@example.com",
        contact_type="business",
        state="VERIFIED",
        source_url="https://example.com/contact",
        confidence=1.0,
    )
    evidence = Evidence(
        lead_id=lead.id,
        kind="screenshot",
        claim_class="OBSERVED_FACT",
        claim="The mobile homepage booking CTA is difficult to spot.",
        source_type="screenshot",
        source_url="https://example.com/",
        confidence=0.95,
    )
    session.add_all([contact, evidence])
    await session.flush()
    session.add(
        ResearchReport(
            lead_id=lead.id,
            status="COMPLETE",
            dossier_json=json.dumps(
                {
                    "business": {
                        "name": "Acme Dental",
                        "summary": "Local dental clinic.",
                    },
                    "business_model": {"primary_conversion": "book appointment"},
                }
            ),
            confidence=0.9,
            prompt_version="researcher:v1",
            model_id="fake-research-1",
        )
    )
    strategy = Strategy(
        lead_id=lead.id,
        decision="CONTACT",
        primary_angle="reduce mobile booking friction",
        persuasion_brief_json=json.dumps(
            {
                "primary_angle": "reduce mobile booking friction",
                "do_not_use": ["unsupported revenue claims"],
            }
        ),
        score_components_json="{}",
        confidence=0.92,
        prompt_version="strategist:v1",
        model_id="fake-strategy-1",
    )
    session.add(strategy)
    await session.flush()
    session.add(
        AuditFinding(
            lead_id=lead.id,
            problem="The mobile homepage booking CTA is difficult to spot.",
            severity=0.75,
            business_impact=0.8,
            confidence=0.95,
            evidence_ids_json=json.dumps([evidence.id]),
            safe_to_reference=True,
        )
    )
    await session.commit()
    return lead, evidence


def _writer_payload(evidence_id: int, variant: int) -> str:
    return json.dumps(
        {
            "subject": f"Mobile booking thought {variant}",
            "body": (
                "I noticed the booking action on your mobile homepage is easy to miss. "
                "That may add friction for visitors trying to book. "
                f"Would it be useful if I sent one focused idea? Version {variant}."
            ),
            "claims": [
                {
                    "text": "The booking action on the mobile homepage is easy to miss.",
                    "claim_class": "OBSERVED_FACT",
                    "evidence_ids": [evidence_id],
                },
                {
                    "text": "That may add friction for visitors trying to book.",
                    "claim_class": "REASONABLE_INFERENCE",
                    "evidence_ids": [evidence_id],
                },
            ],
            "strategy_label": "CONVERSION_PROBLEM",
        }
    )


def _rewrite_review() -> str:
    return json.dumps(
        {
            "decision": "REWRITE",
            "scores": {
                "specificity": 55,
                "naturalness": 70,
                "persuasiveness": 60,
                "evidence_integrity": 100,
                "genericness": 82,
                "spamminess": 12,
            },
            "issues": ["Opening could fit unrelated businesses."],
        }
    )


@pytest.mark.asyncio
async def test_quality_loop_caps_rewrites_at_two_and_surfaces_human_review(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead, evidence = await _seed_lead(session)
        writer_provider = FakeProvider(
            name="fake-writer",
            model="fake-writer-1",
            payloads=[
                _writer_payload(evidence.id, 1),
                _writer_payload(evidence.id, 2),
                _writer_payload(evidence.id, 3),
            ],
        )
        critic_provider = FakeProvider(
            name="fake-critic",
            model="fake-critic-1",
            payloads=[_rewrite_review(), _rewrite_review(), _rewrite_review()],
        )
        gateway = LLMGateway(
            providers={
                "fake-writer": writer_provider,
                "fake-critic": critic_provider,
            },
            task_routes={
                "writer": "fake-writer",
                "critic": "fake-critic",
            },
        )
        loop = WriterCriticQualityLoop(
            session,
            writer=WriterService(
                session,
                gateway=gateway,
                playbook=load_playbook(PLAYBOOK_DIR),
            ),
            critic=CriticService(session, gateway=gateway),
            max_rewrites=2,
        )

        result = await loop.run(lead_id=lead.id)

        assert result.final_decision == "REWRITE"
        assert result.rewrite_count == 2
        assert result.requires_human_review is True
        assert len(writer_provider.calls) == 3
        assert len(critic_provider.calls) == 3
        assert "Opening could fit unrelated businesses." in writer_provider.calls[1]["user"]
        assert "Opening could fit unrelated businesses." in writer_provider.calls[2]["user"]
        assert await session.scalar(select(func.count()).select_from(EmailDraft)) == 3
        assert await session.scalar(select(func.count()).select_from(EmailReview)) == 3

    await engine.dispose()

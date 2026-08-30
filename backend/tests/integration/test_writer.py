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
    EmailDraft,
    EmailDraftClaim,
    Evidence,
    Lead,
    ResearchReport,
    Strategy,
)
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.schemas import ProviderResult
from scout_email.writing.models import DraftGenerationMetadata
from scout_email.writing.playbook import load_playbook
from scout_email.writing.writer import BannedPhraseError, WriterEvidenceError, WriterService


PLAYBOOK_DIR = Path(__file__).parents[3] / "config" / "weberaise"


class FakeProvider:
    name = "fake"
    model = "fake-writer-1"

    def __init__(self, payloads: list[str]) -> None:
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
        f"sqlite+aiosqlite:///{tmp_path / 'writer.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed_contactable_lead(session):
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
    evidence = Evidence(
        lead_id=lead.id,
        kind="screenshot",
        claim_class="OBSERVED_FACT",
        claim="The mobile homepage booking CTA is difficult to spot.",
        source_type="screenshot",
        source_url="https://example.com/",
        artifact_path="campaigns/1/leads/1/screenshots/homepage-mobile.png",
        confidence=0.95,
    )
    session.add(evidence)
    await session.flush()
    session.add(
        ResearchReport(
            lead_id=lead.id,
            status="COMPLETE",
            dossier_json=json.dumps(
                {
                    "business": {"name": "Acme Dental", "summary": "Local dental clinic."},
                    "business_model": {"primary_conversion": "book appointment"},
                    "raw_html": "<html>must never reach Writer</html>",
                }
            ),
            confidence=0.9,
            prompt_version="researcher:v1",
            model_id="fake-research-1",
        )
    )
    await session.flush()
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
    return lead, strategy, evidence


def _valid_payload(evidence_id: int) -> str:
    return json.dumps(
        {
            "subject": "Mobile booking thought",
            "body": "I noticed the booking action on your mobile homepage is easy to miss. That may add friction for visitors trying to book. WEBERAISE designs and builds websites; happy to send over one focused idea if useful.",
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


@pytest.mark.asyncio
async def test_writer_persists_evidence_linked_draft_and_generation_metadata(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead, strategy, evidence = await _seed_contactable_lead(session)
        provider = FakeProvider([_valid_payload(evidence.id)])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"writer": "fake"},
        )
        playbook = load_playbook(PLAYBOOK_DIR)
        output = await WriterService(
            session,
            gateway=gateway,
            playbook=playbook,
        ).write(lead_id=lead.id)

        assert output.prompt_version == "writer:v1"
        assert output.playbook_hash == playbook.version_hash
        assert output.strategy_label == "CONVERSION_PROBLEM"
        assert len(provider.calls) == 1
        assert "<html>" not in provider.calls[0]["user"]

        draft = await session.scalar(select(EmailDraft).where(EmailDraft.lead_id == lead.id))
        assert draft is not None
        assert draft.strategy_id == strategy.id
        assert draft.writer_prompt_version == "writer:v1"
        assert draft.model_id == "fake-writer-1"
        assert await session.scalar(select(func.count()).select_from(EmailDraftClaim)) == 2
        metadata = await session.scalar(
            select(DraftGenerationMetadata).where(DraftGenerationMetadata.draft_id == draft.id)
        )
        assert metadata is not None
        assert metadata.playbook_hash == playbook.version_hash
        assert metadata.strategy_label == "CONVERSION_PROBLEM"
        assert 0.0 <= metadata.recent_similarity <= 1.0

    await engine.dispose()


@pytest.mark.asyncio
async def test_writer_rejects_banned_phrase_before_persistence(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead, _strategy, evidence = await _seed_contactable_lead(session)
        payload = json.loads(_valid_payload(evidence.id))
        payload["body"] = "I hope this message finds you well. " + payload["body"]
        provider = FakeProvider([json.dumps(payload)])
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"writer": "fake"})

        with pytest.raises(BannedPhraseError):
            await WriterService(
                session,
                gateway=gateway,
                playbook=load_playbook(PLAYBOOK_DIR),
            ).write(lead_id=lead.id)

        assert await session.scalar(select(func.count()).select_from(EmailDraft)) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_writer_rejects_unknown_evidence_reference(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead, _strategy, evidence = await _seed_contactable_lead(session)
        payload = json.loads(_valid_payload(evidence.id))
        payload["claims"][0]["evidence_ids"] = [999]
        provider = FakeProvider([json.dumps(payload)])
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"writer": "fake"})

        with pytest.raises(WriterEvidenceError):
            await WriterService(
                session,
                gateway=gateway,
                playbook=load_playbook(PLAYBOOK_DIR),
            ).write(lead_id=lead.id)

        assert await session.scalar(select(func.count()).select_from(EmailDraft)) == 0

    await engine.dispose()

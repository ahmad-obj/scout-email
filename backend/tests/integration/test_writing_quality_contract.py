from __future__ import annotations

import json
from pathlib import Path

import pytest

import scout_email.writing.critic as critic_module
from scout_email.common.enums import ApprovalState, ClaimClass, LeadState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Contact, EmailDraft, EmailDraftClaim, Evidence, Lead
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.prompts import build_system_prompt
from scout_email.llm.schemas import ProviderResult
from scout_email.writing.critic import CriticService, scan_hard_rejection_issues
from scout_email.writing.playbook import load_playbook
from scout_email.writing.schemas import DraftClaim
from scout_email.writing.writer import WriterService


PLAYBOOK_DIR = Path(__file__).parents[3] / "config" / "weberaise"


class FakeProvider:
    name = "fake"
    model = "fake-critic-1"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_json(self, *, system: str, user: str, schema: dict) -> ProviderResult:
        self.calls.append({"system": system, "user": user, "schema": schema})
        return ProviderResult(
            provider=self.name,
            model=self.model,
            text=json.dumps(
                {
                    "decision": "APPROVE",
                    "scores": {
                        "specificity": 90,
                        "naturalness": 90,
                        "persuasiveness": 85,
                        "evidence_integrity": 100,
                        "genericness": 10,
                        "spamminess": 5,
                    },
                    "issues": [],
                }
            ),
        )


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'writing-quality-contract.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


def test_writer_and_critic_prompts_enforce_claim_ledger_quality_policy():
    writer = build_system_prompt(task="writer", prompt_version="writer:v2")
    critic = build_system_prompt(task="critic", prompt_version="critic:v2")

    assert "every material prospect-specific factual or inferential statement" in writer.casefold()
    assert "claims" in writer.casefold()
    assert "fake compliments" in writer.casefold()
    assert "customer behavior" in writer.casefold()
    assert "technical architecture" in writer.casefold()

    assert "audit the complete subject and body" in critic.casefold()
    assert "claim ledger" in critic.casefold()
    assert "uncatalogued" in critic.casefold()
    assert "fake compliments" in critic.casefold()
    assert "unsupported customer behavior" in critic.casefold()

    assert WriterService.PROMPT_VERSION == "writer:v2"
    assert critic_module._PROMPT_VERSION == "critic:v2"


def test_live_smoke_draft_is_not_allowed_to_pass_hard_language_rules():
    body = """I’ve been looking through the Pacific Northwest X-Ray catalog and was impressed by the sheer depth of your inventory. With over 6,800 active stock numbers spanning podiatric, veterinary, and clinical imaging, it’s clearly a vital resource for your customers.

While the depth of information is excellent, I noticed that the current structure—which is a great foundation—is not yet optimized for modern security standards like HTTPS or for the mobile browsing habits of busy medical professionals on the go.

I’m with WEBERAISE, a development agency that helps companies like yours bridge that gap. We specialize in modernizing legacy catalog structures while maintaining the technical integrity of the inventory, essentially giving your current database a more secure and accessible delivery layer.

Would you be open to seeing a brief example of how we could modernize the mobile interface and security foundation for your product pages without disrupting your current ordering flow?"""
    claims = [
        DraftClaim(
            text="Pacific Northwest X-Ray Inc. maintains a large online catalog with over 900 pages and 6,800 active stock numbers.",
            claim_class=ClaimClass.OBSERVED_FACT,
            evidence_ids=[38],
        ),
        DraftClaim(
            text="The company website lacks HTTPS and responsive design elements.",
            claim_class=ClaimClass.OBSERVED_FACT,
            evidence_ids=[35, 36],
        ),
        DraftClaim(
            text="Modernizing the platform could improve accessibility and security for users browsing on mobile devices.",
            claim_class=ClaimClass.REASONABLE_INFERENCE,
            evidence_ids=[35, 38],
        ),
    ]

    issues = scan_hard_rejection_issues(body=body, claims=claims)

    assert "gratuitous_praise" in issues


@pytest.mark.asyncio
async def test_critic_receives_weberaise_rules_and_explicit_body_coverage_policy(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        campaign = Campaign(
            name="Quality Contract",
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
            claim_class=ClaimClass.OBSERVED_FACT.value,
            claim="The mobile booking CTA is difficult to spot.",
            source_type="screenshot",
            source_url="https://example.com/",
            confidence=0.95,
        )
        session.add_all([contact, evidence])
        await session.flush()
        draft = EmailDraft(
            lead_id=lead.id,
            subject="Mobile booking thought",
            body="I noticed the mobile booking CTA is difficult to spot. Would it be useful if I sent one focused idea?",
            writer_prompt_version="writer:v2",
            model_id="fake-writer-1",
            approval_state=ApprovalState.PENDING.value,
        )
        session.add(draft)
        await session.flush()
        session.add(
            EmailDraftClaim(
                draft_id=draft.id,
                claim_text="The mobile booking CTA is difficult to spot.",
                claim_class=ClaimClass.OBSERVED_FACT.value,
                evidence_ids_json=json.dumps([evidence.id]),
            )
        )
        await session.commit()

        provider = FakeProvider()
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})
        playbook = load_playbook(PLAYBOOK_DIR)

        await CriticService(session, gateway=gateway, playbook=playbook).review(draft_id=draft.id)

        assert len(provider.calls) == 1
        payload = json.loads(provider.calls[0]["user"])
        rules = payload["review_rules"]
        assert rules["audit_complete_body_against_claim_ledger"] is True
        assert rules["writing_rules"] == playbook.writing_rules
        assert rules["company_context"] == playbook.company_context
        assert rules["cta_rules"] == playbook.cta_rules

    await engine.dispose()

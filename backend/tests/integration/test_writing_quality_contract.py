from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

import scout_email.writing.critic as critic_module
from scout_email.common.enums import ApprovalState, ClaimClass, DraftReviewDecision, LeadState
from scout_email.db.base import Base
from scout_email.db.models import (
    Campaign,
    Contact,
    EmailDraft,
    EmailDraftClaim,
    EmailReview,
    Evidence,
    Lead,
)
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

    def __init__(
        self,
        *,
        audit_mode: str = "clean",
        coverage_complete: bool = True,
        copy_abstractions: list[str] | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.audit_mode = audit_mode
        self.coverage_complete = coverage_complete
        self.copy_abstractions = copy_abstractions or []

    async def generate_json(self, *, system: str, user: str, schema: dict) -> ProviderResult:
        self.calls.append({"system": system, "user": user, "schema": schema})
        payload = {
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

        # Keep this fake compatible with both the pre-v4 schema and the
        # future structured-audit schema so RED fails on behavior, not parsing.
        if "assertion_audits" in schema.get("properties", {}):
            context = json.loads(user)
            ledger_claim = context["claims"][0]["text"]
            evidence_id = context["claims"][0]["evidence_ids"][0]
            audit = {
                "body_assertion": ledger_claim,
                "assertion_type": "PROSPECT_FACT",
                "ledger_claim": ledger_claim,
                "evidence_ids": [evidence_id],
                "company_context_quote": None,
                "verdict": "ENTAILED",
                "explanation": "The wording preserves the supplied evidence meaning.",
            }
            if self.audit_mode == "semantic_expansion":
                audit["body_assertion"] = (
                    "The site is served over HTTP, so it falls below current web security standards."
                )
                audit["verdict"] = "SEMANTIC_EXPANSION"
                audit["explanation"] = "The standards claim is stronger than the cited observation."
            elif self.audit_mode == "uncatalogued":
                audit["body_assertion"] = "Customers may avoid the site because it uses HTTP."
                audit["ledger_claim"] = None
                audit["verdict"] = "REASONABLE_INFERENCE"
                audit["explanation"] = "This material prospect inference is absent from the ledger."
            elif self.audit_mode == "unsupported_self_claim":
                audit = {
                    "body_assertion": "WEBERAISE specializes in large product databases.",
                    "assertion_type": "WEBERAISE_SELF_CLAIM",
                    "ledger_claim": None,
                    "evidence_ids": [],
                    "company_context_quote": "specializes in large product databases",
                    "verdict": "ENTAILED",
                    "explanation": "Claimed as supported by company context.",
                }
            payload.update(
                {
                    "assertion_audits": [audit],
                    "coverage_complete": self.coverage_complete,
                    "copy_abstractions": self.copy_abstractions,
                }
            )

        return ProviderResult(
            provider=self.name,
            model=self.model,
            text=json.dumps(payload),
        )


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'writing-quality-contract.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed_reviewable_draft(session, *, body: str):
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
        kind="crawl_page",
        claim_class=ClaimClass.OBSERVED_FACT.value,
        claim="The site is served over HTTP rather than HTTPS.",
        source_type="crawl_page",
        source_url="http://example.com/",
        confidence=1.0,
    )
    session.add_all([contact, evidence])
    await session.flush()
    draft = EmailDraft(
        lead_id=lead.id,
        subject="Website security thought",
        body=body,
        writer_prompt_version="writer:v3",
        model_id="fake-writer-1",
        approval_state=ApprovalState.PENDING.value,
    )
    session.add(draft)
    await session.flush()
    session.add(
        EmailDraftClaim(
            draft_id=draft.id,
            claim_text="The site is served over HTTP rather than HTTPS.",
            claim_class=ClaimClass.OBSERVED_FACT.value,
            evidence_ids_json=json.dumps([evidence.id]),
        )
    )
    await session.commit()
    return draft


def test_writer_and_critic_prompts_enforce_v3_semantic_fidelity_policy():
    writer = build_system_prompt(task="writer", prompt_version="writer:v3")
    critic = build_system_prompt(task="critic", prompt_version="critic:v4")

    assert "every material prospect-specific factual or inferential statement" in writer.casefold()
    assert "semantically entailed" in writer.casefold()
    assert "stock numbers" in writer.casefold()
    assert "products" in writer.casefold()
    assert "audience" in writer.casefold()
    assert "company context" in writer.casefold()
    assert "plain" in writer.casefold()

    assert "audit the complete subject and body" in critic.casefold()
    assert "claim ledger" in critic.casefold()
    assert "structured assertion audit" in critic.casefold()
    assert "semantic expansion" in critic.casefold()
    assert "uncatalogued" in critic.casefold()
    assert "company context" in critic.casefold()
    assert "generic" in critic.casefold()

    assert WriterService.PROMPT_VERSION == "writer:v3"
    assert critic_module._PROMPT_VERSION == "critic:v4"


def test_critic_model_schema_requires_structured_assertion_audit():
    schema = critic_module.CriticModelOutput.model_json_schema()
    required = set(schema.get("required", []))

    assert {"assertion_audits", "coverage_complete", "copy_abstractions"} <= required


def test_email_review_model_persists_structured_audit():
    assert hasattr(EmailReview, "audit_json")


def test_original_live_smoke_draft_is_not_allowed_to_pass_hard_language_rules():
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
async def test_critic_receives_v4_structured_audit_and_playbook_rules(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        draft = await _seed_reviewable_draft(
            session,
            body=(
                "I noticed the site is served over HTTP rather than HTTPS. "
                "Would it be useful if I sent one focused idea?"
            ),
        )
        provider = FakeProvider()
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})
        playbook = load_playbook(PLAYBOOK_DIR)

        await CriticService(session, gateway=gateway, playbook=playbook).review(draft_id=draft.id)

        assert len(provider.calls) == 1
        payload = json.loads(provider.calls[0]["user"])
        rules = payload["review_rules"]
        assert rules["audit_complete_body_against_claim_ledger"] is True
        assert rules["require_claim_evidence_entailment"] is True
        assert rules["forbid_unsupported_audience_personas"] is True
        assert rules["require_weberaise_claims_from_company_context"] is True
        assert rules["prefer_plain_language_over_agency_abstractions"] is True
        assert rules["require_structured_assertion_audit"] is True
        assert rules["writing_rules"] == playbook.writing_rules
        assert rules["company_context"] == playbook.company_context
        assert rules["cta_rules"] == playbook.cta_rules
        assert rules["rejected_patterns"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_critic_downgrades_approval_for_unsupported_audience_persona(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        draft = await _seed_reviewable_draft(
            session,
            body=(
                "The site is served over HTTP rather than HTTPS, so security-conscious customers "
                "may experience friction. Would it be useful if I sent one focused idea?"
            ),
        )
        provider = FakeProvider()
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        review = await CriticService(
            session,
            gateway=gateway,
            playbook=load_playbook(PLAYBOOK_DIR),
        ).review(draft_id=draft.id)

        assert review.decision == DraftReviewDecision.REWRITE
        assert "unsupported_audience_persona" in review.issues

    await engine.dispose()


@pytest.mark.asyncio
async def test_critic_downgrades_approval_for_playbook_rejected_pattern(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        draft = await _seed_reviewable_draft(
            session,
            body=(
                "I noticed the site is served over HTTP rather than HTTPS. "
                "WEBERAISE can elevate your online presence. "
                "Would it be useful if I sent one focused idea?"
            ),
        )
        provider = FakeProvider()
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        review = await CriticService(
            session,
            gateway=gateway,
            playbook=load_playbook(PLAYBOOK_DIR),
        ).review(draft_id=draft.id)

        assert review.decision == DraftReviewDecision.REWRITE
        assert any(issue.startswith("rejected_pattern:") for issue in review.issues)

    await engine.dispose()


@pytest.mark.asyncio
async def test_structured_audit_semantic_expansion_cannot_approve(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        draft = await _seed_reviewable_draft(
            session,
            body=(
                "The site is served over HTTP, so it falls below current web security standards. "
                "Would it be useful if I sent one focused idea?"
            ),
        )
        provider = FakeProvider(audit_mode="semantic_expansion")
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        review = await CriticService(
            session,
            gateway=gateway,
            playbook=load_playbook(PLAYBOOK_DIR),
        ).review(draft_id=draft.id)

        assert review.decision == DraftReviewDecision.REWRITE
        assert any(issue.startswith("semantic_expansion:") for issue in review.issues)

    await engine.dispose()


@pytest.mark.asyncio
async def test_structured_audit_uncatalogued_material_assertion_cannot_approve(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        draft = await _seed_reviewable_draft(
            session,
            body=(
                "The site is served over HTTP rather than HTTPS. "
                "Customers may avoid the site because it uses HTTP."
            ),
        )
        provider = FakeProvider(audit_mode="uncatalogued")
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        review = await CriticService(
            session,
            gateway=gateway,
            playbook=load_playbook(PLAYBOOK_DIR),
        ).review(draft_id=draft.id)

        assert review.decision == DraftReviewDecision.REWRITE
        assert "uncatalogued_material_assertion" in review.issues

    await engine.dispose()


@pytest.mark.asyncio
async def test_structured_audit_weberaise_quote_must_exist_in_company_context(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        draft = await _seed_reviewable_draft(
            session,
            body=(
                "I noticed the site is served over HTTP rather than HTTPS. "
                "WEBERAISE specializes in large product databases."
            ),
        )
        provider = FakeProvider(audit_mode="unsupported_self_claim")
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        review = await CriticService(
            session,
            gateway=gateway,
            playbook=load_playbook(PLAYBOOK_DIR),
        ).review(draft_id=draft.id)

        assert review.decision == DraftReviewDecision.REWRITE
        assert "unsupported_weberaise_claim" in review.issues

    await engine.dispose()


@pytest.mark.asyncio
async def test_structured_audit_incomplete_coverage_or_abstraction_cannot_approve(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        draft = await _seed_reviewable_draft(
            session,
            body=(
                "I noticed the site is served over HTTP rather than HTTPS. "
                "We could modernize your site's foundation."
            ),
        )
        provider = FakeProvider(
            coverage_complete=False,
            copy_abstractions=["modernize your site's foundation"],
        )
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        review = await CriticService(
            session,
            gateway=gateway,
            playbook=load_playbook(PLAYBOOK_DIR),
        ).review(draft_id=draft.id)

        assert review.decision == DraftReviewDecision.REWRITE
        assert "incomplete_body_assertion_audit" in review.issues
        assert any(issue.startswith("agency_abstraction:") for issue in review.issues)

    await engine.dispose()


@pytest.mark.asyncio
async def test_structured_audit_is_persisted_with_effective_review(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        draft = await _seed_reviewable_draft(
            session,
            body=(
                "I noticed the site is served over HTTP rather than HTTPS. "
                "Would it be useful if I sent one focused idea?"
            ),
        )
        provider = FakeProvider()
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        review = await CriticService(
            session,
            gateway=gateway,
            playbook=load_playbook(PLAYBOOK_DIR),
        ).review(draft_id=draft.id)
        row = await session.scalar(
            select(EmailReview).where(EmailReview.draft_id == draft.id).order_by(EmailReview.id.desc())
        )

        assert row is not None
        persisted = json.loads(row.audit_json)
        assert persisted["coverage_complete"] is True
        assert persisted["assertion_audits"]
        assert persisted["model_decision"] == "APPROVE"
        assert persisted["effective_decision"] == review.decision.value

    await engine.dispose()

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from scout_email.approval.service import ApprovalService
from scout_email.browser.schemas import BrowserMapLead, BrowserRenderResponse
from scout_email.campaigns.schemas import CampaignCreate, QualificationPolicy
from scout_email.campaigns.service import CampaignService
from scout_email.common.enums import FollowupState, LeadState, ReplyClass, WebsiteState
from scout_email.crawl.persistence import CrawlPersistenceService
from scout_email.crawl.site import crawl_site
from scout_email.db.base import Base
from scout_email.db.models import (
    Contact,
    EmailDraft,
    EmailThread,
    Followup,
    Lead,
    LeadScore,
    OutboundMessage,
    Reply,
    Sender,
)
from scout_email.db.repositories import LeadRepository
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.enrichment.service import EnrichmentService, PublicPage
from scout_email.enrichment.website import WebsiteVerification
from scout_email.evidence.service import EvidenceService
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.schemas import GenerationMetadata, ProviderResult, StructuredGeneration
from scout_email.messaging.service import MessagingService
from scout_email.metrics.service import CampaignMetricsService
from scout_email.replies.followup import FollowupService
from scout_email.replies.schemas import ReplyIntelligence, ReplySyncRequest
from scout_email.replies.service import ReplyService
from scout_email.research.service import ResearchService
from scout_email.scout.schemas import ScoutSearchJobPayload
from scout_email.scout.service import ScoutService
from scout_email.strategy.service import StrategyService
from scout_email.writing.critic import CriticService
from scout_email.writing.playbook import load_playbook
from scout_email.writing.quality import WriterCriticQualityLoop
from scout_email.writing.writer import WriterService

FIXTURES = Path(__file__).parents[1] / "fixtures" / "e2e"
PLAYBOOK_DIR = Path(__file__).parents[3] / "config" / "weberaise"


class FixtureMapsBrowser:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = [BrowserMapLead.model_validate(row) for row in rows]
        self.calls = 0

    async def search_maps(self, query: str, max_results: int):
        self.calls += 1
        return self.rows[:max_results]


class FixtureRenderBrowser:
    def __init__(self, artifact_root: Path, html: str) -> None:
        self.artifact_root = artifact_root
        self.html = html

    async def render(
        self,
        url: str,
        *,
        viewport: str = "desktop",
        screenshot_path: str | None = None,
    ) -> BrowserRenderResponse:
        assert screenshot_path is not None
        relative = Path(screenshot_path)
        assert not relative.is_absolute()
        assert ".." not in relative.parts
        target = self.artifact_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"fixture-{viewport}".encode())
        return BrowserRenderResponse(
            final_url=url,
            title="Fixture Dental",
            html=self.html,
            screenshot_path=str(target),
        )

    async def capture_homepage_screenshots(
        self,
        url: str,
        *,
        desktop_path: str,
        mobile_path: str,
    ):
        return [
            await self.render(url, viewport="desktop", screenshot_path=desktop_path),
            await self.render(url, viewport="mobile", screenshot_path=mobile_path),
        ]


class StaticProvider:
    def __init__(self, *, name: str, model: str, payload: dict) -> None:
        self.name = name
        self.model = model
        self.payload = payload
        self.calls = 0

    async def generate_json(self, *, system: str, user: str, schema: dict) -> ProviderResult:
        self.calls += 1
        return ProviderResult(
            provider=self.name,
            model=self.model,
            text=json.dumps(self.payload),
        )


class PositiveReplyClassifier:
    async def classify(self, request: ReplySyncRequest) -> ReplyIntelligence:
        return ReplyIntelligence(
            classification=ReplyClass.POSITIVE,
            summary="The owner is interested in the proposed website idea.",
            intent_score=0.96,
            questions=[],
            recommended_action="respond_today",
        )


class FollowupGateway:
    async def generate(self, *, task, context, response_model, prompt_version):
        if task == "followup_writer":
            evidence_id = int(context["allowed_evidence"][0]["id"])
            output = response_model.model_validate(
                {
                    "strategy": "ADD_CONCRETE_IDEA",
                    "subject": "Re: mobile booking idea",
                    "body": (
                        "One concrete idea: make the appointment action visible earlier "
                        "on mobile so visitors can reach it with less friction."
                    ),
                    "claims": [
                        {
                            "text": "The mobile booking action is not prominent in the first view.",
                            "claim_class": "OBSERVED_FACT",
                            "evidence_ids": [evidence_id],
                        }
                    ],
                }
            )
        elif task == "followup_critic":
            output = response_model.model_validate({"decision": "APPROVE", "issues": []})
        else:  # pragma: no cover
            raise AssertionError(f"unexpected follow-up task: {task}")
        return StructuredGeneration(
            output=output,
            metadata=GenerationMetadata(
                task=task,
                provider="fixture",
                model="fixture-followup",
                prompt_version=prompt_version,
                status="COMPLETE",
                repair_attempted=False,
                generated_at=datetime.now(UTC),
            ),
        )


def _maps_rows() -> list[dict]:
    return json.loads((FIXTURES / "maps_leads.json").read_text())


def _site_text(name: str) -> str:
    return (FIXTURES / "site" / name).read_text()


async def _database(tmp_path: Path, name: str):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / name}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _campaign(session, *, name: str, target: int):
    return await CampaignService(session).create(
        CampaignCreate(
            name=name,
            searches=["dentist"],
            locations=["Lahore"],
            target_leads=target,
            qualification=QualificationPolicy(minimum_rating=4.0),
        )
    )


async def _scout_fixture(session, *, campaign_id: int, rows: list[dict]):
    browser = FixtureMapsBrowser(rows)
    payload = ScoutSearchJobPayload(
        campaign_id=campaign_id,
        campaign_search_id=1,
        query="dentist in Lahore",
        search_term="dentist",
        location="Lahore",
        max_results=len(rows),
    )
    service = ScoutService(session, browser=browser)
    first = await service.run_search(payload)
    second = await service.run_search(payload)
    return first, second, browser


async def _enrich_crawl_and_evidence(
    session,
    *,
    campaign_id: int,
    lead: Lead,
    tmp_path: Path,
    include_contact: bool,
):
    domain = lead.canonical_domain or "acme.example"
    home_url = f"https://{domain}/"
    contact_url = f"https://{domain}/contact"
    contact_html = (
        _site_text("contact.html")
        if include_contact
        else "<html><body>No public email.</body></html>"
    )
    await EnrichmentService(session).persist(
        lead.id,
        WebsiteVerification(
            state=WebsiteState.LIVE,
            requested_url=home_url,
            final_url=home_url,
            canonical_domain=domain,
            http_status=200,
        ),
        [
            PublicPage(url=home_url, html=_site_text("homepage.html"), verified=True),
            PublicPage(url=contact_url, html=contact_html, verified=True),
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sitemap.xml":
            body = _site_text("sitemap.xml").replace("acme.example", domain)
            content_type = "application/xml"
        elif path == "/services":
            body = _site_text("services.html")
            content_type = "text/html"
        elif path == "/contact":
            body = contact_html
            content_type = "text/html"
        elif path == "/":
            body = _site_text("homepage.html")
            content_type = "text/html"
        else:
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            headers={"content-type": content_type},
            text=body,
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        crawl = await crawl_site(
            home_url,
            client=client,
            max_pages=3,
            url_validator=lambda _url: None,
        )
    await CrawlPersistenceService(session).persist(lead.id, crawl)

    data_root = tmp_path / "data"
    bundle = await EvidenceService(
        session,
        data_root=data_root,
        browser_client=FixtureRenderBrowser(data_root, _site_text("homepage.html")),
    ).build_bundle(
        campaign_id=campaign_id,
        lead_id=lead.id,
        homepage_url=home_url,
    )
    assert len(bundle.screenshots) == 2
    await LeadRepository(session).transition(lead.id, LeadState.RESEARCH_PENDING)
    await session.commit()
    await session.refresh(lead)
    return bundle


def _research_payload(*, lead: Lead, evidence_id: int, contact_id: int | None):
    return {
        "business": {
            "name": lead.name,
            "summary": "Established local dental clinic.",
            "category": lead.category,
            "location": lead.city,
        },
        "business_model": {
            "target_customers": ["local patients"],
            "offerings": ["family dentistry"],
            "primary_conversion": "book appointment",
        },
        "presence": {"website_state": "LIVE", "social_profiles": []},
        "strengths": [
            {
                "text": "The clinic clearly presents its dental services.",
                "evidence_ids": [evidence_id],
            }
        ],
        "website_findings": [
            {
                "text": "The mobile booking path can be made more prominent.",
                "evidence_ids": [evidence_id],
            }
        ],
        "technical_findings": [],
        "contact": {"contact_id": contact_id} if contact_id is not None else None,
        "confidence": 0.92,
        "outcome": "COMPLETE",
    }


def _strategy_contact_payload(evidence_id: int):
    return {
        "decision": "CONTACT",
        "candidates": [
            {
                "problem": "The booking CTA is difficult to notice on mobile.",
                "angle": "Reduce mobile booking friction.",
                "evidence_ids": [evidence_id],
                "score": {
                    "severity": 0.75,
                    "evidence_confidence": 0.95,
                    "business_impact": 0.8,
                    "weberaise_fit": 0.95,
                    "explainability": 0.9,
                    "generic_speculation_risk": 0.1,
                },
                "safe_to_reference": True,
            }
        ],
        "persuasion_brief": {
            "primary_angle": "reduce mobile booking friction",
            "do_not_use": ["unsupported revenue claims"],
        },
        "supporting_evidence_ids": [evidence_id],
        "score_components": {
            "severity": 0.75,
            "evidence_confidence": 0.95,
            "business_impact": 0.8,
            "weberaise_fit": 0.95,
            "explainability": 0.9,
            "generic_speculation_risk": 0.1,
        },
        "confidence": 0.92,
        "rationale": (
            "The opportunity is specific, visible, and relevant to website conversion UX."
        ),
    }


def _writer_payload(evidence_id: int):
    return {
        "subject": "Mobile booking thought",
        "body": (
            "I noticed the booking action on your mobile homepage is easy to miss. "
            "That may add friction for visitors trying to book. WEBERAISE designs and builds "
            "business websites; happy to send over one focused idea if useful."
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


def _critic_approve_payload(evidence_id: int):
    return {
        "decision": "APPROVE",
        "scores": {
            "specificity": 92,
            "naturalness": 88,
            "persuasiveness": 82,
            "evidence_integrity": 100,
            "genericness": 10,
            "spamminess": 8,
        },
        "issues": [],
        "assertion_audits": [
            {
                "body_assertion": "The booking action on your mobile homepage is easy to miss.",
                "assertion_type": "PROSPECT_FACT",
                "ledger_claim": "The booking action on the mobile homepage is easy to miss.",
                "evidence_ids": [evidence_id],
                "company_context_quote": None,
                "verdict": "ENTAILED",
                "explanation": "The wording preserves the observed booking-path issue.",
            },
            {
                "body_assertion": "That may add friction for visitors trying to book.",
                "assertion_type": "PROSPECT_INFERENCE",
                "ledger_claim": "That may add friction for visitors trying to book.",
                "evidence_ids": [evidence_id],
                "company_context_quote": None,
                "verdict": "REASONABLE_INFERENCE",
                "explanation": "The inference remains cautious and tied to the observation.",
            },
            {
                "body_assertion": "WEBERAISE designs and builds business websites.",
                "assertion_type": "WEBERAISE_SELF_CLAIM",
                "ledger_claim": None,
                "evidence_ids": [],
                "company_context_quote": "web design and web development agency",
                "verdict": "ENTAILED",
                "explanation": "The company context explicitly establishes web design and development.",
            },
        ],
        "coverage_complete": True,
        "copy_abstractions": [],
    }


@pytest.mark.asyncio
async def test_full_v1_fixture_flow_reaches_positive_reply_and_is_idempotent(tmp_path):
    engine, factory = await _database(tmp_path, "full-flow.db")
    async with factory() as session:
        campaign = await _campaign(session, name="Fixture Dental", target=2)
        first_scout, repeated_scout, browser = await _scout_fixture(
            session,
            campaign_id=campaign.id,
            rows=_maps_rows()[:2],
        )
        assert first_scout["created"] == 1
        assert repeated_scout["created"] == 0
        assert browser.calls == 2

        leads = list(
            (
                await session.scalars(
                    select(Lead).where(Lead.campaign_id == campaign.id)
                )
            ).all()
        )
        assert len(leads) == 1
        lead = leads[0]
        score = await session.scalar(select(LeadScore).where(LeadScore.lead_id == lead.id))
        assert score is not None
        assert score.score_type == "qualification"
        assert score.total > 0

        bundle = await _enrich_crawl_and_evidence(
            session,
            campaign_id=campaign.id,
            lead=lead,
            tmp_path=tmp_path,
            include_contact=True,
        )
        contact = await session.scalar(
            select(Contact).where(Contact.lead_id == lead.id, Contact.state == "VERIFIED")
        )
        assert contact is not None
        screenshot_evidence = next(
            item for item in bundle.evidence if item.kind == "screenshot"
        )

        research_provider = StaticProvider(
            name="fixture-research",
            model="fixture-research-1",
            payload=_research_payload(
                lead=lead,
                evidence_id=screenshot_evidence.id,
                contact_id=contact.id,
            ),
        )
        research_gateway = LLMGateway(
            providers={"research": research_provider},
            task_routes={"researcher": "research"},
        )
        research = await ResearchService(
            session,
            gateway=research_gateway,
        ).research(lead_id=lead.id)
        assert research.outcome == "COMPLETE"
        assert research_provider.calls == 1

        strategy_provider = StaticProvider(
            name="fixture-strategy",
            model="fixture-strategy-1",
            payload=_strategy_contact_payload(screenshot_evidence.id),
        )
        strategy_gateway = LLMGateway(
            providers={"strategy": strategy_provider},
            task_routes={"strategist": "strategy"},
        )
        strategy = await StrategyService(
            session,
            gateway=strategy_gateway,
        ).strategize(lead_id=lead.id)
        assert strategy.decision == "CONTACT"
        assert strategy.supporting_evidence_ids == [screenshot_evidence.id]

        writer_provider = StaticProvider(
            name="fixture-writer",
            model="fixture-writer-1",
            payload=_writer_payload(screenshot_evidence.id),
        )
        critic_provider = StaticProvider(
            name="fixture-critic",
            model="fixture-critic-1",
            payload=_critic_approve_payload(screenshot_evidence.id),
        )
        writing_gateway = LLMGateway(
            providers={"writer": writer_provider, "critic": critic_provider},
            task_routes={"writer": "writer", "critic": "critic"},
        )
        playbook = load_playbook(PLAYBOOK_DIR)
        quality = await WriterCriticQualityLoop(
            session,
            writer=WriterService(
                session,
                gateway=writing_gateway,
                playbook=playbook,
            ),
            critic=CriticService(
                session,
                gateway=writing_gateway,
                playbook=playbook,
            ),
        ).run(lead_id=lead.id)
        assert quality.final_decision == "APPROVE"
        assert quality.rewrite_count == 0

        approval = await ApprovalService(session).approve(
            draft_id=quality.draft_id,
            reviewer="fixture-human",
        )
        assert approval.approval_state == "APPROVED"

        sender = Sender(
            label="Fixture Sender",
            email="owned-test@weberaise.example",
            enabled=True,
            health_state="HEALTHY",
        )
        session.add(sender)
        await session.commit()

        messaging = MessagingService(session, send_mode="mock")
        sent = await messaging.queue_and_dispatch(
            draft_id=quality.draft_id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )
        repeated_send = await messaging.queue_and_dispatch(
            draft_id=quality.draft_id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )
        assert sent.id == repeated_send.id
        assert sent.state == "SENT"

        outbound = await session.get(OutboundMessage, sent.id)
        assert outbound is not None
        outbound.sent_at = datetime.now(UTC) - timedelta(days=5)
        await session.commit()
        thread = await session.scalar(
            select(EmailThread).where(EmailThread.lead_id == lead.id)
        )
        assert thread is not None

        prepared = await FollowupService(
            session,
            gateway=FollowupGateway(),
            playbook=load_playbook(PLAYBOOK_DIR),
        ).prepare(thread_id=thread.id, now=datetime.now(UTC))
        assert prepared.state == FollowupState.PENDING_APPROVAL

        request = ReplySyncRequest(
            gmail_thread_id=thread.gmail_thread_id,
            gmail_message_id="fixture-positive-reply-1",
            from_email=contact.normalized_email,
            subject="Re: mobile booking thought",
            body="Yes, this sounds useful. Please send the idea over.",
            headers={},
            received_at=datetime.now(UTC),
        )
        replies = ReplyService(session, classifier=PositiveReplyClassifier())
        first_reply = await replies.sync(request)
        repeated_reply = await replies.sync(request)
        assert first_reply.id == repeated_reply.id
        assert first_reply.classification == ReplyClass.POSITIVE

        followup = await session.get(Followup, prepared.followup_id)
        await session.refresh(thread)
        assert followup is not None
        assert followup.state == FollowupState.CANCELLED.value
        assert thread.followup_cancelled is True

        metrics = await CampaignMetricsService(session).get_metrics(campaign.id)
        assert metrics["counts"] == {
            "discovered": 1,
            "qualified": 1,
            "researched": 1,
            "contactable": 1,
            "drafted": 1,
            "critic_approved": 1,
            "human_approved": 1,
            "sent": 1,
            "bounced": 0,
            "replied": 1,
            "positive": 1,
            "skipped": 0,
        }
        assert await session.scalar(select(func.count()).select_from(OutboundMessage)) == 1
        assert await session.scalar(select(func.count()).select_from(Reply)) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_full_v1_fixture_skip_path_never_creates_outbound_message(tmp_path):
    engine, factory = await _database(tmp_path, "skip-flow.db")
    async with factory() as session:
        campaign = await _campaign(session, name="Excellent Presence", target=1)
        first_scout, repeated_scout, _ = await _scout_fixture(
            session,
            campaign_id=campaign.id,
            rows=[_maps_rows()[2]],
        )
        assert first_scout["created"] == 1
        assert repeated_scout["created"] == 0

        lead = await session.scalar(select(Lead).where(Lead.campaign_id == campaign.id))
        assert lead is not None
        score = await session.scalar(select(LeadScore).where(LeadScore.lead_id == lead.id))
        assert score is not None
        assert score.total > 0

        bundle = await _enrich_crawl_and_evidence(
            session,
            campaign_id=campaign.id,
            lead=lead,
            tmp_path=tmp_path,
            include_contact=False,
        )
        evidence = next(item for item in bundle.evidence if item.kind == "screenshot")
        research_provider = StaticProvider(
            name="fixture-research",
            model="fixture-research-1",
            payload=_research_payload(
                lead=lead,
                evidence_id=evidence.id,
                contact_id=None,
            ),
        )
        research_gateway = LLMGateway(
            providers={"research": research_provider},
            task_routes={"researcher": "research"},
        )
        await ResearchService(session, gateway=research_gateway).research(lead_id=lead.id)

        strategy_provider = StaticProvider(
            name="fixture-strategy",
            model="fixture-strategy-1",
            payload={
                "decision": "SKIP",
                "candidates": [],
                "persuasion_brief": None,
                "supporting_evidence_ids": [],
                "score_components": None,
                "confidence": 0.95,
                "rationale": (
                    "The existing web presence is already strong and no specific outreach "
                    "opportunity is justified."
                ),
            },
        )
        strategy_gateway = LLMGateway(
            providers={"strategy": strategy_provider},
            task_routes={"strategist": "strategy"},
        )
        output = await StrategyService(
            session,
            gateway=strategy_gateway,
        ).strategize(lead_id=lead.id)
        assert output.decision == "SKIP"
        await session.refresh(lead)
        assert lead.state == LeadState.SKIPPED.value
        assert await session.scalar(select(func.count()).select_from(EmailDraft)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboundMessage)) == 0

        metrics = await CampaignMetricsService(session).get_metrics(campaign.id)
        assert metrics["counts"]["skipped"] == 1
        assert metrics["counts"]["sent"] == 0

    await engine.dispose()

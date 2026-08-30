from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from scout_email.common.enums import ApprovalState, JobState, LeadState, MessageState
from scout_email.db.base import Base, TimestampMixin


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE", nullable=False, index=True)
    target_leads: Mapped[int | None] = mapped_column(Integer)
    max_per_day: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    human_approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CampaignSearch(Base):
    __tablename__ = "campaign_searches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    search_term: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    __table_args__ = (UniqueConstraint("campaign_id", "search_term", "location", name="uq_campaign_search"),)


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(40), default=LeadState.DISCOVERED.value, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(200), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(80), index=True)
    canonical_domain: Mapped[str | None] = mapped_column(String(300), index=True)
    maps_url: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)


class LeadSource(Base):
    __tablename__ = "lead_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_external_id: Mapped[str | None] = mapped_column(String(300))
    source_query: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    __table_args__ = (UniqueConstraint("source", "source_external_id", name="uq_lead_source_identity"),)


class LeadScore(Base):
    __tablename__ = "lead_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    score_type: Mapped[str] = mapped_column(String(80), default="qualification", nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    components_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class Website(TimestampMixin, Base):
    __tablename__ = "websites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(Text)
    canonical_domain: Mapped[str | None] = mapped_column(String(300), index=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    contact_type: Mapped[str] = mapped_column(String(60), default="business", nullable=False)
    state: Mapped[str] = mapped_column(String(40), default="VERIFIED", nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    __table_args__ = (UniqueConstraint("lead_id", "normalized_email", name="uq_contact_lead_email"),)


class SocialProfile(Base):
    __tablename__ = "social_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    network: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint("lead_id", "network", "url", name="uq_social_profile"),)


class CrawlPage(Base):
    __tablename__ = "crawl_pages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    important_text: Mapped[str | None] = mapped_column(Text)
    extracted_json: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class Screenshot(Base):
    __tablename__ = "screenshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    page_url: Mapped[str] = mapped_column(Text, nullable=False)
    viewport: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    claim_class: Mapped[str] = mapped_column(String(40), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class ResearchReport(Base):
    __tablename__ = "research_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(60), nullable=False)
    dossier_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    model_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class AuditFinding(Base):
    __tablename__ = "audit_findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False)
    business_impact: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    safe_to_reference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Strategy(Base):
    __tablename__ = "strategies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    primary_angle: Mapped[str | None] = mapped_column(String(200))
    persuasion_brief_json: Mapped[str] = mapped_column(Text, nullable=False)
    score_components_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    model_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class EmailDraft(TimestampMixin, Base):
    __tablename__ = "email_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id", ondelete="SET NULL"))
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    writer_prompt_version: Mapped[str | None] = mapped_column(String(80))
    model_id: Mapped[str | None] = mapped_column(String(200))
    approval_state: Mapped[str] = mapped_column(String(40), default=ApprovalState.PENDING.value, nullable=False, index=True)
    approved_content_hash: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailDraftClaim(Base):
    __tablename__ = "email_draft_claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("email_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_class: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)


class EmailReview(Base):
    __tablename__ = "email_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("email_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    issues_json: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    model_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class EmailEdit(Base):
    __tablename__ = "email_edits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("email_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    original_subject: Mapped[str] = mapped_column(Text, nullable=False)
    original_body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_subject: Mapped[str] = mapped_column(Text, nullable=False)
    edited_body: Mapped[str] = mapped_column(Text, nullable=False)
    edit_context: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class Sender(Base):
    __tablename__ = "senders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    health_state: Mapped[str] = mapped_column(String(40), default="UNCONFIGURED", nullable=False)


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("email_drafts.id"), nullable=False, index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("senders.id"))
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(40), default=MessageState.DRAFT.value, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    gmail_thread_id: Mapped[str | None] = mapped_column(String(300), index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailThread(Base):
    __tablename__ = "email_threads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    followup_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    followup_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class Reply(Base):
    __tablename__ = "replies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    classification: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Followup(Base):
    __tablename__ = "followups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_drafts.id", ondelete="SET NULL"))
    stage: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("thread_id", "stage", name="uq_followup_thread_stage"),)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(40), default=JobState.PENDING.value, nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)


class DoNotContact(Base):
    __tablename__ = "do_not_contact"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    domain: Mapped[str | None] = mapped_column(String(300), index=True)
    business_name: Mapped[str | None] = mapped_column(String(300), index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class Bounce(Base):
    __tablename__ = "bounces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outbound_message_id: Mapped[int | None] = mapped_column(ForeignKey("outbound_messages.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    bounce_type: Mapped[str] = mapped_column(String(60), nullable=False)
    diagnostic: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class WritingRule(Base):
    __tablename__ = "writing_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)


class ApprovedExample(Base):
    __tablename__ = "approved_examples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    industry: Mapped[str | None] = mapped_column(String(120), index=True)
    strategy_label: Mapped[str | None] = mapped_column(String(120), index=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)


class RejectedPattern(Base):
    __tablename__ = "rejected_patterns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    __table_args__ = (UniqueConstraint("task", "version", name="uq_prompt_task_version"),)


class CampaignMetric(Base):
    __tablename__ = "campaign_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    __table_args__ = (Index("ix_campaign_metrics_campaign_metric", "campaign_id", "metric"),)

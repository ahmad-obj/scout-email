"""Initial frozen SQLite schema for Scout Email V1.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-30
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_DDL = [
    """CREATE TABLE approved_examples (
        id INTEGER PRIMARY KEY, industry VARCHAR(120), strategy_label VARCHAR(120),
        subject TEXT NOT NULL, body TEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE campaigns (
        id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, status VARCHAR(40) NOT NULL DEFAULT 'ACTIVE',
        target_leads INTEGER, max_per_day INTEGER NOT NULL DEFAULT 10,
        human_approval_required BOOLEAN NOT NULL DEFAULT 1,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE do_not_contact (
        id INTEGER PRIMARY KEY, email VARCHAR(320), domain VARCHAR(300), business_name VARCHAR(300),
        reason TEXT NOT NULL, source VARCHAR(80) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE jobs (
        id INTEGER PRIMARY KEY, job_type VARCHAR(80) NOT NULL, state VARCHAR(40) NOT NULL DEFAULT 'PENDING',
        entity_type VARCHAR(80), entity_id INTEGER, payload_json TEXT NOT NULL DEFAULT '{}', result_json TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
        run_after DATETIME, locked_at DATETIME, last_error TEXT, idempotency_key VARCHAR(128) UNIQUE,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE prompt_versions (
        id INTEGER PRIMARY KEY, task VARCHAR(80) NOT NULL, version VARCHAR(80) NOT NULL,
        content_hash VARCHAR(128) NOT NULL, active BOOLEAN NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_prompt_task_version UNIQUE(task, version))""",
    """CREATE TABLE rejected_patterns (
        id INTEGER PRIMARY KEY, pattern TEXT NOT NULL, reason TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT 1)""",
    """CREATE TABLE senders (
        id INTEGER PRIMARY KEY, label VARCHAR(200) NOT NULL, email VARCHAR(320) NOT NULL UNIQUE,
        enabled BOOLEAN NOT NULL DEFAULT 0, health_state VARCHAR(40) NOT NULL DEFAULT 'UNCONFIGURED')""",
    """CREATE TABLE writing_rules (
        id INTEGER PRIMARY KEY, category VARCHAR(80) NOT NULL, rule_text TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT 1, version VARCHAR(40) NOT NULL)""",
    """CREATE TABLE campaign_searches (
        id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        search_term VARCHAR(200) NOT NULL, location VARCHAR(200) NOT NULL,
        CONSTRAINT uq_campaign_search UNIQUE(campaign_id, search_term, location))""",
    """CREATE TABLE campaign_metrics (
        id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        metric VARCHAR(100) NOT NULL, value FLOAT NOT NULL,
        measured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE leads (
        id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        state VARCHAR(40) NOT NULL DEFAULT 'DISCOVERED', name VARCHAR(300) NOT NULL,
        normalized_name VARCHAR(300) NOT NULL, category VARCHAR(200), city VARCHAR(200), address TEXT,
        phone VARCHAR(80), canonical_domain VARCHAR(300), maps_url TEXT, rating FLOAT, review_count INTEGER,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE audit_findings (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        problem TEXT NOT NULL, severity FLOAT NOT NULL, business_impact FLOAT NOT NULL,
        confidence FLOAT NOT NULL, evidence_ids_json TEXT NOT NULL, safe_to_reference BOOLEAN NOT NULL DEFAULT 0)""",
    """CREATE TABLE contacts (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        email VARCHAR(320) NOT NULL, normalized_email VARCHAR(320) NOT NULL,
        contact_type VARCHAR(60) NOT NULL DEFAULT 'business', state VARCHAR(40) NOT NULL DEFAULT 'VERIFIED',
        source_url TEXT NOT NULL, confidence FLOAT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_contact_lead_email UNIQUE(lead_id, normalized_email))""",
    """CREATE TABLE crawl_pages (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        url TEXT NOT NULL, title TEXT, important_text TEXT, extracted_json TEXT, http_status INTEGER,
        crawled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE evidence (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        kind VARCHAR(80) NOT NULL, claim_class VARCHAR(40) NOT NULL, claim TEXT NOT NULL,
        source_type VARCHAR(80) NOT NULL, source_url TEXT, artifact_path TEXT, confidence FLOAT NOT NULL,
        observed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE lead_scores (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        score_type VARCHAR(80) NOT NULL DEFAULT 'qualification', total FLOAT NOT NULL,
        components_json TEXT NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE lead_sources (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        source VARCHAR(80) NOT NULL, source_external_id VARCHAR(300), source_query VARCHAR(300),
        source_url TEXT, raw_json TEXT, discovered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_lead_source_identity UNIQUE(source, source_external_id))""",
    """CREATE TABLE research_reports (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        status VARCHAR(60) NOT NULL, dossier_json TEXT NOT NULL, confidence FLOAT,
        prompt_version VARCHAR(80), model_id VARCHAR(200), created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE screenshots (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        page_url TEXT NOT NULL, viewport VARCHAR(40) NOT NULL, artifact_path TEXT NOT NULL,
        captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE social_profiles (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        network VARCHAR(80) NOT NULL, url TEXT NOT NULL, verified BOOLEAN NOT NULL DEFAULT 0,
        CONSTRAINT uq_social_profile UNIQUE(lead_id, network, url))""",
    """CREATE TABLE strategies (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        decision VARCHAR(40) NOT NULL, primary_angle VARCHAR(200), persuasion_brief_json TEXT NOT NULL,
        score_components_json TEXT NOT NULL, confidence FLOAT NOT NULL,
        prompt_version VARCHAR(80), model_id VARCHAR(200), created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE websites (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        url TEXT, canonical_domain VARCHAR(300), state VARCHAR(40) NOT NULL, final_url TEXT, http_status INTEGER,
        verified_at DATETIME, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE email_drafts (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        strategy_id INTEGER REFERENCES strategies(id) ON DELETE SET NULL, subject VARCHAR(300) NOT NULL,
        body TEXT NOT NULL, writer_prompt_version VARCHAR(80), model_id VARCHAR(200),
        approval_state VARCHAR(40) NOT NULL DEFAULT 'PENDING', approved_content_hash VARCHAR(128), approved_at DATETIME,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE email_threads (
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id),
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id), gmail_thread_id VARCHAR(300) NOT NULL UNIQUE,
        followup_stage INTEGER NOT NULL DEFAULT 0, followup_cancelled BOOLEAN NOT NULL DEFAULT 0,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE email_draft_claims (
        id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL REFERENCES email_drafts(id) ON DELETE CASCADE,
        claim_text TEXT NOT NULL, claim_class VARCHAR(40) NOT NULL, evidence_ids_json TEXT NOT NULL)""",
    """CREATE TABLE email_edits (
        id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL REFERENCES email_drafts(id) ON DELETE CASCADE,
        original_subject TEXT NOT NULL, original_body TEXT NOT NULL, edited_subject TEXT NOT NULL,
        edited_body TEXT NOT NULL, edit_context VARCHAR(80), created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE email_reviews (
        id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL REFERENCES email_drafts(id) ON DELETE CASCADE,
        decision VARCHAR(40) NOT NULL, scores_json TEXT NOT NULL, issues_json TEXT NOT NULL,
        prompt_version VARCHAR(80), model_id VARCHAR(200), created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE followups (
        id INTEGER PRIMARY KEY, thread_id INTEGER NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
        draft_id INTEGER REFERENCES email_drafts(id) ON DELETE SET NULL, stage INTEGER NOT NULL DEFAULT 1,
        state VARCHAR(40) NOT NULL, due_at DATETIME, cancelled_reason TEXT,
        CONSTRAINT uq_followup_thread_stage UNIQUE(thread_id, stage))""",
    """CREATE TABLE outbound_messages (
        id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
        lead_id INTEGER NOT NULL REFERENCES leads(id), draft_id INTEGER NOT NULL REFERENCES email_drafts(id),
        sender_id INTEGER REFERENCES senders(id), recipient_email VARCHAR(320) NOT NULL,
        subject TEXT NOT NULL, body TEXT NOT NULL, state VARCHAR(40) NOT NULL DEFAULT 'DRAFT',
        idempotency_key VARCHAR(128) NOT NULL UNIQUE, gmail_message_id VARCHAR(300) UNIQUE,
        gmail_thread_id VARCHAR(300), queued_at DATETIME, sent_at DATETIME)""",
    """CREATE TABLE replies (
        id INTEGER PRIMARY KEY, thread_id INTEGER NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
        gmail_message_id VARCHAR(300) NOT NULL UNIQUE, classification VARCHAR(60) NOT NULL,
        summary TEXT, raw_text TEXT, received_at DATETIME NOT NULL)""",
    """CREATE TABLE bounces (
        id INTEGER PRIMARY KEY, outbound_message_id INTEGER REFERENCES outbound_messages(id),
        email VARCHAR(320) NOT NULL, bounce_type VARCHAR(60) NOT NULL, diagnostic TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
]

INDEX_DDL = [
    "CREATE INDEX ix_campaigns_status ON campaigns(status)",
    "CREATE INDEX ix_do_not_contact_email ON do_not_contact(email)",
    "CREATE INDEX ix_do_not_contact_domain ON do_not_contact(domain)",
    "CREATE INDEX ix_do_not_contact_business_name ON do_not_contact(business_name)",
    "CREATE INDEX ix_jobs_state ON jobs(state)",
    "CREATE INDEX ix_jobs_job_type ON jobs(job_type)",
    "CREATE INDEX ix_jobs_run_after ON jobs(run_after)",
    "CREATE INDEX ix_jobs_entity_id ON jobs(entity_id)",
    "CREATE INDEX ix_prompt_versions_task ON prompt_versions(task)",
    "CREATE INDEX ix_writing_rules_category ON writing_rules(category)",
    "CREATE INDEX ix_campaign_searches_campaign_id ON campaign_searches(campaign_id)",
    "CREATE INDEX ix_campaign_metrics_campaign_id ON campaign_metrics(campaign_id)",
    "CREATE INDEX ix_campaign_metrics_campaign_metric ON campaign_metrics(campaign_id, metric)",
    "CREATE INDEX ix_leads_campaign_id ON leads(campaign_id)",
    "CREATE INDEX ix_leads_state ON leads(state)",
    "CREATE INDEX ix_leads_normalized_name ON leads(normalized_name)",
    "CREATE INDEX ix_leads_city ON leads(city)",
    "CREATE INDEX ix_leads_phone ON leads(phone)",
    "CREATE INDEX ix_leads_canonical_domain ON leads(canonical_domain)",
    "CREATE INDEX ix_audit_findings_lead_id ON audit_findings(lead_id)",
    "CREATE INDEX ix_contacts_lead_id ON contacts(lead_id)",
    "CREATE INDEX ix_contacts_email ON contacts(email)",
    "CREATE INDEX ix_contacts_normalized_email ON contacts(normalized_email)",
    "CREATE INDEX ix_crawl_pages_lead_id ON crawl_pages(lead_id)",
    "CREATE INDEX ix_evidence_lead_id ON evidence(lead_id)",
    "CREATE INDEX ix_evidence_kind ON evidence(kind)",
    "CREATE INDEX ix_lead_scores_lead_id ON lead_scores(lead_id)",
    "CREATE INDEX ix_lead_sources_lead_id ON lead_sources(lead_id)",
    "CREATE INDEX ix_research_reports_lead_id ON research_reports(lead_id)",
    "CREATE INDEX ix_screenshots_lead_id ON screenshots(lead_id)",
    "CREATE INDEX ix_social_profiles_lead_id ON social_profiles(lead_id)",
    "CREATE INDEX ix_strategies_lead_id ON strategies(lead_id)",
    "CREATE INDEX ix_strategies_decision ON strategies(decision)",
    "CREATE INDEX ix_websites_lead_id ON websites(lead_id)",
    "CREATE INDEX ix_websites_canonical_domain ON websites(canonical_domain)",
    "CREATE INDEX ix_email_drafts_lead_id ON email_drafts(lead_id)",
    "CREATE INDEX ix_email_drafts_approval_state ON email_drafts(approval_state)",
    "CREATE INDEX ix_email_threads_lead_id ON email_threads(lead_id)",
    "CREATE INDEX ix_email_threads_campaign_id ON email_threads(campaign_id)",
    "CREATE INDEX ix_email_draft_claims_draft_id ON email_draft_claims(draft_id)",
    "CREATE INDEX ix_email_edits_draft_id ON email_edits(draft_id)",
    "CREATE INDEX ix_email_reviews_draft_id ON email_reviews(draft_id)",
    "CREATE INDEX ix_followups_thread_id ON followups(thread_id)",
    "CREATE INDEX ix_followups_state ON followups(state)",
    "CREATE INDEX ix_followups_due_at ON followups(due_at)",
    "CREATE INDEX ix_outbound_messages_campaign_id ON outbound_messages(campaign_id)",
    "CREATE INDEX ix_outbound_messages_lead_id ON outbound_messages(lead_id)",
    "CREATE INDEX ix_outbound_messages_draft_id ON outbound_messages(draft_id)",
    "CREATE INDEX ix_outbound_messages_recipient_email ON outbound_messages(recipient_email)",
    "CREATE INDEX ix_outbound_messages_state ON outbound_messages(state)",
    "CREATE INDEX ix_outbound_messages_gmail_thread_id ON outbound_messages(gmail_thread_id)",
    "CREATE INDEX ix_replies_thread_id ON replies(thread_id)",
    "CREATE INDEX ix_replies_classification ON replies(classification)",
    "CREATE INDEX ix_bounces_outbound_message_id ON bounces(outbound_message_id)",
    "CREATE INDEX ix_bounces_email ON bounces(email)",
    "CREATE INDEX ix_approved_examples_industry ON approved_examples(industry)",
    "CREATE INDEX ix_approved_examples_strategy_label ON approved_examples(strategy_label)",
]

DROP_ORDER = [
    "bounces", "replies", "outbound_messages", "followups", "email_reviews", "email_edits",
    "email_draft_claims", "email_threads", "email_drafts", "websites", "strategies",
    "social_profiles", "screenshots", "research_reports", "lead_sources", "lead_scores", "evidence",
    "crawl_pages", "contacts", "audit_findings", "leads", "campaign_metrics", "campaign_searches",
    "writing_rules", "senders", "rejected_patterns", "prompt_versions", "jobs", "do_not_contact",
    "campaigns", "approved_examples",
]


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)
    for statement in INDEX_DDL:
        op.execute(statement)


def downgrade() -> None:
    for table in DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table}")

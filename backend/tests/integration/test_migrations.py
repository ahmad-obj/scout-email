import os
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


EXPECTED_TABLES = {
    "campaigns",
    "campaign_searches",
    "campaign_policies",
    "leads",
    "lead_sources",
    "lead_scores",
    "websites",
    "contacts",
    "social_profiles",
    "crawl_pages",
    "screenshots",
    "evidence",
    "research_reports",
    "audit_findings",
    "strategies",
    "email_drafts",
    "email_draft_claims",
    "email_reviews",
    "email_edits",
    "outbound_messages",
    "email_threads",
    "replies",
    "followups",
    "jobs",
    "job_runtime",
    "senders",
    "do_not_contact",
    "bounces",
    "writing_rules",
    "approved_examples",
    "rejected_patterns",
    "prompt_versions",
    "campaign_metrics",
}


def _upgrade(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    os.environ["SCOUT_EMAIL_DATABASE_URL"] = f"sqlite:///{db_path}"
    cfg = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        str(Path(__file__).parents[2] / "migrations"),
    )
    command.upgrade(cfg, "head")
    return db_path


def test_upgrade_from_empty_database_creates_v1_tables(tmp_path):
    db_path = _upgrade(tmp_path)
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert EXPECTED_TABLES <= tables


def test_migration_creates_message_idempotency_constraint(tmp_path):
    db_path = _upgrade(tmp_path)
    with sqlite3.connect(db_path) as conn:
        indexes = conn.execute("PRAGMA index_list('outbound_messages')").fetchall()
    assert any(row[2] == 1 for row in indexes), indexes


def test_migration_persists_campaign_policy_table(tmp_path):
    db_path = _upgrade(tmp_path)
    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info('campaign_policies')")
        }
    assert {"campaign_id", "qualification_json", "follow_up_json"} <= columns


def test_migration_creates_job_runtime_lease_metadata(tmp_path):
    db_path = _upgrade(tmp_path)
    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info('job_runtime')")
        }
    assert {
        "job_id",
        "locked_by",
        "lease_expires_at",
        "last_error_code",
        "last_error_message",
    } <= columns

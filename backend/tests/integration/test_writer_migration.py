import os
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_alembic_persists_writer_generation_metadata_table(tmp_path):
    db_path = tmp_path / "writer-migration.db"
    os.environ["SCOUT_EMAIL_DATABASE_URL"] = f"sqlite:///{db_path}"
    cfg = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[2] / "migrations"))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info('draft_generation_metadata')")
        }
    assert {
        "draft_id",
        "playbook_hash",
        "strategy_label",
        "recent_similarity",
        "generated_at",
    } <= columns

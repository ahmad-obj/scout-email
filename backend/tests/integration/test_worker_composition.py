from importlib.util import find_spec
from pathlib import Path


EXPECTED_JOB_KINDS = {
    "MAPS_SCOUT_SEARCH",
    "ENRICH",
    "CRAWL_EVIDENCE",
    "RESEARCH",
    "STRATEGY",
    "WRITER_CRITIC",
}


def test_deployment_starts_background_job_worker():
    repo_root = Path(__file__).resolve().parents[3]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "\n  outreach-worker:" in compose
    assert "python -m scout_email.jobs.runtime" in compose


def test_worker_runtime_declares_every_n8n_job_kind():
    spec = find_spec("scout_email.jobs.runtime")
    assert spec is not None, "deployed stack has no job worker runtime module"

    from scout_email.jobs.runtime import WORKER_JOB_KINDS

    assert set(WORKER_JOB_KINDS) == EXPECTED_JOB_KINDS

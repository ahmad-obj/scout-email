from pathlib import Path

import pytest
from pydantic import ValidationError

from scout_email.settings import Settings


ROOT = Path(__file__).resolve().parents[3]


def test_gmail_mode_requires_explicit_transport_configuration(tmp_path):
    with pytest.raises(ValidationError):
        Settings(
            data_dir=tmp_path,
            send_mode="gmail",
            n8n_send_webhook_url=None,
            n8n_webhook_secret=None,
        )

    configured = Settings(
        data_dir=tmp_path,
        send_mode="gmail",
        n8n_send_webhook_url="http://n8n:5678/webhook/send-approved",
        n8n_webhook_secret="test-shared-secret",
    )
    assert configured.send_mode == "gmail"


def test_local_deployment_contract_is_present_and_safe_by_default():
    backend_dockerfile = ROOT / "backend" / "Dockerfile"
    browser_dockerfile = ROOT / "browser-worker" / "Dockerfile"
    compose_file = ROOT / "docker-compose.yml"
    readme = ROOT / "README.md"
    env_example = ROOT / ".env.example"

    for path in (backend_dockerfile, browser_dockerfile, compose_file, readme):
        assert path.is_file(), f"missing deployment artifact: {path.relative_to(ROOT)}"

    backend_text = backend_dockerfile.read_text(encoding="utf-8")
    browser_text = browser_dockerfile.read_text(encoding="utf-8")
    compose = compose_file.read_text(encoding="utf-8")
    docs = readme.read_text(encoding="utf-8").lower()
    env = env_example.read_text(encoding="utf-8")

    assert "USER app" in backend_text
    assert "USER app" in browser_text
    assert "playwright install" in browser_text

    for service in ("outreach-api:", "browser-worker:", "n8n:"):
        assert service in compose
    assert "./data:/data" in compose
    assert "./n8n_data:/home/node/.n8n" in compose
    assert "SCOUT_EMAIL_SEND_MODE" in compose
    assert "mock" in compose

    assert "SCOUT_EMAIL_SEND_MODE=mock" in env
    assert "docker compose up --build" in docs
    assert "mock" in docs
    assert "/review" in docs
    assert "gmail" in docs
    assert "owned" in docs

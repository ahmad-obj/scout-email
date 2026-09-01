import pytest

from scout_email.jobs import runtime
from scout_email.settings import Settings


RUNTIME_TASKS = {"researcher", "strategist", "writer", "critic"}


def test_build_gateway_is_optional_when_llm_is_unconfigured(tmp_path):
    configured = Settings(data_dir=tmp_path)
    assert runtime.build_gateway(configured) is None


def test_build_gateway_routes_all_worker_tasks_to_ollama(tmp_path):
    configured = Settings(
        data_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3:8b",
        ollama_base_url="http://ollama.example:11434",
    )
    gateway = runtime.build_gateway(configured)
    assert gateway is not None
    assert set(gateway.task_routes) == RUNTIME_TASKS
    assert set(gateway.providers) == {"ollama"}
    assert gateway.providers["ollama"].model == "qwen3:8b"


def test_build_gateway_requires_gemini_key(tmp_path):
    configured = Settings(
        data_dir=tmp_path,
        llm_provider="gemini",
        llm_model="gemini-2.5-flash",
        gemini_api_key=None,
    )
    with pytest.raises(ValueError, match="Gemini API key"):
        runtime.build_gateway(configured)


def test_compose_passes_llm_configuration_to_worker():
    compose = runtime.Path(__file__).resolve().parents[3] / "docker-compose.yml"
    rendered = compose.read_text(encoding="utf-8")
    worker = rendered.split("\n  outreach-worker:", 1)[1].split("\n  n8n:", 1)[0]
    assert "SCOUT_EMAIL_LLM_PROVIDER" in worker
    assert "SCOUT_EMAIL_LLM_MODEL" in worker

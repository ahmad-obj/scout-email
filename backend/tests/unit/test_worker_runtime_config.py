import pytest

from scout_email.db.base import Base
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.jobs import runtime
from scout_email.llm.persistence import LLMGenerationRecorder
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


def test_build_gateway_routes_all_worker_tasks_to_openrouter(tmp_path):
    configured = Settings(
        data_dir=tmp_path,
        llm_provider="openrouter",
        llm_model="google/gemini-3.1-flash-lite",
        openrouter_api_key="secret",
    )
    gateway = runtime.build_gateway(configured)
    assert gateway is not None
    assert set(gateway.task_routes) == RUNTIME_TASKS
    assert set(gateway.providers) == {"openrouter"}
    assert gateway.providers["openrouter"].model == "google/gemini-3.1-flash-lite"


def test_build_gateway_requires_openrouter_key(tmp_path):
    configured = Settings(
        data_dir=tmp_path,
        llm_provider="openrouter",
        llm_model="google/gemini-3.1-flash-lite",
        openrouter_api_key=None,
    )
    with pytest.raises(ValueError, match="OpenRouter API key"):
        runtime.build_gateway(configured)


@pytest.mark.asyncio
async def test_worker_handlers_attach_generation_recorder(tmp_path):
    configured = Settings(
        data_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3:8b",
    )
    gateway = runtime.build_gateway(configured)
    assert gateway is not None

    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'generation-recorder.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        runtime.build_handlers(
            session,
            browser=object(),
            gateway=gateway,
            playbook=object(),
            data_root=tmp_path,
        )
        assert isinstance(gateway.recorder, LLMGenerationRecorder)
        assert gateway.recorder.session is session

    await engine.dispose()


def test_compose_passes_llm_configuration_to_worker():
    compose = runtime.Path(__file__).resolve().parents[3] / "docker-compose.yml"
    rendered = compose.read_text(encoding="utf-8")
    worker = rendered.split("\n  outreach-worker:", 1)[1].split("\n  n8n:", 1)[0]
    assert "SCOUT_EMAIL_LLM_PROVIDER" in worker
    assert "SCOUT_EMAIL_LLM_MODEL" in worker
    assert "SCOUT_EMAIL_OPENROUTER_API_KEY" in worker

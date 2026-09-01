import pytest
from pydantic import ValidationError

from scout_email.settings import Settings


def test_defaults_fail_safe(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert settings.send_mode == "mock"
    assert settings.maps_live_smoke_enabled is False
    assert settings.max_browser_concurrency <= 3
    assert settings.llm_provider is None
    assert settings.llm_model is None


def test_llm_provider_and_model_are_configured_as_pair(tmp_path):
    with pytest.raises(ValidationError, match="llm provider and model"):
        Settings(data_dir=tmp_path, llm_provider="ollama")
    with pytest.raises(ValidationError, match="llm provider and model"):
        Settings(data_dir=tmp_path, llm_model="qwen3:8b")

    configured = Settings(
        data_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3:8b",
    )
    assert configured.llm_provider == "ollama"
    assert configured.llm_model == "qwen3:8b"

import asyncio
import importlib
import importlib.util
import json

import httpx
import pytest

from scout_email.llm.providers.base import ProviderRequestError
from scout_email.llm.providers.gemini import GeminiProvider
from scout_email.llm.providers.ollama import OllamaProvider


_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


@pytest.mark.asyncio
async def test_gemini_provider_uses_interactions_structured_output_contract():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/interactions"
        assert request.headers["x-goog-api-key"] == "secret"
        payload = json.loads(request.content)
        assert payload == {
            "model": "gemini-test",
            "system_instruction": "system rules",
            "input": "user context",
            "response_format": [
                {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": _SCHEMA,
                }
            ],
            "store": False,
        }
        return httpx.Response(
            200,
            json={
                "model": "gemini-test",
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": '{"summary":"ok"}'}],
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://generativelanguage.googleapis.com") as client:
        provider = GeminiProvider(api_key="secret", model="gemini-test", client=client)
        result = await provider.generate_json(system="system rules", user="user context", schema=_SCHEMA)

    assert result.provider == "gemini"
    assert result.model == "gemini-test"
    assert result.text == '{"summary":"ok"}'


@pytest.mark.asyncio
async def test_ollama_provider_uses_chat_schema_and_nonstreaming_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload == {
            "model": "local-test",
            "messages": [
                {"role": "system", "content": "system rules"},
                {"role": "user", "content": "user context"},
            ],
            "stream": False,
            "format": _SCHEMA,
            "options": {"temperature": 0},
        }
        return httpx.Response(
            200,
            json={
                "model": "local-test",
                "message": {"role": "assistant", "content": '{"summary":"local"}'},
                "done": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama") as client:
        provider = OllamaProvider(model="local-test", client=client)
        result = await provider.generate_json(system="system rules", user="user context", schema=_SCHEMA)

    assert result.provider == "ollama"
    assert result.model == "local-test"
    assert result.text == '{"summary":"local"}'


@pytest.mark.asyncio
async def test_openrouter_provider_uses_chat_completions_structured_output_contract():
    module_name = "scout_email.llm.providers.openrouter"
    assert importlib.util.find_spec(module_name) is not None
    OpenRouterProvider = importlib.import_module(module_name).OpenRouterProvider

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload == {
            "model": "openrouter-test",
            "messages": [
                {"role": "system", "content": "system rules"},
                {"role": "user", "content": "user context"},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "scout_email_response",
                    "strict": True,
                    "schema": _SCHEMA,
                },
            },
        }
        return httpx.Response(
            200,
            headers={"x-request-id": "req-123"},
            json={
                "model": "openrouter-test",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"summary":"routed"}',
                        }
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://openrouter.ai",
    ) as client:
        provider = OpenRouterProvider(
            api_key="secret",
            model="openrouter-test",
            client=client,
        )
        result = await provider.generate_json(
            system="system rules",
            user="user context",
            schema=_SCHEMA,
        )

    assert result.provider == "openrouter"
    assert result.model == "openrouter-test"
    assert result.text == '{"summary":"routed"}'
    assert result.request_id == "req-123"


@pytest.mark.asyncio
async def test_openrouter_provider_enforces_total_request_deadline():
    module_name = "scout_email.llm.providers.openrouter"
    OpenRouterProvider = importlib.import_module(module_name).OpenRouterProvider

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(
            200,
            json={
                "model": "openrouter-test",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"summary":"too late"}',
                        }
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://openrouter.ai",
    ) as client:
        provider = OpenRouterProvider(
            api_key="secret",
            model="openrouter-test",
            client=client,
            timeout_seconds=0.01,
        )
        with pytest.raises(ProviderRequestError, match="timed out"):
            await provider.generate_json(
                system="system rules",
                user="user context",
                schema=_SCHEMA,
            )

from __future__ import annotations

from pydantic import BaseModel
import pytest

from scout_email.llm.gateway import LLMGateway, StructuredOutputError
from scout_email.llm.schemas import ProviderResult


class ExampleOutput(BaseModel):
    summary: str
    score: int


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, results: list[str]) -> None:
        self.results = list(results)
        self.calls: list[dict] = []

    async def generate_json(self, *, system: str, user: str, schema: dict) -> ProviderResult:
        self.calls.append({"system": system, "user": user, "schema": schema})
        return ProviderResult(
            provider=self.name,
            model=self.model,
            text=self.results.pop(0),
        )


@pytest.mark.asyncio
async def test_gateway_returns_valid_structured_output_with_metadata():
    provider = FakeProvider(['{"summary":"good fit","score":91}'])
    gateway = LLMGateway(providers={"fake": provider}, task_routes={"researcher": "fake"})

    result = await gateway.generate(
        task="researcher",
        context={"business":"Acme Dental"},
        response_model=ExampleOutput,
        prompt_version="researcher:v1",
    )

    assert result.output == ExampleOutput(summary="good fit", score=91)
    assert result.metadata.provider == "fake"
    assert result.metadata.model == "fake-1"
    assert result.metadata.prompt_version == "researcher:v1"
    assert result.metadata.status == "COMPLETE"
    assert result.metadata.repair_attempted is False
    assert result.metadata.generated_at.tzinfo is not None
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_gateway_allows_exactly_one_schema_repair_attempt():
    provider = FakeProvider([
        '{"summary":"missing score"}',
        '{"summary":"repaired","score":88}',
    ])
    gateway = LLMGateway(providers={"fake": provider}, task_routes={"researcher": "fake"})

    result = await gateway.generate(
        task="researcher",
        context={"business":"Acme Dental"},
        response_model=ExampleOutput,
        prompt_version="researcher:v1",
    )

    assert result.output.score == 88
    assert result.metadata.repair_attempted is True
    assert result.metadata.status == "COMPLETE"
    assert len(provider.calls) == 2
    assert "repair" in provider.calls[1]["system"].casefold()


@pytest.mark.asyncio
async def test_second_invalid_response_fails_typed_and_never_routes_arbitrary_prose():
    provider = FakeProvider([
        "this is not json",
        '{"summary":"still missing score"}',
    ])
    gateway = LLMGateway(providers={"fake": provider}, task_routes={"researcher": "fake"})

    with pytest.raises(StructuredOutputError) as caught:
        await gateway.generate(
            task="researcher",
            context={"business":"Acme Dental"},
            response_model=ExampleOutput,
            prompt_version="researcher:v1",
        )

    assert caught.value.metadata.status == "FAILED_SCHEMA"
    assert caught.value.metadata.repair_attempted is True
    assert caught.value.metadata.provider == "fake"
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_unknown_task_or_provider_fails_before_calling_model():
    provider = FakeProvider(['{"summary":"unused","score":1}'])
    gateway = LLMGateway(providers={"fake": provider}, task_routes={})

    with pytest.raises(ValueError, match="route"):
        await gateway.generate(
            task="writer",
            context={},
            response_model=ExampleOutput,
            prompt_version="writer:v1",
        )

    assert provider.calls == []

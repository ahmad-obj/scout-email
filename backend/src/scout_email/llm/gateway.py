from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from scout_email.llm.prompts import (
    build_repair_user_prompt,
    build_system_prompt,
    build_user_prompt,
)
from scout_email.llm.providers.base import LLMProvider, ProviderRequestError
from scout_email.llm.schemas import GenerationMetadata, StructuredGeneration


T = TypeVar("T", bound=BaseModel)


class GenerationRecorder(Protocol):
    async def record(self, metadata: GenerationMetadata) -> int: ...


class StructuredOutputError(RuntimeError):
    def __init__(self, message: str, *, metadata: GenerationMetadata) -> None:
        super().__init__(message)
        self.metadata = metadata


class ProviderGenerationError(RuntimeError):
    def __init__(self, message: str, *, metadata: GenerationMetadata) -> None:
        super().__init__(message)
        self.metadata = metadata


class LLMGateway:
    def __init__(
        self,
        *,
        providers: Mapping[str, LLMProvider],
        task_routes: Mapping[str, str],
        recorder: GenerationRecorder | None = None,
    ) -> None:
        self.providers = dict(providers)
        self.task_routes = dict(task_routes)
        self.recorder = recorder

    async def generate(
        self,
        *,
        task: str,
        context: Mapping[str, Any],
        response_model: type[T],
        prompt_version: str,
    ) -> StructuredGeneration[T]:
        provider_name = self.task_routes.get(task)
        if provider_name is None:
            raise ValueError(f"no provider route configured for task {task!r}")
        provider = self.providers.get(provider_name)
        if provider is None:
            raise ValueError(f"provider route {provider_name!r} is not configured")

        schema = response_model.model_json_schema()
        system = build_system_prompt(task=task, prompt_version=prompt_version)
        user = build_user_prompt(context)

        try:
            first = await provider.generate_json(system=system, user=user, schema=schema)
        except ProviderRequestError as error:
            metadata = await self._metadata(
                task=task,
                provider=provider,
                prompt_version=prompt_version,
                status="FAILED_PROVIDER",
                repair_attempted=False,
            )
            raise ProviderGenerationError(str(error), metadata=metadata) from error

        try:
            output = self._parse(first.text, response_model)
        except (ValueError, ValidationError) as first_error:
            repair_system = build_system_prompt(
                task=task,
                prompt_version=prompt_version,
                repair=True,
            )
            repair_user = build_repair_user_prompt(
                context=context,
                invalid_output=first.text,
                validation_error=str(first_error),
            )
            try:
                repaired = await provider.generate_json(
                    system=repair_system,
                    user=repair_user,
                    schema=schema,
                )
            except ProviderRequestError as error:
                metadata = await self._metadata(
                    task=task,
                    provider=provider,
                    prompt_version=prompt_version,
                    status="FAILED_PROVIDER",
                    repair_attempted=True,
                )
                raise ProviderGenerationError(str(error), metadata=metadata) from error

            try:
                output = self._parse(repaired.text, response_model)
            except (ValueError, ValidationError) as second_error:
                metadata = await self._metadata(
                    task=task,
                    provider=provider,
                    prompt_version=prompt_version,
                    status="FAILED_SCHEMA",
                    repair_attempted=True,
                )
                raise StructuredOutputError(
                    "provider output failed schema validation after one repair attempt",
                    metadata=metadata,
                ) from second_error

            metadata = await self._metadata(
                task=task,
                provider=provider,
                prompt_version=prompt_version,
                status="COMPLETE",
                repair_attempted=True,
            )
            return StructuredGeneration(output=output, metadata=metadata)

        metadata = await self._metadata(
            task=task,
            provider=provider,
            prompt_version=prompt_version,
            status="COMPLETE",
            repair_attempted=False,
        )
        return StructuredGeneration(output=output, metadata=metadata)

    @staticmethod
    def _parse(text: str, response_model: type[T]) -> T:
        data = json.loads(text)
        return response_model.model_validate(data)

    async def _metadata(
        self,
        *,
        task: str,
        provider: LLMProvider,
        prompt_version: str,
        status: str,
        repair_attempted: bool,
    ) -> GenerationMetadata:
        metadata = GenerationMetadata(
            task=task,
            provider=provider.name,
            model=provider.model,
            prompt_version=prompt_version,
            status=status,
            repair_attempted=repair_attempted,
            generated_at=datetime.now(UTC),
        )
        if self.recorder is not None:
            generation_id = await self.recorder.record(metadata)
            metadata = metadata.model_copy(update={"generation_id": generation_id})
        return metadata

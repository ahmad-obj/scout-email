from __future__ import annotations

from typing import Protocol

from scout_email.llm.schemas import ProviderResult


class ProviderRequestError(RuntimeError):
    """Raised when a provider request fails or returns no usable model output."""


class LLMProvider(Protocol):
    name: str
    model: str

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
    ) -> ProviderResult: ...

from __future__ import annotations

import httpx

from scout_email.llm.providers.base import ProviderRequestError
from scout_email.llm.schemas import ProviderResult


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        model: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 120.0,
    ) -> None:
        if not model:
            raise ValueError("model is required")
        self.model = model
        self._client = client
        self._owns_client = client is None
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        return self._client

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
    ) -> ProviderResult:
        try:
            response = await self._get_client().post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0},
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ProviderRequestError(f"Ollama request failed: {error}") from error

        try:
            payload = response.json()
            text = payload["message"]["content"]
            if not isinstance(text, str):
                raise TypeError("message content is not text")
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderRequestError("Ollama returned no usable text output") from error

        return ProviderResult(
            provider=self.name,
            model=str(payload.get("model") or self.model),
            text=text,
        )

from __future__ import annotations

import httpx

from scout_email.llm.providers.base import ProviderRequestError
from scout_email.llm.schemas import ProviderResult


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not model:
            raise ValueError("model is required")
        self.api_key = api_key
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
                "/v1beta/interactions",
                headers={"x-goog-api-key": self.api_key},
                json={
                    "model": self.model,
                    "system_instruction": system,
                    "input": user,
                    "response_format": [
                        {
                            "type": "text",
                            "mime_type": "application/json",
                            "schema": schema,
                        }
                    ],
                    "store": False,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ProviderRequestError(f"Gemini request failed: {error}") from error

        try:
            payload = response.json()
            text = next(
                item["text"]
                for step in payload.get("steps", [])
                if step.get("type") == "model_output"
                for item in step.get("content", [])
                if item.get("type") == "text" and isinstance(item.get("text"), str)
            )
        except (ValueError, KeyError, StopIteration, TypeError) as error:
            raise ProviderRequestError("Gemini returned no usable text output") from error

        return ProviderResult(
            provider=self.name,
            model=str(payload.get("model") or self.model),
            text=text,
            request_id=response.headers.get("x-request-id"),
        )

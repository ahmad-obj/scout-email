from __future__ import annotations

import asyncio
from typing import Literal

import httpx
from pydantic import TypeAdapter, ValidationError

from scout_email.browser.schemas import BrowserMapLead, BrowserRenderResponse


class BrowserWorkerError(RuntimeError):
    pass


class BrowserWorkerUnavailable(BrowserWorkerError):
    pass


class BrowserWorkerResponseError(BrowserWorkerError):
    pass


class BrowserWorkerClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 45.0, max_attempts: int = 3, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def search_maps(self, query: str, max_results: int) -> list[BrowserMapLead]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await self._get_client().post(f"{self.base_url}/maps/search", json={"query": query, "max_results": max_results})
                if response.status_code in {502, 503, 504}:
                    raise BrowserWorkerUnavailable(f"browser worker returned {response.status_code}")
                response.raise_for_status()
                try:
                    return TypeAdapter(list[BrowserMapLead]).validate_python(response.json())
                except (ValidationError, ValueError) as error:
                    raise BrowserWorkerResponseError("malformed browser worker response") from error
            except BrowserWorkerResponseError:
                raise
            except (httpx.TransportError, httpx.TimeoutException, BrowserWorkerUnavailable) as error:
                last_error = error
                if attempt >= self.max_attempts:
                    break
                await asyncio.sleep(0.15 * attempt)
            except httpx.HTTPStatusError as error:
                raise BrowserWorkerResponseError(f"browser worker rejected request with {error.response.status_code}") from error
        raise BrowserWorkerUnavailable("browser worker unavailable after bounded retries") from last_error

    async def render(
        self,
        url: str,
        *,
        viewport: Literal["desktop", "mobile"] = "desktop",
        screenshot_path: str | None = None,
    ) -> BrowserRenderResponse:
        last_error: Exception | None = None
        payload = {
            "url": url,
            "viewport": viewport,
            "screenshot_path": screenshot_path,
        }
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await self._get_client().post(
                    f"{self.base_url}/render",
                    json=payload,
                )
                if response.status_code in {502, 503, 504}:
                    raise BrowserWorkerUnavailable(
                        f"browser worker returned {response.status_code}"
                    )
                response.raise_for_status()
                try:
                    return BrowserRenderResponse.model_validate(response.json())
                except (ValidationError, ValueError) as error:
                    raise BrowserWorkerResponseError(
                        "malformed browser worker response"
                    ) from error
            except BrowserWorkerResponseError:
                raise
            except (
                httpx.TransportError,
                httpx.TimeoutException,
                BrowserWorkerUnavailable,
            ) as error:
                last_error = error
                if attempt >= self.max_attempts:
                    break
                await asyncio.sleep(0.15 * attempt)
            except httpx.HTTPStatusError as error:
                raise BrowserWorkerResponseError(
                    f"browser worker rejected request with {error.response.status_code}"
                ) from error
        raise BrowserWorkerUnavailable(
            "browser worker unavailable after bounded retries"
        ) from last_error

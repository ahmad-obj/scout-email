import json

import httpx
import pytest

from scout_email.browser.client import BrowserWorkerClient, BrowserWorkerResponseError


@pytest.mark.asyncio
async def test_render_posts_bounded_worker_contract_and_parses_response():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/render"
        payload = json.loads(request.content)
        assert payload == {
            "url": "https://example.com/",
            "viewport": "desktop",
            "screenshot_path": None,
        }
        return httpx.Response(
            200,
            json={
                "final_url": "https://example.com/",
                "title": "Acme",
                "html": "<html><main><h1>Acme</h1></main></html>",
                "screenshot_path": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        worker = BrowserWorkerClient("http://worker", client=client, max_attempts=2)
        rendered = await worker.render("https://example.com/")

    assert rendered.final_url == "https://example.com/"
    assert rendered.title == "Acme"
    assert "<h1>Acme</h1>" in rendered.html
    assert calls == 1


@pytest.mark.asyncio
async def test_render_malformed_success_response_is_not_retried():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"title": "missing required fields"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        worker = BrowserWorkerClient("http://worker", client=client, max_attempts=3)
        with pytest.raises(BrowserWorkerResponseError):
            await worker.render("https://example.com/")

    assert calls == 1

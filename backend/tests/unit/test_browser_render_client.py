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


@pytest.mark.asyncio
async def test_capture_homepage_screenshots_always_requests_desktop_then_mobile():
    payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        return httpx.Response(
            200,
            json={
                "final_url": payload["url"],
                "title": "Acme",
                "html": "<html></html>",
                "screenshot_path": f"/shared/{payload['screenshot_path']}",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        worker = BrowserWorkerClient("http://worker", client=client, max_attempts=1)
        results = await worker.capture_homepage_screenshots(
            "https://example.com/",
            desktop_path="campaigns/7/leads/31/screenshots/homepage-desktop.png",
            mobile_path="campaigns/7/leads/31/screenshots/homepage-mobile.png",
        )

    assert [item["viewport"] for item in payloads] == ["desktop", "mobile"]
    assert [item["screenshot_path"] for item in payloads] == [
        "campaigns/7/leads/31/screenshots/homepage-desktop.png",
        "campaigns/7/leads/31/screenshots/homepage-mobile.png",
    ]
    assert len(results) == 2

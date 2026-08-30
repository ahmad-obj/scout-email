import httpx
import pytest

from scout_email.browser.client import BrowserWorkerClient, BrowserWorkerResponseError


@pytest.mark.asyncio
async def test_semantic_malformed_response_is_not_retried():
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[{"category": "Dentist"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        worker = BrowserWorkerClient("http://worker", client=client, max_attempts=3)
        with pytest.raises(BrowserWorkerResponseError):
            await worker.search_maps("dentist Lahore", 3)
    assert calls == 1


@pytest.mark.asyncio
async def test_transient_503_is_retried_then_succeeds():
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, json={"detail": "busy"})
        return httpx.Response(200, json=[{"name": "ABC Dental"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        worker = BrowserWorkerClient("http://worker", client=client, max_attempts=3)
        result = await worker.search_maps("dentist Lahore", 3)
    assert result[0].name == "ABC Dental"
    assert calls == 3

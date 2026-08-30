import socket

import httpx
import pytest

from scout_email.common.enums import WebsiteState
from scout_email.enrichment.website import verify_website


def _public_dns(monkeypatch):
    def fake_getaddrinfo(host, port, *, type):
        assert type == socket.SOCK_STREAM
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.asyncio
async def test_live_website_verification_follows_public_redirect(monkeypatch):
    _public_dns(monkeypatch)

    def handler(request: httpx.Request):
        if request.url.path == "/":
            return httpx.Response(301, headers={"Location": "/home"})
        return httpx.Response(200, text="<html><title>Acme Dental</title><body>Book today</body></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verify_website("https://example.com/", client=client)

    assert result.state == WebsiteState.LIVE
    assert result.final_url == "https://example.com/home"
    assert result.http_status == 200
    assert result.canonical_domain == "example.com"


@pytest.mark.asyncio
async def test_private_redirect_is_blocked_before_second_request(monkeypatch):
    _public_dns(monkeypatch)
    requested = []

    def handler(request: httpx.Request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verify_website("https://example.com/", client=client)

    assert result.state == WebsiteState.UNCERTAIN
    assert result.error_code == "UNSAFE_REDIRECT"
    assert requested == ["https://example.com/"]


@pytest.mark.asyncio
async def test_parked_domain_is_not_classified_live(monkeypatch):
    _public_dns(monkeypatch)

    def handler(request: httpx.Request):
        return httpx.Response(200, text="<html><body>This domain is for sale. Buy this domain.</body></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verify_website("https://example.com/", client=client)

    assert result.state == WebsiteState.PARKED


@pytest.mark.asyncio
async def test_no_url_and_social_only_are_explicit_states():
    no_site = await verify_website(None)
    social = await verify_website("https://instagram.com/acme")
    assert no_site.state == WebsiteState.NO_WEBSITE
    assert social.state == WebsiteState.SOCIAL_ONLY


@pytest.mark.asyncio
async def test_network_failure_stays_uncertain_not_no_website(monkeypatch):
    _public_dns(monkeypatch)

    def handler(request: httpx.Request):
        raise httpx.ConnectError("connection failed", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verify_website("https://example.com/", client=client)

    assert result.state == WebsiteState.UNCERTAIN
    assert result.error_code == "NETWORK_ERROR"

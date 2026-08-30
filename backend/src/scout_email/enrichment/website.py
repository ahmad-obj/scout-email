from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel

from scout_email.common.enums import WebsiteState
from scout_email.common.url_policy import UnsafeURLError, validate_public_http_url
from scout_email.leads.normalize import canonical_domain


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SOCIAL_ONLY_DOMAINS = {
    "instagram.com",
    "facebook.com",
    "fb.com",
    "linkedin.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
}
_PARKED_MARKERS = (
    "this domain is for sale",
    "buy this domain",
    "domain parking",
    "parked free",
    "sedo domain parking",
    "afternic",
)


class WebsiteVerification(BaseModel):
    state: WebsiteState
    requested_url: str | None = None
    final_url: str | None = None
    canonical_domain: str | None = None
    http_status: int | None = None
    redirect_chain: list[str] = []
    error_code: str | None = None


def _is_social_only_url(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    if host.startswith("www."):
        host = host[4:]
    return host in _SOCIAL_ONLY_DOMAINS


def _looks_parked(body: str) -> bool:
    lowered = body.casefold()
    return any(marker in lowered for marker in _PARKED_MARKERS)


async def verify_website(
    url: str | None,
    *,
    client: httpx.AsyncClient | None = None,
    max_redirects: int = 5,
) -> WebsiteVerification:
    if url is None or not url.strip():
        return WebsiteVerification(state=WebsiteState.NO_WEBSITE)

    requested = url.strip()
    if _is_social_only_url(requested):
        return WebsiteVerification(
            state=WebsiteState.SOCIAL_ONLY,
            requested_url=requested,
            final_url=requested,
            canonical_domain=canonical_domain(requested),
        )

    try:
        validate_public_http_url(requested)
    except UnsafeURLError:
        return WebsiteVerification(
            state=WebsiteState.UNCERTAIN,
            requested_url=requested,
            canonical_domain=canonical_domain(requested),
            error_code="UNSAFE_URL",
        )

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            headers={"User-Agent": "ScoutEmail/0.1 (+public business website verification)"},
        )

    current = requested
    redirect_chain: list[str] = []
    try:
        for redirect_index in range(max_redirects + 1):
            try:
                validate_public_http_url(current)
            except UnsafeURLError:
                return WebsiteVerification(
                    state=WebsiteState.UNCERTAIN,
                    requested_url=requested,
                    final_url=current,
                    canonical_domain=canonical_domain(current),
                    redirect_chain=redirect_chain,
                    error_code="UNSAFE_REDIRECT" if redirect_chain else "UNSAFE_URL",
                )

            try:
                response = await client.get(current, follow_redirects=False)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                return WebsiteVerification(
                    state=WebsiteState.UNCERTAIN,
                    requested_url=requested,
                    final_url=current,
                    canonical_domain=canonical_domain(current),
                    redirect_chain=redirect_chain,
                    error_code="NETWORK_ERROR",
                )

            status = response.status_code
            if status in _REDIRECT_STATUSES and response.headers.get("Location"):
                if redirect_index >= max_redirects:
                    return WebsiteVerification(
                        state=WebsiteState.UNCERTAIN,
                        requested_url=requested,
                        final_url=current,
                        canonical_domain=canonical_domain(current),
                        http_status=status,
                        redirect_chain=redirect_chain,
                        error_code="REDIRECT_LIMIT",
                    )
                target = urljoin(current, response.headers["Location"])
                try:
                    validate_public_http_url(target)
                except UnsafeURLError:
                    return WebsiteVerification(
                        state=WebsiteState.UNCERTAIN,
                        requested_url=requested,
                        final_url=current,
                        canonical_domain=canonical_domain(current),
                        http_status=status,
                        redirect_chain=redirect_chain,
                        error_code="UNSAFE_REDIRECT",
                    )
                redirect_chain.append(target)
                current = target
                continue

            result_kwargs = dict(
                requested_url=requested,
                final_url=str(response.url),
                canonical_domain=canonical_domain(str(response.url)),
                http_status=status,
                redirect_chain=redirect_chain,
            )
            if status in {401, 403, 408, 425, 429} or status >= 500:
                return WebsiteVerification(
                    state=WebsiteState.UNCERTAIN,
                    error_code="HTTP_UNCERTAIN",
                    **result_kwargs,
                )
            if status >= 400:
                return WebsiteVerification(
                    state=WebsiteState.BROKEN,
                    error_code="HTTP_ERROR",
                    **result_kwargs,
                )
            if _looks_parked(response.text):
                return WebsiteVerification(state=WebsiteState.PARKED, **result_kwargs)
            return WebsiteVerification(state=WebsiteState.LIVE, **result_kwargs)

        return WebsiteVerification(
            state=WebsiteState.UNCERTAIN,
            requested_url=requested,
            final_url=current,
            canonical_domain=canonical_domain(current),
            redirect_chain=redirect_chain,
            error_code="REDIRECT_LIMIT",
        )
    finally:
        if owns_client:
            await client.aclose()

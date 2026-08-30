from __future__ import annotations

import asyncio
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Page, Route

from browser_worker.runtime import BrowserRuntime
from browser_worker.schemas import RenderRequest, RenderResponse
from browser_worker.settings import BrowserWorkerSettings


class UnsafeTargetError(ValueError):
    """Raised when a browser navigation could reach a non-public network target."""


class BrowserNavigationError(RuntimeError):
    """Raised when a public page cannot be rendered safely."""


def validate_public_url(url: str, *, resolve_dns: bool = True) -> None:
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeTargetError("Only http and https URLs are allowed")
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeTargetError("URL must include a hostname")
    lowered = hostname.casefold().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".localhost"):
        raise UnsafeTargetError("Localhost targets are blocked")

    try:
        literal_ip = ipaddress.ip_address(lowered)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not literal_ip.is_global:
            raise UnsafeTargetError(
                f"Non-public network address is blocked: {lowered}"
            )
        return

    if not resolve_dns:
        return

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as error:
        raise UnsafeTargetError(f"Hostname could not be resolved: {hostname}") from error
    if not addresses:
        raise UnsafeTargetError(f"Hostname resolved to no addresses: {hostname}")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise UnsafeTargetError(
                f"Hostname resolves to a non-public network address: {address}"
            )


def resolve_screenshot_path(root: Path, requested: str) -> Path:
    relative = Path(requested)
    if relative.is_absolute():
        raise ValueError("screenshot_path must be relative to the artifact directory")
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("screenshot_path cannot escape the artifact directory") from error
    if candidate.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("screenshot_path must end in .png, .jpg, or .jpeg")
    return candidate


def viewport_dimensions(viewport: str) -> dict[str, int]:
    if viewport == "mobile":
        return {"width": 390, "height": 844}
    if viewport == "desktop":
        return {"width": 1440, "height": 900}
    raise ValueError("viewport must be desktop or mobile")


async def install_network_guard(page: Page) -> None:
    cache: dict[str, bool] = {}

    async def guard(route: Route) -> None:
        url = route.request.url
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            await route.continue_()
            return
        host = parsed.hostname or ""
        cache_key = f"{parsed.scheme}:{host}:{parsed.port or ''}"
        if cache_key not in cache:
            try:
                await asyncio.to_thread(validate_public_url, url, resolve_dns=True)
                cache[cache_key] = True
            except UnsafeTargetError:
                cache[cache_key] = False
        if cache[cache_key]:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    await page.route("**/*", guard)


async def render_page(
    runtime: BrowserRuntime,
    request: RenderRequest,
    settings: BrowserWorkerSettings,
) -> RenderResponse:
    url = str(request.url)
    await asyncio.to_thread(validate_public_url, url, resolve_dns=True)
    viewport = viewport_dimensions(request.viewport)

    async with runtime.page(viewport=viewport) as page:
        await install_network_guard(page)
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception as error:
            raise BrowserNavigationError(f"Navigation failed for {url}: {error}") from error

        final_url = page.url
        await asyncio.to_thread(validate_public_url, final_url, resolve_dns=True)
        title = (await page.title()).strip() or None
        html = await page.content()

        screenshot_path = None
        if request.screenshot_path:
            destination = resolve_screenshot_path(
                settings.artifact_dir,
                request.screenshot_path,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(destination), full_page=True)
            screenshot_path = str(destination)

        return RenderResponse(
            final_url=final_url,
            title=title,
            html=html,
            screenshot_path=screenshot_path,
        )

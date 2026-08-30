import os

import pytest

from browser_worker.maps import MapsSearchError, search_maps
from browser_worker.runtime import BrowserRuntime
from browser_worker.settings import BrowserWorkerSettings

pytestmark = [
    pytest.mark.live_maps,
    pytest.mark.skipif(
        os.getenv("MAPS_LIVE_SMOKE_ENABLED", "").casefold() not in {"1", "true", "yes"},
        reason="live Google Maps smoke test is opt-in",
    ),
]


@pytest.mark.asyncio
async def test_live_maps_smoke_returns_at_most_three_normalized_leads(tmp_path):
    settings = BrowserWorkerSettings(
        artifact_dir=tmp_path,
        executable_path=os.getenv("BROWSER_WORKER_EXECUTABLE_PATH") or None,
        headless=True,
        max_concurrency=1,
    )
    runtime = BrowserRuntime(settings)
    await runtime.start()
    try:
        try:
            leads = await search_maps(runtime, "dentist Lahore", max_results=3)
        except MapsSearchError:
            async with runtime.page(viewport={"width": 1440, "height": 1000}) as page:
                await page.goto("https://www.google.com/maps", wait_until="domcontentloaded")
                print("MAPS_DIAGNOSTIC_URL=", page.url)
                print("MAPS_DIAGNOSTIC_TITLE=", await page.title())
                inputs = await page.locator("input").evaluate_all(
                    """els => els.map(e => {
                        const r = e.getBoundingClientRect();
                        const s = getComputedStyle(e);
                        return {
                            id: e.id,
                            aria: e.getAttribute('aria-label'),
                            placeholder: e.getAttribute('placeholder'),
                            type: e.type,
                            disabled: e.disabled,
                            readOnly: e.readOnly,
                            display: s.display,
                            visibility: s.visibility,
                            opacity: s.opacity,
                            rect: {x:r.x, y:r.y, width:r.width, height:r.height},
                            outer: e.outerHTML.slice(0, 400),
                        };
                    })"""
                )
                print("MAPS_DIAGNOSTIC_INPUTS=", inputs)
                buttons = await page.locator("button").evaluate_all(
                    "els => els.slice(0, 30).map(e => ({aria:e.getAttribute('aria-label'), title:e.getAttribute('title'), text:(e.innerText || '').trim().slice(0,80)}))"
                )
                print("MAPS_DIAGNOSTIC_BUTTONS=", buttons)
                text = (await page.locator("body").inner_text())[:800]
                print("MAPS_DIAGNOSTIC_TEXT=", text.replace("\n", " | "))
            raise
    finally:
        await runtime.stop()
    assert 1 <= len(leads) <= 3
    assert all(lead.name.strip() for lead in leads)
    assert all(lead.maps_url for lead in leads)

import os

import pytest

from browser_worker.maps import search_maps
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
        leads = await search_maps(runtime, "dentist Lahore", max_results=3)
    finally:
        await runtime.stop()
    assert 1 <= len(leads) <= 3
    assert all(lead.name.strip() for lead in leads)
    assert all(lead.maps_url for lead in leads)

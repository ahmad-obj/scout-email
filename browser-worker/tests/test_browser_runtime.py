import shutil

import pytest

from browser_worker.runtime import BrowserRuntime
from browser_worker.settings import BrowserWorkerSettings


@pytest.mark.asyncio
async def test_runtime_uses_isolated_browser_context(tmp_path):
    executable = shutil.which("chromium") or shutil.which("google-chrome")
    if executable is None:
        pytest.skip("No system Chromium; CI may use Playwright's installed Chromium")
    settings = BrowserWorkerSettings(
        artifact_dir=tmp_path,
        executable_path=executable,
        headless=True,
        max_concurrency=1,
    )
    runtime = BrowserRuntime(settings)
    await runtime.start()
    try:
        async with runtime.page() as page:
            await page.set_content("<h1>worker-ok</h1>")
            assert await page.text_content("h1") == "worker-ok"
    finally:
        await runtime.stop()

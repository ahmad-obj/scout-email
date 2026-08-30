from __future__ import annotations

import asyncio
import os
import shutil
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from browser_worker.settings import BrowserWorkerSettings


class BrowserUnavailableError(RuntimeError):
    """Raised when Chromium cannot be started or is no longer available."""


class BrowserRuntime:
    def __init__(self, settings: BrowserWorkerSettings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)

    @property
    def browser(self) -> Browser:
        if self._browser is None or not self._browser.is_connected():
            raise BrowserUnavailableError("Chromium is not running")
        return self._browser

    async def start(self) -> None:
        if self._browser is not None and self._browser.is_connected():
            return
        self.settings.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()

        executable = self.settings.executable_path
        if executable is None:
            executable = shutil.which("chromium") or shutil.which("google-chrome")

        launch_kwargs: dict = {"headless": self.settings.headless}
        if executable:
            launch_kwargs["executable_path"] = executable
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            launch_kwargs["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]

        try:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        except Exception as error:
            await self.stop()
            raise BrowserUnavailableError(f"Unable to start Chromium: {error}") from error

    async def stop(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            finally:
                self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    @asynccontextmanager
    async def page(
        self,
        *,
        viewport: dict[str, int] | None = None,
        locale: str = "en-US",
    ) -> AsyncIterator[Page]:
        await self._semaphore.acquire()
        context: BrowserContext | None = None
        try:
            context = await self.browser.new_context(
                viewport=viewport or {"width": 1440, "height": 1000},
                locale=locale,
            )
            page = await context.new_page()
            page.set_default_timeout(self.settings.navigation_timeout_ms)
            page.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
            yield page
        finally:
            if context is not None:
                await context.close()
            self._semaphore.release()

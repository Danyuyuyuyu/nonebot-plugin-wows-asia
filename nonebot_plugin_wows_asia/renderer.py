"""Headless Chromium (Playwright) renderer: HTML card -> PNG bytes."""
import asyncio
from typing import Any


class RenderError(Exception):
    pass


class CardRenderer:
    def __init__(self, browser_path: str = "", scale: float = 1.5, timeout_ms: int = 20000):
        self.browser_path = browser_path.strip()
        self.scale = scale
        self.timeout_ms = timeout_ms
        self._pw: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()

    async def _ensure(self):
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise RenderError("未安装 playwright") from exc
        if self._pw is None:
            self._pw = await async_playwright().start()
        kwargs = {"executable_path": self.browser_path} if self.browser_path else {}
        try:
            self._browser = await self._pw.chromium.launch(headless=True, **kwargs)
        except Exception as exc:
            raise RenderError("无法启动 Chromium：请执行 `playwright install chromium`，或配置 WOWS_BROWSER_PATH") from exc
        return self._browser

    async def render(self, html: str) -> bytes:
        async with self._lock:
            browser = await self._ensure()
            page = await browser.new_page(viewport={"width": 960, "height": 100}, device_scale_factor=self.scale)
            try:
                # Cards are self-contained: block every network request.
                await page.route("**/*", lambda route: route.abort())
                await page.set_content(html, wait_until="load", timeout=self.timeout_ms)
                await page.evaluate("document.fonts.ready.then(() => true)")
                return await page.screenshot(full_page=True, type="png", timeout=self.timeout_ms)
            finally:
                await page.close()

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

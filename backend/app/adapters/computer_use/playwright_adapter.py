import hashlib
import tempfile
from pathlib import Path

from app.adapters.computer_use.base import PageObservation


class PlaywrightComputerUseAdapter:
    """Phase 4A read-only adapter boundary.

    The production implementation belongs in the dedicated Computer Use Worker
    image. The API process intentionally avoids importing Playwright so browser
    dependencies do not leak into the main service.
    """

    async def open_read_only(self, *, session_id: str, url: str) -> PageObservation:
        observed = await self._try_playwright_observe(session_id=session_id, url=url)
        if observed is not None:
            return observed
        return PageObservation(
            url=url,
            title="待连接的隔离浏览器会话",
            summary="已创建受控浏览器会话记录。真实页面打开由 Computer Use Worker 接管。",
            interactive_elements=[],
            screenshot_id=None,
        )

    async def capture_state(self, *, session_id: str, url: str, title: str | None = None) -> PageObservation:
        observed = await self._try_playwright_observe(session_id=session_id, url=url)
        if observed is not None:
            return observed
        return PageObservation(
            url=url,
            title=title or "页面观察",
            summary="已记录只读页面观察。当前 API 服务不采集高分辨率截图或完整 DOM。",
            interactive_elements=[],
            screenshot_id=None,
        )

    async def close(self, *, session_id: str) -> None:
        return None

    async def _try_playwright_observe(self, *, session_id: str, url: str) -> PageObservation | None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None

        screenshot_dir = Path(tempfile.gettempdir()) / "mira-computer-use-screenshots"
        screenshot_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        screenshot_id = hashlib.sha256(f"{session_id}:{url}".encode("utf-8")).hexdigest()[:24]
        screenshot_path = screenshot_dir / f"{screenshot_id}.png"
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(ignore_https_errors=False)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            title = await page.title()
            visible_text = (await page.locator("body").inner_text(timeout=3_000))[:1200]
            elements = await page.locator("a,button,input,select,textarea").evaluate_all(
                """nodes => nodes.slice(0, 30).map((node, index) => ({
                  index,
                  tag: node.tagName.toLowerCase(),
                  text: (node.innerText || node.value || node.getAttribute('aria-label') || node.getAttribute('placeholder') || '').slice(0, 80),
                  role: node.getAttribute('role'),
                  testid: node.getAttribute('data-testid')
                }))"""
            )
            await page.screenshot(path=str(screenshot_path), full_page=False)
            final_url = page.url
            await context.close()
            await browser.close()
        return PageObservation(
            url=final_url,
            title=title,
            summary=visible_text or "页面没有可见正文。",
            interactive_elements=elements,
            screenshot_id=screenshot_id,
        )

"""Reads the GSA ambassador web app with a real browser profile.

`login()` opens a visible window once so you can sign in with Google. The session is stored
in data/browser-profile, so later reads run headless. If Google refuses to sign in inside
an automated browser, set dashboard.cdp_url and start your normal Chrome/Edge with
--remote-debugging-port=9222; Malice then reads tabs from your real, logged-in browser.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import DashboardCfg

log = logging.getLogger("malice.dashboard")

EXTRACT_JS = r"""
() => {
  const main = document.querySelector('main') || document.body;
  const links = [...document.querySelectorAll('a[href]')]
     .map(a => [a.innerText.trim().replace(/\s+/g,' '), a.href])
     .filter(([t, h]) => t && t.length < 120 && !h.startsWith('javascript'))
     .slice(0, 80);
  return { title: document.title, url: location.href, text: main.innerText, links };
}
"""


@dataclass
class PageDump:
    url: str
    title: str
    text: str
    links: list[tuple[str, str]]

    def for_llm(self, max_chars: int = 9000) -> str:
        links = "\n".join(f"- {t}: {h}" for t, h in self.links[:60])
        return f"PAGE: {self.title} ({self.url})\n\n{self.text[:max_chars]}\n\nLINKS:\n{links}"


class DashboardError(RuntimeError):
    pass


class DashboardBrowser:
    def __init__(self, cfg: DashboardCfg):
        self.cfg = cfg

    @property
    def configured(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.url)

    async def _context(self, pw, headless: bool):
        if self.cfg.cdp_url:
            browser = await pw.chromium.connect_over_cdp(self.cfg.cdp_url)
            return browser, browser.contexts[0] if browser.contexts else await browser.new_context()
        Path(self.cfg.profile_dir).mkdir(parents=True, exist_ok=True)
        kwargs = dict(user_data_dir=self.cfg.profile_dir, headless=headless,
                      viewport={"width": 1366, "height": 900},
                      args=["--disable-blink-features=AutomationControlled"])
        channel = self.cfg.browser_channel if self.cfg.browser_channel != "chromium" else None
        try:
            ctx = await pw.chromium.launch_persistent_context(channel=channel, **kwargs)
        except Exception as e:  # noqa: BLE001  - channel browser not installed
            log.warning("Could not launch %s (%s); using bundled Chromium", channel, e)
            ctx = await pw.chromium.launch_persistent_context(**kwargs)
        return None, ctx

    async def login(self) -> None:
        """Open a visible browser on the dashboard and wait until the user closes it."""
        if not self.cfg.url:
            raise DashboardError("Set dashboard.url in config.yaml first.")
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            _, ctx = await self._context(pw, headless=False)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(self.cfg.url)
            print("Sign in to the ambassador dashboard in the window, then close it.")
            await ctx.wait_for_event("close", timeout=0)

    async def read(self) -> list[PageDump]:
        if not self.configured:
            raise DashboardError("Dashboard URL isn't set. Add dashboard.url to config.yaml, then run "
                                 "`python -m malice login-dashboard` once to sign in.")
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise DashboardError("Playwright isn't installed: pip install playwright") from e
        dumps: list[PageDump] = []
        async with async_playwright() as pw:
            browser, ctx = await self._context(pw, headless=True)
            try:
                page = await ctx.new_page()
                for url in [self.cfg.url, *self.cfg.extra_urls]:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=self.cfg.wait_ms + 8000)
                    except Exception:  # noqa: BLE001 - SPAs that never idle
                        pass
                    await page.wait_for_timeout(self.cfg.wait_ms)
                    if "accounts.google.com" in page.url:
                        raise DashboardError("The dashboard wants a fresh Google sign-in. Run "
                                             "`python -m malice login-dashboard`.")
                    d = await page.evaluate(EXTRACT_JS)
                    dumps.append(PageDump(d["url"], d["title"], d["text"], [tuple(x) for x in d["links"]]))
                await page.close()
            finally:
                if browser is None:
                    await ctx.close()
        return dumps

"""Browser automatizzato (Playwright) con un profilo persistente.

Il login a Facebook lo fai tu a mano, una volta, nella finestra che si apre:
il profilo viene salvato in data/browser-profile e riusato ai riavvii.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from .extractor import EXPAND_JS, EXTRACT_JS, SEE_MORE_LABELS, feed_url

log = logging.getLogger(__name__)

LOGIN_URL = "https://www.facebook.com/login"


@dataclass
class ScrapeResult:
    status: str  # ok | checkpoint | logged_out | no_feed
    items: list[dict] = field(default_factory=list)
    title: str = ""
    url: str = ""


class FacebookBrowser:
    def __init__(self, profile_dir: str | Path):
        self.profile_dir = Path(profile_dir)
        self._pw: Optional[Playwright] = None
        self._ctx: Optional[BrowserContext] = None
        self._opts: tuple = ()
        self.lock = asyncio.Lock()  # una sola operazione alla volta sulla pagina

    @property
    def started(self) -> bool:
        return self._ctx is not None

    async def start(self, headless: bool = False, channel: str = "chrome") -> None:
        # Sotto lock: non riavviare il browser mentre sta leggendo un gruppo.
        async with self.lock:
            await self._start(headless, channel)

    async def _start(self, headless: bool, channel: str) -> None:
        opts = (headless, channel)
        if self._ctx is not None and opts == self._opts:
            return
        await self.close()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        kwargs = dict(
            user_data_dir=str(self.profile_dir),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            locale="it-IT",
            args=["--disable-blink-features=AutomationControlled"],
        )
        executable = os.environ.get("FBM_BROWSER_PATH")
        if executable:
            kwargs["executable_path"] = executable
        elif channel:
            kwargs["channel"] = channel
        try:
            self._ctx = await self._pw.chromium.launch_persistent_context(**kwargs)
        except Exception:
            if not channel or executable:
                raise
            # Chrome non installato: ripiega sul Chromium di Playwright.
            log.warning("Chrome non trovato, uso Chromium di Playwright")
            kwargs.pop("channel", None)
            self._ctx = await self._pw.chromium.launch_persistent_context(**kwargs)
        self._opts = opts

    async def close(self) -> None:
        if self._ctx is not None:
            try:
                await self._ctx.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._ctx = None
        self._pw = None

    async def _page(self) -> Page:
        assert self._ctx is not None, "browser non avviato"
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        return pages[0] if pages else await self._ctx.new_page()

    async def is_logged_in(self) -> bool:
        if self._ctx is None:
            return False
        cookies = await self._ctx.cookies("https://www.facebook.com")
        return any(c["name"] == "c_user" and c["value"] for c in cookies)

    async def open_login(self) -> None:
        """Apre la pagina di login nella finestra del browser (visibile)."""
        async with self.lock:
            page = await self._page()
            await page.bring_to_front()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")

    async def scrape_group(self, group_url: str, scrolls: int = 3) -> ScrapeResult:
        async with self.lock:
            page = await self._page()
            await page.goto(feed_url(group_url), wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(random.randint(2500, 4500))

            status = self._blocked_status(page.url)
            if status:
                return ScrapeResult(status, url=page.url)
            if not await self.is_logged_in():
                return ScrapeResult("logged_out", url=page.url)

            try:
                await page.wait_for_selector('[role="feed"]', timeout=15_000)
            except Exception:
                return ScrapeResult("no_feed", title=await page.title(), url=page.url)

            for _ in range(max(0, scrolls)):
                await page.mouse.wheel(0, random.randint(900, 1600))
                await page.wait_for_timeout(random.randint(1500, 3200))

            await page.evaluate(EXPAND_JS, SEE_MORE_LABELS)
            await page.wait_for_timeout(random.randint(600, 1200))
            items = await page.evaluate(EXTRACT_JS)
            return ScrapeResult("ok", items=items, title=await page.title(), url=page.url)

    @staticmethod
    def _blocked_status(url: str) -> Optional[str]:
        if "/checkpoint" in url:
            return "checkpoint"
        if "/login" in url or "login.php" in url:
            return "logged_out"
        return None


def group_name_from_title(title: str) -> str:
    """'(3) Compro Vendo Milano | Facebook' -> 'Compro Vendo Milano'"""
    title = re.sub(r"^\(\d+\+?\)\s*", "", title or "")
    title = re.sub(r"\s*[|\-]\s*Facebook\s*$", "", title)
    return title.strip()

"""Ciclo di controllo: apre i gruppi a rotazione, filtra i post, invia le notifiche."""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from .browser import FacebookBrowser, group_name_from_title
from .db import Database, now_iso
from .extractor import build_posts
from .filters import match_rule
from .notifiers import format_message, notify_all

log = logging.getLogger(__name__)

Notifier = Callable[[dict[str, Any], str], Awaitable[dict[str, Optional[str]]]]

BLOCK_MESSAGES = {
    "checkpoint": "Facebook ha chiesto una verifica di sicurezza. Controlli sospesi: "
                  "apri il browser, completa la verifica e riattiva il monitor.",
    "logged_out": "Sessione Facebook scaduta. Controlli sospesi: rifai il login e riattiva il monitor.",
}

SEED_NOTE = "prima lettura del gruppo: non notificato"


def within_active_hours(now: datetime, start: int, end: int) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end  # fascia a cavallo della mezzanotte


class Monitor:
    def __init__(self, db: Database, browser: FacebookBrowser, notifier: Notifier = notify_all):
        self.db = db
        self.browser = browser
        self.notifier = notifier
        self._task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self.pause_between_groups = asyncio.sleep  # sostituibile nei test
        self.state: dict[str, Any] = {
            "phase": "fermo",
            "current_group": None,
            "last_cycle_at": None,
            "next_cycle_at": None,
            "last_error": None,
            "blocked_reason": None,
        }

    # ---------- avvio / arresto ----------
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def wake(self) -> None:
        """Esegue subito un ciclo (usato da 'Controlla ora' e dopo la ripresa)."""
        self._wake.set()

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    async def _run_forever(self) -> None:
        while True:
            try:
                wait = await self.run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("Errore nel ciclo")
                self.state["last_error"] = str(exc)[:300]
                wait = 120
            self.state["next_cycle_at"] = (datetime.now() + timedelta(seconds=wait)).isoformat(timespec="seconds")
            await self._sleep(wait)

    # ---------- un ciclo ----------
    async def run_cycle(self) -> float:
        """Controlla il prossimo blocco di gruppi. Restituisce i secondi da attendere."""
        s = self.db.get_settings()
        if s["paused"]:
            self.state["phase"] = "in pausa"
            return 30
        now = datetime.now()
        if not within_active_hours(now, s["active_hour_start"], s["active_hour_end"]):
            self.state["phase"] = "fuori orario"
            return 300
        today = now.date().isoformat()
        if self.db.pages_today(today) >= s["daily_page_limit"]:
            self.state["phase"] = "limite giornaliero raggiunto"
            return 600

        groups = self.db.next_groups(s["groups_per_cycle"])
        if not groups:
            self.state["phase"] = "nessun gruppo attivo"
            return 60

        await self.browser.start(headless=s["headless"], channel=s["browser_channel"])
        self.state["phase"] = "controllo in corso"
        for i, group in enumerate(groups):
            if self.db.pages_today(today) >= s["daily_page_limit"]:
                break
            stop = await self.check_group(group, s)
            self.db.increment_pages(today)
            if stop:
                self.state["current_group"] = None
                return 30
            if i < len(groups) - 1:
                await self.pause_between_groups(random.uniform(s["delay_between_groups_min"],
                                                   max(s["delay_between_groups_min"],
                                                       s["delay_between_groups_max"])))
        self.state.update(current_group=None, last_cycle_at=now_iso(), phase="in attesa")
        return s["interval_minutes"] * 60 * random.uniform(0.8, 1.3)

    async def check_group(self, group: dict, settings: dict) -> bool:
        """Controlla un gruppo. Restituisce True se bisogna fermarsi (blocco/logout)."""
        self.state["current_group"] = group["name"] or group["url"]
        first_time = not self.db.group_has_posts(group["id"])
        scrolls = settings["scrolls_per_group"]
        if first_time:
            # Alla prima lettura scorre di più: i post vecchi più in basso vengono
            # memorizzati subito e non sembreranno nuovi ai controlli successivi.
            scrolls = min(scrolls * 2 + 1, 15)
        try:
            result = await self.browser.scrape_group(group["url"], scrolls)
        except Exception as exc:
            log.warning("Errore sul gruppo %s: %s", group["url"], exc)
            self.db.update_group(group["id"], last_checked_at=now_iso(), last_error=str(exc)[:300])
            return False

        if result.status in BLOCK_MESSAGES:
            await self._block(result.status, settings)
            return True
        if result.status == "no_feed":
            self.db.update_group(group["id"], last_checked_at=now_iso(),
                                 last_error="Feed non trovato: sei iscritto al gruppo?")
            return False

        if not group["name"]:
            name = group_name_from_title(result.title)
            if name:
                self.db.update_group(group["id"], name=name)
                group["name"] = name

        await self.process_posts(group, result.items, settings, first_time)
        self.db.update_group(group["id"], last_checked_at=now_iso(), last_error=None)
        self.state["last_error"] = None
        return False

    async def process_posts(self, group: dict, raw_items: list[dict], settings: dict,
                            first_time: bool) -> int:
        """Salva i post nuovi e notifica quelli che soddisfano le regole. Restituisce le notifiche inviate."""
        rules = self.db.active_rules()
        sent = 0
        for post in build_posts(raw_items, group["url"]):
            if self.db.post_exists(post["id"]):
                continue
            self.db.add_post(post, group["id"])
            matched = [r for r in rules
                       if match_rule(r, post["text"], group["id"], post["price"]).matched]
            if not matched:
                continue
            for rule in matched:
                self.db.add_match(post["id"], rule.id)
            if first_time:
                # Alla prima lettura i post sono vecchi: li salva senza inviare notifiche.
                for rule in matched:
                    self.db.set_match_notified(post["id"], rule.id, SEED_NOTE)
                continue
            message = format_message(post, ", ".join(r.name for r in matched), group["name"])
            results = await self.notifier(settings, message)
            errors = "; ".join(f"{c}: {e}" for c, e in results.items() if e)
            if not results:
                errors = "nessun canale di notifica configurato"
            for rule in matched:
                self.db.set_match_notified(post["id"], rule.id, errors or None)
            sent += 1
        return sent

    async def _block(self, reason: str, settings: dict) -> None:
        self.db.update_settings({"paused": True})
        self.state.update(phase="in pausa", blocked_reason=reason, last_error=BLOCK_MESSAGES[reason])
        try:
            await self.notifier(settings, "⚠️ " + BLOCK_MESSAGES[reason])
        except Exception:
            log.exception("Impossibile inviare l'avviso di blocco")

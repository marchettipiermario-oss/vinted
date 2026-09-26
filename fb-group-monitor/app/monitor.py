"""Ciclo di controllo.

Due modalità che lavorano insieme sullo stesso browser:
- notifiche (veloce): ricarica facebook.com/notifications ogni ~40 secondi e apre
  solo i post nuovi segnalati da Facebook;
- rotazione (rete di sicurezza): apre i gruppi della lista uno alla volta.

Lo scheduler esegue un passo alla volta, così il controllo delle notifiche non
aspetta mai la fine di un giro di gruppi.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from .browser import FacebookBrowser, group_name_from_title
from .db import Database, now_iso
from .extractor import build_posts, normalize_group_url, numeric_group_id, parse_notifications
from .filters import Rule, match_rule
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
    def __init__(self, db: Database, browser: FacebookBrowser, notifier: Notifier = notify_all,
                 clock: Callable[[], float] = time.monotonic):
        self.db = db
        self.browser = browser
        self.notifier = notifier
        self.clock = clock
        self._task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self._next_notif = 0.0
        self._next_rot = 0.0
        self._rot_done = 0                      # gruppi letti nel giro in corso
        self._group_events_seen: set[str] = set()  # notifiche "raggruppate" già gestite
        self.state: dict[str, Any] = {
            "phase": "fermo",
            "current_group": None,
            "last_cycle_at": None,
            "last_notif_at": None,
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

    def reset_schedule(self) -> None:
        self._next_notif = self._next_rot = 0.0
        self._rot_done = 0

    def wake(self) -> None:
        """Esegue subito un passo (usato da 'Controlla ora' e dopo la ripresa)."""
        self.reset_schedule()
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
                wait = await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("Errore nel ciclo")
                self.state["last_error"] = str(exc)[:300]
                wait = 60
            self.state["next_cycle_at"] = (datetime.now() + timedelta(seconds=wait)).isoformat(timespec="seconds")
            await self._sleep(wait)

    # ---------- scheduler ----------
    def _under_limit(self, s: dict) -> bool:
        return self.db.pages_today(datetime.now().date().isoformat()) < s["daily_page_limit"]

    def _count_page(self) -> None:
        self.db.increment_pages(datetime.now().date().isoformat())

    async def tick(self) -> float:
        """Esegue ciò che è in scadenza. Restituisce i secondi da attendere."""
        s = self.db.get_settings()
        if s["paused"]:
            self.state["phase"] = "in pausa"
            return 30
        if not within_active_hours(datetime.now(), s["active_hour_start"], s["active_hour_end"]):
            self.state["phase"] = "fuori orario"
            return 300
        if not s["notif_enabled"] and not s["rotation_enabled"]:
            self.state["phase"] = "nessuna modalità attiva"
            return 60

        await self.browser.start(headless=s["headless"], channel=s["browser_channel"])

        if s["notif_enabled"] and self.clock() >= self._next_notif:
            self.state["phase"] = "lettura notifiche"
            if await self.poll_notifications(s):
                return 30
            self._next_notif = self.clock() + s["notif_interval_seconds"] * random.uniform(0.8, 1.25)

        phase = "in attesa"
        if s["rotation_enabled"] and self.clock() >= self._next_rot:
            result = await self.rotation_step(s)
            if result == "stop":
                return 30
            if result == "limit":
                phase = "limite giornaliero raggiunto"

        dues = []
        if s["notif_enabled"]:
            dues.append(self._next_notif)
        if s["rotation_enabled"]:
            dues.append(self._next_rot)
        self.state.update(phase=phase, current_group=None)
        return max(1.0, min(dues) - self.clock())

    async def rotation_step(self, s: dict) -> str:
        """Legge il prossimo gruppo della rotazione. Restituisce 'ok', 'stop', 'limit' o 'idle'."""
        enabled = [g for g in self.db.list_groups() if g["enabled"]]
        if not enabled:
            self._next_rot = self.clock() + 60
            return "idle"
        if not self._under_limit(s):
            self._next_rot = self.clock() + 600
            return "limit"
        group = self.db.next_groups(1)[0]
        self.state["phase"] = "scansione gruppi"
        stop = await self.check_group(group, s)
        self._count_page()
        if stop:
            return "stop"
        self._rot_done += 1
        if self._rot_done >= min(s["groups_per_cycle"], len(enabled)):
            self._rot_done = 0
            self.state["last_cycle_at"] = now_iso()
            self._next_rot = self.clock() + s["interval_minutes"] * 60 * random.uniform(0.8, 1.3)
        else:
            low = s["delay_between_groups_min"]
            self._next_rot = self.clock() + random.uniform(low, max(low, s["delay_between_groups_max"]))
        return "ok"

    # ---------- modalità notifiche ----------
    async def poll_notifications(self, s: dict) -> bool:
        """Legge le notifiche e gestisce i post nuovi. Restituisce True se bisogna fermarsi."""
        result = await self.browser.read_notifications()
        if result.status in BLOCK_MESSAGES:
            await self._block(result.status, s)
            return True
        if result.status != "ok":
            return False
        self.state["last_notif_at"] = now_iso()
        events = parse_notifications(result.items)

        if not s["notif_seeded"]:
            # Primo avvio: le notifiche già presenti sono vecchie, le memorizza senza avvisare.
            for ev in events:
                group = self._group_for_event(ev)
                if ev["kind"] == "post":
                    self.db.add_post(self._post_from_snippet(ev, group), group["id"])
                else:
                    self._group_events_seen.add(self._event_key(ev))
            self.db.update_settings({"notif_seeded": True})
            return False

        rules = self.db.active_rules()
        for ev in events:
            if ev["kind"] == "post":
                if self.db.post_exists(ev["post_id"]):
                    continue
                group = self._group_for_event(ev)
                post = None
                if s["notif_open_posts"] and self._under_limit(s):
                    self.state["current_group"] = group["name"] or group["url"]
                    res = await self.browser.read_post(ev["post_url"])
                    self._count_page()
                    if res.status in BLOCK_MESSAGES:
                        await self._block(res.status, s)
                        return True
                    if res.status == "ok":
                        item = {**res.items[0], "permalink": ev["post_url"]}
                        built = build_posts([item], group["url"])
                        post = built[0] if built else None
                if post is None:
                    post = self._post_from_snippet(ev, group)
                self.db.add_post(post, group["id"])
                await self._handle_new_post(post, group, rules, s, first_time=False)
            else:
                # Notifica raggruppata ("X e altre 5 persone hanno pubblicato"): apre il gruppo.
                key = self._event_key(ev)
                if key in self._group_events_seen:
                    continue
                self._group_events_seen.add(key)
                if len(self._group_events_seen) > 2000:
                    self._group_events_seen = {key}
                if self._under_limit(s):
                    group = self._group_for_event(ev)
                    stop = await self.check_group(group, s)
                    self._count_page()
                    if stop:
                        return True
        return False

    @staticmethod
    def _event_key(ev: dict) -> str:
        return f"{ev['group_ref']}|{ev['text']}"

    def _group_for_event(self, ev: dict) -> dict:
        """Gruppo della notifica; se non è in lista lo aggiunge, escluso dalla rotazione."""
        group = self.db.find_group(ev["group_ref"])
        if group is None:
            group = self.db.add_group(normalize_group_url(ev["group_ref"]), ev["group_name"], enabled=False)
        elif not group["name"] and ev["group_name"]:
            self.db.update_group(group["id"], name=ev["group_name"])
            group["name"] = ev["group_name"]
        return group

    @staticmethod
    def _post_from_snippet(ev: dict, group: dict) -> dict:
        item = {"permalink": ev["post_url"], "text": ev["snippet"], "full_text": ev["text"], "author": ""}
        return build_posts([item], group["url"])[0]

    # ---------- modalità rotazione ----------
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
        fb_id = numeric_group_id(result.items)
        if fb_id and group.get("fb_id") != fb_id:
            self.db.link_group_id(group["id"], fb_id)
            group["fb_id"] = fb_id

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
            if await self._handle_new_post(post, group, rules, settings, first_time):
                sent += 1
        return sent

    # ---------- comune ----------
    async def _handle_new_post(self, post: dict, group: dict, rules: list[Rule],
                               settings: dict, first_time: bool) -> bool:
        """Applica le regole a un post appena salvato e invia la notifica. True se inviata."""
        matched = [r for r in rules if match_rule(r, post["text"], group["id"], post["price"]).matched]
        if not matched:
            return False
        for rule in matched:
            self.db.add_match(post["id"], rule.id)
        if first_time:
            # Alla prima lettura di un gruppo i post sono vecchi: niente notifica.
            for rule in matched:
                self.db.set_match_notified(post["id"], rule.id, SEED_NOTE)
            return False
        message = format_message(post, ", ".join(r.name for r in matched), group["name"])
        results = await self.notifier(settings, message)
        errors = "; ".join(f"{c}: {e}" for c, e in results.items() if e)
        if not results:
            errors = "nessun canale di notifica configurato"
        for rule in matched:
            self.db.set_match_notified(post["id"], rule.id, errors or None)
        return True

    async def _block(self, reason: str, settings: dict) -> None:
        self.db.update_settings({"paused": True})
        self.state.update(phase="in pausa", blocked_reason=reason, last_error=BLOCK_MESSAGES[reason])
        try:
            await self.notifier(settings, "⚠️ " + BLOCK_MESSAGES[reason])
        except Exception:
            log.exception("Impossibile inviare l'avviso di blocco")

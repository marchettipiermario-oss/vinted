from datetime import datetime

import httpx
import pytest

from app.browser import ScrapeResult
from app.db import Database
from app.monitor import SEED_NOTE, Monitor, within_active_hours
from app.notifiers import enabled_channels, format_message, notify_all

GROUP = "https://www.facebook.com/groups/123456/"


class FakeBrowser:
    def __init__(self, results):
        self.results = list(results)
        self.started = False
        self.visited = []

    async def start(self, headless=False, channel="chrome"):
        self.started = True

    async def scrape_group(self, url, scrolls=3):
        self.visited.append(url)
        return self.results.pop(0)


class Recorder:
    def __init__(self):
        self.messages = []

    async def __call__(self, settings, message):
        self.messages.append(message)
        return {"discord": None}


def item(pid, text):
    return {"permalink": f"{GROUP}posts/{pid}/", "text": text, "full_text": text, "author": "Mario"}


@pytest.fixture
def db():
    d = Database(":memory:")
    d.update_settings({"paused": False, "active_hour_start": 0, "active_hour_end": 0})
    return d


def make_monitor(db, browser, notifier):
    mon = Monitor(db, browser, notifier=notifier)
    mon.pauses = []

    async def no_pause(seconds):
        mon.pauses.append(seconds)
    mon.pause_between_groups = no_pause
    return mon


async def test_first_read_is_silent_then_new_posts_notify(db):
    g = db.add_group(GROUP)
    db.save_rule({"name": "Nike", "keywords": "nike", "max_price": 50})
    rec = Recorder()
    browser = FakeBrowser([
        ScrapeResult("ok", items=[item(1, "Nike 40€"), item(2, "Puma 10€")], title="Scarpe | Facebook"),
        ScrapeResult("ok", items=[item(1, "Nike 40€"), item(3, "Nike nuove 45 €"), item(4, "Nike 90€")]),
    ])
    mon = make_monitor(db, browser, rec)

    await mon.run_cycle()
    assert rec.messages == [], "la prima lettura non deve notificare i post vecchi"
    m = db.list_matches()
    assert len(m) == 1 and m[0]["notify_error"] == SEED_NOTE
    assert db.get_group(g["id"])["name"] == "Scarpe"

    await mon.run_cycle()
    assert len(rec.messages) == 1
    assert "Nike nuove" in rec.messages[0] and "45,00 €" in rec.messages[0]
    latest = db.list_matches()[0]
    assert latest["post_id"] == "3" and latest["notified"] == 1


async def test_checkpoint_pauses_and_alerts(db):
    db.add_group(GROUP)
    rec = Recorder()
    mon = make_monitor(db, FakeBrowser([ScrapeResult("checkpoint")]), rec)
    await mon.run_cycle()
    assert db.get_settings()["paused"] is True
    assert mon.state["blocked_reason"] == "checkpoint"
    assert "verifica" in rec.messages[0]


async def test_rotation_and_daily_limit(db):
    for i in range(5):
        db.add_group(f"https://www.facebook.com/groups/g{i}/")
    db.update_settings({"groups_per_cycle": 2, "daily_page_limit": 3})
    browser = FakeBrowser([ScrapeResult("ok") for _ in range(10)])
    mon = make_monitor(db, browser, Recorder())
    await mon.run_cycle()
    await mon.run_cycle()
    await mon.run_cycle()
    assert len(browser.visited) == 3
    assert len(set(browser.visited)) == 3, "deve ruotare sui gruppi controllati meno di recente"
    assert mon.state["phase"] == "limite giornaliero raggiunto"
    assert mon.pauses and all(25 <= p <= 75 for p in mon.pauses)


async def test_failed_first_read_still_seeds_silently(db):
    db.add_group(GROUP)
    db.save_rule({"name": "Nike", "keywords": "nike"})
    rec = Recorder()
    browser = FakeBrowser([
        ScrapeResult("no_feed"),
        ScrapeResult("ok", items=[item(1, "Nike vecchie")]),
        ScrapeResult("ok", items=[item(1, "Nike vecchie"), item(2, "Nike nuove")]),
    ])
    mon = make_monitor(db, browser, rec)
    await mon.run_cycle()
    await mon.run_cycle()
    assert rec.messages == [], "dopo un errore la prima lettura riuscita resta silenziosa"
    await mon.run_cycle()
    assert len(rec.messages) == 1 and "Nike nuove" in rec.messages[0]


def test_settings_are_clamped(db):
    s = db.update_settings({"interval_minutes": 0, "groups_per_cycle": 500, "active_hour_end": 30})
    assert s["interval_minutes"] == 3 and s["groups_per_cycle"] == 20 and s["active_hour_end"] == 23


async def test_paused_does_nothing(db):
    db.add_group(GROUP)
    db.update_settings({"paused": True})
    browser = FakeBrowser([])
    await make_monitor(db, browser, Recorder()).run_cycle()
    assert browser.visited == []


def test_active_hours():
    at = lambda h: datetime(2026, 1, 1, h)
    assert within_active_hours(at(10), 8, 23)
    assert not within_active_hours(at(7), 8, 23)
    assert within_active_hours(at(1), 22, 6)
    assert not within_active_hours(at(12), 22, 6)
    assert within_active_hours(at(3), 0, 0)


def test_format_message():
    msg = format_message({"text": "Nike", "price": 12.5, "url": "https://x", "author": "Anna"}, "R", "G")
    assert "12,50 €" in msg and "https://x" in msg and "Anna" in msg


async def test_notify_all_sends_to_each_channel_and_isolates_errors():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.host)
        if "telegram" in request.url.host:
            return httpx.Response(401)
        return httpx.Response(200)

    settings = {
        "discord_webhook_url": "https://discord.com/api/webhooks/1/abc",
        "telegram_bot_token": "T", "telegram_chat_id": "42",
        "whatsapp_phone": "+39333", "whatsapp_apikey": "K",
    }
    assert enabled_channels(settings) == ["discord", "telegram", "whatsapp"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        res = await notify_all(settings, "ciao", client=client)
    assert res == {"discord": None, "telegram": "HTTP 401", "whatsapp": None}
    assert calls == ["discord.com", "api.telegram.org", "api.callmebot.com"]

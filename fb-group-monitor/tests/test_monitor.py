from datetime import datetime

import httpx
import pytest

from app.browser import ScrapeResult
from app.db import Database
from app.monitor import SEED_NOTE, Monitor, within_active_hours
from app.notifiers import enabled_channels, format_message, notify_all

GROUP = "https://www.facebook.com/groups/123456/"


class FakeBrowser:
    def __init__(self, groups=(), notifications=(), posts=None):
        self.group_results = list(groups)
        self.notif_results = list(notifications)
        self.posts = posts or {}
        self.started = False
        self.visited = []
        self.opened_posts = []

    async def start(self, headless=False, channel="chrome"):
        self.started = True

    async def scrape_group(self, url, scrolls=3):
        self.visited.append(url)
        return self.group_results.pop(0)

    async def read_notifications(self):
        return self.notif_results.pop(0)

    async def read_post(self, url):
        self.opened_posts.append(url)
        return self.posts.get(url, ScrapeResult("no_feed"))


class Recorder:
    def __init__(self):
        self.messages = []

    async def __call__(self, settings, message):
        self.messages.append(message)
        return {"discord": None}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def item(pid, text, group=GROUP):
    return {"permalink": f"{group}posts/{pid}/", "text": text, "full_text": text, "author": "Mario"}


def notif(href, text):
    return {"href": href, "text": text}


@pytest.fixture
def db():
    d = Database(":memory:")
    d.update_settings({"paused": False})
    return d


def rotation_only(db):
    db.update_settings({"notif_enabled": False, "rotation_enabled": True})


def notif_only(db):
    db.update_settings({"notif_enabled": True, "rotation_enabled": False})


async def run_now(mon):
    """Come il pulsante 'Controlla ora': esegue subito ciò che è attivo."""
    mon.reset_schedule()
    return await mon.tick()


# ---------------- rotazione ----------------

async def test_first_read_is_silent_then_new_posts_notify(db):
    rotation_only(db)
    g = db.add_group(GROUP)
    db.save_rule({"name": "Nike", "keywords": "nike", "max_price": 50})
    rec = Recorder()
    browser = FakeBrowser(groups=[
        ScrapeResult("ok", items=[item(1, "Nike 40€"), item(2, "Puma 10€")], title="Scarpe | Facebook"),
        ScrapeResult("ok", items=[item(1, "Nike 40€"), item(3, "Nike nuove 45 €"), item(4, "Nike 90€")]),
    ])
    mon = Monitor(db, browser, notifier=rec)

    await run_now(mon)
    assert rec.messages == [], "la prima lettura non deve notificare i post vecchi"
    m = db.list_matches()
    assert len(m) == 1 and m[0]["notify_error"] == SEED_NOTE
    assert db.get_group(g["id"])["name"] == "Scarpe"
    assert db.get_group(g["id"])["fb_id"] == "123456"

    await run_now(mon)
    assert len(rec.messages) == 1
    assert "Nike nuove" in rec.messages[0] and "45,00 €" in rec.messages[0]
    latest = db.list_matches()[0]
    assert latest["post_id"] == "3" and latest["notified"] == 1


async def test_failed_first_read_still_seeds_silently(db):
    rotation_only(db)
    db.add_group(GROUP)
    db.save_rule({"name": "Nike", "keywords": "nike"})
    rec = Recorder()
    browser = FakeBrowser(groups=[
        ScrapeResult("no_feed"),
        ScrapeResult("ok", items=[item(1, "Nike vecchie")]),
        ScrapeResult("ok", items=[item(1, "Nike vecchie"), item(2, "Nike nuove")]),
    ])
    mon = Monitor(db, browser, notifier=rec)
    await run_now(mon)
    await run_now(mon)
    assert rec.messages == [], "dopo un errore la prima lettura riuscita resta silenziosa"
    await run_now(mon)
    assert len(rec.messages) == 1 and "Nike nuove" in rec.messages[0]


async def test_rotation_schedule_one_group_per_step(db):
    rotation_only(db)
    for i in range(5):
        db.add_group(f"https://www.facebook.com/groups/g{i}/")
    db.update_settings({"groups_per_cycle": 2, "interval_minutes": 10,
                        "delay_between_groups_min": 20, "delay_between_groups_max": 20})
    clock = Clock()
    browser = FakeBrowser(groups=[ScrapeResult("ok") for _ in range(10)])
    mon = Monitor(db, browser, notifier=Recorder(), clock=clock)

    wait = await mon.tick()
    assert len(browser.visited) == 1 and wait == pytest.approx(20)
    assert await mon.tick() == pytest.approx(20) and len(browser.visited) == 1, "non ancora in scadenza"

    clock.t += 20
    wait = await mon.tick()
    assert len(browser.visited) == 2
    assert 8 * 60 <= wait <= 13 * 60, "finito il giro, attende l'intervallo tra i giri"
    assert len(set(browser.visited)) == 2, "ruota sui gruppi controllati meno di recente"


async def test_daily_limit(db):
    rotation_only(db)
    for i in range(5):
        db.add_group(f"https://www.facebook.com/groups/g{i}/")
    db.update_settings({"daily_page_limit": 3})
    browser = FakeBrowser(groups=[ScrapeResult("ok") for _ in range(10)])
    mon = Monitor(db, browser, notifier=Recorder())
    for _ in range(5):
        await run_now(mon)
    assert len(browser.visited) == 3
    assert mon.state["phase"] == "limite giornaliero raggiunto"


async def test_checkpoint_pauses_and_alerts(db):
    rotation_only(db)
    db.add_group(GROUP)
    rec = Recorder()
    mon = Monitor(db, FakeBrowser(groups=[ScrapeResult("checkpoint")]), notifier=rec)
    await run_now(mon)
    assert db.get_settings()["paused"] is True
    assert mon.state["blocked_reason"] == "checkpoint"
    assert "verifica" in rec.messages[0]


async def test_paused_does_nothing(db):
    db.add_group(GROUP)
    db.update_settings({"paused": True})
    browser = FakeBrowser()
    await run_now(Monitor(db, browser, notifier=Recorder()))
    assert browser.visited == [] and not browser.started


# ---------------- modalità veloce (notifiche) ----------------

POST_A = f"{GROUP}posts/111/?notif_id=1&notif_t=group_activity&ref=notif"
POST_B = f"{GROUP}posts/222/?notif_id=2&notif_t=group_activity&ref=notif"
POST_C = f"{GROUP}posts/333/?notif_id=3&notif_t=group_activity&ref=notif"


async def test_notifications_first_poll_is_silent_then_opens_new_posts(db):
    notif_only(db)
    db.save_rule({"name": "Nike", "keywords": "nike", "max_price": 50})
    rec = Recorder()
    old = notif(POST_A, 'Mario ha pubblicato in Scarpe Milano: "Nike 40€"')
    browser = FakeBrowser(
        notifications=[
            ScrapeResult("ok", items=[old]),
            ScrapeResult("ok", items=[
                notif(POST_C, 'Anna ha pubblicato in Scarpe Milano: "Vendo scarpe…"'),
                notif(POST_B, 'Luca ha pubblicato in Scarpe Milano: "Nike Air…"'),
                old,
            ]),
        ],
        posts={
            f"{GROUP}posts/222/": ScrapeResult("ok", items=[{"text": "Nike Air Max 43 a 45 €", "full_text": "", "author": "Luca"}]),
            f"{GROUP}posts/333/": ScrapeResult("ok", items=[{"text": "Vendo scarpe Adidas 30€", "full_text": "", "author": "Anna"}]),
        },
    )
    mon = Monitor(db, browser, notifier=rec)

    await run_now(mon)
    assert rec.messages == [] and browser.opened_posts == [], "le notifiche già presenti non vanno notificate"
    group = db.find_group("123456")
    assert group and group["name"] == "Scarpe Milano" and group["enabled"] == 0, \
        "il gruppo viene aggiunto da solo ma fuori dalla rotazione"

    await run_now(mon)
    assert browser.opened_posts == [f"{GROUP}posts/333/", f"{GROUP}posts/222/"], "apre solo i post nuovi"
    assert len(rec.messages) == 1
    assert "Nike Air Max 43" in rec.messages[0] and "45,00 €" in rec.messages[0]
    assert "https://www.facebook.com/groups/123456/posts/222/" in rec.messages[0]


async def test_notifications_without_opening_use_snippet(db):
    notif_only(db)
    db.update_settings({"notif_open_posts": False, "notif_seeded": True})
    db.save_rule({"name": "Nike", "keywords": "nike"})
    rec = Recorder()
    browser = FakeBrowser(notifications=[
        ScrapeResult("ok", items=[notif(POST_B, 'Luca ha pubblicato in Scarpe: "Nike 43 a 45€"')]),
    ])
    await run_now(Monitor(db, browser, notifier=rec))
    assert browser.opened_posts == []
    assert len(rec.messages) == 1 and "45,00 €" in rec.messages[0]


async def test_bundled_notification_scans_group_once(db):
    notif_only(db)
    db.update_settings({"notif_seeded": True})
    db.save_rule({"name": "Nike", "keywords": "nike"})
    g = db.add_group(GROUP, "Scarpe", enabled=False)
    db.add_post({"id": "1", "text": "vecchio"}, g["id"])  # gruppo già letto in passato
    bundled = notif(f"{GROUP}?ref=notif&notif_t=group_activity",
                    "Luca e altre 5 persone hanno pubblicato in Scarpe.")
    rec = Recorder()
    browser = FakeBrowser(
        notifications=[ScrapeResult("ok", items=[bundled]), ScrapeResult("ok", items=[bundled])],
        groups=[ScrapeResult("ok", items=[item(9, "Nike 43 a 50€")])],
    )
    mon = Monitor(db, browser, notifier=rec)
    await run_now(mon)
    await run_now(mon)
    assert browser.visited == [GROUP], "la stessa notifica raggruppata apre il gruppo una sola volta"
    assert len(rec.messages) == 1 and "Nike 43" in rec.messages[0]


async def test_notification_checkpoint_pauses(db):
    notif_only(db)
    rec = Recorder()
    mon = Monitor(db, FakeBrowser(notifications=[ScrapeResult("logged_out")]), notifier=rec)
    await run_now(mon)
    assert db.get_settings()["paused"] is True and "login" in rec.messages[0]


async def test_notifications_and_rotation_interleave(db):
    db.update_settings({"notif_enabled": True, "rotation_enabled": True, "notif_seeded": True,
                        "notif_interval_seconds": 40, "delay_between_groups_min": 60,
                        "delay_between_groups_max": 60})
    for i in range(3):
        db.add_group(f"https://www.facebook.com/groups/g{i}/")
    clock = Clock()
    browser = FakeBrowser(notifications=[ScrapeResult("ok") for _ in range(10)],
                          groups=[ScrapeResult("ok") for _ in range(10)])
    mon = Monitor(db, browser, notifier=Recorder(), clock=clock)
    wait = await mon.tick()
    assert len(browser.visited) == 1
    assert 32 <= wait <= 50, "il prossimo passo è il controllo notifiche, non la pausa tra gruppi"


def test_group_merge_when_numeric_id_learned(db):
    vanity = db.add_group("https://www.facebook.com/groups/scarpemilano/")
    numeric = db.add_group(GROUP, "Scarpe", enabled=False)  # arrivato dalle notifiche
    db.add_post({"id": "5", "text": "x"}, numeric["id"])
    db.link_group_id(vanity["id"], "123456")
    assert db.get_group(numeric["id"]) is None
    assert db.find_group("123456")["id"] == vanity["id"]
    assert db.group_has_posts(vanity["id"])


# ---------------- varie ----------------

def test_settings_are_clamped(db):
    s = db.update_settings({"notif_interval_seconds": 1, "interval_minutes": 0,
                            "groups_per_cycle": 500, "active_hour_end": 30})
    assert s["notif_interval_seconds"] == 15 and s["interval_minutes"] == 1
    assert s["groups_per_cycle"] == 100 and s["active_hour_end"] == 23


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

"""Prova il vero FacebookBrowser, servendo la pagina di prova al posto di facebook.com."""
from pathlib import Path

import pytest

from app.browser import FacebookBrowser

FIXTURE = Path(__file__).parent / "fixtures" / "group_feed.html"
CHROMIUM = Path("/opt/pw-browsers/chromium")


@pytest.fixture
async def browser(tmp_path, monkeypatch):
    if CHROMIUM.exists():
        monkeypatch.setenv("FBM_BROWSER_PATH", str(CHROMIUM))
    b = FacebookBrowser(tmp_path / "profile")
    await b.start(headless=True, channel="")
    yield b
    await b.close()


async def serve(browser, body: str, redirect_to: str | None = None):
    async def handler(route):
        if redirect_to and "/groups/" in route.request.url:
            await route.fulfill(status=200, content_type="text/html",
                                body=f"<script>location.replace({redirect_to!r})</script>")
        else:
            await route.fulfill(status=200, content_type="text/html", body=body)
    await browser._ctx.route("https://www.facebook.com/**", handler)


async def login(browser):
    await browser._ctx.add_cookies([{"name": "c_user", "value": "1", "domain": ".facebook.com", "path": "/"}])


async def test_scrape_group_logged_in(browser):
    await serve(browser, FIXTURE.read_text())
    await login(browser)
    assert await browser.is_logged_in()
    res = await browser.scrape_group("https://www.facebook.com/groups/123456/", scrolls=1)
    assert res.status == "ok"
    assert len(res.items) == 4
    assert "Compro Vendo Scarpe Milano" in res.title


async def test_scrape_group_logged_out(browser):
    await serve(browser, FIXTURE.read_text())
    res = await browser.scrape_group("https://www.facebook.com/groups/123456/", scrolls=0)
    assert res.status == "logged_out"


async def test_scrape_group_checkpoint(browser):
    await serve(browser, "<html><body>Verifica</body></html>",
                redirect_to="https://www.facebook.com/checkpoint/123/")
    await login(browser)
    res = await browser.scrape_group("https://www.facebook.com/groups/123456/", scrolls=0)
    assert res.status == "checkpoint"


NOTIFS = Path(__file__).parent / "fixtures" / "notifications.html"
POST = Path(__file__).parent / "fixtures" / "post.html"


async def test_read_notifications(browser):
    await serve(browser, NOTIFS.read_text())
    await login(browser)
    res = await browser.read_notifications()
    assert res.status == "ok"
    hrefs = [i["href"] for i in res.items]
    assert len(hrefs) == 2, "solo i link ai gruppi dentro role=main"
    assert "Vendo Nike Air Max" in res.items[0]["text"]


async def test_read_post_expands_text_and_skips_comments(browser):
    await serve(browser, POST.read_text())
    await login(browser)
    res = await browser.read_post("https://www.facebook.com/groups/123456/posts/9876543210/")
    assert res.status == "ok"
    post = res.items[0]
    assert "45€ spedizione inclusa" in post["text"]
    assert post["author"] == "Mario Rossi"
    assert "20 €" not in post["full_text"]


async def test_end_to_end_notification_to_message(browser):
    """Monitor + browser veri: notifica → apertura del post → regola → messaggio."""
    from app.db import Database
    from app.monitor import Monitor

    pages = {"/notifications": NOTIFS.read_text(), "/posts/": POST.read_text()}

    async def handler(route):
        body = next((html for key, html in pages.items() if key in route.request.url), "<html></html>")
        await route.fulfill(status=200, content_type="text/html", body=body)
    await browser._ctx.route("https://www.facebook.com/**", handler)
    await login(browser)

    db = Database(":memory:")
    db.update_settings({"paused": False, "rotation_enabled": False, "notif_seeded": True})
    db.save_rule({"name": "Nike 43", "keywords": "nike", "max_price": 50})
    sent = []

    async def notifier(settings, message):
        sent.append(message)
        return {"telegram": None}

    mon = Monitor(db, browser, notifier=notifier)
    mon.browser.start = lambda **kw: _noop()  # browser già avviato dal fixture
    await mon.tick()

    assert len(sent) == 1
    assert "45,00 €" in sent[0] and "Compro Vendo Scarpe Milano" in sent[0]
    assert "https://www.facebook.com/groups/123456/posts/9876543210/" in sent[0]


async def _noop():
    return None

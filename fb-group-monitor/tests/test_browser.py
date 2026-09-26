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

import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.browser import group_name_from_title
from app.extractor import (EXPAND_JS, EXTRACT_JS, SEE_MORE_LABELS, build_posts, feed_url,
                           normalize_group_url, post_id_from_url)

FIXTURE = Path(__file__).parent / "fixtures" / "group_feed.html"
GROUP = "https://www.facebook.com/groups/123456/"


@pytest.mark.parametrize("raw", [
    "https://www.facebook.com/groups/123456",
    "https://facebook.com/groups/123456/?ref=share",
    "https://m.facebook.com/groups/123456/posts/99/",
    "www.facebook.com/groups/123456",
    "groups/123456",
    "123456",
])
def test_normalize_group_url(raw):
    assert normalize_group_url(raw) == GROUP


@pytest.mark.parametrize("raw", ["", "https://example.com/groups/1", "https://www.facebook.com/marketplace"])
def test_normalize_group_url_rejects(raw):
    with pytest.raises(ValueError):
        normalize_group_url(raw)


def test_feed_url_sorts_by_newest():
    assert feed_url("groups/abc") == "https://www.facebook.com/groups/abc/?sorting_setting=CHRONOLOGICAL"


@pytest.mark.parametrize("url, pid", [
    ("https://www.facebook.com/groups/1/posts/555/?x=1", "555"),
    ("https://www.facebook.com/groups/nome/permalink/777/", "777"),
    ("https://www.facebook.com/groups/1/?multi_permalinks=888&ref=share", "888"),
    ("https://www.facebook.com/permalink.php?story_fbid=999&id=1", "999"),
    ("https://www.facebook.com/groups/1/user/2/", None),
    (None, None),
])
def test_post_id_from_url(url, pid):
    assert post_id_from_url(url) == pid


def test_group_name_from_title():
    assert group_name_from_title("(3) Compro Vendo Milano | Facebook") == "Compro Vendo Milano"
    assert group_name_from_title("Gruppo | Facebook") == "Gruppo"


def _launch_kwargs():
    path = os.environ.get("FBM_BROWSER_PATH") or "/opt/pw-browsers/chromium"
    return {"executable_path": path} if Path(path).exists() else {}


async def test_extract_from_fixture_page():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**_launch_kwargs())
        page = await browser.new_page()
        await page.goto(FIXTURE.as_uri())
        clicked = await page.evaluate(EXPAND_JS, SEE_MORE_LABELS)
        raw = await page.evaluate(EXTRACT_JS)
        await browser.close()

    assert clicked == 1
    assert len(raw) == 4, "i commenti annidati non devono essere contati come post"

    posts = {p["id"]: p for p in build_posts(raw, GROUP)}
    nike = posts["9876543210"]
    assert nike["url"] == GROUP + "posts/9876543210/"
    assert nike["author"] == "Mario Rossi"
    assert nike["price"] == 45.0
    assert "Offro 30" not in nike["text"]

    samba = posts["1111111111"]
    assert "budget massimo 70 euro" in samba["text"], "il testo espanso con 'Altro' va letto"
    assert samba["price"] == 70.0

    jordan = posts["2222222222"]
    assert "Jordan 1 Mid rosse" in jordan["text"]
    assert jordan["price"] == 120.0

    hashed = [p for pid, p in posts.items() if pid.startswith("h")]
    assert len(hashed) == 1 and "scatole" in hashed[0]["text"]


def test_hash_id_is_stable():
    raw = [{"permalink": None, "text": "Regalo divano", "full_text": "", "author": "Anna"}]
    assert build_posts(raw, GROUP)[0]["id"] == build_posts(raw, GROUP)[0]["id"]

"""Drive the agent flows against local stand-ins for the Subito / Facebook forms.

The real sites are not reachable from CI, so these pages reproduce the shape of the
forms (labels, custom dropdowns, file inputs, multi-step submit, upsell page) and the
browser requests to subito.it / facebook.com are answered locally.
"""
import asyncio
import glob
import sys
from pathlib import Path

import pytest

pw_api = pytest.importorskip("playwright.async_api")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
import sites  # noqa: E402

CHROME = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome") or [None])[0]

SUBITO_FORM = """<html><body><form id=f onsubmit="event.preventDefault(); go()">
<label for=cat>Categoria</label><select id=cat><option>Scegli</option><option>Abbigliamento e accessori</option></select>
<input type=file accept="image/*" multiple id=ph>
<label for=t>Titolo</label><input id=t>
<label for=d>Descrizione</label><textarea id=d></textarea>
<label for=p>Prezzo</label><input id=p type=number>
<label for=c>Comune</label><input id=c role=combobox autocomplete=off oninput="sug()">
<ul id=s></ul>
<button>Continua</button></form>
<script>
function sug(){ document.getElementById('s').innerHTML = '<li role=option onclick="document.getElementById(\\'c\\').value=\\'Milano (MI)\\'">Milano (MI)</li>' }
function go(){
  window.parent.__sent = {cat: cat.value, t: t.value, d: d.value, p: p.value, c: c.value, photos: ph.files.length};
  localStorage.setItem('sent', JSON.stringify(window.parent.__sent));
  location.href = 'https://www.subito.it/upsell';
}
</script></body></html>"""
SUBITO_UPSELL = """<html><body><h1>Dai visibilità al tuo annuncio</h1>
<button onclick="alert('paid!')">Vetrina 4,99 €</button>
<button onclick="location.href='https://www.subito.it/conferma'">Pubblica gratis</button></body></html>"""
SUBITO_DONE = "<html><body>Il tuo annuncio è stato inserito ed è in revisione.</body></html>"
SUBITO_PAY = "<html><body><label>Carta di credito <input></label><button>Paga ora</button></body></html>"

FB_FORM = """<html><body>
<input type=file accept="image/*,image/heif" multiple id=ph style="display:none">
<label>Titolo <input id=t></label>
<label>Prezzo <input id=p></label>
<label>Categoria <input id=cat readonly onclick="menu('cat',['Abbigliamento','Elettronica'])"></label>
<label>Condizione <input id=cond readonly onclick="menu('cond',['Nuovo','Usato - Come nuovo','Usato - Buone condizioni'])"></label>
<label>Descrizione <textarea id=d></textarea></label>
<div id=m role=listbox></div>
<div role=button tabindex=0 onclick="step()">Avanti</div>
<script>
function menu(id, opts){ m.innerHTML = opts.map(o => '<div role=option onclick="document.getElementById(\\''+id+'\\').value=\\''+o+'\\';m.innerHTML=\\'\\'">'+o+'</div>').join('') }
function step(){
  localStorage.setItem('sent', JSON.stringify({t: t.value, p: p.value, cat: cat.value, cond: cond.value, d: d.value, photos: ph.files.length}));
  document.body.innerHTML = '<div role=button tabindex=0 onclick="location.href=\\'https://www.facebook.com/marketplace/item/42/\\'">Pubblica</div>';
}
</script></body></html>"""

LISTING = {
    "title": "Giacca jeans Levi's", "description": "Usata poche volte.\nMarca: Levi's", "price": 45.0,
    "condition": "Ottime condizioni", "condition_key": "very_good", "category": "", "location": "Milano",
    "brand": "Levi's",
}


def run_with_pages(pages: dict, fn):
    async def main():
        async with pw_api.async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME)
            ctx = await browser.new_context()

            async def route(r):
                url = r.request.url
                for prefix, body in pages.items():
                    if url.startswith(prefix):
                        return await r.fulfill(status=200, content_type="text/html", body=body)
                await r.fulfill(status=404, body="not found")
            await ctx.route("**/*", route)
            page = await ctx.new_page()
            try:
                return await fn(page)
            finally:
                await browser.close()
    return asyncio.run(main())


@pytest.fixture
def photos(tmp_path):
    files = []
    for i in range(2):
        f = tmp_path / f"{i}.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
        files.append(str(f))
    return files


async def _sent(page):
    import json
    return json.loads(await page.evaluate("localStorage.getItem('sent')"))


def test_subito_publish_fills_form_and_skips_paid_upsell(photos):
    async def fn(page):
        page.on("dialog", lambda d: (_ for _ in ()).throw(AssertionError("clicked a paid option")))
        listing = {**LISTING, "category": "Abbigliamento e accessori"}
        url = await sites.subito_publish(page, listing, photos, human_timeout=0)
        await page.goto("https://www.subito.it/upsell")  # same origin, to read localStorage
        return url, await _sent(page)

    url, sent = run_with_pages({
        "https://www.subito.it/inserisci-annuncio": SUBITO_FORM,
        "https://www.subito.it/upsell": SUBITO_UPSELL,
        "https://www.subito.it/conferma": SUBITO_DONE,
    }, fn)
    assert url == "https://www.subito.it/conferma"
    assert sent == {"cat": "Abbigliamento e accessori", "t": "Giacca jeans Levi's", "d": LISTING["description"],
                    "p": "45", "c": "Milano (MI)", "photos": 2}


def test_subito_never_pays(photos):
    async def fn(page):
        with pytest.raises(sites.NeedsHuman, match="pagamento"):
            await sites.subito_publish(page, LISTING, photos, human_timeout=0)

    run_with_pages({
        "https://www.subito.it/inserisci-annuncio": SUBITO_FORM,
        "https://www.subito.it/upsell": SUBITO_PAY,
    }, fn)


def test_subito_unknown_form_hands_over_to_user(photos):
    async def fn(page):
        async def user_finishes():
            await page.wait_for_selector("#__vb_agent", timeout=60000)
            await page.goto("https://www.subito.it/conferma")
        task = asyncio.create_task(user_finishes())
        url = await sites.subito_publish(page, LISTING, photos, human_timeout=30)
        await task
        return url

    url = run_with_pages({
        "https://www.subito.it/inserisci-annuncio": "<html><body>Nuovo layout misterioso</body></html>",
        "https://www.subito.it/conferma": SUBITO_DONE,
    }, fn)
    assert url == "https://www.subito.it/conferma"


def test_facebook_publish_custom_dropdowns(photos):
    async def fn(page):
        url = await sites.facebook_publish(page, LISTING, photos, human_timeout=0)
        await page.goto("https://www.facebook.com/marketplace/create/item")
        return url, await _sent(page)

    url, sent = run_with_pages({
        "https://www.facebook.com/marketplace/create/item": FB_FORM,
        "https://www.facebook.com/marketplace/item/42/": "<html><body>Il tuo annuncio</body></html>",
    }, fn)
    assert url == "https://www.facebook.com/marketplace/item/42/"
    assert sent == {"t": "Giacca jeans Levi's", "p": "45", "cat": "Abbigliamento",
                    "cond": "Usato - Come nuovo", "d": LISTING["description"], "photos": 2}


def test_login_wall_waits_for_user(photos):
    async def fn(page):
        async def user_logs_in():
            await page.wait_for_selector("#__vb_agent", timeout=60000)
            await page.goto("https://www.facebook.com/marketplace/create/item")
        task = asyncio.create_task(user_logs_in())
        url = await sites.facebook_publish(page, LISTING, photos, human_timeout=30,
                                           post_url="https://www.facebook.com/login/?next=create")
        await task
        return url

    url = run_with_pages({
        "https://www.facebook.com/login": "<html><body>Accedi</body></html>",
        "https://www.facebook.com/marketplace/create/item": FB_FORM,
        "https://www.facebook.com/marketplace/item/42/": "<html><body>ok</body></html>",
    }, fn)
    assert url == "https://www.facebook.com/marketplace/item/42/"

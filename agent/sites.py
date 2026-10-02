"""Browser flows that publish / remove listings on Subito and Facebook Marketplace.

The flows drive the user's own logged-in browser profile. Sites change their
markup often, so fields are located the way a person would find them (label,
placeholder, accessible name) in Italian and English, never by CSS class.

When a step cannot be completed automatically (unknown field, login wall,
captcha, a page asking for payment) the flow hands the browser over to the
user: it shows a banner and waits for them to finish, then carries on.
The agent never clicks anything that pays.
"""
import asyncio
import re
from typing import Awaitable, Callable, Iterable, List, Optional

SUBITO_HOME = "https://www.subito.it/"
SUBITO_POST = "https://www.subito.it/inserisci-annuncio"
FB_POST = "https://www.facebook.com/marketplace/create/item"
FB_SELLING = "https://www.facebook.com/marketplace/you/selling"

# Buttons tried in order to move a multi-step form forward. Free options first,
# so promotional upsell pages are skipped instead of accepted.
SUBITO_NEXT = ["Pubblica gratis", "Continua senza", "Non ora", "No, grazie", "Pubblica annuncio",
               "Pubblica", "Inserisci annuncio", "Continua", "Avanti", "Conferma"]
FB_NEXT = ["Avanti", "Next", "Pubblica", "Publish"]

PAYMENT_TEXT = re.compile(r"carta di credito|metodo di pagamento|paga ora|checkout|credit card|pay now", re.I)
SUBITO_DONE_TEXT = re.compile(
    r"annuncio (è stato |e' stato )?(inserito|pubblicato|ricevuto)|in revisione|in attesa di (approvazione|moderazione)|"
    r"il tuo annuncio sarà online", re.I)
LOGIN_URL = re.compile(r"login|signin|accedi|areariservata/login|checkpoint", re.I)

FB_CONDITIONS = {
    "new_with_tags": ["Nuovo", "New"],
    "new_without_tags": ["Nuovo", "New"],
    "very_good": ["Usato - Come nuovo", "Come nuovo", "Used - Like New", "Like New"],
    "good": ["Usato - Buone condizioni", "Buone condizioni", "Used - Good", "Good"],
    "satisfactory": ["Usato - Discrete condizioni", "Discrete condizioni", "Used - Fair", "Fair"],
}


class NeedsHuman(Exception):
    """Raised when the flow cannot continue on its own."""


def _rx(names: Iterable[str]) -> re.Pattern:
    return re.compile("|".join(re.escape(n) for n in names), re.I)


async def _visible(loc) -> Optional[object]:
    try:
        n = await loc.count()
    except Exception:
        return None
    for i in range(min(n, 5)):
        item = loc.nth(i)
        try:
            if await item.is_visible():
                return item
        except Exception:
            continue
    return None


async def find_field(page, names: List[str], timeout: float = 8.0):
    """First visible text field matching one of the names by label, placeholder or accessible name."""
    rx = _rx(names)
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        for loc in (page.get_by_label(rx), page.get_by_placeholder(rx),
                    page.get_by_role("textbox", name=rx), page.get_by_role("combobox", name=rx),
                    page.get_by_role("spinbutton", name=rx)):
            item = await _visible(loc)
            if item:
                return item
        if asyncio.get_event_loop().time() > deadline:
            return None
        await page.wait_for_timeout(400)


async def fill(page, names: List[str], value, required: bool = True, timeout: float = 8.0) -> bool:
    if value in (None, ""):
        return False
    field = await find_field(page, names, timeout)
    if not field:
        if required:
            raise NeedsHuman(f"Campo non trovato: {names[0]}")
        return False
    await field.click()
    await field.fill(str(value))
    return True


async def choose(page, names: List[str], values: List[str], required: bool = False, timeout: float = 6.0) -> bool:
    """Pick an option in a native <select> or a custom dropdown."""
    values = [v for v in values if v]
    if not values:
        return False
    field = await find_field(page, names, timeout)
    if field is None:
        trigger = await _visible(page.get_by_role("button", name=_rx(names)))
        if trigger is None:
            trigger = await _visible(page.get_by_text(_rx(names)))
        field = trigger
    if field is None:
        if required:
            raise NeedsHuman(f"Campo non trovato: {names[0]}")
        return False
    tag = (await field.evaluate("e => e.tagName")).lower()
    if tag == "select":
        for v in values:
            try:
                await field.select_option(label=v)
                return True
            except Exception:
                continue
        options = await field.evaluate("e => [...e.options].map(o => o.label)")
        for v in values:
            for o in options:
                if v.lower() in o.lower():
                    await field.select_option(label=o)
                    return True
    else:
        await field.click()
        if tag in ("input", "textarea") and await field.is_editable():
            await field.fill(values[0])  # autocomplete: type to get suggestions
        await page.wait_for_timeout(600)
        for v in values:
            for loc in (page.get_by_role("option", name=re.compile(re.escape(v), re.I)),
                        page.get_by_role("menuitem", name=re.compile(re.escape(v), re.I)),
                        page.get_by_text(re.compile(r"^\s*" + re.escape(v), re.I))):
                item = await _visible(loc)
                if item:
                    await item.click()
                    return True
        await page.keyboard.press("Escape")
    if required:
        raise NeedsHuman(f"Valore non trovato per {names[0]}: {values[0]}")
    return False


async def upload_photos(page, files: List[str], required: bool = True) -> bool:
    if not files:
        return False
    inputs = page.locator("input[type=file]")
    for _ in range(20):
        if await inputs.count():
            break
        await page.wait_for_timeout(400)
    if not await inputs.count():
        if required:
            raise NeedsHuman("Campo foto non trovato")
        return False
    target = inputs.first
    for i in range(await inputs.count()):
        accept = (await inputs.nth(i).get_attribute("accept")) or ""
        if "image" in accept:
            target = inputs.nth(i)
            break
    multiple = await target.get_attribute("multiple") is not None
    if multiple:
        await target.set_input_files(files)
    else:
        for f in files:
            await target.set_input_files(f)
            await page.wait_for_timeout(500)
    await page.wait_for_timeout(1500)
    return True


async def click_first(page, names: List[str]) -> Optional[str]:
    """Click the first visible, enabled button/link among `names` (priority order). Returns its name."""
    for name in names:
        rx = re.compile(r"^\s*" + re.escape(name) + r"\s*$", re.I)
        for loc in (page.get_by_role("button", name=rx), page.get_by_role("link", name=rx)):
            item = await _visible(loc)
            if item and await item.is_enabled():
                await item.click()
                return name
    return None


async def ensure_no_payment(page) -> None:
    text = await page.locator("body").inner_text()
    if PAYMENT_TEXT.search(text):
        raise NeedsHuman("La pagina chiede un pagamento: l'agente non paga mai, decidi tu")


async def handover(page, message: str, done: Callable[[], Awaitable[bool]], timeout_s: int) -> bool:
    """Show a banner in the page and wait for the user to finish the step by hand."""
    js = """msg => {
        let b = document.getElementById('__vb_agent');
        if (!b) { b = document.createElement('div'); b.id = '__vb_agent'; document.body.appendChild(b); }
        b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#FFD600;color:#000;' +
          'font:bold 15px sans-serif;padding:12px 16px;border-bottom:3px solid #000;pointer-events:none';
        b.textContent = '🤖 VINTED.BOT agente: ' + msg;
    }"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        try:
            await page.evaluate(js, message)
        except Exception:
            pass  # page navigating
        try:
            if await done():
                return True
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


async def _logged_in_or_wait(page, site: str, timeout_s: int) -> None:
    if LOGIN_URL.search(page.url):
        ok = await handover(page, f"accedi a {site} in questa finestra, poi l'agente continua da solo",
                            lambda: _not_login(page), timeout_s)
        if not ok:
            raise NeedsHuman(f"Login {site} non completato")


async def _not_login(page) -> bool:
    return not LOGIN_URL.search(page.url)


# -----------------------------------------------------------------------------
# Subito
# -----------------------------------------------------------------------------
async def subito_done(page) -> bool:
    if re.search(r"conferma|success|grazie|thank", page.url, re.I):
        return True
    return bool(SUBITO_DONE_TEXT.search(await page.locator("body").inner_text()))


async def subito_publish(page, listing: dict, photos: List[str], human_timeout: int = 600,
                         post_url: str = SUBITO_POST) -> str:
    async def run():
        await page.goto(post_url, wait_until="domcontentloaded")
        await _logged_in_or_wait(page, "Subito", human_timeout)
        if not await find_field(page, ["Titolo", "Oggetto"], timeout=10):
            await page.goto(SUBITO_HOME, wait_until="domcontentloaded")
            if not await click_first(page, ["Inserisci annuncio", "Vendi"]):
                raise NeedsHuman("Non trovo il modulo di inserimento")
            await _logged_in_or_wait(page, "Subito", human_timeout)
        await choose(page, ["Categoria"], [listing.get("category")])
        await upload_photos(page, photos)
        await fill(page, ["Titolo", "Oggetto"], listing["title"])
        await fill(page, ["Descrizione", "Testo dell'annuncio", "Testo"], listing["description"])
        await fill(page, ["Prezzo"], int(round(listing["price"])) if float(listing["price"]).is_integer() else listing["price"])
        await choose(page, ["Condizioni", "Condizione", "Stato"], [listing.get("condition")])
        if listing.get("location"):
            await choose(page, ["Comune", "Città", "Località", "Indirizzo"], [listing["location"]])
        for _ in range(6):
            if await subito_done(page):
                return
            await ensure_no_payment(page)
            if not await click_first(page, SUBITO_NEXT):
                raise NeedsHuman("Non trovo il pulsante per pubblicare")
            await page.wait_for_timeout(2500)
        if not await subito_done(page):
            raise NeedsHuman("Pubblicazione non confermata")

    await _run_with_handover(page, run, lambda: subito_done(page), human_timeout,
                             "completa tu l'annuncio e premi Pubblica (gratis)")
    return page.url


async def subito_delete(page, url: str, human_timeout: int = 600) -> None:
    async def gone() -> bool:
        text = await page.locator("body").inner_text()
        return bool(re.search(r"annuncio (è stato )?(eliminato|cancellato|rimosso)|non (è più )?disponibile", text, re.I))

    async def run():
        await page.goto(url, wait_until="domcontentloaded")
        await _logged_in_or_wait(page, "Subito", human_timeout)
        if not await click_first(page, ["Elimina", "Cancella annuncio", "Elimina annuncio", "Rimuovi"]):
            raise NeedsHuman("Pulsante Elimina non trovato")
        await page.wait_for_timeout(1200)
        await choose(page, ["Motivo"], ["Venduto su un altro sito", "Venduto", "Altro"])
        await click_first(page, ["Venduto altrove", "Venduto su un altro sito", "Elimina", "Conferma", "Sì", "Si"])
        await page.wait_for_timeout(2500)
        if not await gone():
            raise NeedsHuman("Eliminazione non confermata")

    await _run_with_handover(page, run, gone, human_timeout, "elimina tu l'annuncio di Subito")


# -----------------------------------------------------------------------------
# Facebook Marketplace
# -----------------------------------------------------------------------------
async def fb_done(page) -> bool:
    return "/marketplace/create" not in page.url and "/marketplace" in page.url


async def facebook_publish(page, listing: dict, photos: List[str], human_timeout: int = 600,
                           post_url: str = FB_POST) -> str:
    async def run():
        await page.goto(post_url, wait_until="domcontentloaded")
        await _logged_in_or_wait(page, "Facebook", human_timeout)
        if "/marketplace/create" not in page.url and not await find_field(page, ["Titolo", "Title"], timeout=2):
            await page.goto(post_url, wait_until="domcontentloaded")
        await upload_photos(page, photos)
        await fill(page, ["Titolo", "Title"], listing["title"])
        await fill(page, ["Prezzo", "Price"], int(round(listing["price"])))
        await choose(page, ["Categoria", "Category"], [listing.get("category") or "Abbigliamento", "Clothing"])
        await choose(page, ["Condizione", "Condition"], FB_CONDITIONS.get(listing.get("condition_key"), []))
        await fill(page, ["Descrizione", "Description"], listing["description"], required=False)
        if listing.get("brand"):
            await fill(page, ["Marca", "Brand"], listing["brand"], required=False, timeout=1)
        if listing.get("location"):
            await choose(page, ["Luogo", "Posizione", "Location"], [listing["location"]])
        for _ in range(4):
            if await fb_done(page):
                return
            await ensure_no_payment(page)
            if not await click_first(page, FB_NEXT):
                raise NeedsHuman("Non trovo Avanti/Pubblica")
            await page.wait_for_timeout(3000)
        for _ in range(10):
            if await fb_done(page):
                return
            await page.wait_for_timeout(1000)
        raise NeedsHuman("Pubblicazione non confermata")

    await _run_with_handover(page, run, lambda: fb_done(page), human_timeout,
                             "completa tu l'annuncio e premi Pubblica")
    return page.url if "/item/" in page.url else FB_SELLING


async def facebook_delete(page, url: str, title: str, human_timeout: int = 600) -> None:
    async def gone() -> bool:
        text = await page.locator("body").inner_text()
        return bool(re.search(r"annuncio eliminato|eliminato|listing deleted|deleted", text, re.I))

    async def run():
        await page.goto(url or FB_SELLING, wait_until="domcontentloaded")
        await _logged_in_or_wait(page, "Facebook", human_timeout)
        if "/item/" not in page.url:
            card = await _visible(page.get_by_text(title[:40]))
            if not card:
                raise NeedsHuman(f"Annuncio non trovato: {title}")
            await card.click()
            await page.wait_for_timeout(2000)
        if not await click_first(page, ["Elimina annuncio", "Elimina", "Delete listing", "Delete"]):
            await click_first(page, ["Altro", "More", "Altre opzioni", "More options"])
            await page.wait_for_timeout(800)
            if not await click_first(page, ["Elimina annuncio", "Elimina", "Delete listing", "Delete"]):
                raise NeedsHuman("Pulsante Elimina non trovato")
        await page.wait_for_timeout(1000)
        await click_first(page, ["Elimina", "Delete"])
        await page.wait_for_timeout(1500)
        await click_first(page, ["Preferisco non rispondere", "Venduto altrove", "Rather not answer", "Avanti", "Next"])
        await page.wait_for_timeout(1500)
        if not await gone():
            raise NeedsHuman("Eliminazione non confermata")

    await _run_with_handover(page, run, gone, human_timeout, f"elimina tu l'annuncio «{title}»")


# -----------------------------------------------------------------------------
async def _run_with_handover(page, run, done, timeout_s: int, message: str) -> None:
    try:
        await run()
        return
    except NeedsHuman as e:
        reason = str(e)
    if timeout_s <= 0:
        raise NeedsHuman(reason)
    ok = await handover(page, f"{reason} → {message}", done, timeout_s)
    if not ok:
        raise NeedsHuman(f"{reason} (nessun intervento entro {timeout_s} s)")

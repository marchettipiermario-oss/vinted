"""Estrazione dei post dalla pagina di un gruppo Facebook.

Facebook cambia spesso l'HTML e usa classi offuscate, quindi qui ci si appoggia
solo ad attributi stabili: role="feed", role="article", data-ad-preview e i link
permanenti dei post.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import urlparse

from .filters import parse_price

# Testi del pulsante che espande i post lunghi (italiano e inglese).
SEE_MORE_LABELS = ["Altro", "Vedi altro", "Mostra altro", "See more", "See More"]

# Eseguito nella pagina: restituisce i post visibili nel feed del gruppo.
EXTRACT_JS = r"""
() => {
  const feed = document.querySelector('[role="feed"]') || document.body;
  const all = Array.from(feed.querySelectorAll('[role="article"]'));
  // Solo articoli di primo livello: quelli annidati sono commenti.
  const articles = all.filter(a => !a.parentElement || !a.parentElement.closest('[role="article"]'));
  const postRe = /\/groups\/[^/?#]+\/(?:posts|permalink)\/\d+|[?&](?:story_fbid|multi_permalinks)=\d+/;
  return articles.map(a => {
    const hrefs = Array.from(a.querySelectorAll('a[href]')).map(x => x.href);
    const permalink = hrefs.find(h => postRe.test(h)) || null;

    let text = '';
    const msg = a.querySelector('[data-ad-preview="message"], [data-ad-comet-preview="message"]');
    if (msg) {
      text = msg.innerText;
    } else {
      const parts = [];
      a.querySelectorAll('div[dir="auto"], span[dir="auto"]').forEach(el => {
        if (el.closest('[role="button"], a, h2, h3, h4')) return;
        if (el.querySelector('div[dir="auto"], span[dir="auto"]')) return;
        const t = (el.innerText || '').trim();
        if (t && !parts.includes(t)) parts.push(t);
      });
      text = parts.join('\n');
    }

    const authorEl = a.querySelector('h2 a, h3 a, h4 a, strong a, h2 span, h3 span, h4 span');
    return {
      permalink,
      text: (text || '').trim(),
      full_text: (a.innerText || '').slice(0, 6000),
      author: authorEl ? authorEl.innerText.trim() : '',
    };
  });
}
"""

EXPAND_JS = r"""
(labels) => {
  const feed = document.querySelector('[role="feed"]') || document.body;
  let clicked = 0;
  feed.querySelectorAll('[role="button"]').forEach(b => {
    const t = (b.innerText || '').trim();
    if (labels.includes(t) && clicked < 25) { b.click(); clicked++; }
  });
  return clicked;
}
"""

_ID_PATTERNS = [
    re.compile(r"/groups/([^/?#]+)/(?:posts|permalink)/(\d+)"),
    re.compile(r"[?&]story_fbid=(\d+)"),
    re.compile(r"[?&]multi_permalinks=(\d+)"),
]


def normalize_group_url(url: str) -> str:
    """Accetta link o ID del gruppo e restituisce https://www.facebook.com/groups/<id>/"""
    url = (url or "").strip()
    if not url:
        raise ValueError("URL del gruppo vuoto")
    if not re.match(r"^https?://", url):
        url = url.lstrip("/")
        if not url.startswith(("groups/", "www.facebook.com", "facebook.com", "m.facebook.com")):
            url = f"groups/{url}"
        if not url.startswith(("www.", "facebook.com", "m.facebook.com")):
            url = f"www.facebook.com/{url}"
        url = f"https://{url}"
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not (host == "facebook.com" or host.endswith(".facebook.com")):
        raise ValueError("Non è un link di Facebook")
    m = re.match(r"^/groups/([^/?#]+)", parsed.path)
    if not m:
        raise ValueError("Il link deve essere di un gruppo (facebook.com/groups/...)")
    return f"https://www.facebook.com/groups/{m.group(1)}/"


def feed_url(group_url: str) -> str:
    """Pagina del gruppo ordinata per post più recenti."""
    return normalize_group_url(group_url) + "?sorting_setting=CHRONOLOGICAL"


def post_id_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    for pattern in _ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(m.lastindex)
    return None


def clean_post_url(url: Optional[str], group_url: str) -> Optional[str]:
    pid = post_id_from_url(url)
    if not pid:
        return url
    return normalize_group_url(group_url) + f"posts/{pid}/"


def build_posts(raw_items: list[dict], group_url: str) -> list[dict]:
    """Trasforma i dati grezzi della pagina in post con ID stabile e prezzo."""
    posts: dict[str, dict] = {}
    for item in raw_items:
        text = (item.get("text") or "").strip()
        full_text = (item.get("full_text") or "").strip()
        if not text and not full_text:
            continue
        pid = post_id_from_url(item.get("permalink"))
        if not pid:
            # Senza link permanente: ID dal contenuto, per non notificare due volte.
            basis = f"{group_url}|{item.get('author', '')}|{(text or full_text)[:300]}"
            pid = "h" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]
        # Il testo del messaggio è più pulito; il testo completo include
        # annunci in formato "vendita" dove il prezzo sta in un campo separato.
        match_text = text or full_text
        price = parse_price(text) if text else None
        if price is None:
            price = parse_price(full_text)
        posts[pid] = {
            "id": pid,
            "url": clean_post_url(item.get("permalink"), group_url),
            "author": (item.get("author") or "").strip()[:200],
            "text": match_text[:4000],
            "price": price,
        }
    return list(posts.values())


# ---------------------------------------------------------------------------
# Modalità veloce: pagina delle notifiche e singolo post
# ---------------------------------------------------------------------------

NOTIFICATIONS_URL = "https://www.facebook.com/notifications"

# Eseguito nella pagina delle notifiche: link verso gruppi con il testo della notifica.
NOTIFICATIONS_JS = r"""
() => {
  const root = document.querySelector('[role="main"]') || document.body;
  const out = [];
  const seen = new Set();
  root.querySelectorAll('a[href*="/groups/"]').forEach(a => {
    const href = a.href;
    if (seen.has(href)) return;
    seen.add(href);
    const box = a.closest('[role="row"], [role="listitem"], [role="gridcell"], [role="article"]') || a;
    out.push({ href, text: (box.innerText || a.innerText || '').trim().slice(0, 1500) });
  });
  return out;
}
"""

# Eseguito nella pagina di un singolo post: il primo articolo è il post, gli altri commenti.
POST_JS = r"""
() => {
  const all = Array.from(document.querySelectorAll('[role="article"]'));
  const top = all.filter(a => !a.parentElement || !a.parentElement.closest('[role="article"]'));
  const msgSel = '[data-ad-preview="message"], [data-ad-comet-preview="message"]';
  const art = top[0] || null;
  const scope = art || document;
  const msg = scope.querySelector(msgSel);
  const authorEl = scope.querySelector('h2 a, h3 a, h4 a, strong a, h2 span, h3 span, h4 span');
  let full = art ? art.innerText : '';
  if (art) {
    // Toglie dal testo completo i commenti annidati.
    art.querySelectorAll('[role="article"]').forEach(c => { full = full.replace(c.innerText, ''); });
  }
  return {
    text: msg ? msg.innerText.trim() : '',
    full_text: (full || '').slice(0, 6000),
    author: authorEl ? authorEl.innerText.trim() : '',
  };
}
"""

_GROUP_REF = re.compile(r"/groups/([^/?#]+)")
_GROUP_NAME = re.compile(
    r"(?:pubblicato|condiviso|scritto|posted|shared)\b.*?\bin\s+(.+?)\s*(?::|[.\n]|$)",
    re.IGNORECASE,
)
_QUOTED = re.compile(r"[\"“«„](.+?)[\"”»“]", re.DOTALL)
_NOT_GROUP_PAGES = {"feed", "discover", "joins", "search", "create", "notifications"}


def group_ref_from_url(url: Optional[str]) -> Optional[str]:
    """'https://www.facebook.com/groups/123/posts/9/' -> '123'"""
    m = _GROUP_REF.search(url or "")
    if not m or m.group(1) in _NOT_GROUP_PAGES:
        return None
    return m.group(1)


def numeric_group_id(raw_items: list[dict]) -> Optional[str]:
    """ID numerico del gruppo ricavato dai link dei post (anche se il link del gruppo usa un nome)."""
    for item in raw_items:
        ref = group_ref_from_url(item.get("permalink"))
        if ref and ref.isdigit():
            return ref
    return None


def parse_notifications(raw: list[dict]) -> list[dict]:
    """Trasforma le notifiche grezze in eventi: nuovo post o attività in un gruppo."""
    events: dict[str, dict] = {}
    for item in raw:
        href = item.get("href") or ""
        ref = group_ref_from_url(href)
        if not ref:
            continue
        text = (item.get("text") or "").strip()
        pid = post_id_from_url(href)
        name_match = _GROUP_NAME.search(text)
        quoted = _QUOTED.search(text)
        event = {
            "kind": "post" if pid else "group",
            "group_ref": ref,
            "group_name": name_match.group(1).strip(' "“«') if name_match else "",
            "post_id": pid,
            "post_url": f"https://www.facebook.com/groups/{ref}/posts/{pid}/" if pid else None,
            # Anteprima del post presente nella notifica (di solito troncata).
            "snippet": quoted.group(1).strip() if quoted else text,
            "text": text,
        }
        key = f"p:{pid}" if pid else f"g:{ref}:{hashlib.sha1(text.encode()).hexdigest()[:12]}"
        events.setdefault(key, event)
    return list(events.values())

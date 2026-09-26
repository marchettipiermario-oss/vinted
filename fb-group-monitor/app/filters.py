"""Filtri sui post: parole chiave, parole escluse e prezzo."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_NUM = r"\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"

# L'ordine conta: prima i formati con valuta esplicita, poi "prezzo: 30".
_PRICE_PATTERNS = [
    re.compile(rf"(?:€|\beur(?:o|i)?\b)\s*({_NUM})", re.IGNORECASE),
    re.compile(rf"({_NUM})\s*(?:€|\beur(?:o|i)?\b)", re.IGNORECASE),
    re.compile(rf"\b(?:prezzo|price|costo)\b\s*[:\-=]?\s*({_NUM})", re.IGNORECASE),
]


def normalize(text: str) -> str:
    """Minuscolo, senza accenti, spazi compattati."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def _to_float(raw: str) -> Optional[float]:
    raw = raw.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", raw):
        # 1.200 o 1.200,50 -> separatore delle migliaia italiano
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_price(text: str) -> Optional[float]:
    """Restituisce il primo prezzo trovato nel testo, o None."""
    if not text:
        return None
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(text):
            value = _to_float(match.group(1))
            if value is not None and value > 0:
                return value
    return None


def split_terms(value: str) -> list[str]:
    """'nike, air max ,  ' -> ['nike', 'air max']"""
    return [normalize(t) for t in (value or "").split(",") if normalize(t)]


def _contains(haystack: str, term: str) -> bool:
    # Confini di parola, così "air" non trova "chair".
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", haystack) is not None


@dataclass
class Rule:
    id: int
    name: str
    keywords: str = ""
    exclude: str = ""
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    require_price: bool = False
    group_ids: Optional[list[int]] = None  # None = tutti i gruppi


@dataclass
class MatchResult:
    matched: bool
    price: Optional[float]
    reason: str = ""


def match_rule(rule: Rule, text: str, group_id: Optional[int] = None,
               price: Optional[float] = None) -> MatchResult:
    """Verifica se un post soddisfa una regola.

    `price` può essere passato se già calcolato; altrimenti viene letto dal testo.
    """
    if rule.group_ids and group_id is not None and group_id not in rule.group_ids:
        return MatchResult(False, price, "gruppo non incluso")

    norm = normalize(text)
    keywords = split_terms(rule.keywords)
    if keywords and not any(_contains(norm, k) for k in keywords):
        return MatchResult(False, price, "nessuna parola chiave")

    for term in split_terms(rule.exclude):
        if _contains(norm, term):
            return MatchResult(False, price, f"contiene '{term}'")

    if price is None:
        price = parse_price(text)

    has_price_filter = rule.min_price is not None or rule.max_price is not None
    if price is None:
        if rule.require_price:
            return MatchResult(False, None, "prezzo non trovato")
        return MatchResult(True, None, "prezzo non trovato" if has_price_filter else "")

    if rule.min_price is not None and price < rule.min_price:
        return MatchResult(False, price, "prezzo sotto il minimo")
    if rule.max_price is not None and price > rule.max_price:
        return MatchResult(False, price, "prezzo sopra il massimo")
    return MatchResult(True, price)

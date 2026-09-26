import pytest

from app.filters import Rule, match_rule, normalize, parse_price


@pytest.mark.parametrize("text, expected", [
    ("Vendo a 45€", 45.0),
    ("prezzo 45 €", 45.0),
    ("€ 12,50 trattabili", 12.5),
    ("€12.5", 12.5),
    ("costa 30 euro", 30.0),
    ("1.200€ non trattabili", 1200.0),
    ("1.200,50 €", 1200.5),
    ("Prezzo: 80", 80.0),
    ("EUR 99", 99.0),
    ("taglia 43, usate", None),
    ("iPhone 13 128GB", None),
    ("", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_normalize_strips_accents_and_case():
    assert normalize("  Città   PERCHÉ ") == "citta perche"


def rule(**kw):
    return Rule(id=1, name="r", **kw)


def test_keyword_any_match_is_case_and_accent_insensitive():
    assert match_rule(rule(keywords="nike, adidas"), "Vendo NIKE air").matched
    assert match_rule(rule(keywords="citta studi"), "Zona Città Studi").matched
    assert not match_rule(rule(keywords="nike"), "Vendo Puma").matched


def test_keyword_needs_word_boundary():
    assert not match_rule(rule(keywords="air"), "vendo chair da ufficio").matched
    assert match_rule(rule(keywords="air max"), "Nike Air Max 90").matched


def test_exclude_words_reject_post():
    r = rule(keywords="nike", exclude="cerco, rotte")
    assert not match_rule(r, "Cerco Nike 43").matched
    assert match_rule(r, "Vendo Nike 43").matched


def test_price_range():
    r = rule(keywords="nike", max_price=50)
    ok = match_rule(r, "Nike 45€")
    assert ok.matched and ok.price == 45
    assert not match_rule(r, "Nike 60€").matched
    assert not match_rule(rule(keywords="nike", min_price=20), "Nike 10€").matched


def test_missing_price_passes_unless_required():
    assert match_rule(rule(keywords="nike", max_price=50), "Nike nuove").matched
    assert not match_rule(rule(keywords="nike", max_price=50, require_price=True), "Nike nuove").matched


def test_explicit_price_overrides_text():
    assert match_rule(rule(keywords="jordan", max_price=150), "Jordan 1", price=120).matched
    assert not match_rule(rule(keywords="jordan", max_price=100), "Jordan 1", price=120).matched


def test_price_only_rule_without_keywords():
    assert match_rule(rule(max_price=20), "Qualsiasi cosa a 15€").matched


def test_group_restriction():
    r = rule(keywords="nike", group_ids=[2])
    assert not match_rule(r, "Nike", group_id=1).matched
    assert match_rule(r, "Nike", group_id=2).matched

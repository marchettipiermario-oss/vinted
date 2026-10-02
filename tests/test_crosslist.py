import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import crosslist  # noqa: E402

LISTING = {
    "title": "Giacca di jeans Levi's Trucker vintage anni 90 lavaggio chiaro ottime condizioni taglia M uomo",
    "description": "Giacca usata poche volte.\nNessun difetto.",
    "price": 45.0,
    "currency": "EUR",
    "brand": "Levi's",
    "size": "M",
    "condition": "very_good",
    "quantity": 1,
    "price_overrides": {"ebay": 49.9},
    "ebay_category_id": "57988",
    "vinted_catalog_id": 1203,
    "vinted_brand_id": 10,
    "vinted_size_id": 207,
    "vinted_package_size_id": 2,
}

CFG = {
    "marketplace_id": "EBAY_IT",
    "merchant_location_key": "casa",
    "fulfillment_policy_id": "F1",
    "payment_policy_id": "P1",
    "return_policy_id": "R1",
    "client_id": "cid",
    "client_secret": "secret",
    "refresh_token": "rt",
}


def test_truncate_title_cuts_on_word_boundary():
    t = crosslist.truncate_title(LISTING["title"], 50)
    assert len(t) <= 50
    assert LISTING["title"].startswith(t)
    assert not t.endswith(" ")
    assert LISTING["title"][len(t)] == " "


def test_truncate_title_keeps_short_titles():
    assert crosslist.truncate_title("  Borsa   Gucci ", 50) == "Borsa Gucci"


def test_format_for_platforms():
    for p, limit in crosslist.TITLE_LIMITS.items():
        f = crosslist.format_for(LISTING, p)
        assert len(f["title"]) <= limit
    assert crosslist.format_for(LISTING, "ebay")["price"] == 49.9
    assert crosslist.format_for(LISTING, "subito")["price"] == 45.0
    assert "Marca: Levi's" in crosslist.format_for(LISTING, "subito")["description"]
    assert "Marca" not in crosslist.format_for(LISTING, "vinted")["description"]


def test_ebay_payloads():
    item = crosslist.build_ebay_inventory_item(LISTING, ["https://x/1.jpg"])
    assert item["condition"] == "USED_VERY_GOOD"
    assert item["product"]["aspects"] == {"Marca": ["Levi's"], "Taglia": ["M"]}
    assert "<br>" in item["product"]["description"]
    assert "&#x27;" in item["product"]["description"]
    offer = crosslist.build_ebay_offer(LISTING, "SKU1", CFG)
    assert offer["pricingSummary"]["price"] == {"value": "49.90", "currency": "EUR"}
    assert offer["categoryId"] == "57988"
    assert offer["listingPolicies"]["returnPolicyId"] == "R1"


def test_vinted_payload():
    body = crosslist.build_vinted_item(LISTING, [11, 12], "tmp")
    item = body["item"]
    assert item["status_id"] == 2
    assert item["catalog_id"] == 1203
    assert item["assigned_photos"] == [{"id": 11, "orientation": 0}, {"id": 12, "orientation": 0}]


def test_ebay_missing_config():
    assert crosslist.ebay_missing_config(CFG, LISTING) == []
    missing = crosslist.ebay_missing_config({}, {})
    assert "token OAuth" in missing and "categoria eBay" in missing


def _ebay_transport(calls, offer_exists=False):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        path = req.url.path
        if path == "/identity/v1/oauth2/token":
            assert b"grant_type=refresh_token" in req.content
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 7200})
        assert req.headers["Authorization"] == "Bearer AT"
        if path.startswith("/sell/inventory/v1/inventory_item/"):
            urls = json.loads(req.content)["product"]["imageUrls"]
            assert urls and all(u.startswith("https://") for u in urls)
            return httpx.Response(204)
        if path == "/sell/inventory/v1/offer" and req.method == "POST":
            if offer_exists:
                return httpx.Response(400, json={"errors": [{"errorId": 25002, "message": "Offer entity already exists"}]})
            return httpx.Response(201, json={"offerId": "O1"})
        if path == "/sell/inventory/v1/offer" and req.method == "GET":
            return httpx.Response(200, json={"offers": [{"offerId": "O9"}]})
        if path == "/sell/inventory/v1/offer/O9" and req.method == "PUT":
            return httpx.Response(204)
        if path.endswith("/publish"):
            return httpx.Response(200, json={"listingId": "123456"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_ebay_publish_refreshes_token_and_publishes():
    calls = []
    cl = crosslist.EbayClient(dict(CFG), transport=_ebay_transport(calls))
    res = asyncio.run(cl.publish(LISTING, "SKU1", ["https://x/1.jpg"]))
    assert res == {"offer_id": "O1", "listing_id": "123456", "url": "https://www.ebay.it/itm/123456"}
    assert calls[0] == ("POST", "/identity/v1/oauth2/token")
    assert cl.token_updates["access_token"] == "AT"
    # the refreshed token is reused, not refreshed again per request
    assert sum(1 for c in calls if c[1] == "/identity/v1/oauth2/token") == 1


def test_ebay_publish_reuses_existing_offer():
    calls = []
    cl = crosslist.EbayClient(dict(CFG), transport=_ebay_transport(calls, offer_exists=True))
    res = asyncio.run(cl.publish(LISTING, "SKU1", ["https://x/1.jpg"]))
    assert res["offer_id"] == "O9"
    assert ("PUT", "/sell/inventory/v1/offer/O9") in calls


def test_ebay_publish_reports_api_error():
    def handler(req):
        if req.url.path == "/identity/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 7200})
        return httpx.Response(400, json={"errors": [{"message": "x", "longMessage": "Categoria non valida"}]})
    cl = crosslist.EbayClient(dict(CFG), transport=httpx.MockTransport(handler))
    try:
        asyncio.run(cl.publish(LISTING, "SKU1", []))
        raise AssertionError("expected EbayError")
    except crosslist.EbayError as e:
        assert "Categoria non valida" in str(e)


# -----------------------------------------------------------------------------
# Router flow (in-memory Mongo)
# -----------------------------------------------------------------------------
def test_router_full_flow(tmp_path, monkeypatch):
    import pytest
    mm = pytest.importorskip("mongomock_motor")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(crosslist, "UPLOAD_DIR", tmp_path)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://bot.example.com")
    user_id = "a" * 24

    async def current_user():
        return {"id": user_id}

    async def vinted_client(_uid):
        return object()

    vinted_calls = []
    monkeypatch.setattr(crosslist, "vinted_publish_sync",
                        lambda client, listing, paths: vinted_calls.append(paths) or {"item_id": 777, "url": "https://www.vinted.it/items/777"})
    monkeypatch.setattr(crosslist, "vinted_delete_sync", lambda client, item_id: vinted_calls.append(("del", item_id)))

    ebay_calls = []
    base_transport = _ebay_transport(ebay_calls)

    def handler(req):
        if req.url.path.endswith("/withdraw"):
            ebay_calls.append(("POST", req.url.path))
            return httpx.Response(200, json={})
        return base_transport.handle_request(req)

    db = mm.AsyncMongoMockClient()["t"]
    app = FastAPI()
    app.include_router(crosslist.build_router(db, current_user, vinted_client, ebay_transport=httpx.MockTransport(handler)))
    c = TestClient(app)

    assert c.put("/crosslist/ebay/config", json={**CFG}).json() == {"ok": True}
    cfg = c.get("/crosslist/ebay/config").json()
    assert cfg["client_secret"] == "" and cfg["has_client_secret"] is True

    photos = c.post("/crosslist/photos", files=[("files", ("a.jpg", b"\xff\xd8jpeg", "image/jpeg"))]).json()
    assert photos[0]["url"].startswith("https://bot.example.com/api/crosslist/photos/")
    assert c.get(f"/crosslist/photos/{user_id}/{photos[0]['id']}").content == b"\xff\xd8jpeg"
    assert c.get(f"/crosslist/photos/{user_id}/..%2Fx.jpg").status_code == 404

    body = {k: v for k, v in LISTING.items()}
    body["photos"] = [photos[0]["id"]]
    lst = c.post("/crosslist/listings", json=body).json()
    lid = lst["id"]

    r = c.post(f"/crosslist/listings/{lid}/publish", json={"platforms": ["ebay", "vinted", "subito", "facebook"]}).json()
    assert r["results"]["ebay"]["status"] == "published", r
    assert r["results"]["ebay"]["offer_id"] == "O1"
    assert r["results"]["vinted"]["external_id"] == 777
    assert r["results"]["subito"]["status"] == "manual_pending"
    assert c.get("/crosslist/ebay/config").json()["has_access_token"] is True  # refreshed token persisted

    # publishing again skips platforms already live
    r2 = c.post(f"/crosslist/listings/{lid}/publish", json={"platforms": ["ebay"]}).json()
    assert r2["results"] == {}

    a = c.get(f"/crosslist/listings/{lid}/assist/subito").json()
    assert len(a["title"]) <= 50 and a["post_url"].startswith("https://www.subito.it")

    c.post(f"/crosslist/listings/{lid}/platforms/subito/mark", json={"status": "published", "url": "https://subito.it/x"})
    s = c.post(f"/crosslist/listings/{lid}/sold", json={"sold_on": "subito"}).json()
    assert s["ended"]["ebay"]["status"] == "ended"
    assert s["ended"]["vinted"]["status"] == "ended"
    assert s["ended"]["facebook"]["status"] == "remove_manually"
    assert ("POST", "/sell/inventory/v1/offer/O1/withdraw") in ebay_calls
    assert ("del", 777) in vinted_calls
    final = c.get(f"/crosslist/listings/{lid}").json()
    assert final["status"] == "sold" and final["platforms"]["subito"]["status"] == "sold"
    assert c.post(f"/crosslist/listings/{lid}/publish", json={"platforms": ["ebay"]}).status_code == 400

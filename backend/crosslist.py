"""Crosslisting: one listing, published on Vinted, eBay, Subito and Facebook Marketplace.

Channel support differs because the platforms differ:
- eBay       → automatic, via the official Sell Inventory API (OAuth user token).
- Vinted     → automatic, via the same unofficial web API the autobuy feature uses
               (session cookie from Settings). Experimental: it can break whenever
               Vinted changes its private endpoints.
- Subito     → assisted: no public API exists, so we generate ready-to-paste text
- Facebook     and open the platform's "new listing" page; the user marks it published.

The router is built by `build_router(...)` so this module does not import server.py.
"""
import asyncio
import html
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

import httpx
from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("vintedbot.crosslist")

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", Path(__file__).parent / "uploads"))
MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}

PLATFORMS = ("vinted", "ebay", "subito", "facebook")
AUTO_PLATFORMS = ("vinted", "ebay")
ASSISTED_PLATFORMS = ("subito", "facebook")

# Title limits. eBay's 80 is documented; the others are conservative values
# that stay under each site's form limit.
TITLE_LIMITS = {"ebay": 80, "vinted": 100, "subito": 50, "facebook": 100}

POST_URLS = {
    "subito": "https://www.subito.it/inserisci-annuncio",
    "facebook": "https://www.facebook.com/marketplace/create/item",
}

Condition = Literal["new_with_tags", "new_without_tags", "very_good", "good", "satisfactory"]

CONDITION_LABELS_IT = {
    "new_with_tags": "Nuovo con cartellino",
    "new_without_tags": "Nuovo senza cartellino",
    "very_good": "Ottime condizioni",
    "good": "Buone condizioni",
    "satisfactory": "Discrete condizioni",
}
EBAY_CONDITIONS = {
    "new_with_tags": "NEW",
    "new_without_tags": "NEW_OTHER",
    "very_good": "USED_VERY_GOOD",
    "good": "USED_GOOD",
    "satisfactory": "USED_ACCEPTABLE",
}
VINTED_STATUS_IDS = {
    "new_with_tags": 6,
    "new_without_tags": 1,
    "very_good": 2,
    "good": 3,
    "satisfactory": 4,
}

EBAY_SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
])


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class ListingIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    price: float = Field(gt=0)
    currency: str = "EUR"
    brand: str = ""
    size: str = ""
    condition: Condition = "very_good"
    quantity: int = Field(default=1, ge=1)
    location: str = ""
    photos: List[str] = []
    price_overrides: Dict[str, float] = {}
    # platform-specific fields
    ebay_category_id: str = ""
    vinted_catalog_id: Optional[int] = None
    vinted_brand_id: Optional[int] = None
    vinted_size_id: Optional[int] = None
    vinted_package_size_id: Optional[int] = None
    subito_category: str = ""
    facebook_category: str = ""


class PublishIn(BaseModel):
    platforms: List[Literal["vinted", "ebay", "subito", "facebook"]]


class MarkIn(BaseModel):
    status: Literal["published", "ended", "sold"]
    url: str = ""


class SoldIn(BaseModel):
    sold_on: Literal["vinted", "ebay", "subito", "facebook", "other"]


class EbayConfigIn(BaseModel):
    sandbox: bool = False
    marketplace_id: str = "EBAY_IT"
    content_language: str = "it-IT"
    client_id: str = ""
    client_secret: str = ""   # empty = keep stored value
    refresh_token: str = ""   # empty = keep stored value
    access_token: str = ""    # empty = keep stored value
    merchant_location_key: str = ""
    fulfillment_policy_id: str = ""
    payment_policy_id: str = ""
    return_policy_id: str = ""
    default_category_id: str = ""


# -----------------------------------------------------------------------------
# Pure helpers (unit-tested)
# -----------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate_title(title: str, limit: int) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    if len(title) <= limit:
        return title
    cut = title[:limit].rstrip()
    space = cut.rfind(" ")
    return cut[:space] if space >= limit * 0.6 else cut


def price_for(listing: dict, platform: str) -> float:
    override = (listing.get("price_overrides") or {}).get(platform)
    return round(float(override if override else listing["price"]), 2)


def details_lines(listing: dict) -> List[str]:
    lines = []
    if listing.get("brand"):
        lines.append(f"Marca: {listing['brand']}")
    if listing.get("size"):
        lines.append(f"Taglia: {listing['size']}")
    lines.append(f"Condizioni: {CONDITION_LABELS_IT.get(listing.get('condition'), '')}")
    return lines


def format_for(listing: dict, platform: str) -> Dict[str, Any]:
    """Platform-ready title/description/price for a listing."""
    title = truncate_title(listing["title"], TITLE_LIMITS[platform])
    desc = (listing.get("description") or "").strip()
    if platform == "vinted":
        # Vinted shows brand/size/condition as structured fields already.
        description = desc
    else:
        description = "\n\n".join(p for p in [desc, "\n".join(details_lines(listing))] if p)
    return {
        "title": title,
        "description": description,
        "price": price_for(listing, platform),
        "currency": listing.get("currency", "EUR"),
        "condition": CONDITION_LABELS_IT.get(listing.get("condition"), ""),
    }


def ebay_description_html(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def build_ebay_inventory_item(listing: dict, image_urls: List[str]) -> dict:
    f = format_for(listing, "ebay")
    aspects: Dict[str, List[str]] = {}
    if listing.get("brand"):
        aspects["Marca"] = [listing["brand"]]
    if listing.get("size"):
        aspects["Taglia"] = [listing["size"]]
    product: Dict[str, Any] = {
        "title": f["title"],
        "description": ebay_description_html(f["description"]),
        "imageUrls": image_urls,
    }
    if aspects:
        product["aspects"] = aspects
    return {
        "availability": {"shipToLocationAvailability": {"quantity": int(listing.get("quantity", 1))}},
        "condition": EBAY_CONDITIONS[listing.get("condition", "very_good")],
        "product": product,
    }


def build_ebay_offer(listing: dict, sku: str, cfg: dict) -> dict:
    f = format_for(listing, "ebay")
    return {
        "sku": sku,
        "marketplaceId": cfg.get("marketplace_id") or "EBAY_IT",
        "format": "FIXED_PRICE",
        "availableQuantity": int(listing.get("quantity", 1)),
        "categoryId": listing.get("ebay_category_id") or cfg.get("default_category_id"),
        "listingDescription": ebay_description_html(f["description"]),
        "listingPolicies": {
            "fulfillmentPolicyId": cfg.get("fulfillment_policy_id"),
            "paymentPolicyId": cfg.get("payment_policy_id"),
            "returnPolicyId": cfg.get("return_policy_id"),
        },
        "pricingSummary": {"price": {"value": f"{f['price']:.2f}", "currency": f["currency"]}},
        "merchantLocationKey": cfg.get("merchant_location_key"),
    }


def build_vinted_item(listing: dict, photo_ids: List[int], temp_uuid: str) -> dict:
    f = format_for(listing, "vinted")
    return {
        "item": {
            "id": None,
            "currency": f["currency"],
            "temp_uuid": temp_uuid,
            "title": f["title"],
            "description": f["description"],
            "brand_id": listing.get("vinted_brand_id"),
            "brand": listing.get("brand") or None,
            "size_id": listing.get("vinted_size_id"),
            "catalog_id": listing.get("vinted_catalog_id"),
            "isbn": None,
            "is_unisex": False,
            "status_id": VINTED_STATUS_IDS[listing.get("condition", "very_good")],
            "price": f["price"],
            "package_size_id": listing.get("vinted_package_size_id"),
            "shipment_prices": {"domestic": None, "international": None},
            "color_ids": [],
            "assigned_photos": [{"id": pid, "orientation": 0} for pid in photo_ids],
            "item_attributes": [],
        },
        "feedback_id": None,
        "push_up": False,
        "parcel": None,
        "upload_session_id": temp_uuid,
    }


def ebay_missing_config(cfg: dict, listing: dict) -> List[str]:
    missing = []
    if not (cfg.get("access_token") or cfg.get("refresh_token")):
        missing.append("token OAuth")
    for key, label in [
        ("merchant_location_key", "merchant location key"),
        ("fulfillment_policy_id", "fulfillment policy"),
        ("payment_policy_id", "payment policy"),
        ("return_policy_id", "return policy"),
    ]:
        if not cfg.get(key):
            missing.append(label)
    if not (listing.get("ebay_category_id") or cfg.get("default_category_id")):
        missing.append("categoria eBay")
    return missing


# -----------------------------------------------------------------------------
# eBay client (official Sell Inventory API)
# -----------------------------------------------------------------------------
class EbayError(Exception):
    pass


class EbayClient:
    def __init__(self, cfg: dict, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.cfg = cfg
        self.base = "https://api.sandbox.ebay.com" if cfg.get("sandbox") else "https://api.ebay.com"
        self.transport = transport
        self.token_updates: Dict[str, Any] = {}  # caller persists these after a refresh

    def _token_valid(self) -> bool:
        tok = self.cfg.get("access_token")
        exp = self.cfg.get("access_token_expires_at")
        if not tok:
            return False
        if not exp:
            return True  # manually pasted token, expiry unknown
        try:
            return datetime.fromisoformat(exp) > datetime.now(timezone.utc) + timedelta(seconds=60)
        except ValueError:
            return True

    async def _access_token(self, http: httpx.AsyncClient) -> str:
        if self._token_valid():
            return self.cfg["access_token"]
        if not (self.cfg.get("refresh_token") and self.cfg.get("client_id") and self.cfg.get("client_secret")):
            if self.cfg.get("access_token"):
                return self.cfg["access_token"]
            raise EbayError("Token eBay mancante: configura access token o refresh token + client id/secret")
        r = await http.post(
            f"{self.base}/identity/v1/oauth2/token",
            auth=(self.cfg["client_id"], self.cfg["client_secret"]),
            data={"grant_type": "refresh_token", "refresh_token": self.cfg["refresh_token"], "scope": EBAY_SCOPES},
        )
        if r.status_code != 200:
            raise EbayError(f"Refresh token eBay fallito ({r.status_code}): {r.text[:200]}")
        data = r.json()
        expires = datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 7200)))
        self.cfg["access_token"] = data["access_token"]
        self.cfg["access_token_expires_at"] = expires.isoformat()
        self.token_updates = {"access_token": data["access_token"], "access_token_expires_at": expires.isoformat()}
        return data["access_token"]

    async def _request(self, http: httpx.AsyncClient, method: str, path: str, **kw) -> httpx.Response:
        token = await self._access_token(http)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Language": self.cfg.get("content_language") or "it-IT",
            "Accept-Language": self.cfg.get("content_language") or "it-IT",
        }
        return await http.request(method, f"{self.base}{path}", headers=headers, **kw)

    @staticmethod
    def _err(r: httpx.Response) -> str:
        try:
            errs = r.json().get("errors") or []
            if errs:
                return "; ".join(e.get("longMessage") or e.get("message", "") for e in errs)
        except Exception:
            pass
        return f"HTTP {r.status_code}: {r.text[:300]}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30, transport=self.transport)

    async def publish(self, listing: dict, sku: str, image_urls: List[str]) -> Dict[str, Any]:
        async with self._client() as http:
            r = await self._request(http, "PUT", f"/sell/inventory/v1/inventory_item/{sku}",
                                    json=build_ebay_inventory_item(listing, image_urls))
            if r.status_code not in (200, 201, 204):
                raise EbayError(f"inventory_item: {self._err(r)}")

            offer_body = build_ebay_offer(listing, sku, self.cfg)
            r = await self._request(http, "POST", "/sell/inventory/v1/offer", json=offer_body)
            if r.status_code in (200, 201):
                offer_id = r.json()["offerId"]
            else:
                # An offer for this SKU may already exist (re-publish): reuse and update it.
                g = await self._request(http, "GET", "/sell/inventory/v1/offer",
                                        params={"sku": sku, "marketplace_id": offer_body["marketplaceId"]})
                offers = g.json().get("offers", []) if g.status_code == 200 else []
                if not offers:
                    raise EbayError(f"offer: {self._err(r)}")
                offer_id = offers[0]["offerId"]
                u = await self._request(http, "PUT", f"/sell/inventory/v1/offer/{offer_id}", json=offer_body)
                if u.status_code not in (200, 204):
                    raise EbayError(f"offer update: {self._err(u)}")

            r = await self._request(http, "POST", f"/sell/inventory/v1/offer/{offer_id}/publish")
            if r.status_code != 200:
                raise EbayError(f"publish: {self._err(r)}")
            listing_id = r.json().get("listingId")
            domain = "sandbox.ebay.com" if self.cfg.get("sandbox") else "www.ebay.it"
            return {"offer_id": offer_id, "listing_id": listing_id, "url": f"https://{domain}/itm/{listing_id}"}

    async def withdraw(self, offer_id: str) -> None:
        async with self._client() as http:
            r = await self._request(http, "POST", f"/sell/inventory/v1/offer/{offer_id}/withdraw")
            if r.status_code != 200:
                raise EbayError(f"withdraw: {self._err(r)}")

    async def policies(self) -> Dict[str, Any]:
        mk = self.cfg.get("marketplace_id") or "EBAY_IT"
        out: Dict[str, Any] = {}
        async with self._client() as http:
            for kind, key in [("fulfillment_policy", "fulfillmentPolicies"),
                              ("payment_policy", "paymentPolicies"),
                              ("return_policy", "returnPolicies")]:
                r = await self._request(http, "GET", f"/sell/account/v1/{kind}", params={"marketplace_id": mk})
                if r.status_code != 200:
                    raise EbayError(f"{kind}: {self._err(r)}")
                id_key = kind.split("_")[0] + "PolicyId"
                out[kind] = [{"id": p.get(id_key), "name": p.get("name")} for p in r.json().get(key, [])]
            r = await self._request(http, "GET", "/sell/inventory/v1/location")
            out["locations"] = ([{"key": l.get("merchantLocationKey"), "name": l.get("name")}
                                 for l in r.json().get("locations", [])] if r.status_code == 200 else [])
        return out


# -----------------------------------------------------------------------------
# Vinted upload (unofficial web API, same session as autobuy)
# -----------------------------------------------------------------------------
def vinted_publish_sync(client, listing: dict, photo_paths: List[Path]) -> Dict[str, Any]:
    from curl_cffi import CurlMime

    if not client.cookie:
        raise RuntimeError("Cookie di sessione Vinted non configurato (Settings)")
    csrf = client.refresh_csrf(force=False)
    if not csrf:
        raise RuntimeError("CSRF token Vinted non disponibile: sessione scaduta?")
    base = f"https://{client.domain}"
    temp_uuid = str(uuid.uuid4())
    photo_ids: List[int] = []
    for p in photo_paths:
        mp = CurlMime()
        mp.addpart(name="photo[type]", data=b"item")
        mp.addpart(name="photo[temp_uuid]", data=temp_uuid.encode())
        mp.addpart(name="photo[file]", filename=p.name, content_type=_content_type(p), local_path=str(p))
        try:
            r = client.session.post(f"{base}/api/v2/photos", multipart=mp, headers={"X-Csrf-Token": csrf}, timeout=30)
        finally:
            mp.close()
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Upload foto Vinted fallito ({r.status_code}): {r.text[:200]}")
        photo_ids.append(r.json()["id"])

    r = client.session.post(
        f"{base}/api/v2/item_upload/items",
        json=build_vinted_item(listing, photo_ids, temp_uuid),
        headers={"X-Csrf-Token": csrf, "Content-Type": "application/json"},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Creazione annuncio Vinted fallita ({r.status_code}): {r.text[:300]}")
    item = r.json().get("item") or {}
    item_id = item.get("id")
    url = item.get("url") or (f"{base}/items/{item_id}" if item_id else "")
    if url.startswith("/"):
        url = base + url
    return {"item_id": item_id, "url": url}


def vinted_delete_sync(client, item_id: Any) -> None:
    csrf = client.refresh_csrf(force=False)
    r = client.session.post(f"https://{client.domain}/api/v2/items/{item_id}/delete",
                            headers={"X-Csrf-Token": csrf or ""}, timeout=20)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Rimozione Vinted fallita ({r.status_code}): {r.text[:200]}")


def _content_type(p: Path) -> str:
    return {".png": "image/png", ".webp": "image/webp"}.get(p.suffix.lower(), "image/jpeg")


# -----------------------------------------------------------------------------
# Router
# -----------------------------------------------------------------------------
def build_router(db, get_current_user: Callable, get_vinted_client: Callable,
                 ebay_transport: Optional[httpx.AsyncBaseTransport] = None) -> APIRouter:
    router = APIRouter(prefix="/crosslist")

    def public_base() -> str:
        return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

    def photo_url(user_id: str, name: str) -> str:
        return f"{public_base()}/api/crosslist/photos/{user_id}/{name}"

    def photo_path(user_id: str, name: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|jpeg|png|webp)", name) or not re.fullmatch(r"[0-9a-f]{24}", user_id):
            raise HTTPException(status_code=404, detail="Not found")
        return UPLOAD_DIR / user_id / name

    async def load(listing_id: str, user: dict) -> dict:
        try:
            oid = ObjectId(listing_id)
        except Exception:
            raise HTTPException(status_code=404, detail="Not found")
        d = await db.listings.find_one({"_id": oid, "user_id": user["id"]})
        if not d:
            raise HTTPException(status_code=404, detail="Not found")
        return d

    def to_out(d: dict) -> dict:
        res = {k: v for k, v in d.items() if k not in ("_id", "user_id")}
        res["id"] = str(d["_id"])
        res["photo_urls"] = [photo_url(d["user_id"], p) for p in d.get("photos", [])]
        return res

    async def set_platform(d: dict, platform: str, state: dict) -> None:
        state = {**(d.get("platforms", {}).get(platform) or {}), **state, "updated_at": now_iso()}
        d.setdefault("platforms", {})[platform] = state
        await db.listings.update_one({"_id": d["_id"]}, {"$set": {f"platforms.{platform}": state}})

    async def ebay_cfg(user_id: str) -> dict:
        return await db.ebay_configs.find_one({"user_id": user_id}) or {}

    async def ebay_client(user_id: str) -> EbayClient:
        return EbayClient(dict(await ebay_cfg(user_id)), transport=ebay_transport)

    async def persist_tokens(user_id: str, cl: EbayClient) -> None:
        if cl.token_updates:
            await db.ebay_configs.update_one({"user_id": user_id}, {"$set": cl.token_updates})

    # ---- photos -------------------------------------------------------------
    @router.post("/photos")
    async def upload_photos(files: List[UploadFile] = File(...), user: dict = Depends(get_current_user)):
        folder = UPLOAD_DIR / user["id"]
        folder.mkdir(parents=True, exist_ok=True)
        saved = []
        for f in files:
            ext = Path(f.filename or "").suffix.lower()
            if ext not in ALLOWED_PHOTO_EXT:
                raise HTTPException(status_code=400, detail=f"Formato non supportato: {f.filename}")
            data = await f.read()
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(status_code=400, detail=f"Foto troppo grande: {f.filename}")
            name = f"{uuid.uuid4().hex}{ext}"
            (folder / name).write_bytes(data)
            saved.append({"id": name, "url": photo_url(user["id"], name)})
        return saved

    # Public on purpose: eBay fetches images from these URLs. Names are random UUIDs.
    @router.get("/photos/{user_id}/{name}")
    async def get_photo(user_id: str, name: str):
        p = photo_path(user_id, name)
        if not p.exists():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(p)

    # ---- listings CRUD ------------------------------------------------------
    @router.get("/listings")
    async def list_listings(user: dict = Depends(get_current_user)):
        cur = db.listings.find({"user_id": user["id"]}).sort("created_at", -1)
        return [to_out(d) async for d in cur]

    @router.post("/listings")
    async def create_listing(payload: ListingIn, user: dict = Depends(get_current_user)):
        doc = payload.model_dump()
        doc.update({"user_id": user["id"], "created_at": now_iso(), "status": "active", "platforms": {}})
        doc["sku"] = f"VB-{uuid.uuid4().hex[:12].upper()}"
        res = await db.listings.insert_one(doc)
        doc["_id"] = res.inserted_id
        return to_out(doc)

    @router.get("/listings/{listing_id}")
    async def get_listing(listing_id: str, user: dict = Depends(get_current_user)):
        return to_out(await load(listing_id, user))

    @router.put("/listings/{listing_id}")
    async def update_listing(listing_id: str, payload: ListingIn, user: dict = Depends(get_current_user)):
        d = await load(listing_id, user)
        await db.listings.update_one({"_id": d["_id"]}, {"$set": {**payload.model_dump(), "updated_at": now_iso()}})
        return to_out(await load(listing_id, user))

    @router.delete("/listings/{listing_id}")
    async def delete_listing(listing_id: str, user: dict = Depends(get_current_user)):
        d = await load(listing_id, user)
        await db.listings.delete_one({"_id": d["_id"]})
        return {"ok": True}

    # ---- publishing ---------------------------------------------------------
    async def publish_ebay(d: dict, user_id: str) -> dict:
        cl = await ebay_client(user_id)
        missing = ebay_missing_config(cl.cfg, d)
        if missing:
            return {"status": "error", "error": "Configurazione eBay incompleta: " + ", ".join(missing)}
        if not public_base():
            return {"status": "error", "error": "PUBLIC_BASE_URL non impostato: eBay deve poter scaricare le foto"}
        if not d.get("photos"):
            return {"status": "error", "error": "eBay richiede almeno una foto"}
        try:
            res = await cl.publish(d, d["sku"], [photo_url(user_id, p) for p in d["photos"]])
        except EbayError as e:
            return {"status": "error", "error": str(e)}
        finally:
            await persist_tokens(user_id, cl)
        return {"status": "published", "error": "", "external_id": res["listing_id"],
                "offer_id": res["offer_id"], "url": res["url"]}

    async def publish_vinted(d: dict, user_id: str) -> dict:
        if not d.get("vinted_catalog_id"):
            return {"status": "error", "error": "Serve la categoria Vinted (catalog_id)"}
        if not d.get("photos"):
            return {"status": "error", "error": "Vinted richiede almeno una foto"}
        client = await get_vinted_client(user_id)
        paths = [UPLOAD_DIR / user_id / p for p in d["photos"]]
        try:
            res = await asyncio.to_thread(vinted_publish_sync, client, d, paths)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        return {"status": "published", "error": "", "external_id": res["item_id"], "url": res["url"]}

    def assisted_state(platform: str) -> dict:
        return {"status": "manual_pending", "error": "", "post_url": POST_URLS[platform]}

    @router.post("/listings/{listing_id}/publish")
    async def publish(listing_id: str, payload: PublishIn, user: dict = Depends(get_current_user)):
        d = await load(listing_id, user)
        if d.get("status") == "sold":
            raise HTTPException(status_code=400, detail="Articolo già venduto")
        jobs: Dict[str, Any] = {}
        for p in dict.fromkeys(payload.platforms):
            current = (d.get("platforms") or {}).get(p) or {}
            if current.get("status") == "published":
                continue
            if p == "ebay":
                jobs[p] = publish_ebay(d, user["id"])
            elif p == "vinted":
                jobs[p] = publish_vinted(d, user["id"])
        results = dict(zip(jobs.keys(), await asyncio.gather(*jobs.values())))
        for p in payload.platforms:
            if p in ASSISTED_PLATFORMS and ((d.get("platforms") or {}).get(p) or {}).get("status") != "published":
                results[p] = assisted_state(p)
        for p, state in results.items():
            await set_platform(d, p, state)
        return {"results": results, "listing": to_out(d)}

    @router.get("/listings/{listing_id}/assist/{platform}")
    async def assist(listing_id: str, platform: str, user: dict = Depends(get_current_user)):
        if platform not in PLATFORMS:
            raise HTTPException(status_code=404, detail="Unknown platform")
        d = await load(listing_id, user)
        f = format_for(d, platform)
        category = d.get(f"{platform}_category") or ""
        return {**f, "category": category, "location": d.get("location", ""),
                "post_url": POST_URLS.get(platform, ""),
                "photo_urls": [photo_url(user["id"], p) for p in d.get("photos", [])]}

    @router.post("/listings/{listing_id}/platforms/{platform}/mark")
    async def mark(listing_id: str, platform: str, payload: MarkIn, user: dict = Depends(get_current_user)):
        if platform not in PLATFORMS:
            raise HTTPException(status_code=404, detail="Unknown platform")
        d = await load(listing_id, user)
        state: Dict[str, Any] = {"status": payload.status, "error": ""}
        if payload.url:
            state["url"] = payload.url
        await set_platform(d, platform, state)
        return to_out(d)

    @router.post("/listings/{listing_id}/sold")
    async def sold(listing_id: str, payload: SoldIn, user: dict = Depends(get_current_user)):
        """Mark sold and take the listing down everywhere else to avoid double sales."""
        d = await load(listing_id, user)
        ended: Dict[str, Any] = {}
        for p, state in (d.get("platforms") or {}).items():
            if p == payload.sold_on:
                await set_platform(d, p, {"status": "sold"})
                continue
            if state.get("status") not in ("published", "manual_pending"):
                continue
            try:
                if p == "ebay" and state.get("offer_id"):
                    cl = await ebay_client(user["id"])
                    try:
                        await cl.withdraw(state["offer_id"])
                    finally:
                        await persist_tokens(user["id"], cl)
                    ended[p] = {"status": "ended", "error": ""}
                elif p == "vinted" and state.get("external_id"):
                    client = await get_vinted_client(user["id"])
                    await asyncio.to_thread(vinted_delete_sync, client, state["external_id"])
                    ended[p] = {"status": "ended", "error": ""}
                else:
                    ended[p] = {"status": "remove_manually", "error": "Rimuovi l'annuncio a mano"}
            except Exception as e:
                ended[p] = {"status": "remove_manually", "error": f"Rimozione automatica fallita: {e}"}
            await set_platform(d, p, ended[p])
        await db.listings.update_one({"_id": d["_id"]},
                                     {"$set": {"status": "sold", "sold_on": payload.sold_on, "sold_at": now_iso()}})
        d.update({"status": "sold", "sold_on": payload.sold_on})
        return {"ended": ended, "listing": to_out(d)}

    # ---- eBay config --------------------------------------------------------
    SECRET_FIELDS = ("client_secret", "refresh_token", "access_token")

    @router.get("/ebay/config")
    async def get_ebay_config(user: dict = Depends(get_current_user)):
        cfg = await ebay_cfg(user["id"])
        res = EbayConfigIn().model_dump()
        res.update({k: cfg.get(k, res[k]) for k in res if k not in SECRET_FIELDS})
        for k in SECRET_FIELDS:
            res[k] = ""
            res[f"has_{k}"] = bool(cfg.get(k))
        res["public_base_url"] = public_base()
        return res

    @router.put("/ebay/config")
    async def put_ebay_config(payload: EbayConfigIn, user: dict = Depends(get_current_user)):
        data = payload.model_dump()
        for k in SECRET_FIELDS:
            if not data[k]:
                data.pop(k)
        if "access_token" in data:
            data["access_token_expires_at"] = None
        await db.ebay_configs.update_one({"user_id": user["id"]},
                                         {"$set": {**data, "user_id": user["id"], "updated_at": now_iso()}},
                                         upsert=True)
        return {"ok": True}

    @router.get("/ebay/policies")
    async def ebay_policies(user: dict = Depends(get_current_user)):
        cl = await ebay_client(user["id"])
        try:
            return await cl.policies()
        except EbayError as e:
            raise HTTPException(status_code=400, detail=str(e))
        finally:
            await persist_tokens(user["id"], cl)

    return router

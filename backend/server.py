from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import logging
import asyncio
import uuid
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import bcrypt
import jwt as pyjwt
import requests
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, status
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("vintedbot")

# -----------------------------------------------------------------------------
# Mongo
# -----------------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="Vinted Bot API")
api = APIRouter(prefix="/api")

JWT_ALGORITHM = "HS256"


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


# -----------------------------------------------------------------------------
# Password hashing
# -----------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# -----------------------------------------------------------------------------
# JWT helpers
# -----------------------------------------------------------------------------
def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        "type": "access",
    }
    return pyjwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return pyjwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=False, samesite="lax", max_age=12 * 3600, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=False, samesite="lax", max_age=7 * 24 * 3600, path="/")


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = pyjwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user["id"] = str(user["_id"])
        del user["_id"]
        user.pop("password_hash", None)
        return user
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: Optional[str] = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class VintedConfigIn(BaseModel):
    domain: str = Field(default="www.vinted.it", description="Vinted domain (www.vinted.it, www.vinted.fr, ...)")
    cookie: str = Field(default="", description="Full cookie header from logged-in Vinted browser session")
    user_agent: Optional[str] = None


class SavedSearchIn(BaseModel):
    name: str
    keyword: Optional[str] = ""
    brand_ids: Optional[str] = ""   # comma separated
    catalog_ids: Optional[str] = ""  # comma separated
    size_ids: Optional[str] = ""
    color_ids: Optional[str] = ""
    status_ids: Optional[str] = ""  # condition ids
    price_from: Optional[float] = None
    price_to: Optional[float] = None
    currency: Optional[str] = "EUR"
    order: Optional[str] = "newest_first"
    autobuy: bool = False
    max_autobuy_price: Optional[float] = None
    enabled: bool = True  # background worker pollserà solo se True
    polling_interval: int = Field(default=2, ge=2, le=60)  # seconds


class AutobuyIn(BaseModel):
    item_id: str


# -----------------------------------------------------------------------------
# Vinted Service
# -----------------------------------------------------------------------------
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class VintedClient:
    def __init__(self, domain: str, cookie: str = "", user_agent: Optional[str] = None):
        self.domain = (domain or "www.vinted.it").strip().replace("https://", "").replace("http://", "").rstrip("/")
        self.cookie = cookie or ""
        self.user_agent = user_agent or DEFAULT_UA
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
            "Referer": f"https://{self.domain}/",
        })
        if self.cookie:
            self.session.headers["Cookie"] = self.cookie
        self._csrf: Optional[str] = None

    def _bootstrap_guest(self) -> None:
        """If no cookie supplied, hit homepage to obtain guest cookies."""
        if self.cookie:
            return
        try:
            r = self.session.get(f"https://{self.domain}/", timeout=10)
            # try to extract CSRF token from HTML
            m = re.search(r'"CSRF_TOKEN":"([^"]+)"', r.text)
            if m:
                self._csrf = m.group(1)
        except Exception as e:
            logger.warning(f"Guest bootstrap failed: {e}")

    def search(self, params: Dict[str, Any], per_page: int = 24) -> List[Dict[str, Any]]:
        self._bootstrap_guest()
        url = f"https://{self.domain}/api/v2/catalog/items"
        query = {
            "page": 1,
            "per_page": per_page,
            "order": params.get("order") or "newest_first",
        }
        if params.get("keyword"):
            query["search_text"] = params["keyword"]
        if params.get("brand_ids"):
            query["brand_ids"] = params["brand_ids"]
        if params.get("catalog_ids"):
            query["catalog_ids"] = params["catalog_ids"]
        if params.get("size_ids"):
            query["size_ids"] = params["size_ids"]
        if params.get("color_ids"):
            query["color_ids"] = params["color_ids"]
        if params.get("status_ids"):
            query["status_ids"] = params["status_ids"]
        if params.get("price_from") is not None:
            query["price_from"] = params["price_from"]
        if params.get("price_to") is not None:
            query["price_to"] = params["price_to"]
        if params.get("currency"):
            query["currency"] = params["currency"]
        try:
            r = self.session.get(url, params=query, timeout=12)
            if r.status_code == 401 or r.status_code == 403:
                logger.warning(f"Vinted auth failed: {r.status_code}")
                return []
            r.raise_for_status()
            data = r.json()
            return data.get("items", []) or []
        except Exception as e:
            logger.error(f"Vinted search error: {e}")
            return []

    def buy(self, item_id: str) -> Dict[str, Any]:
        """Attempt to autobuy. Returns dict with success/url/message.
        Real autobuy requires logged-in cookies and CSRF tokens.
        We construct the checkout URL and POST the buy intent.
        """
        if not self.cookie:
            return {"success": False, "message": "Vinted session cookie not configured. Add it in Settings."}
        # Fetch CSRF from item page if not present
        try:
            page = self.session.get(f"https://{self.domain}/items/{item_id}", timeout=10)
            m = re.search(r'"CSRF_TOKEN":"([^"]+)"', page.text)
            if m:
                self._csrf = m.group(1)
        except Exception as e:
            return {"success": False, "message": f"Failed to load item page: {e}"}
        if not self._csrf:
            return {"success": False, "message": "CSRF token not found. Session may be invalid."}
        url = f"https://{self.domain}/api/v2/transactions"
        payload = {"transaction": {"item_id": int(item_id)}}
        headers = {"X-Csrf-Token": self._csrf, "Content-Type": "application/json"}
        try:
            r = self.session.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code in (200, 201):
                data = r.json()
                tx_id = data.get("transaction", {}).get("id") or data.get("id")
                checkout = f"https://{self.domain}/transaction/{tx_id}/checkout" if tx_id else None
                return {"success": True, "message": "Transaction created. Open checkout to confirm payment.", "checkout_url": checkout, "transaction_id": tx_id}
            return {"success": False, "message": f"Vinted returned {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"success": False, "message": f"Buy request failed: {e}"}


async def get_vinted_client(user_id: str) -> VintedClient:
    cfg = await db.vinted_configs.find_one({"user_id": user_id})
    if not cfg:
        return VintedClient(domain="www.vinted.it")
    return VintedClient(domain=cfg.get("domain", "www.vinted.it"), cookie=cfg.get("cookie", ""), user_agent=cfg.get("user_agent"))


# -----------------------------------------------------------------------------
# Auth Endpoints
# -----------------------------------------------------------------------------
@api.post("/auth/register")
async def register(payload: RegisterIn, response: Response):
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "email": email,
        "password_hash": hash_password(payload.password),
        "name": payload.name or email.split("@")[0],
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.users.insert_one(doc)
    uid = str(res.inserted_id)
    access = create_access_token(uid, email)
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    return {"id": uid, "email": email, "name": doc["name"], "role": "user", "access_token": access}


@api.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    uid = str(user["_id"])
    access = create_access_token(uid, email)
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    return {"id": uid, "email": email, "name": user.get("name", ""), "role": user.get("role", "user"), "access_token": access}


@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# -----------------------------------------------------------------------------
# Vinted Config Endpoints
# -----------------------------------------------------------------------------
@api.get("/vinted/config")
async def get_config(user: dict = Depends(get_current_user)):
    cfg = await db.vinted_configs.find_one({"user_id": user["id"]})
    if not cfg:
        return {"domain": "www.vinted.it", "cookie": "", "user_agent": "", "configured": False}
    return {
        "domain": cfg.get("domain", "www.vinted.it"),
        "cookie": cfg.get("cookie", ""),
        "user_agent": cfg.get("user_agent", ""),
        "configured": bool(cfg.get("cookie")),
    }


@api.put("/vinted/config")
async def update_config(payload: VintedConfigIn, user: dict = Depends(get_current_user)):
    await db.vinted_configs.update_one(
        {"user_id": user["id"]},
        {"$set": {
            "user_id": user["id"],
            "domain": payload.domain,
            "cookie": payload.cookie,
            "user_agent": payload.user_agent or "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True, "configured": bool(payload.cookie)}


@api.post("/vinted/test")
async def test_connection(user: dict = Depends(get_current_user)):
    client = await get_vinted_client(user["id"])
    items = await asyncio.to_thread(client.search, {"keyword": "nike"}, 5)
    return {"ok": len(items) > 0, "count": len(items), "domain": client.domain}


# -----------------------------------------------------------------------------
# Saved Searches Endpoints
# -----------------------------------------------------------------------------
def _search_doc_to_out(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "keyword": d.get("keyword", ""),
        "brand_ids": d.get("brand_ids", ""),
        "catalog_ids": d.get("catalog_ids", ""),
        "size_ids": d.get("size_ids", ""),
        "color_ids": d.get("color_ids", ""),
        "status_ids": d.get("status_ids", ""),
        "price_from": d.get("price_from"),
        "price_to": d.get("price_to"),
        "currency": d.get("currency", "EUR"),
        "order": d.get("order", "newest_first"),
        "autobuy": d.get("autobuy", False),
        "max_autobuy_price": d.get("max_autobuy_price"),
        "enabled": d.get("enabled", True),
        "polling_interval": d.get("polling_interval", 2),
        "created_at": d.get("created_at"),
        "last_run_at": d.get("last_run_at"),
        "last_poll_duration_ms": d.get("last_poll_duration_ms"),
        "poll_count": d.get("poll_count", 0),
        "error_count": d.get("error_count", 0),
        "items_found_total": d.get("items_found_total", 0),
    }


@api.get("/searches")
async def list_searches(user: dict = Depends(get_current_user)):
    cur = db.searches.find({"user_id": user["id"]}).sort("created_at", -1)
    return [_search_doc_to_out(d) async for d in cur]


@api.post("/searches")
async def create_search(payload: SavedSearchIn, user: dict = Depends(get_current_user)):
    doc = payload.model_dump()
    doc["user_id"] = user["id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["items_found_total"] = 0
    res = await db.searches.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _search_doc_to_out(doc)


@api.get("/searches/{search_id}")
async def get_search(search_id: str, user: dict = Depends(get_current_user)):
    d = await db.searches.find_one({"_id": ObjectId(search_id), "user_id": user["id"]})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return _search_doc_to_out(d)


@api.put("/searches/{search_id}")
async def update_search(search_id: str, payload: SavedSearchIn, user: dict = Depends(get_current_user)):
    res = await db.searches.update_one(
        {"_id": ObjectId(search_id), "user_id": user["id"]},
        {"$set": payload.model_dump()},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    d = await db.searches.find_one({"_id": ObjectId(search_id)})
    return _search_doc_to_out(d)


@api.delete("/searches/{search_id}")
async def delete_search(search_id: str, user: dict = Depends(get_current_user)):
    await db.searches.delete_one({"_id": ObjectId(search_id), "user_id": user["id"]})
    await db.items_seen.delete_many({"search_id": search_id})
    return {"ok": True}


# -----------------------------------------------------------------------------
# Run Search (live)
# -----------------------------------------------------------------------------
def _normalize_item(raw: dict) -> dict:
    photo = (raw.get("photo") or {}).get("url") or ""
    price_obj = raw.get("price") or {}
    if isinstance(price_obj, dict):
        amount = price_obj.get("amount")
        currency = price_obj.get("currency_code", "EUR")
    else:
        amount = price_obj
        currency = "EUR"
    try:
        amount_f = float(amount) if amount is not None else None
    except Exception:
        amount_f = None
    brand = raw.get("brand_title") or raw.get("brand") or ""
    user = raw.get("user") or {}
    return {
        "id": str(raw.get("id")),
        "title": raw.get("title", ""),
        "brand": brand,
        "size": raw.get("size_title", ""),
        "price": amount_f,
        "currency": currency,
        "photo": photo,
        "url": raw.get("url") or "",
        "seller": user.get("login", ""),
        "favourite_count": raw.get("favourite_count", 0),
        "created_at_ts": raw.get("created_at_ts") or raw.get("photo", {}).get("high_resolution", {}).get("timestamp"),
    }


@api.post("/searches/{search_id}/run")
async def run_search(search_id: str, user: dict = Depends(get_current_user)):
    d = await db.searches.find_one({"_id": ObjectId(search_id), "user_id": user["id"]})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    result = await _execute_search(d)
    return result


async def _execute_search(d: dict) -> Dict[str, Any]:
    """Core search execution shared by manual /run and background worker."""
    started = datetime.now(timezone.utc)
    search_id = str(d["_id"])
    user_id = d["user_id"]
    client = await get_vinted_client(user_id)
    try:
        raw_items = await asyncio.to_thread(client.search, d, 24)
    except Exception as e:
        await db.searches.update_one({"_id": d["_id"]}, {"$inc": {"error_count": 1}})
        logger.warning(f"Search {search_id} error: {e}")
        return {"items": [], "new_count": 0, "total": 0, "autobuy_attempts": [], "error": str(e)}
    items = [_normalize_item(x) for x in raw_items]

    seen_ids = set()
    cur = db.items_seen.find({"search_id": search_id}, {"item_id": 1})
    async for s in cur:
        seen_ids.add(s["item_id"])

    new_ids = []
    autobuy_attempts = []
    new_items_to_store = []
    for it in items:
        if it["id"] not in seen_ids:
            it["is_new"] = True
            new_ids.append(it["id"])
            new_items_to_store.append({
                "search_id": search_id,
                "user_id": user_id,
                "item_id": it["id"],
                "data": it,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            if d.get("autobuy"):
                cap = d.get("max_autobuy_price")
                if cap is None or (it["price"] is not None and it["price"] <= cap):
                    result = await asyncio.to_thread(client.buy, it["id"])
                    autobuy_attempts.append({"item_id": it["id"], "result": result})
                    await db.autobuy_log.insert_one({
                        "user_id": user_id,
                        "search_id": search_id,
                        "item_id": it["id"],
                        "title": it["title"],
                        "price": it["price"],
                        "success": result.get("success", False),
                        "message": result.get("message", ""),
                        "checkout_url": result.get("checkout_url"),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
        else:
            it["is_new"] = False

    if new_ids:
        await db.items_seen.insert_many([
            {"search_id": search_id, "item_id": iid, "ts": datetime.now(timezone.utc).isoformat()}
            for iid in new_ids
        ])
    if new_items_to_store:
        await db.items_cache.insert_many(new_items_to_store)

    elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    await db.searches.update_one(
        {"_id": d["_id"]},
        {"$set": {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_poll_duration_ms": elapsed,
         },
         "$inc": {"items_found_total": len(new_ids), "poll_count": 1}},
    )
    return {
        "items": items,
        "new_count": len(new_ids),
        "total": len(items),
        "autobuy_attempts": autobuy_attempts,
        "elapsed_ms": elapsed,
    }


@api.get("/searches/{search_id}/items")
async def get_cached_items(search_id: str, limit: int = 48, user: dict = Depends(get_current_user)):
    """Return latest items cached by the background worker for this search."""
    d = await db.searches.find_one({"_id": ObjectId(search_id), "user_id": user["id"]})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    cur = db.items_cache.find({"search_id": search_id}).sort("ts", -1).limit(limit)
    items = []
    seen = set()
    async for doc in cur:
        if doc["item_id"] in seen:
            continue
        seen.add(doc["item_id"])
        it = doc["data"]
        it["cached_at"] = doc["ts"]
        items.append(it)
    return {
        "items": items,
        "last_run_at": d.get("last_run_at"),
        "last_poll_duration_ms": d.get("last_poll_duration_ms"),
        "poll_count": d.get("poll_count", 0),
        "enabled": d.get("enabled", True),
        "polling_interval": d.get("polling_interval", 2),
    }


# -----------------------------------------------------------------------------
# Background Worker
# -----------------------------------------------------------------------------
WORKER_STATE: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "total_polls": 0,
    "total_errors": 0,
    "last_tick_at": None,
}
_search_locks: Dict[str, asyncio.Lock] = {}
_worker_task: Optional[asyncio.Task] = None


async def _poll_one(search_doc: dict) -> None:
    sid = str(search_doc["_id"])
    lock = _search_locks.setdefault(sid, asyncio.Lock())
    if lock.locked():
        return  # previous poll still running, skip this tick
    async with lock:
        try:
            res = await _execute_search(search_doc)
            WORKER_STATE["total_polls"] += 1
            if res.get("new_count"):
                logger.info(f"[worker] search={sid} new={res['new_count']} elapsed={res.get('elapsed_ms')}ms")
            if res.get("error"):
                WORKER_STATE["total_errors"] += 1
        except Exception as e:
            WORKER_STATE["total_errors"] += 1
            logger.warning(f"[worker] poll error {sid}: {e}")


async def background_worker() -> None:
    """Loop forever. Every 500ms, find searches due for a poll and execute them in parallel."""
    logger.info("[worker] background worker started")
    WORKER_STATE["running"] = True
    WORKER_STATE["started_at"] = datetime.now(timezone.utc).isoformat()
    while True:
        try:
            WORKER_STATE["last_tick_at"] = datetime.now(timezone.utc).isoformat()
            now = datetime.now(timezone.utc)
            due: List[dict] = []
            cur = db.searches.find({"enabled": {"$ne": False}})
            async for s in cur:
                interval = int(s.get("polling_interval", 2))
                last_iso = s.get("last_run_at")
                if not last_iso:
                    due.append(s)
                    continue
                try:
                    last = datetime.fromisoformat(last_iso)
                except Exception:
                    due.append(s)
                    continue
                if (now - last).total_seconds() >= interval:
                    due.append(s)
            if due:
                await asyncio.gather(*[_poll_one(s) for s in due], return_exceptions=True)
        except Exception as e:
            logger.exception(f"[worker] loop error: {e}")
        await asyncio.sleep(0.5)


@api.get("/worker/status")
async def worker_status(user: dict = Depends(get_current_user)):
    return {
        **WORKER_STATE,
        "active_searches": await db.searches.count_documents({"user_id": user["id"], "enabled": {"$ne": False}}),
        "total_searches": await db.searches.count_documents({"user_id": user["id"]}),
    }


@api.post("/searches/{search_id}/toggle")
async def toggle_search(search_id: str, user: dict = Depends(get_current_user)):
    d = await db.searches.find_one({"_id": ObjectId(search_id), "user_id": user["id"]})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    new_enabled = not d.get("enabled", True)
    await db.searches.update_one({"_id": d["_id"]}, {"$set": {"enabled": new_enabled}})
    return {"enabled": new_enabled}


@api.post("/buy")
async def manual_buy(payload: AutobuyIn, user: dict = Depends(get_current_user)):
    client = await get_vinted_client(user["id"])
    result = await asyncio.to_thread(client.buy, payload.item_id)
    await db.autobuy_log.insert_one({
        "user_id": user["id"],
        "search_id": None,
        "item_id": payload.item_id,
        "title": "(manual)",
        "price": None,
        "success": result.get("success", False),
        "message": result.get("message", ""),
        "checkout_url": result.get("checkout_url"),
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return result


@api.get("/stats")
async def stats(user: dict = Depends(get_current_user)):
    total_searches = await db.searches.count_documents({"user_id": user["id"]})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items_today = await db.items_seen.count_documents({
        "search_id": {"$in": [str(s["_id"]) async for s in db.searches.find({"user_id": user["id"]}, {"_id": 1})]},
        "ts": {"$regex": f"^{today}"},
    })
    autobuys_total = await db.autobuy_log.count_documents({"user_id": user["id"]})
    autobuys_ok = await db.autobuy_log.count_documents({"user_id": user["id"], "success": True})
    return {
        "total_searches": total_searches,
        "items_today": items_today,
        "autobuys_total": autobuys_total,
        "autobuys_ok": autobuys_ok,
    }


@api.get("/autobuy/log")
async def autobuy_log(user: dict = Depends(get_current_user), limit: int = 50):
    cur = db.autobuy_log.find({"user_id": user["id"]}).sort("ts", -1).limit(limit)
    out = []
    async for d in cur:
        d["id"] = str(d["_id"])
        del d["_id"]
        out.append(d)
    return out


@api.get("/")
async def root():
    return {"service": "vinted-bot", "status": "ok"}


# -----------------------------------------------------------------------------
# Startup
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.searches.create_index([("user_id", 1)])
    await db.items_seen.create_index([("search_id", 1), ("item_id", 1)], unique=True)
    await db.items_cache.create_index([("search_id", 1), ("ts", -1)])
    # Auto-expire cached items after 24h to keep the DB lean
    try:
        await db.items_cache.create_index("ts", expireAfterSeconds=86400)
    except Exception:
        pass
    await db.vinted_configs.create_index("user_id", unique=True)
    # seed admin
    email = os.environ.get("ADMIN_EMAIL", "admin@vintedbot.app")
    pw = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": email})
    if not existing:
        await db.users.insert_one({
            "email": email,
            "password_hash": hash_password(pw),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Admin seeded: {email}")
    elif not verify_password(pw, existing["password_hash"]):
        await db.users.update_one({"email": email}, {"$set": {"password_hash": hash_password(pw)}})

    # Launch background worker
    global _worker_task
    _worker_task = asyncio.create_task(background_worker())


@app.on_event("shutdown")
async def shutdown():
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
    client.close()


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # because we use Authorization header for fetch from cross-origin
    allow_methods=["*"],
    allow_headers=["*"],
)

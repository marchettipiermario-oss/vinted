"""Server web locale: API + interfaccia."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .browser import FacebookBrowser
from .db import DEFAULT_SETTINGS, Database
from .extractor import normalize_group_url
from .monitor import Monitor
from .notifiers import enabled_channels, notify_all

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FBM_DATA_DIR", ROOT / "data"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Campi che non vengono mai rimandati al browser in chiaro.
SECRET_KEYS = {"discord_webhook_url", "telegram_bot_token", "whatsapp_apikey"}


# ---------- modelli delle richieste ----------
class GroupIn(BaseModel):
    url: str
    name: str = ""


class GroupPatch(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None


class RuleIn(BaseModel):
    name: str = Field(min_length=1)
    keywords: str = ""
    exclude: str = ""
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    require_price: bool = False
    group_ids: Optional[list[int]] = None
    enabled: bool = True


class ClearIn(BaseModel):
    key: str


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(db: Optional[Database] = None, browser: Optional[FacebookBrowser] = None,
               start_monitor: bool = True) -> FastAPI:
    db = db or Database(DATA_DIR / "monitor.db")
    browser = browser or FacebookBrowser(DATA_DIR / "browser-profile")
    monitor = Monitor(db, browser)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_monitor:
            monitor.start()
        yield
        await monitor.stop()
        await browser.close()

    app = FastAPI(title="Monitor gruppi Facebook", lifespan=lifespan)
    app.state.db, app.state.browser, app.state.monitor = db, browser, monitor

    # ---------- stato ----------
    @app.get("/api/status")
    async def status():
        s = db.get_settings()
        logged_in = await browser.is_logged_in() if browser.started else None
        return {
            **monitor.state,
            "paused": s["paused"],
            "browser_started": browser.started,
            "logged_in": logged_in,
            "groups": len(db.list_groups()),
            "rules": len(db.list_rules()),
            "posts_seen": db.count_posts(),
            "channels": enabled_channels(s),
        }

    @app.post("/api/monitor/resume")
    async def resume():
        db.update_settings({"paused": False})
        monitor.state.update(blocked_reason=None, last_error=None)
        monitor.wake()
        return {"ok": True}

    @app.post("/api/monitor/pause")
    async def pause():
        db.update_settings({"paused": True})
        monitor.state["phase"] = "in pausa"
        return {"ok": True}

    @app.post("/api/monitor/run-now")
    async def run_now():
        if db.get_settings()["paused"]:
            raise HTTPException(400, "Il monitor è in pausa: riattivalo prima.")
        monitor.wake()
        return {"ok": True}

    # ---------- browser / login ----------
    @app.post("/api/browser/login")
    async def open_login():
        s = db.get_settings()
        # Il login va fatto sempre in una finestra visibile.
        await browser.start(headless=False, channel=s["browser_channel"])
        await browser.open_login()
        return {"ok": True}

    # ---------- gruppi ----------
    @app.get("/api/groups")
    async def list_groups():
        return db.list_groups()

    @app.post("/api/groups")
    async def add_group(body: GroupIn):
        try:
            url = normalize_group_url(body.url)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return db.add_group(url, body.name.strip())

    @app.patch("/api/groups/{group_id}")
    async def patch_group(group_id: int, body: GroupPatch):
        if not db.get_group(group_id):
            raise HTTPException(404, "Gruppo non trovato")
        fields = body.model_dump(exclude_none=True)
        if "enabled" in fields:
            fields["enabled"] = int(fields["enabled"])
        db.update_group(group_id, **fields)
        return db.get_group(group_id)

    @app.delete("/api/groups/{group_id}")
    async def delete_group(group_id: int):
        db.delete_group(group_id)
        return {"ok": True}

    # ---------- regole ----------
    def _check_rule(body: RuleIn) -> dict:
        if not body.keywords.strip() and body.min_price is None and body.max_price is None:
            raise HTTPException(400, "Indica almeno una parola chiave o un limite di prezzo.")
        if body.min_price is not None and body.max_price is not None and body.min_price > body.max_price:
            raise HTTPException(400, "Il prezzo minimo è maggiore del massimo.")
        return body.model_dump()

    @app.get("/api/rules")
    async def list_rules():
        return db.list_rules()

    @app.post("/api/rules")
    async def create_rule(body: RuleIn):
        return db.save_rule(_check_rule(body))

    @app.put("/api/rules/{rule_id}")
    async def update_rule(rule_id: int, body: RuleIn):
        return db.save_rule(_check_rule(body), rule_id)

    @app.delete("/api/rules/{rule_id}")
    async def delete_rule(rule_id: int):
        db.delete_rule(rule_id)
        return {"ok": True}

    # ---------- post trovati ----------
    @app.get("/api/matches")
    async def matches(limit: int = 200):
        return db.list_matches(min(max(limit, 1), 1000))

    # ---------- impostazioni ----------
    @app.get("/api/settings")
    async def get_settings():
        s = db.get_settings()
        return {k: (bool(v) if k in SECRET_KEYS else v) for k, v in s.items()}

    @app.put("/api/settings")
    async def put_settings(body: dict):
        values = {k: v for k, v in body.items() if k in DEFAULT_SETTINGS and k != "paused"}
        # I segreti vuoti lasciano il valore già salvato (il form non li riceve in chiaro).
        for key in SECRET_KEYS:
            if key in values and values[key] in ("", None, True):
                values.pop(key)
        try:
            db.update_settings(values)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"Valore non valido: {exc}")
        return await get_settings()

    @app.post("/api/settings/clear")
    async def clear_secret(body: ClearIn):
        if body.key not in SECRET_KEYS:
            raise HTTPException(400, "Campo non valido")
        db.update_settings({body.key: ""})
        return {"ok": True}

    @app.post("/api/notify/test")
    async def test_notify():
        s = db.get_settings()
        if not enabled_channels(s):
            raise HTTPException(400, "Nessun canale di notifica configurato.")
        return await notify_all(s, "✅ Test dal monitor dei gruppi Facebook: le notifiche funzionano.")

    # ---------- interfaccia ----------
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app

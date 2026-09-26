"""Archivio SQLite: gruppi, regole, post visti, impostazioni."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .filters import Rule

DEFAULT_SETTINGS: dict[str, Any] = {
    # Modalità veloce: legge la pagina delle notifiche di Facebook. Richiede che su
    # ogni gruppo le notifiche siano impostate su "Tutti i post".
    "notif_enabled": True,
    "notif_interval_seconds": 40,  # ogni quanto ricarica le notifiche (con variazione casuale)
    "notif_open_posts": True,      # apre il post per leggere testo completo e prezzo
    # Scansione dei gruppi a rotazione: rete di sicurezza per ciò che le notifiche perdono.
    "rotation_enabled": True,
    "interval_minutes": 15,        # pausa tra un giro di gruppi e il successivo
    "groups_per_cycle": 5,         # quanti gruppi apre per giro, a rotazione
    "delay_between_groups_min": 20,  # secondi
    "delay_between_groups_max": 60,
    "scrolls_per_group": 3,
    # Limiti generali
    "active_hour_start": 0,        # fascia oraria attiva (ora locale); 0-0 = sempre
    "active_hour_end": 0,
    "daily_page_limit": 1500,      # pagine di gruppi e post aperte al giorno (le notifiche non contano)
    "headless": False,             # browser visibile: meno riconoscibile come bot
    "browser_channel": "chrome",   # usa Chrome installato sul Mac; "" = Chromium di Playwright
    "paused": True,                # parte in pausa finché non fai il login
    "notif_seeded": False,         # uso interno: la prima lettura delle notifiche non avvisa
    # Notifiche in uscita
    "discord_webhook_url": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "whatsapp_phone": "",
    "whatsapp_apikey": "",
}

SETTING_LIMITS: dict[str, tuple[int, int]] = {
    "notif_interval_seconds": (15, 3600),
    "interval_minutes": (1, 1440),
    "groups_per_cycle": (1, 100),
    "delay_between_groups_min": (3, 600),
    "delay_between_groups_max": (3, 900),
    "scrolls_per_group": (0, 15),
    "active_hour_start": (0, 23),
    "active_hour_end": (0, 23),
    "daily_page_limit": (1, 20000),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    fb_id TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    exclude TEXT NOT NULL DEFAULT '',
    min_price REAL,
    max_price REAL,
    require_price INTEGER NOT NULL DEFAULT 0,
    group_ids TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    group_id INTEGER NOT NULL,
    url TEXT,
    author TEXT,
    text TEXT,
    price REAL,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    post_id TEXT NOT NULL,
    rule_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    notify_error TEXT,
    PRIMARY KEY (post_id, rule_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page_loads (
    day TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_posts_group ON posts(group_id);
CREATE INDEX IF NOT EXISTS idx_matches_created ON matches(created_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(groups)")}
            if "fb_id" not in cols:  # database creato dalla prima versione
                self._conn.execute("ALTER TABLE groups ADD COLUMN fb_id TEXT")
            self._conn.commit()

    def _q(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            self._conn.commit()
            return rows

    def _exec(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    # ---------- impostazioni ----------
    def get_settings(self) -> dict[str, Any]:
        stored = {r["key"]: json.loads(r["value"]) for r in self._q("SELECT key, value FROM settings")}
        return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        for key, value in values.items():
            if key not in DEFAULT_SETTINGS:
                continue
            default = DEFAULT_SETTINGS[key]
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(value)
                if key in SETTING_LIMITS:
                    low, high = SETTING_LIMITS[key]
                    value = min(max(value, low), high)
            elif isinstance(default, str):
                value = str(value or "").strip()
            self._exec(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        return self.get_settings()

    # ---------- gruppi ----------
    def list_groups(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM groups ORDER BY name COLLATE NOCASE, id")]

    def get_group(self, group_id: int) -> Optional[dict]:
        rows = self._q("SELECT * FROM groups WHERE id = ?", (group_id,))
        return dict(rows[0]) if rows else None

    def add_group(self, url: str, name: str = "", enabled: bool = True) -> dict:
        existing = self._q("SELECT id FROM groups WHERE url = ?", (url,))
        if existing:
            return self.get_group(existing[0]["id"])
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        gid = self._exec(
            "INSERT INTO groups(url, name, fb_id, enabled, created_at) VALUES(?, ?, ?, ?, ?)",
            (url, name, slug if slug.isdigit() else None, int(enabled), now_iso()),
        )
        return self.get_group(gid)

    def find_group(self, ref: str) -> Optional[dict]:
        """Trova un gruppo dal nome nel link (es. 'mercatinoroma') o dall'ID numerico."""
        rows = self._q(
            "SELECT * FROM groups WHERE fb_id = ? OR url = ? LIMIT 1",
            (ref, f"https://www.facebook.com/groups/{ref}/"),
        )
        return dict(rows[0]) if rows else None

    def update_group(self, group_id: int, **fields) -> None:
        allowed = {"name", "enabled", "fb_id", "last_checked_at", "last_error"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._exec(f"UPDATE groups SET {cols} WHERE id = ?", (*sets.values(), group_id))

    def link_group_id(self, group_id: int, fb_id: str) -> None:
        """Salva l'ID numerico del gruppo e unisce un eventuale doppione
        (lo stesso gruppo aggiunto dalle notifiche con l'ID numerico)."""
        for dup in self._q(
            "SELECT id, enabled FROM groups WHERE id != ? AND (fb_id = ? OR url = ?)",
            (group_id, fb_id, f"https://www.facebook.com/groups/{fb_id}/"),
        ):
            self._exec("UPDATE posts SET group_id = ? WHERE group_id = ?", (group_id, dup["id"]))
            if dup["enabled"]:
                self._exec("UPDATE groups SET enabled = 1 WHERE id = ?", (group_id,))
            self._exec("DELETE FROM groups WHERE id = ?", (dup["id"],))
        self._exec("UPDATE groups SET fb_id = ? WHERE id = ?", (fb_id, group_id))

    def delete_group(self, group_id: int) -> None:
        self._exec("DELETE FROM groups WHERE id = ?", (group_id,))

    def next_groups(self, limit: int) -> list[dict]:
        """Gruppi attivi controllati meno di recente (i mai controllati per primi)."""
        rows = self._q(
            "SELECT * FROM groups WHERE enabled = 1 "
            "ORDER BY last_checked_at IS NOT NULL, last_checked_at, id LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    # ---------- regole ----------
    @staticmethod
    def _rule_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["require_price"] = bool(d["require_price"])
        d["enabled"] = bool(d["enabled"])
        d["group_ids"] = json.loads(d["group_ids"]) if d["group_ids"] else None
        return d

    def list_rules(self) -> list[dict]:
        return [self._rule_row(r) for r in self._q("SELECT * FROM rules ORDER BY id")]

    def active_rules(self) -> list[Rule]:
        return [
            Rule(
                id=r["id"], name=r["name"], keywords=r["keywords"], exclude=r["exclude"],
                min_price=r["min_price"], max_price=r["max_price"],
                require_price=r["require_price"], group_ids=r["group_ids"],
            )
            for r in self.list_rules() if r["enabled"]
        ]

    def save_rule(self, data: dict, rule_id: Optional[int] = None) -> dict:
        values = (
            data.get("name") or "Regola",
            data.get("keywords") or "",
            data.get("exclude") or "",
            data.get("min_price"),
            data.get("max_price"),
            int(bool(data.get("require_price"))),
            json.dumps(data["group_ids"]) if data.get("group_ids") else None,
            int(data.get("enabled", True)),
        )
        if rule_id is None:
            rule_id = self._exec(
                "INSERT INTO rules(name, keywords, exclude, min_price, max_price, require_price, "
                "group_ids, enabled, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*values, now_iso()),
            )
        else:
            self._exec(
                "UPDATE rules SET name=?, keywords=?, exclude=?, min_price=?, max_price=?, "
                "require_price=?, group_ids=?, enabled=? WHERE id=?",
                (*values, rule_id),
            )
        return self._rule_row(self._q("SELECT * FROM rules WHERE id = ?", (rule_id,))[0])

    def delete_rule(self, rule_id: int) -> None:
        self._exec("DELETE FROM rules WHERE id = ?", (rule_id,))
        self._exec("DELETE FROM matches WHERE rule_id = ?", (rule_id,))

    # ---------- post ----------
    def post_exists(self, post_id: str) -> bool:
        return bool(self._q("SELECT 1 FROM posts WHERE id = ?", (post_id,)))

    def group_has_posts(self, group_id: int) -> bool:
        return bool(self._q("SELECT 1 FROM posts WHERE group_id = ? LIMIT 1", (group_id,)))

    def add_post(self, post: dict, group_id: int) -> None:
        self._exec(
            "INSERT OR IGNORE INTO posts(id, group_id, url, author, text, price, first_seen_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (post["id"], group_id, post.get("url"), post.get("author"),
             post.get("text"), post.get("price"), now_iso()),
        )

    def add_match(self, post_id: str, rule_id: int) -> None:
        self._exec(
            "INSERT OR IGNORE INTO matches(post_id, rule_id, created_at) VALUES(?, ?, ?)",
            (post_id, rule_id, now_iso()),
        )

    def set_match_notified(self, post_id: str, rule_id: int, error: Optional[str]) -> None:
        self._exec(
            "UPDATE matches SET notified = ?, notify_error = ? WHERE post_id = ? AND rule_id = ?",
            (0 if error else 1, error, post_id, rule_id),
        )

    def list_matches(self, limit: int = 200) -> list[dict]:
        rows = self._q(
            "SELECT m.post_id, m.rule_id, m.created_at, m.notified, m.notify_error, "
            "p.url, p.author, p.text, p.price, p.group_id, "
            "g.name AS group_name, g.url AS group_url, r.name AS rule_name "
            "FROM matches m JOIN posts p ON p.id = m.post_id "
            "LEFT JOIN groups g ON g.id = p.group_id "
            "LEFT JOIN rules r ON r.id = m.rule_id "
            "ORDER BY m.created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def count_posts(self) -> int:
        return self._q("SELECT COUNT(*) AS n FROM posts")[0]["n"]

    # ---------- limite giornaliero ----------
    def pages_today(self, day: str) -> int:
        rows = self._q("SELECT count FROM page_loads WHERE day = ?", (day,))
        return rows[0]["count"] if rows else 0

    def increment_pages(self, day: str) -> None:
        self._exec(
            "INSERT INTO page_loads(day, count) VALUES(?, 1) "
            "ON CONFLICT(day) DO UPDATE SET count = count + 1",
            (day,),
        )

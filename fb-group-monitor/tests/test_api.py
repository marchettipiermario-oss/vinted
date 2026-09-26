import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app


@pytest.fixture
def client():
    app = create_app(db=Database(":memory:"), start_monitor=False)
    with TestClient(app) as c:
        yield c


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Monitor gruppi Facebook" in r.text


def test_groups_crud(client):
    r = client.post("/api/groups", json={"url": "https://facebook.com/groups/abc?ref=x"})
    assert r.status_code == 200
    g = r.json()
    assert g["url"] == "https://www.facebook.com/groups/abc/"
    assert client.post("/api/groups", json={"url": "https://example.com"}).status_code == 400
    assert client.patch(f"/api/groups/{g['id']}", json={"enabled": False}).json()["enabled"] == 0
    assert client.delete(f"/api/groups/{g['id']}").status_code == 200
    assert client.get("/api/groups").json() == []


def test_rules_validation_and_update(client):
    assert client.post("/api/rules", json={"name": "vuota"}).status_code == 400
    assert client.post("/api/rules", json={"name": "x", "keywords": "a", "min_price": 50, "max_price": 10}).status_code == 400
    r = client.post("/api/rules", json={"name": "Nike", "keywords": "nike", "max_price": 50, "group_ids": [1]}).json()
    assert r["group_ids"] == [1] and r["enabled"] is True
    r2 = client.put(f"/api/rules/{r['id']}", json={**r, "enabled": False}).json()
    assert r2["enabled"] is False


def test_settings_hide_secrets(client):
    client.put("/api/settings", json={"telegram_bot_token": "segreto", "interval_minutes": 15})
    s = client.get("/api/settings").json()
    assert s["telegram_bot_token"] is True and s["interval_minutes"] == 15
    # Un campo segreto vuoto non cancella il valore salvato.
    client.put("/api/settings", json={"telegram_bot_token": ""})
    assert client.get("/api/settings").json()["telegram_bot_token"] is True
    # "paused" si cambia solo dai pulsanti del monitor.
    client.put("/api/settings", json={"paused": False})
    assert client.get("/api/settings").json()["paused"] is True


def test_status_and_pause_resume(client):
    s = client.get("/api/status").json()
    assert s["paused"] is True and s["logged_in"] is None
    assert client.post("/api/monitor/run-now").status_code == 400
    client.post("/api/monitor/resume")
    assert client.get("/api/status").json()["paused"] is False


def test_test_notify_requires_channel(client):
    assert client.post("/api/notify/test").status_code == 400

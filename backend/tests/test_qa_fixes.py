"""Regression tests for issues found in the QA pass."""
import asyncio

from app.config import Settings, settings
from app.db import db
from tests.conftest import PROFILE, go_live, login, new_owner


async def test_public_deployment_never_shows_or_logs_codes(client, monkeypatch):
    monkeypatch.setattr(Settings, "local_dev", property(lambda s: False))
    r = await client.post("/api/auth/otp", json={"phone": "9824011111"})
    assert r.status_code == 503 and "dev_code" not in r.text  # no WhatsApp/SMS keys → nobody can log in with a shown code
    assert await db().outbox.count_documents({}) == 0


async def test_lead_alert_without_whatsapp_keys_on_public_deployment(client, monkeypatch):
    await login(client, "9824022222")
    site = await go_live(client)
    monkeypatch.setattr(Settings, "local_dev", property(lambda s: False))
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Neha Joshi", "phone": "9833000000"})
    lead = (await client.get("/api/leads")).json()[0]
    assert lead["alert"] == {"sent": False, "via": "whatsapp-not-configured"}  # recorded honestly, lead still saved


async def test_paused_owner_cannot_log_in(client):
    owner = await new_owner("9824033333")
    admin = await new_owner("9999900000")
    uid = (await owner.get("/api/me")).json()["user"]["id"]
    await admin.patch(f"/api/admin/users/{uid}", json={"disabled": True})
    code = (await client.post("/api/auth/otp", json={"phone": "9824033333"})).json()["dev_code"]
    r = await client.post("/api/auth/verify", json={"phone": "9824033333", "code": code})
    assert r.status_code == 403 and "paused" in r.json()["detail"]


async def test_admin_role_follows_admin_phones(client):
    a = await new_owner("9999900000")
    assert (await a.get("/api/me")).json()["user"]["role"] == "admin"
    object.__setattr__(settings, "admin_phones", ())
    try:
        await a.post("/api/auth/logout")
        await login(a, "9999900000")
        assert (await a.get("/api/me")).json()["user"]["role"] == "owner"
        assert (await a.get("/api/admin/pulse")).status_code == 403
    finally:
        object.__setattr__(settings, "admin_phones", ("+919999900000",))


async def test_bad_inquiry_body_is_a_clear_400(client):
    await login(client, "9824044444")
    site = await go_live(client)
    r = await client.post(f"/s/{site['slug']}/inquiry", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    r = await client.post(f"/s/{site['slug']}/inquiry", json=["a", "list"])
    assert r.status_code == 400


async def test_double_click_build_creates_one_website(client):
    await login(client, "9824055555")
    await client.put("/api/business", json=PROFILE)
    results = await asyncio.gather(client.post("/api/site/generate"), client.post("/api/site/generate"))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert await db().sites.count_documents({}) == 1


async def test_workshop_room_on_one_wifi_can_all_log_in(client):
    for i in range(40):
        r = await client.post("/api/auth/otp", json={"phone": f"98250{i:05d}"}, headers={"x-forwarded-for": "203.0.113.7"})
        assert r.status_code == 200

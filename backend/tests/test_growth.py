from datetime import timedelta

from app.ai import tasks
from app.ai.provider import AIError
from app.db import db, now
from tests.conftest import PROFILE, go_live, login, new_owner

ADMIN = "+919999900000"


async def test_free_runs_run_out_then_ask_invite_or_upgrade(client):
    await login(client, "9821011111")
    await client.put("/api/business", json=PROFILE)
    for _ in range(10):
        assert (await client.post("/api/studio/ask", json={"question": "What should I fix first?"})).status_code == 200
    r = await client.post("/api/studio/ask", json={"question": "What should I fix first?"})
    assert r.status_code == 402
    detail = r.json()["detail"]
    assert detail["code"] == "runs_exhausted" and "/join?ref=" in detail["invite"]["link"] and detail["upgrade"]["tier"] == "lite"
    assert await db().events.count_documents({"type": "limit_hit"}) == 1


async def test_failed_ai_call_refunds_the_run(client, monkeypatch):
    await login(client, "9821022222")
    await client.put("/api/business", json=PROFILE)

    async def broken(*a, **k):
        raise AIError("down")
    monkeypatch.setattr(tasks, "business_qa", broken)
    r = await client.post("/api/studio/ask", json={"question": "Will this fail?"})
    assert r.status_code == 502 and "not used" in r.json()["detail"]
    assert (await client.get("/api/me")).json()["runs"]["used"] == 0


async def test_referral_loop_rewards_on_activation_not_signup(client):
    a = await new_owner("9821033333")
    await go_live(a)
    code = (await a.get("/api/me")).json()["invite_link"].split("ref=")[1].split("&")[0]
    assert (await client.get(f"/api/public/invite/{code}?src=badge")).json() == {"valid": True, "business": "Shree Ganesh Interiors", "trial_days": 30}

    b = await new_owner("9821044444", ref=code, src="badge")
    me_b = (await b.get("/api/me")).json()
    assert me_b["user"]["effective_plan"] == "lite" and me_b["user"]["plan"] == "free" and me_b["features"]["badge_off"]
    assert me_b["runs"]["allowance"] == 150
    assert (await a.get("/api/me")).json()["user"]["effective_plan"] == "free"  # nothing for a signup alone

    await go_live(b, {**PROFILE, "name": "Kapoor Dental Clinic"})
    me_a = (await a.get("/api/me")).json()
    assert me_a["user"]["effective_plan"] == "lite" and me_a["user"]["trial_until"]
    assert "Kapoor Dental Clinic just went live" in me_a["notices"][0]["text"]
    await b.post("/api/site/unpublish"); await b.post("/api/site/publish")  # republishing never rewards twice
    assert await db().referral_rewards.count_documents({}) == 1

    c = await new_owner("9821055555", ref=code, src="invite")
    await go_live(c, {**PROFILE, "name": "Arora Traders"})
    me_a = (await a.get("/api/me")).json()
    assert me_a["runs"]["bonus"] == 10
    refs = (await a.get("/api/referrals")).json()
    assert {f["business"] for f in refs["friends"]} == {"Kapoor Dental Clinic", "Arora Traders"} and all(f["live"] for f in refs["friends"])
    assert [r["kind"] for r in refs["rewards"]] == ["bonus_runs", "membership_days"]


async def test_trial_expires_back_to_free(client):
    await login(client, "9821066666")
    me = (await client.get("/api/me")).json()
    await db().users.update_one({"_id": me["user"]["id"]}, {"$set": {"trial": {"plan": "lite", "until": now() - timedelta(minutes=1)}}})
    assert (await client.get("/api/me")).json()["user"]["effective_plan"] == "free"


async def test_self_referral_ignored(client):
    a = await new_owner("9821077777")
    code = (await a.get("/api/me")).json()["invite_link"].split("ref=")[1].split("&")[0]
    await a.post("/api/auth/logout")
    await login(a, "9821077777", ref=code)
    assert (await a.get("/api/me")).json()["user"]["effective_plan"] == "free"


async def test_membership_removes_badge_and_never_messages_customers(client):
    owner = await new_owner("9821088888")
    site = await go_live(owner)
    admin = await new_owner(ADMIN)
    users = (await admin.get("/api/admin/users?q=9821088888")).json()
    assert (await admin.patch(f"/api/admin/users/{users[0]['id']}", json={"plan": "lite"})).status_code == 200
    html = (await client.get(f"/s/{site['slug']}")).text
    assert "Built free with" not in html
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Vikram Shah", "phone": "+91 98440 00000", "message": "Office fit-out"})
    lead = (await owner.get("/api/leads")).json()[0]
    assert lead["name"] == "Vikram Shah" and lead["stage"] == "identification" and "auto_reply" not in lead
    assert await db().outbox.count_documents({"to": "+919844000000"}) == 0   # the hub's number only alerts the owner
    assert await db().outbox.count_documents({"kind": "lead_alert"}) == 1


async def test_admin_pulse_and_cohorts(client):
    owner = await new_owner("9821099999")
    assert (await owner.get("/api/admin/pulse")).status_code == 403
    admin = await new_owner(ADMIN)
    r = await admin.post("/api/admin/cohorts", json={"code": "bai-oct-11", "name": "Business AI · 11 Oct", "workshop_date": "2026-10-11"})
    assert r.json()["join_link"] == "https://hub.example.in/join?c=BAI-OCT-11"
    assert (await admin.post("/api/admin/cohorts", json={"code": "BAI-OCT-11"})).status_code == 409
    attendee = await new_owner("9822011111", cohort="bai-oct-11")
    await go_live(attendee)
    friend = await new_owner("9822022222", ref=(await attendee.get("/api/me")).json()["invite_link"].split("ref=")[1].split("&")[0], src="badge")
    p = (await admin.get("/api/admin/pulse")).json()
    assert p["activation"]["site_live"] == 1 and p["totals"]["referred_signups"] == 1
    assert p["viral"]["by_source"]["cohort"] == 1 and p["viral"]["by_source"]["badge"] == 1
    assert p["cohorts"][0] == {"code": "BAI-OCT-11", "name": "Business AI · 11 Oct", "workshop_date": "2026-10-11", "signups": 1, "sites_live": 1, "brought_in": 1}
    assert p["ai"]["runs"] == 2 and p["plans"]["trials"] == 1
    await admin.patch(f"/api/admin/users/{(await owner.get('/api/me')).json()['user']['id']}", json={"disabled": True})
    assert (await owner.get("/api/me")).status_code == 401


async def test_upgrade_click_tracked(client):
    await login(client, "9822033333")
    r = await client.post("/api/upgrade-click", json={"tier": "lite", "from_feature": "badge_off"})
    assert r.status_code == 200 and r.json() == {"url": None}
    ladder = (await client.get("/api/plans")).json()["ladder"]
    assert [t["tier"] for t in ladder] == ["free", "lite", "program", "running", "growth", "office"]
    assert ladder[1]["price_minor"] == 199_900 and any(u["key"] == "week" for u in ladder[1]["unlocks"]) and len(ladder) == 6
    assert ladder[4]["team_size"] == 10 and ladder[5]["team_size"] == 25 and "razorpay_plan_id" not in ladder[1]

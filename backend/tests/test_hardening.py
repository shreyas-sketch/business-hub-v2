"""Safeguards added in the final review: who sees what, real phone numbers, caps on automatic messages,
fixed template wording, reminder spacing, interrupted office runs, review links and upload limits."""
from datetime import timedelta

from app.agents import approvals, hooks, office
from app.db import IST, db, now
from app.routers.hub import clean_link
from app.security import normalise_phone
from tests.conftest import PROFILE, go_live, new_owner

ADMIN = "9999900000"


async def owner_on(phone: str, plan: str, live: bool = True):
    c = await new_owner(phone, name="Harsh Mehta")
    site = await go_live(c) if live else None
    if not live:
        await c.put("/api/business", json=PROFILE)
    uid = (await c.get("/api/me")).json()["user"]["id"]
    admin = await new_owner(ADMIN)
    assert (await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})).status_code == 200
    return c, uid, site


async def connect_demo_whatsapp(uid: str):
    from app import connections
    await connections.save(uid, "whatsapp", {"provider": "demo", "tpl_instant": "instant_v1", "tpl_followup": "followup_v1",
                                             "tpl_review": "review_v1", "tpl_reminder": "reminder_v1"}, "test", "test")


async def join(owner, phone: str, name: str, role: str):
    assert (await owner.post("/api/team/invites", json={"phone": phone, "name": name, "role": role})).status_code == 200
    return await new_owner(phone)


async def inquiry(client, site, name, phone, message="Need a quote"):
    r = await client.post(f"/s/{site['slug']}/inquiry", json={"name": name, "phone": phone, "message": message})
    assert r.status_code == 200, r.text
    return await db().leads.find_one({"phone": normalise_phone(phone)}, sort=[("created_at", -1)])


# ───────────────────────── who sees which saved outputs ─────────────────────────
async def test_outputs_are_scoped_by_role(client):
    owner, uid, _ = await owner_on("9836000001", "growth", live=False)
    staff = await join(owner, "9836000002", "Ravi Kumar", "staff")
    manager = await join(owner, "9836000003", "Priya Shah", "manager")
    for kind in ("posts", "kit:decision", "report", "goal_coach"):
        await db().outputs.insert_one({"_id": f"out-{kind}", "user_id": uid, "kind": kind, "title": kind, "content": {}, "created_at": now()})

    kinds = lambda rows: sorted(r["kind"] for r in rows)  # noqa: E731
    assert kinds((await owner.get("/api/outputs")).json()) == ["goal_coach", "kit:decision", "posts", "report"]
    assert kinds((await manager.get("/api/outputs")).json()) == ["posts", "report"]
    assert kinds((await staff.get("/api/outputs")).json()) == ["posts"]
    assert (await manager.get("/api/outputs?kind=kit:decision")).json() == []
    assert (await staff.get("/api/outputs?kind=report")).json() == []

    assert (await staff.delete("/api/outputs/out-posts")).status_code == 403
    await manager.delete("/api/outputs/out-kit:decision")  # not theirs to see, so not theirs to delete
    assert await db().outputs.find_one({"_id": "out-kit:decision"})
    await manager.delete("/api/outputs/out-report")
    assert not await db().outputs.find_one({"_id": "out-report"})


# ───────────────────────── website inquiries need a real mobile number ─────────────────────────
async def test_inquiry_needs_a_real_mobile_number(client):
    _, uid, site = await owner_on("9836000010", "free")
    bad = await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Neha Joshi", "phone": "12345"})
    assert bad.status_code == 400 and "10-digit" in bad.json()["detail"]

    form = await client.post(f"/s/{site['slug']}/inquiry", data={"name": "Neha Joshi", "phone": "55555 55555"})
    assert form.status_code == 303 and form.headers["location"] == f"/s/{site['slug']}?err=phone#contact"
    page = await client.get(f"/s/{site['slug']}?err=phone")
    assert "Please add your name and a 10-digit mobile number." in page.text and 'name="phone"' in page.text
    assert await db().leads.count_documents({}) == 0

    ok = await client.post(f"/s/{site['slug']}/inquiry", data={"name": "Neha Joshi", "phone": "098330 00000"})
    assert ok.status_code == 303 and "sent=1" in ok.headers["location"]
    assert (await db().leads.find_one({"owner_id": uid}))["phone"] == "+919833000000"


# ───────────────────────── caps on automatic messages ─────────────────────────
async def test_instant_replies_have_a_daily_cap(client, monkeypatch):
    from app.agents import growth
    monkeypatch.setattr(growth, "INSTANT_PER_DAY", 2)
    c, uid, site = await owner_on("9836000020", "growth")
    await connect_demo_whatsapp(uid)
    first = await inquiry(client, site, "Asha Rao", "98360 00021")
    second = await inquiry(client, site, "Vikram Shah", "98360 00022")
    third = await inquiry(client, site, "Meena Iyer", "98360 00023")
    assert first["instant_reply"]["sent"] and second["instant_reply"]["sent"]
    assert third["instant_reply"]["sent"] is False and third["instant_reply"]["via"] == "skipped-cap"
    assert await db().outbox.count_documents({"kind": "instant"}) == 2


async def test_one_follow_up_sequence_per_number_and_a_daily_ceiling(client, monkeypatch):
    monkeypatch.setattr(hooks, "FOLLOWUP_LEADS_PER_SITE_PER_DAY", 2)
    _, _, site = await owner_on("9836000030", "program")
    a = await inquiry(client, site, "Asha Rao", "98360 00031", "Kitchen")
    again = await inquiry(client, site, "Asha Rao", "98360 00031", "Kitchen, also wardrobes")
    b = await inquiry(client, site, "Vikram Shah", "98360 00032")
    c = await inquiry(client, site, "Meena Iyer", "98360 00033")
    assert a.get("followups") and b.get("followups")
    assert not again.get("followups")  # the same customer is already being followed up this week
    assert not c.get("followups")  # today's ceiling for this website
    jobs = await db().agent_jobs.count_documents({"agent": "followup"})
    assert jobs == 6  # 3 follow-ups each for two leads


# ───────────────────────── fixed template wording ─────────────────────────
async def test_reminders_keep_the_template_wording_they_were_sent_with(client):
    c, uid, _ = await owner_on("9836000040", "growth", live=False)
    await connect_demo_whatsapp(uid)
    owner = await db().users.find_one({"_id": uid})
    a = await approvals.create_approval(owner, uid, "payment_reminder", "reminder", "Reminder to Ramesh", "Ramesh Patel", "+919836000041",
                                        "Hi Ramesh, a gentle reminder about ₹12,500 due on 1 Oct.",
                                        params=["Ramesh", "Shree Ganesh Interiors", "₹12,500", "1 Oct", "UPI sgi@okaxis"])
    assert a["status"] == "pending" and a["template_text"] == a["text"]
    edited = "Ramesh bhai, please clear the balance today or we stop work."
    assert (await c.patch(f"/api/approvals/{a['_id']}", json={"text": edited})).status_code == 200
    r = await c.post(f"/api/approvals/{a['_id']}/send")
    assert r.status_code == 200, r.text
    saved = await db().approvals.find_one({"_id": a["_id"]})
    assert saved["text"] == a["template_text"] and saved["edited_text"] == edited  # the record shows what really went out
    out = await db().outbox.find_one({"kind": "reminder"})
    assert edited not in str(out["params"]) and out["params"][2] == "₹12,500"


async def test_follow_ups_with_links_and_money_messages_always_wait(client):
    c, uid, _ = await owner_on("9836000050", "office", live=False)
    await connect_demo_whatsapp(uid)
    owner = await db().users.find_one({"_id": uid})
    assert (await c.patch("/api/agents/followup", json={"autonomy": "act"})).status_code == 200
    plain = await approvals.create_approval(owner, uid, "followup", "followup", "Follow-up", "Asha", "+919836000051", "Hi Asha, still keen?")
    linked = await approvals.create_approval(owner, uid, "followup", "followup", "Follow-up", "Asha", "+919836000051",
                                             "Hi Asha, see our work at https://example.com", allow_act=False)
    assert plain["status"] == "sent" and linked["status"] == "pending"
    assert (await c.patch("/api/agents/payment_reminder", json={"autonomy": "act"})).status_code == 200
    money = await approvals.create_approval(owner, uid, "payment_reminder", "reminder", "Reminder", "Asha", "+919836000051", "Hi Asha, ₹5,000 is due.",
                                            params=["Asha", "SGI", "₹5,000", "1 Oct", "UPI"])
    assert money["status"] == "pending"   # money messages always wait for a person


# ───────────────────────── office: reminder spacing and interrupted runs ─────────────────────────
async def test_office_reminders_respect_the_gap_between_reminders(client):
    c, uid, _ = await owner_on("9836000060", "office", live=False)
    yesterday = (now().astimezone(IST) - timedelta(days=5)).strftime("%Y-%m-%d")
    await c.post("/api/money", json={"customer": "Ramesh Patel", "phone": "98360 00061", "amount": 12500, "due_date": yesterday})
    run = (await c.post("/api/office/runs", json={"instruction": "Remind customers who owe us money"})).json()
    remind = next(s for s in run["steps"] if s["tool"] == "accounts.remind_overdue")
    assert remind["status"] == "waiting" and len(remind["refs"]["approvals"]) == 1
    await c.post(f"/api/approvals/{remind['refs']['approvals'][0]}/skip")

    run = (await c.post("/api/office/runs", json={"instruction": "Remind customers who owe us money"})).json()
    remind = next(s for s in run["steps"] if s["tool"] == "accounts.remind_overdue")
    assert remind["status"] == "done" and "every few days" in remind["note"]  # reminded today already: not again
    assert await db().approvals.count_documents({"kind": "reminder"}) == 1

    await db().dues.update_many({}, {"$set": {"last_reminded_at": now() - timedelta(days=4)}})
    run = (await c.post("/api/office/runs", json={"instruction": "Remind customers who owe us money"})).json()
    remind = next(s for s in run["steps"] if s["tool"] == "accounts.remind_overdue")
    assert remind["status"] == "waiting" and await db().approvals.count_documents({"kind": "reminder"}) == 2


async def test_interrupted_office_run_is_resumed_once(client):
    c, uid, _ = await owner_on("9836000070", "office", live=False)
    owner = await db().users.find_one({"_id": uid})
    run = await office.start(owner, uid, "Write next week's posts and an SOP for site visits", await db().businesses.find_one({"owner_id": uid}))
    run["steps"][0]["status"] = "running"  # the worker restarted mid-step
    await db().office_runs.update_one({"_id": run["_id"]}, {"$set": {"steps": run["steps"], "lease_until": now() - timedelta(minutes=1)}})
    assert (await c.get(f"/api/office/runs/{run['_id']}")).json()["status"] == "running"

    assert await office.resume_stale() == 1
    done = await db().office_runs.find_one({"_id": run["_id"]})
    assert done["status"] == "partial" and done["steps"][0]["status"] == "failed" and "Interrupted" in done["steps"][0]["note"]
    assert all(s["status"] in ("done", "waiting") for s in done["steps"][1:])
    assert await office.resume_stale() == 0  # never twice


async def test_managers_cannot_use_owner_only_office_tools(client):
    owner, uid, _ = await owner_on("9836000080", "office", live=False)
    manager = await join(owner, "9836000081", "Priya Shah", "manager")
    run = (await manager.post("/api/office/runs", json={"instruction": "Review this month and write role clarity for the sales role"})).json()
    tools = [s["tool"] for s in run["steps"]]
    assert "chief.review_month" not in tools and "hr.role_clarity" not in tools
    run = (await owner.post("/api/office/runs", json={"instruction": "Review this month and write role clarity for the sales role"})).json()
    assert {"chief.review_month", "hr.role_clarity"} <= {s["tool"] for s in run["steps"]}


# ───────────────────────── review links, team invites, uploads ─────────────────────────
async def test_review_link_is_checked_and_completed(client):
    c, _, _ = await owner_on("9836000090", "running", live=False)
    r = await c.put("/api/business", json={**PROFILE, "review_link": "g.page/r/CabcXYZ/review"})
    assert r.status_code == 200 and r.json()["review_link"] == "https://g.page/r/CabcXYZ/review"
    bad = await c.put("/api/business", json={**PROFILE, "review_link": "leave us a review please"})
    assert bad.status_code == 400 and "https://" in bad.json()["detail"]
    assert (await c.put("/api/business", json={**PROFILE, "review_link": ""})).json()["review_link"] == ""
    assert clean_link("HTTPS://maps.app.goo.gl/xyz") == "HTTPS://maps.app.goo.gl/xyz"


async def test_paying_owner_is_never_folded_into_someone_elses_team(client):
    owner, _, _ = await owner_on("9836000100", "growth", live=False)
    paying = await new_owner("9836000101")
    pid = (await paying.get("/api/me")).json()["user"]["id"]
    admin = await new_owner(ADMIN)
    await admin.patch(f"/api/admin/users/{pid}", json={"plan": "program"})
    r = await owner.post("/api/team/invites", json={"phone": "9836000101", "name": "Kapil", "role": "staff"})
    assert r.status_code in (400, 409) or (await new_owner("9836000101") and True)
    me = (await (await new_owner("9836000101")).get("/api/me")).json()
    assert me["workspace"]["is_team"] is False and me["user"]["effective_plan"] == "program"


async def test_voice_upload_without_a_size_is_refused(client):
    c, _, _ = await owner_on("9836000110", "program", live=False)

    async def body():
        yield b"--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"v.webm\"\r\nContent-Type: audio/webm\r\n\r\n"
        yield b"\0" * 1000
        yield b"\r\n--x--\r\n"
    r = await c.post("/api/voice/transcribe", content=body(), headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411

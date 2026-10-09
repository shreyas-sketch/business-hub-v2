"""The AI office (LegacyWorkforce plan): departments, hired roles, planning, tools, the Send list, autonomy, run limits and the standup."""
from datetime import datetime, timedelta, timezone

from app.agents import scheduler
from app.db import db, month_key, now
from tests.conftest import PROFILE, go_live, login, new_owner


async def _office_owner(client, phone: str, plan: str = "office") -> str:
    await login(client, phone)
    await go_live(client)
    uid = (await client.get("/api/me")).json()["user"]["id"]
    admin = await new_owner("9999900000")
    await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})
    return uid


async def _demo_whatsapp(uid: str):
    from app import connections
    await connections.save(uid, "whatsapp", {"provider": "demo", "tpl_followup": "followup_v1", "tpl_reminder": "reminder_v1"}, "test", "test")


async def _old_lead(uid: str, name="Ravi Kumar", phone="9835011111", days=2, status="new") -> str:
    site = await db().sites.find_one({"owner_id": uid})
    lead = {"_id": f"lead-{name}", "owner_id": uid, "site_id": site["_id"], "name": name, "phone": phone,
            "message": "Need a modular kitchen for our new flat", "status": status, "source": "website",
            "created_at": now() - timedelta(days=days)}
    await db().leads.insert_one(lead)
    return lead["_id"]


async def test_office_is_locked_below_legacyworkforce(client):
    await _office_owner(client, "9835000001", plan="growth")
    r = await client.get("/api/office")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "locked" and r.json()["detail"]["tier"] == "office"
    assert (await client.post("/api/office/runs", json={"instruction": "Follow up every lead"})).status_code == 403


async def test_chief_of_staff_and_five_departments(client):
    await _office_owner(client, "9835000002")
    data = (await client.get("/api/office")).json()
    assert [s["key"] for s in data["staff"]] == ["chief", "marketing", "sales", "support", "intelligence", "operations"]
    assert data["can_act"] is True and data["hired"] == 0
    assert {t["name"] for s in data["staff"] for t in s["tools"]} >= {"sales.follow_up_leads", "ops.create_tasks", "hr.write_jd"}
    assert "role.draft" not in {t["name"] for s in data["staff"] for t in s["tools"]}
    assert (await client.post("/api/workforce/recommended")).json()["hired"] == 30
    data = (await client.get("/api/office")).json()
    assert data["hired"] == 30 and all(len(s["roles"]) == 6 for s in data["staff"] if s["key"] != "chief")


async def test_follow_up_instruction_waits_for_approval(client):
    uid = await _office_owner(client, "9835000003")
    lead_id = await _old_lead(uid)
    await _old_lead(uid, name="Fresh Lead", phone="9835011112", days=0)  # too new to chase
    run = (await client.post("/api/office/runs", json={"instruction": "Follow up with every lead that is still waiting"})).json()
    assert run["status"] == "done"
    step = run["steps"][0]
    assert step["tool"] == "sales.follow_up_leads" and step["status"] == "waiting" and "waiting in Approvals" in step["note"]
    pending = (await client.get("/api/approvals")).json()
    assert len(pending) == 1 and pending[0]["lead_id"] == lead_id and pending[0]["agent_name"] == "Sales (AI office)"
    assert await db().outbox.count_documents({"kind": "followup"}) == 0  # nothing reached the customer


async def test_sales_can_act_on_their_own_but_marketing_and_money_cannot(client):
    uid = await _office_owner(client, "9835000004")
    await _old_lead(uid)
    await _demo_whatsapp(uid)
    assert (await client.patch("/api/office/staff/marketing", json={"autonomy": "act"})).status_code == 400
    assert (await client.patch("/api/office/staff/operations", json={"autonomy": "act"})).status_code == 400   # money waits
    assert (await client.patch("/api/office/staff/sales", json={"autonomy": "act"})).status_code == 200
    run = (await client.post("/api/office/runs", json={"instruction": "Follow up the leads"})).json()
    assert run["steps"][0]["status"] == "done" and "Sent 1 follow-up" in run["steps"][0]["note"]
    msg = await db().outbox.find_one({"kind": "followup", "via": "owner-demo"})
    assert msg and msg["params"][0] == "Ravi" and "modular kitchen" in msg["params"][2]
    lead = await db().leads.find_one({"owner_id": uid})
    assert lead["status"] == "contacted"


async def test_posts_sop_and_tasks_from_one_instruction(client):
    await _office_owner(client, "9835000005")
    run = (await client.post("/api/office/runs", json={"instruction": "Write an SOP for handling a new order, then assign tasks to the team"})).json()
    tools = [s["tool"] for s in run["steps"]]
    assert tools[:2] == ["ops.write_sop", "ops.create_tasks"] and run["status"] == "done"
    sop = (await client.get("/api/kits/sop")).json()
    assert len(sop) == 1 and sop[0]["by_agent"] == "Operations & people"
    tasks = (await client.get("/api/tasks?scope=all")).json()
    assert len(tasks) == 1 and tasks[0]["source"]["kind"] == "office"
    run = (await client.post("/api/office/runs", json={"instruction": "Write next week's posts about our Diwali offer"})).json()
    assert run["steps"][0]["tool"] == "marketing.write_posts" and "Diwali offer" in run["steps"][0]["note"]
    assert await db().outputs.count_documents({"kind": "posts"}) == 1


async def test_money_and_hiring(client):
    uid = await _office_owner(client, "9835000006")
    await db().dues.insert_one({"_id": "due-1", "ws": uid, "customer": "Mrs. Kulkarni", "phone": "9835022222", "amount": 1250000,
                                "due_date": "2026-01-10", "status": "due", "reminders_sent": 0, "last_reminded_at": None, "created_at": now()})
    run = (await client.post("/api/office/runs", json={"instruction": "Remind customers who owe us money"})).json()
    assert [s["tool"] for s in run["steps"]] == ["accounts.remind_overdue", "accounts.money_summary"]
    assert "₹12,500" in run["steps"][1]["note"]
    a = (await client.get("/api/approvals")).json()
    assert a[0]["kind"] == "reminder" and "Mrs. Kulkarni" in a[0]["text"]
    assert (await db().dues.find_one({"_id": "due-1"}))["reminders_sent"] == 1
    run = (await client.post("/api/office/runs", json={"instruction": "We need to hire a sales executive"})).json()
    assert run["steps"][0]["tool"] == "hr.write_jd"
    assert (await client.get("/api/kits/jd")).json()[0]["by_agent"] == "Operations & people"


async def test_a_question_gets_a_written_report(client):
    await _office_owner(client, "9835000007")
    run = (await client.post("/api/office/runs", json={"instruction": "What should I focus on to grow faster?"})).json()
    assert run["steps"][0]["tool"] == "chief.write_report" and run["status"] == "done"
    assert await db().outputs.count_documents({"kind": "report"}) == 1


async def test_running_out_of_ai_runs_stops_the_rest(client):
    uid = await _office_owner(client, "9835000008")
    await db().usage.update_one({"user_id": uid, "month": month_key()}, {"$set": {"used": 5999}}, upsert=True)  # one run left: the plan
    run = (await client.post("/api/office/runs", json={"instruction": "Write an SOP for deliveries and write posts about our new range"})).json()
    assert run["steps"][0]["status"] == "failed" and "used up" in run["steps"][0]["note"]
    assert all(s["status"] == "skipped" for s in run["steps"][1:]) and run["status"] == "failed"


async def test_switched_off_staff(client):
    await _office_owner(client, "9835000009")
    await client.patch("/api/office/staff/operations", json={"on": False})
    run = (await client.post("/api/office/runs", json={"instruction": "Hire a store manager"})).json()
    assert all(s["staff"] != "operations" for s in run["steps"])  # the planner only sees departments that are on
    await client.patch("/api/office/staff/chief", json={"on": False})
    r = await client.post("/api/office/runs", json={"instruction": "Write posts about Holi"})
    assert r.status_code == 400 and "Chief of Staff" in r.json()["detail"]


async def test_standup_now_and_on_schedule(client):
    uid = await _office_owner(client, "9835000010")
    await _old_lead(uid)
    r = await client.post("/api/office/standup")
    assert r.status_code == 200 and "headline" in r.json()
    assert (await client.get("/api/office")).json()["standup"]["content"]["headline"]
    at = datetime(2026, 10, 9, 4, 5, tzinfo=timezone.utc)  # 9:35am IST
    await scheduler.tick(at=at)
    await scheduler.tick(at=at + timedelta(minutes=1))  # same slot: runs once
    log = [e async for e in db().agent_log.find({"ws": uid, "agent": "office_standup"})]
    assert len(log) == 1 and log[0]["status"] == "done"


async def test_hired_roles_take_jobs_from_the_chief_of_staff(client):
    uid = await _office_owner(client, "9835000011")
    r = await client.post("/api/workforce/hire", json={"role_id": 14})   # Competitor Watcher
    assert r.status_code == 200 and r.json()["hired"] == 1
    run = (await client.post("/api/office/runs", json={"instruction": "Ask the competitor watcher what to track about Sharma Interiors"})).json()
    step = run["steps"][0]
    assert step["tool"] == "role.draft" and step["staff"] == "marketing" and step["status"] == "done" and "Competitor Watcher" in step["note"]
    assert await db().outputs.count_documents({"user_id": uid, "kind": "tool:role:14"}) == 1
    # six per department, never more
    for rid in (1, 2, 3, 4, 5):
        assert (await client.post("/api/workforce/hire", json={"role_id": rid})).status_code == 200
    full = await client.post("/api/workforce/hire", json={"role_id": 6})
    assert full.status_code == 400 and "already has 6" in full.json()["detail"]
    assert (await client.post("/api/workforce/release", json={"role_id": 14})).json()["hired"] == 5
    assert (await client.post("/api/tools/role:14/run", json={"inputs": {"brief": "Sharma Interiors"}})).status_code == 400   # released

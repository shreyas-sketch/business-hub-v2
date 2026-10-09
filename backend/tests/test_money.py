"""Money owed: add, list with totals, mark paid, edit, delete — and who may see it."""
from datetime import timedelta

from app.db import IST, db, now
from tests.conftest import PROFILE, new_owner

ADMIN = "9999900000"


async def owner_on(phone: str, plan: str):
    c = await new_owner(phone)
    assert (await c.put("/api/business", json=PROFILE)).status_code == 200
    uid = (await c.get("/api/me")).json()["user"]["id"]
    if plan != "free":
        admin = await new_owner(ADMIN)
        assert (await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})).status_code == 200
    return c, uid


def day(offset: int) -> str:
    return (now().astimezone(IST) + timedelta(days=offset)).strftime("%Y-%m-%d")


async def test_money_owed_crud_and_totals(client):
    c, uid = await owner_on("9834002000", "running")
    empty = (await c.get("/api/money")).json()
    assert empty == {"items": [], "totals": {"due": 0, "overdue": 0, "collected_month": 0, "count_due": 0, "count_overdue": 0}}

    late = await c.post("/api/money", json={"customer": "Ramesh Patel", "phone": "98340 02001", "amount": 12500.5, "due_date": day(-10),
                                            "invoice_no": "SGI-104", "note": "Kitchen balance"})
    assert late.status_code == 200, late.text
    late = late.json()
    assert late["amount"] == 1_250_050 and late["status"] == "due" and late["reminders_sent"] == 0 and late["overdue"] and late["days_overdue"] == 10
    soon = (await c.post("/api/money", json={"customer": "Kiran Shah", "amount": 9000, "due_date": day(5)})).json()
    assert soon["overdue"] is False and soon["phone"] == ""
    today = (await c.post("/api/money", json={"customer": "Asha Rao", "phone": "9834002003", "amount": 1000, "due_date": day(0)})).json()
    assert today["overdue"] is False  # due today is not overdue yet

    body = (await c.get("/api/money")).json()
    assert [i["customer"] for i in body["items"]] == ["Ramesh Patel", "Asha Rao", "Kiran Shah"]  # earliest due first
    assert body["totals"] == {"due": 1_250_050 + 900_000 + 100_000, "overdue": 1_250_050, "collected_month": 0, "count_due": 3, "count_overdue": 1}

    r = await c.patch(f"/api/money/{late['id']}", json={"status": "paid"})
    assert r.status_code == 200 and r.json()["status"] == "paid" and r.json()["paid_at"] and r.json()["overdue"] is False
    body = (await c.get("/api/money")).json()
    assert body["totals"]["collected_month"] == 1_250_050 and body["totals"]["due"] == 1_000_000 and body["totals"]["overdue"] == 0
    assert [i["customer"] for i in body["items"]] == ["Asha Rao", "Kiran Shah", "Ramesh Patel"]  # paid ones last

    r = await c.patch(f"/api/money/{late['id']}", json={"status": "due"})
    assert r.json()["status"] == "due" and r.json()["paid_at"] is None
    await db().dues.update_one({"_id": soon["id"]}, {"$set": {"reminders_sent": 2, "last_reminded_at": now()}})
    r = await c.patch(f"/api/money/{soon['id']}", json={"amount": 9500, "customer": "Kiran Shah & Co", "due_date": day(12), "phone": "9834002002"})
    assert r.json()["amount"] == 950_000 and r.json()["customer"] == "Kiran Shah & Co" and r.json()["reminders_sent"] == 0 and r.json()["phone"] == "9834002002"

    for bad in ({"customer": "X", "amount": 10, "due_date": day(1)}, {"customer": "Ramesh", "amount": 0, "due_date": day(1)},
                {"customer": "Ramesh", "amount": 10, "due_date": "31/10/2026"}, {"customer": "Ramesh", "amount": 10, "due_date": day(1), "phone": "12345"},
                {"customer": "Ramesh", "amount": 1e12, "due_date": day(1)}):
        assert (await c.post("/api/money", json=bad)).status_code == 422, bad
    assert (await c.patch(f"/api/money/{soon['id']}", json={"status": "gone"})).status_code == 422

    assert (await c.delete(f"/api/money/{today['id']}")).status_code == 200
    assert (await c.delete(f"/api/money/{today['id']}")).status_code == 404
    assert (await c.patch(f"/api/money/{today['id']}", json={"status": "paid"})).status_code == 404
    assert len((await c.get("/api/money")).json()["items"]) == 2

    other, _ = await owner_on("9834002010", "running")  # another business never sees or changes these
    assert (await other.get("/api/money")).json()["items"] == []
    assert (await other.patch(f"/api/money/{late['id']}", json={"status": "paid"})).status_code == 404
    assert (await other.delete(f"/api/money/{late['id']}")).status_code == 404


async def test_marking_paid_or_deleting_expires_waiting_reminders(client):
    c, uid = await owner_on("9834002100", "running")
    a = (await c.post("/api/money", json={"customer": "Ramesh Patel", "phone": "9834002101", "amount": 500, "due_date": day(-3)})).json()
    b = (await c.post("/api/money", json={"customer": "Kiran Shah", "phone": "9834002102", "amount": 700, "due_date": day(-3)})).json()
    from app.agents import scheduler
    tick_at = now().astimezone(IST).replace(hour=10, minute=5) + timedelta(days=1)
    await c.patch("/api/agents/digest", json={"on": False})
    await c.patch("/api/agents/weekly_posts", json={"on": False})
    await scheduler.tick(at=tick_at)
    assert await db().approvals.count_documents({"status": "pending", "kind": "reminder"}) == 2
    await c.patch(f"/api/money/{a['id']}", json={"status": "paid"})
    await c.delete(f"/api/money/{b['id']}")
    assert await db().approvals.count_documents({"status": "pending"}) == 0
    assert await db().approvals.count_documents({"status": "expired", "kind": "reminder"}) == 2
    assert (await c.get("/api/me")).json()["approvals_waiting"] == 0


async def test_money_owed_needs_running_the_business_and_a_manager(client):
    lite, lite_uid = await owner_on("9834002200", "program")
    r = await lite.get("/api/money")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "locked" and r.json()["detail"]["tier"] == "running"
    assert (await lite.post("/api/money", json={"customer": "Ramesh", "amount": 10, "due_date": day(1)})).status_code == 403

    owner, uid = await owner_on("9834002201", "growth")
    staff = await new_owner("9834002202")
    await db().users.update_one({"_id": (await staff.get("/api/me")).json()["user"]["id"]}, {"$set": {"team_of": uid, "team_role": "staff"}})
    manager = await new_owner("9834002203")
    await db().users.update_one({"_id": (await manager.get("/api/me")).json()["user"]["id"]}, {"$set": {"team_of": uid, "team_role": "manager"}})
    assert (await staff.get("/api/money")).status_code == 403
    assert (await staff.post("/api/money", json={"customer": "Ramesh", "amount": 10, "due_date": day(1)})).status_code == 403
    r = await manager.post("/api/money", json={"customer": "Ramesh Patel", "amount": 10, "due_date": day(1)})
    assert r.status_code == 200
    d = await db().dues.find_one({"_id": r.json()["id"]})
    assert d["ws"] == uid and d["created_by"] != uid
    assert [i["customer"] for i in (await owner.get("/api/money")).json()["items"]] == ["Ramesh Patel"]
    assert (await manager.delete(f"/api/money/{d['_id']}")).status_code == 200

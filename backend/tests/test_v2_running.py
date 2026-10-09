"""v2 — Running the Business: customers (A/B/C), quotations and invoices with GST, quote follow-ups, the customer desk,
and the Employz.ai CRM starter (sync out, webhook in). Every customer message waits in the Send list."""
import json
from datetime import datetime, timedelta

import httpx

from app import integrations
from app.agents import scheduler
from app.db import IST, db
from tests.conftest import PROFILE, go_live, new_owner

ADMIN = "9999900000"
QUIET = ("week_plan", "calendar_auto", "digest", "payment_reminder", "quote_followup", "customer_desk", "ceo_report", "monthly_review",
         "results", "recall")


def ist(*a) -> datetime:
    return datetime(*a, tzinfo=IST)


async def owner_on(phone: str, plan: str = "running", live: bool = True):
    c = await new_owner(phone)
    site = await go_live(c) if live else None
    if not live:
        assert (await c.put("/api/business", json=PROFILE)).status_code == 200
    uid = (await c.get("/api/me")).json()["user"]["id"]
    if plan != "free":
        admin = await new_owner(ADMIN)
        assert (await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})).status_code == 200
    return c, uid, site


async def quiet(c, *keys):
    for k in keys:
        assert (await c.patch(f"/api/agents/{k}", json={"on": False})).status_code in (200, 403), k


async def pending(c):
    return (await c.get("/api/approvals?status=pending")).json()


async def test_customers_sorted_into_a_b_c_by_value(client):
    prog, _, _ = await owner_on("9839000001", "program", live=False)
    assert (await prog.get("/api/customers")).status_code == 403
    c, _, _ = await owner_on("9839000002", live=False)
    for name, phone, value in (("Mehta family", "98390 10001", 700000), ("Shah", "98390 10002", 200000), ("Iyer", "98390 10003", 60000),
                               ("Rao", "98390 10004", 40000)):
        r = await c.post("/api/customers", json={"name": name, "phone": phone, "total_value": value, "last_purchase": "2026-08-01"})
        assert r.status_code == 200, r.text
    assert (await c.post("/api/customers", json={"name": "Dup", "phone": "98390 10001"})).status_code == 409
    assert (await c.post("/api/customers", json={"name": "Bad", "phone": "12345"})).status_code == 400
    d = (await c.get("/api/customers")).json()
    assert {x["name"]: x["tier"] for x in d["items"]} == {"Mehta family": "A", "Shah": "B", "Iyer": "C", "Rao": "C"}
    assert d["counts"] == {"A": 1, "B": 1, "C": 2} and d["can_import"] is False
    assert d["items"][0]["days_since"] >= 0
    rao = next(x for x in d["items"] if x["name"] == "Rao")
    await c.patch(f"/api/customers/{rao['id']}", json={"total_value": 900000})
    tiers = {x["name"]: x["tier"] for x in (await c.get("/api/customers")).json()["items"]}
    assert tiers["Rao"] == "A" and tiers["Mehta family"] == "A"
    assert (await c.post("/api/customers/import", files={"file": ("x.csv", b"Name,Mobile\nA,9839000000\n", "text/csv")})).status_code == 403


async def test_customer_import_cleans_merges_and_sorts(client):
    c, _, _ = await owner_on("9839000003", "growth", live=False)
    csv_bytes = ("Contact No,Customer Name,Total spent,Last purchase,Birthday\n"
                 "98390 20001,Kavita Desai,\"1,50,000\",12/03/2026,14-11-1985\n"
                 "9839020002,Arjun Rao,40000,2026-01-05,\n"
                 "+91 98390 20001,Kavita Desai,50000,2026-06-01,\n"
                 "12345,Not a number,9000,,\n"
                 ",No phone,100,,\n").encode()
    r = await c.post("/api/customers/import", files={"file": ("old customers.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 2, "merged": 1, "skipped": 2, "tiers": {"A": 1, "B": 1, "C": 0}}
    k = await db().customers.find_one({"name": "Kavita Desai"})
    assert k["total_value"] == 200000 and k["last_purchase"] == "2026-06-01" and k["occasion"] == {"label": "birthday", "date": "11-14"}
    bad = await c.post("/api/customers/import", files={"file": ("x.csv", b"Foo,Bar\n1,2\n", "text/csv")})
    assert bad.status_code == 400 and "name column" in bad.json()["detail"]
    assert (await c.post("/api/customers/import", files={"file": ("x.pdf", b"%PDF", "application/pdf")})).status_code == 415


async def test_quotation_gst_invoice_and_money_owed(client):
    c, uid, site = await owner_on("9839000004")
    await quiet(c, *QUIET)
    assert (await c.put("/api/quotes/settings", json={"gstin": "27ABCDE1234F1Z5", "address": "Thane West", "payment": "UPI sgi@okicici",
                                                      "terms": "50% advance"})).status_code == 200
    d = (await c.post("/api/quotes/draft", json={"brief": "Kitchen for Mr Shah: 10 ft modular kitchen, chimney, installation"})).json()
    assert d["items"] and "missing_rates" in d

    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Rohit Shah", "phone": "98390 30001", "message": "Kitchen"})
    lead = await db().leads.find_one({"owner_id": uid})
    body = {"customer": {"name": "Rohit Shah", "phone": "98390 30001"}, "lead_id": lead["_id"],
            "items": [{"name": "Modular kitchen 10 ft", "qty": 1, "unit": "set", "rate": 185000, "gst": 18},
                      {"name": "Chimney", "qty": 1, "rate": 22000, "gst": 28}]}
    q = (await c.post("/api/quotes", json=body)).json()
    assert q["number"] == "Q-0001" and q["status"] == "draft" and q["terms"] == "50% advance"
    t = q["totals"]
    assert t["subtotal"] == 207000 and t["gst"] == 33300 + 6160 and t["cgst"] + t["sgst"] == t["gst"] and t["total"] == 246460 and t["igst"] == 0
    assert "Total: ₹2,46,460" in q["share_text"] and q["whatsapp_link"].startswith("https://wa.me/919839030001?text=")
    q2 = (await c.post("/api/quotes", json={**body, "gst_mode": "inter", "lead_id": None})).json()
    assert q2["number"] == "Q-0002" and q2["totals"]["igst"] == 39460 and q2["totals"]["cgst"] == 0
    page = await c.get(f"/api/quotes/{q['id']}/print")
    assert page.status_code == 200 and "27ABCDE1234F1Z5" in page.text and "Q-0001" in page.text

    sent = (await c.post(f"/api/quotes/{q['id']}/status", json={"status": "sent"})).json()
    assert sent["sent_on"]
    inv = (await c.post(f"/api/quotes/{q['id']}/invoice", json={"due_in_days": 7})).json()
    assert inv["kind"] == "invoice" and inv["number"] == "INV-0001" and inv["status"] == "due"
    assert (await c.post(f"/api/quotes/{q['id']}/invoice", json={})).status_code == 409
    [due] = (await c.get("/api/money")).json()["items"]
    assert due["invoice_no"] == "INV-0001" and due["amount"] == 24646000 and due["invoice_id"] == inv["id"]   # paise
    assert (await c.delete(f"/api/quotes/{inv['id']}")).status_code == 400
    assert (await c.put(f"/api/quotes/{q['id']}", json=body)).status_code == 400            # accepted: closed
    assert (await c.patch(f"/api/money/{due['id']}", json={"status": "paid"})).status_code == 200
    assert (await db().quotes.find_one({"_id": inv["id"]}))["status"] == "paid"

    # an accepted quotation wins the lead, and the won lead becomes a customer
    lead = await db().leads.find_one({"_id": lead["_id"]})
    assert lead["status"] == "won" and lead["value"] == 246460
    cust = await db().customers.find_one({"ws": uid, "phone": lead["phone"]})
    assert cust and cust["source"] == "won lead" and cust["total_value"] == 246460


async def test_quote_followups_on_day_2_5_10_wait_and_stop_when_closed(client):
    c, uid, _ = await owner_on("9839000005", live=False)
    await quiet(c, *[k for k in QUIET if k != "quote_followup"])
    q = (await c.post("/api/quotes", json={"customer": {"name": "Sunita Kulkarni", "phone": "98390 40001"},
                                           "items": [{"name": "Wardrobe", "qty": 2, "rate": 60000}]})).json()
    other = (await c.post("/api/quotes", json={"customer": {"name": "Draft only", "phone": "98390 40002"},
                                               "items": [{"name": "Bed", "qty": 1, "rate": 30000}]})).json()
    await db().quotes.update_one({"_id": q["id"]}, {"$set": {"status": "sent", "sent_on": "2026-10-01"}})
    await scheduler.tick(at=ist(2026, 10, 2, 11, 5))           # day 1: nothing
    assert await pending(c) == []
    await scheduler.tick(at=ist(2026, 10, 3, 11, 5))           # day 2
    [a] = await pending(c)
    assert a["kind"] == "quote" and a["money"] and a["title"].startswith("Follow-up 1 of 3 on quotation Q-0001")
    assert "Q-0001" in a["text"] and a["own_link"].startswith("https://wa.me/919839040001")
    await scheduler.tick(at=ist(2026, 10, 3, 15, 0))           # same day again: no duplicate
    assert len(await pending(c)) == 1
    r = await c.post(f"/api/approvals/{a['id']}/own")
    assert r.status_code == 200 and (await db().quotes.find_one({"_id": q["id"]}))["followups"] == 1
    await scheduler.tick(at=ist(2026, 10, 6, 11, 5))           # day 5
    [b] = await pending(c)
    assert b["title"].startswith("Follow-up 2 of 3")
    await c.post(f"/api/quotes/{q['id']}/status", json={"status": "lost"})
    assert await pending(c) == []                              # closed: the waiting follow-up expires
    await scheduler.tick(at=ist(2026, 10, 11, 11, 5))
    assert await pending(c) == [] and await db().approvals.count_documents({"quote_id": other["id"]}) == 0


async def test_quote_followups_never_go_out_on_their_own_even_at_legacyworkforce(client):
    c, uid, _ = await owner_on("9839000006", "office", live=False)
    await quiet(c, *[k for k in QUIET if k != "quote_followup"])
    from tests.test_agents import connect_demo_whatsapp
    await connect_demo_whatsapp(uid)
    assert (await c.patch("/api/agents/quote_followup", json={"on": True, "autonomy": "act"})).status_code == 200
    q = (await c.post("/api/quotes", json={"customer": {"name": "A B", "phone": "98390 40003"}, "items": [{"name": "X", "qty": 1, "rate": 100}]})).json()
    await db().quotes.update_one({"_id": q["id"]}, {"$set": {"status": "sent", "sent_on": "2026-10-01"}})
    await scheduler.tick(at=ist(2026, 10, 3, 11, 5))
    [a] = await pending(c)
    assert a["status"] == "pending" and await db().outbox.count_documents({"kind": "quote"}) == 0


async def test_customer_desk_reorders_greetings_referrals_and_quiet_customers(client):
    c, uid, _ = await owner_on("9839000007", live=False)
    await quiet(c, *[k for k in QUIET if k != "customer_desk"])
    day = ist(2026, 10, 20, 11, 35)

    async def add(name, phone, **kw):
        r = await c.post("/api/customers", json={"name": name, "phone": phone, "total_value": 50000, **kw})
        assert r.status_code == 200, r.text
        return r.json()
    await add("Priya Nair", "98390 50001", last_purchase="2026-05-01", occasion={"label": "birthday", "date": "10-20"})
    await add("Vikram Joshi", "98390 50002", last_purchase="2026-09-22", reorder_days=30, last_item="water purifier service")
    await add("Anita Gupta", "98390 50003", last_purchase="2026-10-08")
    await add("Rakesh Iyer", "98390 50004", last_purchase="2026-06-01", purchases=3)
    await add("New today", "98390 50005", last_purchase="2026-10-19")
    opted = await add("Opted out", "98390 50006", last_purchase="2026-05-01", occasion={"label": "birthday", "date": "10-20"})
    await c.patch(f"/api/customers/{opted['id']}", json={"opted_out": True})

    await scheduler.tick(at=day)
    items = {a["to_name"]: a for a in await pending(c)}
    assert set(items) == {"Priya Nair", "Vikram Joshi", "Anita Gupta", "Rakesh Iyer"}
    assert all(a["kind"] == "customer" and not a["money"] for a in items.values())
    assert "birthday" in items["Priya Nair"]["text"] and "reorder for water purifier service" in items["Vikram Joshi"]["text"]
    assert "share our number" in items["Anita Gupta"]["text"] and "been a while" in items["Rakesh Iyer"]["text"]
    await scheduler.tick(at=day + timedelta(hours=3))            # once a day
    assert len(await pending(c)) == 4
    await scheduler.tick(at=ist(2026, 10, 21, 11, 35))           # tomorrow: each was asked already
    assert len(await pending(c)) == 4
    agent = next(a for a in (await c.get("/api/agents")).json()["agents"] if a["key"] == "customer_desk")
    assert "Send list" in agent["last_note"] or agent["last_status"] in ("done", "skipped")


# ───────────────────────── Employz.ai ─────────────────────────
class FakeEmployz:
    def __init__(self):
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/contacts/upsert"):
            return httpx.Response(200, json={"contact": {"id": "ct_1"}})
        if path.endswith("/opportunities/") and request.method == "POST":
            return httpx.Response(201, json={"opportunity": {"id": "op_1"}})
        if "/opportunities/op_1" in path and request.method == "PUT":
            return httpx.Response(200, json={"opportunity": {"id": "op_1"}})
        if path.endswith("/opportunities/pipelines"):
            return httpx.Response(200, json={"pipelines": [{"name": "Football Field"}]})
        return httpx.Response(404, json={})


async def test_employz_crm_sync_and_webhook(client, monkeypatch):
    fake = FakeEmployz()
    monkeypatch.setattr(integrations, "TRANSPORT", httpx.MockTransport(fake))
    c, uid, site = await owner_on("9839000008")
    await quiet(c, *QUIET)
    assert (await c.post("/api/crm/sync")).status_code == 400              # not connected yet
    r = await c.put("/api/connections/employz", json={"values": {"location_id": "x"}})   # the owner may start it; the team finishes it
    assert r.status_code == 200 and r.json()["connected"] is False
    admin = await new_owner(ADMIN)
    stages = {f"stage_{k}": f"st_{k}" for k in ("identification", "logic", "pain", "vision", "close")}
    r = await admin.put(f"/api/admin/owners/{uid}/connections/employz",
                        json={"values": {"location_id": "loc_9", "token": "pit-secret", "pipeline_id": "pipe_1", **stages,
                                         "app_link": "https://app.employz.ai/v2/location/loc_9"}})
    assert r.status_code == 200, r.text
    view = r.json()
    tok = next(f for f in view["fields"] if f["key"] == "token")
    assert view["connected"] and tok["set"] is True and tok["value"] == ""
    stored = (await db().connections.find_one({"_id": uid}))["employz"]
    assert stored["token"] != "pit-secret"                                   # encrypted at rest

    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Neha Joshi", "phone": "98340 00001", "message": "Kitchen please"})
    lead = await db().leads.find_one({"owner_id": uid})
    assert lead["crm"]["contact_id"] == "ct_1" and lead["crm"]["opportunity_id"] == "op_1" and lead["crm"]["error"] is None
    up, opp = fake.calls[0], fake.calls[1]
    assert up.headers["Authorization"] == "Bearer pit-secret" and up.headers["Version"] == "2021-07-28"
    assert json.loads(up.content) == {"locationId": "loc_9", "firstName": "Neha", "lastName": "Joshi", "phone": "+919834000001",
                                      "source": "Action Hub · website", "tags": ["action-hub", "website"]}
    ob = json.loads(opp.content)
    assert ob["pipelineId"] == "pipe_1" and ob["pipelineStageId"] == "st_identification" and ob["contactId"] == "ct_1" and ob["status"] == "open"

    await c.patch(f"/api/leads/{lead['_id']}", json={"stage": "vision", "value": 300000})
    put = fake.calls[-1]
    assert put.method == "PUT" and put.url.path.endswith("/opportunities/op_1")
    assert json.loads(put.content) == {"pipelineStageId": "st_vision", "status": "open", "monetaryValue": 300000.0}
    crm = (await c.get("/api/crm")).json()
    assert crm["ready"] and crm["synced"] == 1 and crm["open_link"].startswith("https://app.employz.ai")

    # Employz.ai tells the hub when the deal moves there
    token = stored["webhook_token"]
    assert (await client.post("/api/hooks/employz/wrong", json={})).status_code == 404
    r = await client.post(f"/api/hooks/employz/{token}", json={"opportunity_id": "op_1", "pipeline_stage_id": "st_close", "status": "won",
                                                               "monetary_value": "320000"})
    assert r.json() == {"ok": True, "matched": True, "changed": ["stage", "status", "updated_at", "value"]}
    lead = await db().leads.find_one({"_id": lead["_id"]})
    assert lead["stage"] == "close" and lead["status"] == "won" and lead["value"] == 320000
    assert await db().customers.find_one({"ws": uid, "phone": lead["phone"]})
    r = await client.post(f"/api/hooks/employz/{token}", json={"phone": "98340 99999", "status": "won"})
    assert r.json() == {"ok": True, "matched": False}

    # a failure is recorded on the lead, and Sync now retries
    monkeypatch.setattr(integrations, "TRANSPORT", httpx.MockTransport(lambda req: httpx.Response(401, json={})))
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Kiran", "phone": "98340 00002", "message": "Hi"})
    kiran = await db().leads.find_one({"owner_id": uid, "name": "Kiran"})
    assert kiran["crm"]["error"] == "contact 401"
    monkeypatch.setattr(integrations, "TRANSPORT", httpx.MockTransport(fake))
    assert (await c.post("/api/crm/sync")).json() == {"tried": 1, "synced": 1}

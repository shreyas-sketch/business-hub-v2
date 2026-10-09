"""v2 — Growth Mentorship (6 AI staff, done-for-you setup, WhatsApp chats on the owner's number, the AI Telecaller,
Company Brain, money campaigns, Control Room, Sales Training Gym, AI results) and LegacyWorkforce (30 AI staff from 82 roles).
Integration request shapes (AiSensy, ElevenLabs) are checked against a fake server."""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta

import httpx
import pytest

from app import connections, integrations, roles_catalog
from app.agents import scheduler
from app.config import settings
from app.db import IST, db, now
from tests.conftest import PROFILE, go_live, new_owner
from tests.test_agents import connect_demo_whatsapp

ADMIN = "9999900000"
QUIET = ("week_plan", "calendar_auto", "digest", "payment_reminder", "quote_followup", "customer_desk", "ceo_report", "monthly_review",
         "results", "recall")


def ist(*a) -> datetime:
    return datetime(*a, tzinfo=IST)


async def owner_on(phone: str, plan: str = "growth", live: bool = True):
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


def meta_message(frm: str, text: str, mid: str, name: str = "Neha") -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": frm, "profile": {"name": name}}],
        "messages": [{"from": frm, "id": mid, "type": "text", "text": {"body": text}}]}}]}]}


@pytest.fixture
def setting():
    changed = []

    def set_(name, value):
        changed.append((name, getattr(settings, name)))
        object.__setattr__(settings, name, value)
    yield set_
    for name, old in reversed(changed):
        object.__setattr__(settings, name, old)


# ───────────────────────── the 6 AI staff and the setup ─────────────────────────
async def test_six_ai_staff_and_the_done_for_you_setup(client):
    prog, _, _ = await owner_on("9840000001", "program", live=False)
    assert (await prog.get("/api/staff")).status_code == 403
    c, uid, _ = await owner_on("9840000002", live=False)
    d = (await c.get("/api/staff")).json()
    assert [s["key"] for s in d["staff"]] == ["sales", "telecaller", "marketing", "accounts", "care", "chief"]
    assert d["connections"] == {"whatsapp": False, "voice": False, "employz": False}
    sales = d["staff"][0]
    assert sales["on"] and "instant_reply" in sales["agents"]
    assert (await c.patch("/api/staff/sales", json={"on": False})).json()["on"] is False
    agents = {a["key"]: a for a in (await c.get("/api/agents")).json()["agents"]}
    assert all(not agents[k]["on"] for k in sales["agents"] if k in agents)

    setup = (await c.get("/api/setup")).json()
    assert setup["total"] == 10 and setup["done"] == 0 and setup["steps"][0]["month"] == 1
    admin = await new_owner(ADMIN)
    step = setup["steps"][0]["key"]
    r = await admin.put(f"/api/admin/owners/{uid}/setup/{step}", json={"done": True, "note": "Snapshot loaded"})
    assert r.status_code == 200 and r.json()["done"] == 1
    me = (await c.get("/api/me")).json()
    assert any(n["text"].startswith("Set up for you:") for n in me["notices"])
    assert (await admin.put(f"/api/admin/owners/{uid}/setup/nope", json={"done": True})).status_code == 404


# ───────────────────────── connections ─────────────────────────
async def test_connections_are_encrypted_and_never_shown(client):
    c, uid, _ = await owner_on("9840000003", live=False)
    r = await c.put("/api/connections/whatsapp", json={"values": {"provider": "aisensy", "number": "98200 12345", "api_key": "ais-secret-key",
                                                                   "tpl_instant": "instant_v1", "unknown": "x"}})
    assert r.status_code == 200, r.text
    v = r.json()
    key = next(f for f in v["fields"] if f["key"] == "api_key")
    assert v["connected"] and key == {**key, "set": True, "value": ""} and v["webhook"].startswith("https://hub.example.in/api/hooks/whatsapp/")
    raw = (await db().connections.find_one({"_id": uid}))["whatsapp"]
    assert raw["api_key"] != "ais-secret-key" and "unknown" not in raw
    assert (await connections.get(uid, "whatsapp"))["api_key"] == "ais-secret-key"
    # saving again without the secret keeps it; null clears it
    await c.put("/api/connections/whatsapp", json={"values": {"tpl_followup": "followup_v1", "api_key": ""}})
    assert (await connections.get(uid, "whatsapp"))["api_key"] == "ais-secret-key"
    await c.put("/api/connections/whatsapp", json={"values": {"api_key": None}})
    assert not (await connections.get(uid, "whatsapp")).get("api_key")
    assert (await c.put("/api/connections/whatsapp", json={"values": {"provider": "carrier-pigeon"}})).status_code == 400
    assert (await c.put("/api/connections/tally", json={"values": {"bridge_url": "x"}})).status_code == 403   # LegacyWorkforce only
    kinds = [x["kind"] for x in (await c.get("/api/connections")).json()]
    assert kinds[:3] == ["whatsapp", "employz", "voice"]


async def test_aisensy_and_meta_request_shapes(client, monkeypatch):
    seen: list[httpx.Request] = []

    def fake(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})
    monkeypatch.setattr(integrations, "TRANSPORT", httpx.MockTransport(fake))
    conn = {"provider": "aisensy", "api_key": "K", "project_id": "P1", "project_password": "PW"}
    r = await integrations.wa_template("ws", conn, "98200 00001", "followup_v1", ["Neha", "Shree Ganesh", "Hello  there\n"], "Neha Joshi", "followup")
    assert r == {"sent": True, "via": "owner-whatsapp", "id": "wamid.1", "error": None}
    assert str(seen[0].url) == integrations.AISENSY_CAMPAIGN_URL
    assert json.loads(seen[0].content) == {"apiKey": "K", "campaignName": "followup_v1", "destination": "919820000001", "userName": "Neha Joshi",
                                           "templateParams": ["Neha", "Shree Ganesh", "Hello there"], "source": "action-hub"}
    await integrations.wa_text("ws", conn, "+91 98200 00001", "Thanks!")
    assert str(seen[1].url) == f"{settings.aisensy_project_api_base}/project/P1/messages" and seen[1].headers["X-AiSensy-Project-API-Pwd"] == "PW"
    assert json.loads(seen[1].content) == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "919820000001", "type": "text",
                                           "text": {"preview_url": False, "body": "Thanks!"}}
    meta = {"provider": "meta", "phone_number_id": "PN", "access_token": "T", "language": "en"}
    await integrations.wa_template("ws", meta, "9820000001", "review_v1", ["Neha"], "", "review")
    assert str(seen[2].url) == f"{settings.whatsapp_graph_base}/PN/messages" and seen[2].headers["Authorization"] == "Bearer T"
    body = json.loads(seen[2].content)
    assert body["template"]["name"] == "review_v1" and body["template"]["components"][0]["parameters"] == [{"type": "text", "text": "Neha"}]
    monkeypatch.setattr(integrations, "TRANSPORT", httpx.MockTransport(lambda req: httpx.Response(400, json={"error": "x"})))
    assert (await integrations.wa_text("ws", conn, "9820000001", "x"))["sent"] is False
    assert (await integrations.wa_text("ws", {"provider": "aisensy", "api_key": "K"}, "9820000001", "x"))["error"].startswith("Add the AiSensy project")


async def test_elevenlabs_call_shape_and_signature(client, monkeypatch):
    seen = []

    def fake(req):
        seen.append(req)
        return httpx.Response(200, json={"success": True, "conversation_id": "conv_1", "callSid": "CA1"})
    monkeypatch.setattr(integrations, "TRANSPORT", httpx.MockTransport(fake))
    conn = {"api_key": "xi", "agent_id": "ag", "phone_number_id": "ph", "mode": "twilio"}
    r = await integrations.voice_call("ws", conn, "98340 00001", {"lead_name": "Neha", "lead_id": "L1"})
    assert r == {"ok": True, "conversation_id": "conv_1"}
    assert seen[0].url.path == "/v1/convai/twilio/outbound-call" and seen[0].headers["xi-api-key"] == "xi"
    assert json.loads(seen[0].content) == {"agent_id": "ag", "agent_phone_number_id": "ph", "to_number": "+919834000001",
                                           "conversation_initiation_client_data": {"dynamic_variables": {"lead_name": "Neha", "lead_id": "L1"}}}
    await integrations.voice_call("ws", {**conn, "mode": "sip"}, "9834000001", {})
    assert seen[1].url.path == "/v1/convai/sip-trunk/outbound-call"
    body = b'{"type":"post_call_transcription"}'
    t = int(time.time())
    sig = hmac.new(b"whsec", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    assert integrations.elevenlabs_signature_ok("whsec", f"t={t},v0={sig}", body)
    assert not integrations.elevenlabs_signature_ok("whsec", f"t={t},v0={sig}", body + b" ")
    assert not integrations.elevenlabs_signature_ok("whsec", f"t={t - 4000},v0={sig}", body)
    assert not integrations.elevenlabs_signature_ok("", f"t={t},v0={sig}", body)


# ───────────────────────── WhatsApp chats on the owner's number ─────────────────────────
async def test_whatsapp_ai_replies_hands_over_and_the_team_replies(client, setting):
    c, uid, _ = await owner_on("9840000004", live=False)
    await connect_demo_whatsapp(uid)
    token = (await db().connections.find_one({"_id": uid}))["whatsapp"]["webhook_token"]
    v = await client.get(f"/api/hooks/whatsapp/{token}", params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "42"})
    assert v.text == "42"
    assert (await client.get(f"/api/hooks/whatsapp/{token}", params={"hub.mode": "subscribe", "hub.verify_token": "x"})).status_code == 403
    assert (await client.post("/api/hooks/whatsapp/nope", json={})).status_code == 404

    r = await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000201", "Hi, what is the price of a modular kitchen?", "m1"))
    assert r.json() == {"ok": True, "handled": 1}
    [t] = (await c.get("/api/chats")).json()["threads"]
    assert t["name"] == "Neha" and t["intent"] == "sales" and not t["needs_person"]
    chat = (await c.get(f"/api/chats/{t['id']}")).json()
    assert [m["dir"] for m in chat["messages"]] == ["in", "out"] and "₹1,85,000" in chat["messages"][1]["text"] and chat["can_reply"]
    out = await db().outbox.find_one({"kind": "chat", "ws": uid})
    assert out["to"] == "919834000201" and out["via"] == "owner-demo"
    await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000201", "Hi, what is the price of a modular kitchen?", "m1"))
    assert await db().wa_messages.count_documents({"thread_id": t["id"]}) == 2     # WhatsApp retried: no duplicate

    await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000201", "Great, I want to book a site visit", "m2"))
    t = (await c.get(f"/api/chats/{t['id']}")).json()["thread"]
    assert t["needs_person"] and t["handover_reason"] == "Ready to go ahead"
    lead = await db().leads.find_one({"owner_id": uid, "source": "whatsapp"})
    assert lead and lead["stage"] == "logic" and lead["phone"] == "+919834000201"
    alert = await db().outbox.find_one({"kind": "owner_alert"})
    assert alert["to"] == "+919840000004"          # from the hub's number, to the owner only
    await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000201", "Saturday works", "m3"))
    assert await db().wa_messages.count_documents({"thread_id": t["id"], "dir": "out"}) == 2   # a person has it now: AI quiet
    assert (await c.post(f"/api/chats/{t['id']}/reply", json={"text": "Booked for Saturday 11am. — Suresh"})).json() == {"ok": True}
    msgs = (await c.get(f"/api/chats/{t['id']}")).json()["messages"]
    assert msgs[-1]["text"].startswith("Booked") and msgs[-1]["by"] != "ai"
    # back to the AI
    t = (await c.patch(f"/api/chats/{t['id']}", json={"ai_on": True})).json()
    assert not t["needs_person"]

    # outside the 24-hour window only a template may go: the reply box refuses
    await db().wa_threads.update_one({"_id": t["id"]}, {"$set": {"last_in_at": now() - timedelta(hours=25)}})
    r = await c.post(f"/api/chats/{t['id']}/reply", json={"text": "Hello?"})
    assert r.status_code == 400 and "24 hours" in r.json()["detail"]

    # an unhappy customer goes to Customer Care and straight to a person; the daily AI cap per chat
    await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000299", "The hinge is broken, this is a problem", "m9", "Ravi"))
    ravi = next(x for x in (await c.get("/api/chats")).json()["threads"] if x["name"] == "Ravi")
    assert ravi["intent"] == "support" and ravi["needs_person"]
    setting("ai_replies_per_chat_per_day", 1)
    await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000300", "hello", "n1", "Asha"))
    await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000300", "anyone there?", "n2", "Asha"))
    asha = next(x for x in (await c.get("/api/chats")).json()["threads"] if x["name"] == "Asha")
    assert await db().wa_messages.count_documents({"thread_id": asha["id"], "dir": "out"}) == 1
    # the owner can switch the AI off for all chats
    await c.post("/api/chats-ai", json={"on": False})
    await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000301", "price?", "p1", "Om"))
    om = next(x for x in (await c.get("/api/chats")).json()["threads"] if x["name"] == "Om")
    assert await db().wa_messages.count_documents({"thread_id": om["id"], "dir": "out"}) == 0


async def test_meta_webhook_signature(client):
    c, uid, _ = await owner_on("9840000005", live=False)
    await c.put("/api/connections/whatsapp", json={"values": {"provider": "meta", "phone_number_id": "PN", "access_token": "T",
                                                              "app_secret": "appsecret"}})
    token = (await db().connections.find_one({"_id": uid}))["whatsapp"]["webhook_token"]
    body = json.dumps(meta_message("919834000400", "hello", "z1")).encode()
    bad = await client.post(f"/api/hooks/whatsapp/{token}", content=body, headers={"content-type": "application/json", "x-hub-signature-256": "sha256=00"})
    assert bad.status_code == 401
    good = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    assert (await client.post(f"/api/hooks/whatsapp/{token}", content=body,
                              headers={"content-type": "application/json", "x-hub-signature-256": good})).status_code == 200


async def test_whatsapp_chats_locked_below_growth(client):
    c, uid, _ = await owner_on("9840000006", "running", live=False)
    assert (await c.get("/api/chats")).status_code == 403
    await connect_demo_whatsapp(uid)     # even a stored connection doesn't let a lower plan reply
    token = (await db().connections.find_one({"_id": uid}))["whatsapp"]["webhook_token"]
    await client.post(f"/api/hooks/whatsapp/{token}", json=meta_message("919834000500", "price?", "q1"))
    assert await db().wa_messages.count_documents({"ws": uid, "dir": "out"}) == 0


# ───────────────────────── the AI Telecaller ─────────────────────────
async def test_telecaller_calls_new_leads_in_hours_and_the_call_comes_back(client):
    c, uid, site = await owner_on("9840000007")
    await quiet(c, *QUIET, "followup")
    await db().connections.update_one({"_id": uid}, {"$set": {"voice": {"provider": "demo", "webhook_token": "voice-token-0123456789",
                                                                        "webhook_secret": connections.seal("whsec"), "hours": "10-19"}}}, upsert=True)
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Neha Joshi", "phone": "98340 00601", "message": "Kitchen"})
    lead = await db().leads.find_one({"owner_id": uid})
    [job] = [j async for j in db().agent_jobs.find({"agent": "telecaller", "ws": uid})]
    local = job["run_at"].astimezone(IST)
    assert 10 <= local.hour < 19
    await scheduler.tick(at=job["run_at"] + timedelta(minutes=1))
    call = await db().calls.find_one({"ws": uid})
    assert call and call["status"] == "calling" and call["lead_id"] == lead["_id"]
    sent = await db().outbox.find_one({"channel": "voice", "ws": uid})
    assert sent["to"] == "919834000601" and sent["params"]["lead_name"] == "Neha"

    payload = {"type": "post_call_transcription", "data": {
        "conversation_id": call["conversation_id"], "metadata": {"call_duration_secs": 95},
        "conversation_initiation_client_data": {"dynamic_variables": {"lead_id": lead["_id"]}},
        "analysis": {"transcript_summary": "Wants a kitchen by Diwali; site visit booked for Saturday.", "call_successful": "success"},
        "transcript": [{"role": "agent", "message": "Hello Neha, calling from Shree Ganesh Interiors. Is this a good time?"},
                       {"role": "user", "message": "Yes, tell me the price."},
                       {"role": "agent", "message": "It depends on size. What size is your kitchen? Shall we book a visit on Saturday?"},
                       {"role": "user", "message": "Okay, Saturday."}]}}
    body = json.dumps(payload).encode()
    assert (await client.post("/api/hooks/voice/voice-token-0123456789", content=body, headers={"elevenlabs-signature": "t=1,v0=00"})).status_code == 401
    t = int(time.time())
    sig = hmac.new(b"whsec", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    r = await client.post("/api/hooks/voice/voice-token-0123456789", content=body, headers={"elevenlabs-signature": f"t={t},v0={sig}", "content-type": "application/json"})
    assert r.status_code == 200, r.text
    call = await db().calls.find_one({"_id": call["_id"]})
    assert call["status"] == "done" and call["duration"] == 95 and len(call["transcript"]) == 4 and call["score"]["overall"] > 0
    lead = await db().leads.find_one({"_id": lead["_id"]})
    assert lead["status"] == "contacted" and "[AI call" in lead["note"] and "Saturday" in lead["note"]
    staff = (await c.get("/api/staff")).json()
    assert staff["calls"][0]["summary"].startswith("Wants a kitchen")

    # won leads are never called
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Kiran", "phone": "98340 00602", "message": "Bed"})
    kiran = await db().leads.find_one({"owner_id": uid, "name": "Kiran"})
    await c.patch(f"/api/leads/{kiran['_id']}", json={"status": "won"})
    assert await db().agent_jobs.count_documents({"agent": "telecaller", "payload.lead_id": kiran["_id"], "status": "scheduled"}) == 0


# ───────────────────────── Company Brain ─────────────────────────
async def test_company_brain_documents_answer_questions_and_feed_tools(client):
    c, uid, _ = await owner_on("9840000008", live=False)
    text = "PRICE LIST 2026\nModular kitchen L-shape 10 ft: Rs 1,85,000\nWardrobe 7 ft sliding: Rs 62,000 each\nWarranty: 10 years on hardware."
    r = await c.post("/api/brain-docs", json={"title": "Price list", "kind": "price", "text": text})
    assert r.status_code == 200, r.text
    up = await c.post("/api/brain-docs", files={"file": ("faq.txt", b"FAQ: Do you give a warranty? Yes, 10 years on hardware and 1 year on work.", "text/plain")},
                      data={"title": "FAQs", "kind": "faq"})
    assert up.status_code == 200, up.text
    docs = (await c.get("/api/brain-docs")).json()["docs"]
    assert {d["title"] for d in docs} == {"Price list", "FAQs"}
    ans = (await c.post("/api/brain-docs/ask", json={"question": "What is the price of a wardrobe?"})).json()
    assert ans["answer"]
    from app import company_brain
    ctx = await company_brain.context(uid, "wardrobe price")
    assert "62,000" in ctx
    assert (await c.post("/api/brain-docs", json={"title": "x", "text": "short"})).status_code == 400
    await c.delete(f"/api/brain-docs/{docs[0]['id']}")
    assert len((await c.get("/api/brain-docs")).json()["docs"]) == 1
    prog, _, _ = await owner_on("9840000009", "program", live=False)
    assert (await prog.get("/api/brain-docs")).status_code == 403


# ───────────────────────── money campaigns ─────────────────────────
async def test_money_campaign_approved_once_sent_in_hours_from_the_owners_number(client, setting):
    c, uid, _ = await owner_on("9840000010", live=False)
    await quiet(c, *QUIET)
    for i in range(5):
        await c.post("/api/customers", json={"name": f"Customer {i}", "phone": f"98340 007{i:02d}", "total_value": 10000 * (i + 1),
                                             "last_purchase": "2026-01-10"})
    d = (await c.post("/api/campaigns/draft", json={"kind": "festival", "notes": "Diwali: free chimney with any kitchen"})).json()
    assert d["message"] and d["title"]
    assert (await c.post("/api/campaigns", json={"kind": "festival", "title": "Diwali", "message": "See https://x.in for the offer"})).status_code == 400
    camp = (await c.post("/api/campaigns", json={"kind": "festival", "title": "Diwali offer", "message": d["message"],
                                                 "audience": {"tiers": ["A", "B", "C"], "quiet_days": 60}})).json()
    assert camp["status"] == "draft"
    assert (await c.post("/api/campaigns/preview", json={"tiers": ["A"]})).json()["count"] >= 1
    r = await c.post(f"/api/campaigns/{camp['id']}/approve")
    assert r.json()["status"] == "running" and r.json()["recipients"] == 5
    assert (await c.post(f"/api/campaigns/{camp['id']}/approve")).status_code == 409
    assert (await c.delete(f"/api/campaigns/{camp['id']}")).status_code == 400

    await scheduler.tick(at=ist(2026, 10, 12, 11, 0))
    assert (await db().campaigns.find_one({"_id": camp["id"]}))["note"].startswith("Waiting")   # no number connected yet
    await connect_demo_whatsapp(uid)
    await scheduler.tick(at=ist(2026, 10, 12, 8, 0))           # before 10am: nothing
    assert await db().outbox.count_documents({"kind": "campaign"}) == 0
    setting("campaign_daily_cap", 3)
    await scheduler.tick(at=ist(2026, 10, 12, 11, 0))
    assert await db().outbox.count_documents({"kind": "campaign"}) == 3       # the daily cap
    await scheduler.tick(at=ist(2026, 10, 12, 12, 0))
    assert await db().outbox.count_documents({"kind": "campaign"}) == 3
    await scheduler.tick(at=ist(2026, 10, 13, 11, 0))
    assert await db().outbox.count_documents({"kind": "campaign"}) == 5
    done = await db().campaigns.find_one({"_id": camp["id"]})
    assert done["status"] == "done" and done["sent"] == 5
    first = await db().outbox.find_one({"kind": "campaign"})
    assert first["params"][0].startswith("Customer") and first["params"][1] == PROFILE["name"] and first["params"][2] == " ".join(d["message"].split())
    lst = (await c.get("/api/campaigns")).json()
    assert lst["connected"] and lst["template"] == "campaign_v1"

    prog, _, _ = await owner_on("9840000011", "program", live=False)
    assert (await prog.get("/api/campaigns")).status_code == 403


# ───────────────────────── Control Room, Gym, results ─────────────────────────
async def test_control_room_gym_and_results(client):
    c, uid, site = await owner_on("9840000012")
    await quiet(c, *QUIET)
    await c.put("/api/magic", json={"monthly_target": 500000, "avg_sale": 100000, "close_rate": 25})
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Neha", "phone": "98340 00801", "message": "Kitchen"})
    lead = await db().leads.find_one({"owner_id": uid})
    await c.patch(f"/api/leads/{lead['_id']}", json={"status": "won", "value": 200000})
    ctrl = (await c.get("/api/control")).json()
    assert ctrl["ceo_line"] and isinstance(ctrl, dict)
    text = json.dumps(ctrl)
    assert "200000" in text or "2,00,000" in text

    g = (await c.get("/api/gym")).json()
    assert [s["key"] for s in g["scenarios"]] == ["haggler", "thinker", "comparer", "unhappy"]
    s = (await c.post("/api/gym/sessions", json={"scenario": "haggler"})).json()
    assert s["messages"][0]["role"] == "customer"
    assert (await c.post(f"/api/gym/sessions/{s['id']}/finish")).status_code == 400
    s = (await c.post(f"/api/gym/sessions/{s['id']}/say", json={"text": "What size is your kitchen? When do you need it? What matters most?"})).json()
    assert len(s["messages"]) == 3
    s = (await c.post(f"/api/gym/sessions/{s['id']}/say", json={"text": "The price includes a 10 year warranty. Shall we book a visit on Saturday?"})).json()
    done = (await c.post(f"/api/gym/sessions/{s['id']}/finish")).json()
    assert done["status"] == "scored" and len(done["score"]["scores"]) == 4 and done["score"]["fixes"]
    assert (await c.post(f"/api/gym/sessions/{s['id']}/say", json={"text": "more"})).status_code == 400
    call = (await c.post("/api/gym/score-call", json={"transcript": "Customer: Too costly\nMe: I can give 20% discount\nCustomer: ok"})).json()
    assert call["kind"] == "call" and call["score"]["overall"] < done["score"]["overall"]
    assert (await c.post("/api/gym/score-call", json={"transcript": "hello"})).status_code == 400

    res = (await c.get("/api/results")).json()
    assert res["this_month"]["label"].endswith("so far") and res["past"]


# ───────────────────────── LegacyWorkforce ─────────────────────────
async def test_workforce_six_per_department_thirty_in_all(client):
    g, _, _ = await owner_on("9840000013", live=False)
    assert (await g.get("/api/workforce")).status_code == 403
    c, uid, _ = await owner_on("9840000014", "office", live=False)
    w = (await c.get("/api/workforce")).json()
    assert w["total_roles"] == 82 and w["max"] == 30 and w["hired"] == 0 and len(w["departments"]) == 5
    marketing = [r["id"] for r in roles_catalog.ROLES if r["department"] == "marketing"]
    for rid in marketing[:6]:
        assert (await c.post("/api/workforce/hire", json={"role_id": rid})).status_code == 200
    r = await c.post("/api/workforce/hire", json={"role_id": marketing[6]})
    assert r.status_code == 400 and "already has 6" in r.json()["detail"]
    await c.post("/api/workforce/release", json={"role_id": marketing[0]})
    assert (await c.post("/api/workforce/hire", json={"role_id": marketing[6]})).status_code == 200

    w = (await c.post("/api/workforce/recommended")).json()
    assert w["hired"] == 30 and all(d["hired"] == 6 for d in w["departments"])
    hired = {r["id"] for d in w["departments"] for r in d["roles"] if r["hired"]}
    assert set(roles_catalog.HERO_IDS) <= hired
    run = await c.post("/api/tools/role:7/run", json={"inputs": {"brief": "Diwali offer for 2BHK owners in Thane"}})
    assert run.status_code == 200, run.text
    assert (await c.post("/api/tools/role:13/run", json={"inputs": {"brief": "anything"}})).status_code == 400   # not hired
    lib = (await c.get("/api/tools")).json()
    assert len(lib["roles"]) == 30
    cat = (await c.get("/api/tools/roles/catalog")).json()
    assert len(cat["roles"]) == 82 and cat["per_department"] == 6


def test_recommended_roles_sit_in_their_departments():
    from app.routers.workforce import RECOMMENDED
    for dept, ids in RECOMMENDED.items():
        assert len(ids) == 6 and all(roles_catalog.department_of(i) == dept for i in ids), dept

"""Payments: Razorpay checkout, verify, webhooks, refunds and referral commissions, against a fake Razorpay API."""
import base64
import hashlib
import hmac
import json
import re
from datetime import timedelta

import httpx
import pytest

from app import billing
from app.config import Settings, settings
from app.db import db, now
from tests.conftest import PROFILE, new_owner

KEY, SECRET, WH = "rzp_test_K3y", "rzp_test_s3cret", "whsec_t3st"
ADMIN = "9999900000"
REAL_CLIENT = httpx.AsyncClient


class FakeRazorpay:
    """A small in-memory Razorpay: orders, subscriptions, cancel. Records every request."""
    def __init__(self):
        self.calls, self.orders, self.subs, self.down, self.n = [], {}, {}, False, 0

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        assert req.url.host == "api.razorpay.com"
        assert req.headers["authorization"] == "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
        if self.down:
            return httpx.Response(503, json={"error": {"code": "SERVER_ERROR", "description": "We are facing some trouble"}})
        body = json.loads(req.content) if req.content else {}
        path = req.url.path
        self.n += 1
        if req.method == "POST" and path == "/v1/orders":
            o = {"id": f"order_T{self.n}", "entity": "order", "status": "created", "amount_paid": 0, **body}
            self.orders[o["id"]] = o
            return httpx.Response(200, json=o)
        if req.method == "POST" and path == "/v1/subscriptions":
            s = {"id": f"sub_T{self.n}", "entity": "subscription", "status": "created", "short_url": f"https://rzp.io/i/T{self.n}",
                 "current_start": None, "current_end": None, "paid_count": 0, "charge_at": body.get("start_at"), **body}
            self.subs[s["id"]] = s
            return httpx.Response(200, json=s)
        m = re.fullmatch(r"/v1/subscriptions/(sub_\w+)(/cancel)?", path)
        if m and m.group(1) in self.subs:
            s = self.subs[m.group(1)]
            if m.group(2):
                if not body.get("cancel_at_cycle_end"):
                    s["status"] = "cancelled"
                return httpx.Response(200, json=s)
            return httpx.Response(200, json=s)
        return httpx.Response(404, json={"error": {"description": "The requested URL was not found on the server."}})

    def client(self):
        return REAL_CLIENT(transport=httpx.MockTransport(self.handle), timeout=5)

    def last(self, method: str, path: str) -> dict:
        req = [r for r in self.calls if r.method == method and r.url.path == path][-1]
        return json.loads(req.content) if req.content else {}


@pytest.fixture
def rzp(monkeypatch):
    fake = FakeRazorpay()
    keys = {"razorpay_key_id": KEY, "razorpay_key_secret": SECRET, "razorpay_webhook_secret": WH, "razorpay_plan_id_lite": "plan_Lite1999"}
    old = {k: getattr(settings, k) for k in keys}
    for k, v in keys.items():
        object.__setattr__(settings, k, v)
    monkeypatch.setattr(billing, "http_client", fake.client)
    try:
        yield fake
    finally:
        for k, v in old.items():
            object.__setattr__(settings, k, v)


def sig(secret: str, msg: str | bytes) -> str:
    return hmac.new(secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256).hexdigest()


async def hook(client, event: str, secret: str = WH, **entities) -> httpx.Response:
    raw = json.dumps({"entity": "event", "event": event, "payload": {k: {"entity": v} for k, v in entities.items()}}).encode()
    return await client.post("/api/razorpay/webhook", content=raw,
                             headers={"content-type": "application/json", "x-razorpay-signature": sig(secret, raw)})


async def uid(c) -> str:
    return (await c.get("/api/me")).json()["user"]["id"]


async def ref_code(c) -> str:
    return (await c.get("/api/me")).json()["invite_link"].split("ref=")[1].split("&")[0]


async def user(c) -> dict:
    return await db().users.find_one({"_id": await uid(c)})


def close(a, b, seconds=5) -> bool:
    return abs((a - b).total_seconds()) <= seconds


async def buy_order(c, tier: str, fake: FakeRazorpay, pay_id: str = "pay_O1") -> dict:
    r = await c.post("/api/billing/checkout", json={"tier": tier})
    assert r.status_code == 200, r.text
    co = r.json()
    r = await c.post("/api/billing/verify", json={"razorpay_order_id": co["order_id"], "razorpay_payment_id": pay_id,
                                                  "razorpay_signature": sig(SECRET, f"{co['order_id']}|{pay_id}")})
    assert r.status_code == 200, r.text
    return co


async def buy_dev(c, tier: str) -> dict:
    co = (await c.post("/api/billing/checkout", json={"tier": tier})).json()
    assert co["mode"] == "dev", co
    r = await c.post("/api/billing/dev-complete", json={"payment_id": co["payment_id"]})
    assert r.status_code == 200, r.text
    return r.json()


# ───────────────────────── one-time orders ─────────────────────────
async def test_order_checkout_then_verify_grants_access_once(client, rzp):
    c = await new_owner("9833010001")
    await c.put("/api/business", json=PROFILE)
    r = await c.post("/api/billing/checkout", json={"tier": "program"})
    assert r.status_code == 200, r.text
    co = r.json()
    assert co["mode"] == "razorpay" and co["kind"] == "order" and co["key_id"] == KEY and co["amount"] == 1_000_000
    assert co["prefill"] == {"contact": "+919833010001", "name": "Shree Ganesh Interiors"}
    sent = rzp.last("POST", "/v1/orders")
    assert sent == {"amount": 1_000_000, "currency": "INR", "receipt": co["payment_id"],
                    "notes": {"user_id": await uid(c), "tier": "program", "payment_id": co["payment_id"]}}
    p = await db().payments.find_one({"_id": co["payment_id"]})
    assert p["status"] == "created" and p["rzp_order_id"] == co["order_id"] and p["kind"] == "order"

    body = {"razorpay_order_id": co["order_id"], "razorpay_payment_id": "pay_A1", "razorpay_signature": sig(SECRET, f"{co['order_id']}|pay_A1")}
    r = await c.post("/api/billing/verify", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "program" and r.json()["source"] == "purchase"
    u = await user(c)
    until = u["access"]["program"]
    assert close(until, now() + timedelta(days=365), 60)
    me = (await c.get("/api/me")).json()["user"]
    assert me["effective_plan"] == "program" and me["plan_source"] == "purchase"

    # verifying again (double click, retry) changes nothing
    assert (await c.post("/api/billing/verify", json=body)).status_code == 200
    assert (await user(c))["access"]["program"] == until
    p = await db().payments.find_one({"_id": co["payment_id"]})
    assert p["status"] == "paid" and p["rzp_payment_id"] == "pay_A1"
    assert await db().events.count_documents({"type": "payment_paid"}) == 1

    info = (await c.get("/api/billing")).json()
    assert info["mode"] == "razorpay" and info["key_id"] == KEY and info["plan"] == "program" and info["source"] == "purchase"
    assert info["access"]["program"] and [x["tier"] for x in info["payments"]] == ["program"] and len(info["ladder"]) == 6


async def test_wrong_signature_is_refused(client, rzp):
    c = await new_owner("9833010002")
    co = (await c.post("/api/billing/checkout", json={"tier": "running"})).json()
    for bad in [sig("not-the-secret", f"{co['order_id']}|pay_X"), sig(SECRET, f"{co['order_id']}|pay_OTHER"), "0" * 64]:
        r = await c.post("/api/billing/verify", json={"razorpay_order_id": co["order_id"], "razorpay_payment_id": "pay_X", "razorpay_signature": bad})
        assert r.status_code == 400
    assert (await db().payments.find_one({"_id": co["payment_id"]}))["status"] == "created"
    assert (await c.get("/api/me")).json()["user"]["effective_plan"] == "free"
    # someone else's order can't be claimed even with a valid signature
    other = await new_owner("9833010003")
    r = await other.post("/api/billing/verify", json={"razorpay_order_id": co["order_id"], "razorpay_payment_id": "pay_X",
                                                      "razorpay_signature": sig(SECRET, f"{co['order_id']}|pay_X")})
    assert r.status_code == 404


async def test_webhook_signature_and_order_paid_without_client_verify(client, rzp):
    c = await new_owner("9833010004")
    co = (await c.post("/api/billing/checkout", json={"tier": "growth"})).json()
    order = {"id": co["order_id"], "entity": "order", "amount": 15_000_000, "amount_paid": 15_000_000, "status": "paid"}
    pay = {"id": "pay_G1", "entity": "payment", "order_id": co["order_id"], "amount": 15_000_000, "status": "captured"}

    assert (await hook(client, "order.paid", secret="wrong", order=order, payment=pay)).status_code == 400
    raw = json.dumps({"event": "order.paid", "payload": {}}).encode()
    assert (await client.post("/api/razorpay/webhook", content=raw)).status_code == 400  # no signature at all
    assert (await c.get("/api/me")).json()["user"]["effective_plan"] == "free"
    assert (await hook(client, "invoice.paid", invoice={"id": "inv_1"})).status_code == 200  # events we don't use: 200

    # the owner closed the tab before the browser could verify; the webhook alone grants
    assert (await hook(client, "order.paid", order=order, payment=pay)).status_code == 200
    me = (await c.get("/api/me")).json()["user"]
    assert me["effective_plan"] == "growth"
    until = (await user(c))["access"]["growth"]
    assert close(until, now() + timedelta(days=180), 60)
    # both events, repeated, and a late client verify: still one grant
    assert (await hook(client, "payment.captured", payment=pay)).status_code == 200
    assert (await hook(client, "order.paid", order=order, payment=pay)).status_code == 200
    r = await c.post("/api/billing/verify", json={"razorpay_order_id": co["order_id"], "razorpay_payment_id": "pay_G1",
                                                  "razorpay_signature": sig(SECRET, f"{co['order_id']}|pay_G1")})
    assert r.status_code == 200 and r.json()["plan"] == "growth"
    assert (await user(c))["access"]["growth"] == until
    assert await db().payments.count_documents({"status": "paid"}) == 1

    # a payment for less than the order is never granted
    co2 = (await c.post("/api/billing/checkout", json={"tier": "office"})).json()
    short = {"id": "pay_SHORT", "order_id": co2["order_id"], "amount": 100, "status": "captured"}
    assert (await hook(client, "payment.captured", payment=short)).status_code == 200
    assert (await db().payments.find_one({"_id": co2["payment_id"]}))["status"] == "created"


async def test_one_time_tiers_refuse_lower_and_stack_same_tier(client):
    c = await new_owner("9833010005")
    await buy_dev(c, "growth")
    first = (await user(c))["access"]["growth"]
    r = await c.post("/api/billing/checkout", json={"tier": "program"})
    assert r.status_code == 409 and "Growth Mentorship" in r.json()["detail"]
    await buy_dev(c, "growth")  # an extension of the same tier is allowed, and adds on to the end
    second = (await user(c))["access"]["growth"]
    assert close(second, first + timedelta(days=180), 2)
    assert (await c.post("/api/billing/checkout", json={"tier": "office"})).status_code == 200  # going up is always fine


async def test_razorpay_down_is_a_plain_502(client, rzp):
    c = await new_owner("9833010006")
    rzp.down = True
    r = await c.post("/api/billing/checkout", json={"tier": "program"})
    assert r.status_code == 502 and "Nothing was charged" in r.json()["detail"]
    assert await db().payments.count_documents({}) == 0
    r = await c.post("/api/billing/checkout", json={"tier": "lite"})
    assert r.status_code == 502 and not (await user(c)).get("sub")


# ───────────────────────── Membership subscription ─────────────────────────
async def test_subscription_starts_when_referral_trial_ends(client, rzp):
    a = await new_owner("9833020001")
    b = await new_owner("9833020002", ref=await ref_code(a), src="invite")
    trial_until = (await user(b))["trial"]["until"]
    r = await b.post("/api/billing/checkout", json={"tier": "lite"})
    assert r.status_code == 200, r.text
    co = r.json()
    assert co["mode"] == "razorpay" and co["kind"] == "subscription" and co["subscription_id"].startswith("sub_") and co["key_id"] == KEY
    sent = rzp.last("POST", "/v1/subscriptions")
    assert sent == {"plan_id": "plan_Lite1999", "total_count": 120, "quantity": 1, "customer_notify": 1,
                    "notes": {"user_id": await uid(b)}, "start_at": int(trial_until.timestamp())}
    sub = (await user(b))["sub"]
    assert sub["id"] == co["subscription_id"] and sub["status"] == "created" and sub["plan"] == "lite" and sub["cancel_at_cycle_end"] is False
    assert int(sub["start_at"].timestamp()) == int(trial_until.timestamp())

    # closing the checkout and trying again reuses the same subscription
    again = (await b.post("/api/billing/checkout", json={"tier": "lite"})).json()
    assert again["subscription_id"] == co["subscription_id"] and len(rzp.subs) == 1

    # mandate set up: authenticated, nothing charged yet, the trial still carries the plan
    rzp.subs[co["subscription_id"]]["status"] = "authenticated"
    r = await b.post("/api/billing/verify", json={"razorpay_subscription_id": co["subscription_id"], "razorpay_payment_id": "pay_AUTH",
                                                  "razorpay_signature": sig(SECRET, f"pay_AUTH|{co['subscription_id']}")})
    assert r.status_code == 200 and r.json()["sub"]["status"] == "authenticated" and r.json()["plan"] == "lite" and r.json()["source"] == "trial"
    assert (await user(b))["sub"].get("paid_until") is None
    r = await b.post("/api/billing/checkout", json={"tier": "lite"})
    assert r.status_code == 409 and "first charge" in r.json()["detail"]

    # an owner without a trial starts now
    c = await new_owner("9833020003")
    await c.post("/api/billing/checkout", json={"tier": "lite"})
    assert "start_at" not in rzp.last("POST", "/v1/subscriptions")


async def test_subscription_verify_and_charged_webhook(client, rzp):
    c = await new_owner("9833020004")
    co = (await c.post("/api/billing/checkout", json={"tier": "lite"})).json()
    sid = co["subscription_id"]
    end1 = int((now() + timedelta(days=30)).timestamp())
    rzp.subs[sid].update(status="active", current_start=int(now().timestamp()), current_end=end1, paid_count=1)
    good = {"razorpay_subscription_id": sid, "razorpay_payment_id": "pay_S1", "razorpay_signature": sig(SECRET, f"pay_S1|{sid}")}
    assert (await c.post("/api/billing/verify", json={**good, "razorpay_signature": sig(SECRET, f"{sid}|pay_S1")})).status_code == 400
    r = await c.post("/api/billing/verify", json=good)
    assert r.status_code == 200 and r.json()["plan"] == "lite" and r.json()["source"] == "subscription"
    assert int((await user(c))["sub"]["paid_until"].timestamp()) == end1
    assert (await c.post("/api/billing/checkout", json={"tier": "lite"})).status_code == 409  # already a member

    sub_entity = {**rzp.subs[sid]}
    pay1 = {"id": "pay_S1", "entity": "payment", "amount": 199_900, "currency": "INR", "status": "captured", "invoice_id": "inv_1"}
    for _ in range(2):  # Razorpay delivers at least once
        assert (await hook(client, "subscription.charged", subscription=sub_entity, payment=pay1)).status_code == 200
    payments = [p async for p in db().payments.find({"kind": "subscription"})]
    assert len(payments) == 1 and payments[0]["_id"] == "rzp_pay_S1" and payments[0]["amount"] == 199_900 and payments[0]["tier"] == "lite"

    end2 = end1 + 30 * 86400
    sub2 = {**sub_entity, "current_start": end1, "current_end": end2, "paid_count": 2}
    assert (await hook(client, "subscription.charged", subscription=sub2, payment={**pay1, "id": "pay_S2"})).status_code == 200
    assert await db().payments.count_documents({"kind": "subscription"}) == 2
    assert int((await user(c))["sub"]["paid_until"].timestamp()) == end2
    # an older event arriving late never pulls paid_until back
    await hook(client, "subscription.charged", subscription=sub_entity, payment=pay1)
    assert int((await user(c))["sub"]["paid_until"].timestamp()) == end2
    hist = (await c.get("/api/billing")).json()["payments"]
    assert [p["kind"] for p in hist] == ["subscription", "subscription"]


async def test_subscription_statuses_and_paid_until_on_effective_plan(client, rzp):
    c = await new_owner("9833020005")
    sid = (await c.post("/api/billing/checkout", json={"tier": "lite"})).json()["subscription_id"]
    plan = lambda: c.get("/api/me")  # noqa: E731
    future = int((now() + timedelta(days=10)).timestamp())
    await hook(client, "subscription.activated", subscription={"id": sid, "status": "active", "current_end": future, "notes": []})
    assert (await plan()).json()["user"]["effective_plan"] == "lite"

    # a failing renewal: pending keeps Membership while Razorpay retries; the unpaid cycle's end is never granted
    later = future + 30 * 86400
    await hook(client, "subscription.pending", subscription={"id": sid, "status": "pending", "current_end": later})
    u = await user(c)
    assert u["sub"]["status"] == "pending" and int(u["sub"]["paid_until"].timestamp()) == future
    assert (await plan()).json()["user"]["effective_plan"] == "lite"
    await hook(client, "subscription.halted", subscription={"id": sid, "status": "halted", "current_end": later})
    assert (await user(c))["sub"]["status"] == "halted"
    assert (await plan()).json()["user"]["effective_plan"] == "lite"  # still paid up to `future`
    await db().users.update_one({"_id": await uid(c)}, {"$set": {"sub.paid_until": now() - timedelta(minutes=1)}})
    assert (await plan()).json()["user"]["effective_plan"] == "free"  # halted and past paid_until

    # cancelled keeps what was paid for, then ends; a late event never revives it
    await db().users.update_one({"_id": await uid(c)}, {"$set": {"sub.status": "active", "sub.paid_until": now() + timedelta(days=5)}})
    await hook(client, "subscription.cancelled", subscription={"id": sid, "status": "cancelled"})
    assert (await user(c))["sub"]["status"] == "cancelled"
    assert (await plan()).json()["user"]["effective_plan"] == "lite"
    await hook(client, "subscription.activated", subscription={"id": sid, "status": "active"})
    assert (await user(c))["sub"]["status"] == "cancelled"
    await db().users.update_one({"_id": await uid(c)}, {"$set": {"sub.paid_until": now() - timedelta(seconds=1)}})
    assert (await plan()).json()["user"]["effective_plan"] == "free"

    # events for a subscription that isn't ours (and has no owner in its notes) are acknowledged and ignored
    assert (await hook(client, "subscription.activated", subscription={"id": "sub_STRANGER", "status": "active"})).status_code == 200


async def test_cancel_at_period_end(client, rzp):
    c = await new_owner("9833020006")
    sid = (await c.post("/api/billing/checkout", json={"tier": "lite"})).json()["subscription_id"]
    end = int((now() + timedelta(days=20)).timestamp())
    rzp.subs[sid].update(status="active", current_end=end)
    await hook(client, "subscription.activated", subscription=rzp.subs[sid])
    r = await c.post("/api/billing/cancel")
    assert r.status_code == 200 and r.json()["sub"]["cancel_at_cycle_end"] is True and r.json()["plan"] == "lite"
    assert rzp.last("POST", f"/v1/subscriptions/{sid}/cancel") == {"cancel_at_cycle_end": 1}
    assert (await c.post("/api/billing/cancel")).status_code == 200  # twice is fine, no second call
    assert len([x for x in rzp.calls if x.url.path.endswith("/cancel")]) == 1
    info = (await c.get("/api/billing")).json()
    assert info["member"] is False and info["sub"]["cancel_at_cycle_end"] is True
    # changing their mind: a new Membership starts when the paid period ends, with no gap and no double charge
    co = (await c.post("/api/billing/checkout", json={"tier": "lite"})).json()
    assert rzp.last("POST", "/v1/subscriptions")["start_at"] == end and co["subscription_id"] != sid
    assert int((await user(c))["sub"]["paid_until"].timestamp()) == end
    # the old subscription ending later does not replace the new one
    await hook(client, "subscription.cancelled", subscription={"id": sid, "status": "cancelled", "notes": {"user_id": await uid(c)}})
    assert (await user(c))["sub"]["id"] == co["subscription_id"]


# ───────────────────────── refunds and commissions ─────────────────────────
async def test_refund_revokes_access_and_voids_commission(client, rzp):
    a = await new_owner("9833030001")
    b = await new_owner("9833030002", ref=await ref_code(a), src="badge")
    await b.put("/api/business", json={**PROFILE, "name": "Kapoor Dental Clinic"})
    co = await buy_order(b, "program", rzp, "pay_R1")
    pid = co["payment_id"]
    cm = await db().commissions.find_one({"_id": f"cm_{pid}"})
    assert cm["amount"] == 300_000 and cm["status"] == "pending" and cm["referrer_id"] == await uid(a)
    assert "program" in (await user(b))["access"]

    refund = {"id": "rfnd_1", "entity": "refund", "payment_id": "pay_R1", "amount": 1_000_000, "status": "processed"}
    for _ in range(2):
        assert (await hook(client, "refund.processed", refund=refund)).status_code == 200
    assert await db().refunds.count_documents({}) == 1
    p = await db().payments.find_one({"_id": pid})
    assert p["status"] == "refunded" and p["refunded_amount"] == 1_000_000
    assert "program" not in ((await user(b)).get("access") or {})
    me = (await b.get("/api/me")).json()["user"]
    assert me["effective_plan"] == "lite" and me["plan_source"] == "trial"  # back to the referral trial, nothing paid
    cm = await db().commissions.find_one({"_id": f"cm_{pid}"})
    assert cm["status"] == "void" and cm["void_reason"] == "refunded"
    # a late webhook for the refunded payment never grants again
    await hook(client, "order.paid", order={"id": co["order_id"], "amount_paid": 1_000_000}, payment={"id": "pay_R1"})
    assert "program" not in ((await user(b)).get("access") or {})

    # stacking survives a refund of one purchase in the middle
    co1 = await buy_order(b, "running", rzp, "pay_R2")
    await buy_order(b, "running", rzp, "pay_R3")
    await hook(client, "refund.processed", refund={"id": "rfnd_2", "payment_id": "pay_R2", "amount": 2_500_000})
    remaining = await db().payments.find_one({"rzp_payment_id": "pay_R3"})
    assert close((await user(b))["access"]["running"], remaining["paid_at"] + timedelta(days=365), 1)
    assert (await db().payments.find_one({"_id": co1["payment_id"]}))["status"] == "refunded"


async def test_refund_after_payout_flags_clawback(client, rzp):
    a = await new_owner("9833030003")
    b = await new_owner("9833030004", ref=await ref_code(a), src="invite")
    co = await buy_order(b, "running", rzp, "pay_C1")
    cid = f"cm_{co['payment_id']}"
    await db().commissions.update_one({"_id": cid}, {"$set": {"status": "paid", "paid_at": now(), "reference": "UTR1"}})
    await hook(client, "refund.processed", refund={"id": "rfnd_p1", "payment_id": "pay_C1", "amount": 1_000_000})  # partial
    cm = await db().commissions.find_one({"_id": cid})
    assert cm["status"] == "paid" and cm["clawback"] is True and cm["clawback_amount"] == 300_000
    assert (await db().payments.find_one({"_id": co["payment_id"]}))["status"] == "paid"  # partly refunded, access kept
    assert "running" in (await user(b))["access"]
    await hook(client, "refund.processed", refund={"id": "rfnd_p2", "payment_id": "pay_C1", "amount": 1_500_000})
    cm = await db().commissions.find_one({"_id": cid})
    assert cm["clawback_amount"] == 750_000 and (await db().payments.find_one({"_id": co["payment_id"]}))["status"] == "refunded"
    assert "running" not in (await user(b))["access"]


async def test_commission_rules_window_hold_approve_and_payout(client, rzp):
    a = await new_owner("9833040001")
    await a.put("/api/business", json={**PROFILE, "name": "Arora Traders"})
    code = await ref_code(a)
    b = await new_owner("9833040002", ref=code, src="badge")
    await b.put("/api/business", json={**PROFILE, "name": "Kapoor Dental Clinic"})
    stranger = await new_owner("9833040003")
    old_friend = await new_owner("9833040004", ref=code, src="invite")
    await db().users.update_one({"_id": await uid(old_friend)}, {"$set": {"created_at": now() - timedelta(days=400)}})

    # a referred owner's Membership charge earns 30%
    sid = (await b.post("/api/billing/checkout", json={"tier": "lite"})).json()["subscription_id"]
    sub = {"id": sid, "status": "active", "current_end": int((now() + timedelta(days=30)).timestamp())}
    await hook(client, "subscription.charged", subscription=sub, payment={"id": "pay_M1", "amount": 199_900})
    cm = await db().commissions.find_one({"_id": "cm_rzp_pay_M1"})
    assert cm["amount"] == 59_970 and cm["percent"] == 30 and cm["status"] == "pending" and cm["friend_id"] == await uid(b)
    pay = await db().payments.find_one({"_id": "rzp_pay_M1"})
    assert close(cm["available_at"], pay["paid_at"] + timedelta(days=7), 1)
    notes = (await a.get("/api/me")).json()["notices"]
    assert any(n["text"] == "You earned ₹599.70 from Kapoor Dental Clinic's payment. It's paid out after a 7-day refund window." for n in notes)
    await hook(client, "subscription.charged", subscription=sub, payment={"id": "pay_M1", "amount": 199_900})
    assert await db().commissions.count_documents({}) == 1

    # not referred, or referred more than 12 months ago: no commission
    await buy_order(stranger, "program", rzp, "pay_N1")
    await buy_order(old_friend, "program", rzp, "pay_N2")
    assert await db().commissions.count_documents({}) == 1

    # held for the refund window
    admin = await new_owner(ADMIN)
    r = (await admin.post("/api/admin/commissions/approve", json={"ids": [cm["_id"]]})).json()
    assert r["approved"] == [] and r["skipped"][0]["reason"] == "still in the refund window"
    e = (await a.get("/api/earnings")).json()
    assert e["totals"]["pending"] == 59_970 and e["commissions"][0]["friend"] == "Kapoor Dental Clinic" and not e["commissions"][0]["ready"]
    assert e["rules"] == {"percent": 30, "months": 12, "hold_days": 7} and e["payout"] is None

    await db().commissions.update_one({"_id": cm["_id"]}, {"$set": {"available_at": now() - timedelta(minutes=1)}})
    assert (await a.get("/api/earnings")).json()["commissions"][0]["ready"]
    # only approved ones can be marked paid, and only with a reference
    assert (await admin.post("/api/admin/commissions/mark-paid", json={"ids": [cm["_id"]], "reference": "UTR123456"})).json()["paid"] == []
    assert (await admin.post("/api/admin/commissions/approve", json={"ids": [cm["_id"]]})).json()["approved"] == [cm["_id"]]
    assert (await admin.post("/api/admin/commissions/approve", json={"ids": [cm["_id"]]})).json()["approved"] == []
    assert (await admin.post("/api/admin/commissions/mark-paid", json={"ids": [cm["_id"]]})).status_code == 422
    assert (await admin.post("/api/admin/commissions/mark-paid", json={"ids": [cm["_id"]], "reference": "  "})).status_code in (400, 422)
    r = await admin.post("/api/admin/commissions/mark-paid", json={"ids": [cm["_id"]], "reference": "UTR123456"})
    assert r.json()["paid"] == [cm["_id"]]
    done = await db().commissions.find_one({"_id": cm["_id"]})
    assert done["status"] == "paid" and done["reference"] == "UTR123456"
    assert any("We've paid you ₹599.70 commission" in n["text"] for n in (await a.get("/api/me")).json()["notices"])
    assert (await admin.post("/api/admin/commissions/mark-paid", json={"ids": [cm["_id"]], "reference": "UTR123456"})).json()["paid"] == []
    assert (await admin.post(f"/api/admin/commissions/{cm['_id']}/void")).status_code == 409
    assert (await a.get("/api/earnings")).json()["totals"]["paid"] == 59_970

    # a refunded payment's commission can't be approved; void works on pending
    co = await buy_order(b, "program", rzp, "pay_M2")
    cid = f"cm_{co['payment_id']}"
    await db().commissions.update_one({"_id": cid}, {"$set": {"available_at": now() - timedelta(days=1)}})
    await db().payments.update_one({"_id": co["payment_id"]}, {"$set": {"status": "refunded"}})
    r = (await admin.post("/api/admin/commissions/approve", json={"ids": [cid]})).json()
    assert r["approved"] == [] and r["skipped"][0]["reason"] == "payment refunded"
    assert (await admin.post(f"/api/admin/commissions/{cid}/void", json={"reason": "refunded by hand"})).status_code == 200
    assert (await db().commissions.find_one({"_id": cid}))["status"] == "void"
    assert (await admin.post("/api/admin/commissions/nope/void")).status_code == 404

    listed = (await admin.get("/api/admin/commissions")).json()
    assert {c["id"] for c in listed["commissions"]} == {cm["_id"], cid}
    assert listed["commissions"][0]["referrer"]["business"] == "Arora Traders"
    assert [c["id"] for c in (await admin.get("/api/admin/commissions?status=paid")).json()["commissions"]] == [cm["_id"]]


async def test_payout_upi_validation(client):
    a = await new_owner("9833050001")
    for bad in ["", "no-at-sign", "a@1", "x@okhdfc", "name@ok hdfc", "naïve@okhdfc", "name@" + "b" * 65]:
        r = await a.put("/api/earnings/payout", json={"upi_id": bad, "name": "Asha Arora"})
        assert r.status_code in (400, 422), bad
    assert (await a.put("/api/earnings/payout", json={"upi_id": "asha.arora-1@okhdfcbank", "name": "A"})).status_code == 422
    r = await a.put("/api/earnings/payout", json={"upi_id": " asha.arora-1@okhdfcbank ", "name": " Asha   Arora "})
    assert r.status_code == 200 and r.json()["payout"] == {"upi_id": "asha.arora-1@okhdfcbank", "name": "Asha Arora"}
    assert (await a.get("/api/earnings")).json()["payout"] == {"upi_id": "asha.arora-1@okhdfcbank", "name": "Asha Arora"}
    b = await new_owner("9833050002", ref=await ref_code(a))
    await buy_dev(b, "program")
    admin = await new_owner(ADMIN)
    row = (await admin.get("/api/admin/commissions")).json()["commissions"][0]
    assert row["referrer"]["upi_id"] == "asha.arora-1@okhdfcbank" and row["referrer"]["payout_name"] == "Asha Arora"


# ───────────────────────── modes ─────────────────────────
async def test_dev_mode_works_only_on_a_local_setup(client, monkeypatch):
    c = await new_owner("9833060001")
    co = (await c.post("/api/billing/checkout", json={"tier": "lite"})).json()
    assert co["mode"] == "dev" and co["amount"] == 199_900
    assert (await c.get("/api/billing")).json()["mode"] == "dev"
    r = await c.post("/api/billing/dev-complete", json={"payment_id": co["payment_id"]})
    assert r.status_code == 200 and r.json()["plan"] == "lite" and r.json()["source"] == "subscription"
    sub = (await user(c))["sub"]
    assert sub["status"] == "active" and close(sub["paid_until"], now() + timedelta(days=30), 60)
    assert (await c.post("/api/billing/dev-complete", json={"payment_id": co["payment_id"]})).status_code == 200
    assert (await user(c))["sub"]["paid_until"] == sub["paid_until"]  # completing twice changes nothing
    assert (await c.post("/api/billing/checkout", json={"tier": "lite"})).status_code == 409
    # test cancel: ends at paid_until
    r = await c.post("/api/billing/cancel")
    assert r.status_code == 200 and r.json()["sub"]["status"] == "cancelled" and r.json()["plan"] == "lite"
    other = await new_owner("9833060002")
    stranger_try = await other.post("/api/billing/dev-complete", json={"payment_id": co["payment_id"]})
    assert stranger_try.status_code == 404

    pending = (await c.post("/api/billing/checkout", json={"tier": "program"})).json()
    monkeypatch.setattr(Settings, "local_dev", property(lambda s: False))
    r = await c.post("/api/billing/dev-complete", json={"payment_id": pending["payment_id"]})
    assert r.status_code == 403
    assert (await db().payments.find_one({"_id": pending["payment_id"]}))["status"] == "created"


async def test_contact_mode_on_a_real_deployment_without_keys(client, monkeypatch):
    c = await new_owner("9833060003")
    monkeypatch.setattr(Settings, "local_dev", property(lambda s: False))
    monkeypatch.setitem(settings.upgrade_urls, "growth", "https://rzp.io/l/growth-mentorship")
    r = await c.post("/api/billing/checkout", json={"tier": "growth"})
    assert r.json() == {"mode": "contact", "tier": "growth", "url": "https://rzp.io/l/growth-mentorship"}
    r = await c.post("/api/billing/checkout", json={"tier": "office"})
    assert r.json() == {"mode": "contact", "tier": "office", "url": None}
    assert (await c.get("/api/billing")).json()["mode"] == "contact"
    assert await db().payments.count_documents({}) == 0


async def test_webhook_refused_without_a_secret(client, rzp):
    object.__setattr__(settings, "razorpay_webhook_secret", "")
    assert (await hook(client, "order.paid", secret="", order={"id": "order_x"})).status_code == 400


# ───────────────────────── access control and admin desk ─────────────────────────
async def test_team_members_and_non_owners_are_refused(client):
    owner = await new_owner("9833070001")
    member = await new_owner("9833070002")
    await db().users.update_one({"_id": await uid(owner)}, {"$set": {"plan": "growth"}})
    await db().users.update_one({"_id": await uid(member)}, {"$set": {"team_of": await uid(owner), "team_role": "manager"}})
    for method, path, body in [("GET", "/api/billing", None), ("POST", "/api/billing/checkout", {"tier": "office"}),
                               ("POST", "/api/billing/cancel", None), ("GET", "/api/earnings", None),
                               ("PUT", "/api/earnings/payout", {"upi_id": "a.b@okicici", "name": "Team Person"}),
                               ("POST", "/api/billing/verify", {"razorpay_payment_id": "pay_1", "razorpay_order_id": "order_1", "razorpay_signature": "x" * 64})]:
        r = await member.request(method, path, json=body)
        assert r.status_code == 403, (path, r.text)
    for method, path, body in [("GET", "/api/admin/commissions", None), ("GET", "/api/admin/payments", None), ("GET", "/api/admin/revenue", None),
                               ("POST", "/api/admin/commissions/approve", {"ids": ["x"]}),
                               ("POST", "/api/admin/commissions/mark-paid", {"ids": ["x"], "reference": "UTR1"}),
                               ("POST", "/api/admin/commissions/x/void", None)]:
        assert (await owner.request(method, path, json=body)).status_code == 403, path
    assert (await client.get("/api/billing")).status_code == 401


async def test_admin_revenue_and_payments(client, rzp):
    a = await new_owner("9833080001")
    b = await new_owner("9833080002", ref=await ref_code(a))
    await buy_order(b, "program", rzp, "pay_V1")
    sid = (await a.post("/api/billing/checkout", json={"tier": "lite"})).json()["subscription_id"]
    sub = {"id": sid, "status": "active", "current_end": int((now() + timedelta(days=30)).timestamp())}
    await hook(client, "subscription.charged", subscription=sub, payment={"id": "pay_V2", "amount": 199_900})
    c = await new_owner("9833080003")
    co = await buy_order(c, "running", rzp, "pay_V3")
    await hook(client, "refund.processed", refund={"id": "rfnd_V3", "payment_id": "pay_V3", "amount": 2_500_000})
    admin = await new_owner(ADMIN)
    rev = (await admin.get("/api/admin/revenue?days=30")).json()
    assert rev["paid_total"] == 1_000_000 + 199_900 and rev["by_tier"] == {"program": 1_000_000, "lite": 199_900}
    assert rev["members_active"] == 1 and rev["mrr"] == 199_900 and rev["refunds"] == 2_500_000
    assert rev["commissions"] == {"pending": 300_000, "approved": 0, "paid": 0}
    pays = (await admin.get("/api/admin/payments?days=30")).json()
    assert {p["status"] for p in pays} == {"paid", "refunded"} and len(pays) == 3
    assert [p["id"] for p in (await admin.get("/api/admin/payments?status=refunded")).json()] == [co["payment_id"]]
    assert all(p["phone"] for p in pays)


# ───────────────────────── out-of-order and edge deliveries ─────────────────────────
async def test_refund_that_arrives_before_its_payment_still_revokes(client, rzp):
    c = await new_owner("9833090101")
    co = (await c.post("/api/billing/checkout", json={"tier": "program"})).json()
    assert (await hook(client, "refund.processed", refund={"id": "rfnd_early", "payment_id": "pay_E1", "amount": 1_000_000})).status_code == 200
    await hook(client, "order.paid", order={"id": co["order_id"], "amount_paid": 1_000_000}, payment={"id": "pay_E1", "order_id": co["order_id"]})
    p = await db().payments.find_one({"_id": co["payment_id"]})
    assert p["status"] == "refunded" and "program" not in ((await user(c)).get("access") or {})
    assert (await db().refunds.find_one({"_id": "rfnd_early"}))["payment_id"] == co["payment_id"]


async def test_foreign_order_ids_are_ignored(client, rzp):
    c = await new_owner("9833090102")
    # subscription invoices also carry an order id; they are not ours to grant
    r = await hook(client, "payment.captured", payment={"id": "pay_inv", "order_id": "order_NOT_OURS", "amount": 199_900, "invoice_id": "inv_9"})
    assert r.status_code == 200 and await db().payments.count_documents({}) == 0
    assert (await c.get("/api/me")).json()["user"]["effective_plan"] == "free"


async def test_second_tab_subscription_is_adopted_but_never_duplicates_a_running_one(client, rzp):
    c = await new_owner("9833090103")
    me = await uid(c)
    first = (await c.post("/api/billing/checkout", json={"tier": "lite"})).json()["subscription_id"]
    # the owner paid a different subscription (another tab); ours was never completed, so theirs becomes current
    end = int((now() + timedelta(days=30)).timestamp())
    await hook(client, "subscription.activated", subscription={"id": "sub_TAB2", "status": "active", "current_end": end, "notes": {"user_id": me}})
    sub = (await user(c))["sub"]
    assert sub["id"] == "sub_TAB2" and sub["status"] == "active" and int(sub["paid_until"].timestamp()) == end and first != "sub_TAB2"
    # a third one while that runs is recorded for the team to refund, never taken over
    await hook(client, "subscription.charged", subscription={"id": "sub_TAB3", "status": "active", "current_end": end + 86400 * 30, "notes": {"user_id": me}},
               payment={"id": "pay_TAB3", "amount": 199_900})
    sub = (await user(c))["sub"]
    assert sub["id"] == "sub_TAB2" and int(sub["paid_until"].timestamp()) == end
    assert (await db().payments.find_one({"_id": "rzp_pay_TAB3"}))["rzp_subscription_id"] == "sub_TAB3"
    assert await db().events.count_documents({"type": "subscription_duplicate"}) == 1


async def test_membership_without_a_plan_id_falls_back_to_contact(client, rzp):
    object.__setattr__(settings, "razorpay_plan_id_lite", "")
    c = await new_owner("9833090104")
    r = await c.post("/api/billing/checkout", json={"tier": "lite"})
    assert r.json()["mode"] == "contact" and not rzp.calls
    assert (await c.post("/api/billing/checkout", json={"tier": "program"})).json()["mode"] == "razorpay"  # one-time still works


async def test_full_refund_of_a_membership_charge_ends_it_and_stops_charges(client, rzp):
    c = await new_owner("9833090001")
    sid = (await c.post("/api/billing/checkout", json={"tier": "lite"})).json()["subscription_id"]
    end = int((now() + timedelta(days=30)).timestamp())
    rzp.subs[sid].update(status="active", current_start=int(now().timestamp()), current_end=end, paid_count=1)
    pay = {"id": "pay_M1", "entity": "payment", "amount": 199_900, "currency": "INR", "status": "captured"}
    await hook(client, "subscription.charged", subscription=rzp.subs[sid], payment=pay)
    assert (await c.get("/api/me")).json()["user"]["effective_plan"] == "lite"

    await hook(client, "refund.processed", refund={"id": "rfnd_M1", "payment_id": "pay_M1", "amount": 199_900})
    u = await user(c)
    assert u["sub"]["status"] == "cancelled" and u["sub"]["paid_until"] <= now()
    assert rzp.last("POST", f"/v1/subscriptions/{sid}/cancel") == {"cancel_at_cycle_end": 0}  # no further charges
    assert (await c.get("/api/me")).json()["user"]["effective_plan"] == "free"


async def test_refund_of_an_old_subscriptions_charge_leaves_the_current_one(client, rzp):
    c = await new_owner("9833090002")
    sid = (await c.post("/api/billing/checkout", json={"tier": "lite"})).json()["subscription_id"]
    rzp.subs[sid].update(status="active", current_end=int((now() + timedelta(days=30)).timestamp()), paid_count=1)
    await hook(client, "subscription.charged", subscription=rzp.subs[sid], payment={"id": "pay_N1", "amount": 199_900, "status": "captured"})
    await db().payments.update_one({"rzp_payment_id": "pay_N1"}, {"$set": {"rzp_subscription_id": "sub_OLDER"}})
    await hook(client, "refund.processed", refund={"id": "rfnd_N1", "payment_id": "pay_N1", "amount": 199_900})
    assert (await user(c))["sub"]["status"] == "active"
    assert not [r for r in rzp.calls if r.url.path.endswith("/cancel")]

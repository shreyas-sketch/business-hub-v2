"""
Payments: Razorpay orders (one-time tiers) and subscriptions (Membership), signature checks, granting and
revoking access, and referral commissions.

Money rules
- Amounts are integers in paise everywhere (₹1,999 = 199900).
- Every change is idempotent, because Razorpay retries webhooks and the browser may verify after the webhook:
  a payment moves "created" → "paid" with a conditional update; subscription charges and commissions have
  deterministic ids (rzp_<payment id>, cm_<payment doc id>); refunds are keyed by Razorpay's refund id.
- One-time access is derived from the paid payments (each grants `access_days` from its paid_at, same-tier
  purchases stack), so applying a payment twice never adds time twice. Grants use $max, so they never shorten.
"""
import calendar
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

import httpx
from pymongo.errors import DuplicateKeyError

from . import plans
from .config import settings
from .db import db, now
from .services import notify, track

log = logging.getLogger("billing")
API = "https://api.razorpay.com/v1"
ONE_TIME = tuple(t for t, p in plans.PLANS.items() if p["billing"] == "one_time")
LIVE_SUB = ("active", "pending", "authenticated", "paused")    # a subscription that is running or about to
FINAL_SUB = ("cancelled", "completed", "expired")              # a subscription that will never charge again
MEMBERSHIP_DAYS = 30


# ───────────────────────── Razorpay API ─────────────────────────
class RazorpayError(Exception):
    """Razorpay could not be reached, or refused the request."""


def configured() -> bool:
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def mode() -> str:
    """razorpay = real checkout · dev = test payments on a local machine · contact = "our team will call you"."""
    if configured():
        return "razorpay"
    return "dev" if settings.local_dev else "contact"


def http_client() -> httpx.AsyncClient:
    """One place to build the HTTP client, so tests can put a fake Razorpay behind it."""
    return httpx.AsyncClient(timeout=20)


async def rzp(method: str, path: str, body: dict | None = None) -> dict:
    try:
        async with http_client() as client:
            r = await client.request(method, f"{API}{path}", json=body,
                                     auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    except httpx.HTTPError as e:
        log.warning("Razorpay %s %s unreachable: %s", method, path, type(e).__name__)
        raise RazorpayError("Razorpay could not be reached") from e
    if r.status_code >= 400:
        try:
            desc = str(r.json()["error"]["description"])[:200]
        except Exception:
            desc = ""
        log.warning("Razorpay %s %s → %s %s", method, path, r.status_code, desc)
        raise RazorpayError(desc or f"Razorpay answered {r.status_code}")
    try:
        data = r.json()
    except ValueError as e:
        raise RazorpayError("Razorpay sent an unreadable answer") from e
    if not isinstance(data, dict):
        raise RazorpayError("Razorpay sent an unexpected answer")
    return data


# ───────────────────────── signatures ─────────────────────────
def _hmac(secret: str, message: bytes | str) -> str:
    data = message if isinstance(message, bytes) else message.encode()
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


def _same(expected: str, given: str | None) -> bool:
    return bool(given) and hmac.compare_digest(expected, str(given).strip().lower())


def order_signature_ok(order_id: str, payment_id: str, signature: str | None) -> bool:
    if not settings.razorpay_key_secret:
        return False
    return _same(_hmac(settings.razorpay_key_secret, f"{order_id}|{payment_id}"), signature)


def subscription_signature_ok(payment_id: str, subscription_id: str, signature: str | None) -> bool:
    if not settings.razorpay_key_secret:
        return False
    return _same(_hmac(settings.razorpay_key_secret, f"{payment_id}|{subscription_id}"), signature)


def webhook_signature_ok(raw_body: bytes, signature: str | None) -> bool:
    if not settings.razorpay_webhook_secret:
        log.error("Razorpay webhook refused: RAZORPAY_WEBHOOK_SECRET is not set")
        return False
    return _same(_hmac(settings.razorpay_webhook_secret, raw_body), signature)


# ───────────────────────── small helpers ─────────────────────────
def inr(paise: int) -> str:
    """199900 → ₹1,999 · 59970 → ₹599.70 (Indian digit grouping)."""
    paise = int(paise or 0)
    rupees, rest = divmod(abs(paise), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    return f"{'-' if paise < 0 else ''}₹{s}" + (f".{rest:02d}" if rest else "")


def percent_of(amount: int, percent: int) -> int:
    """Rounded half-up to the nearest paisa, in whole-number arithmetic."""
    return (int(amount) * int(percent) + 50) // 100


def add_months(at: datetime, months: int) -> datetime:
    month = at.month - 1 + months
    year, month = at.year + month // 12, month % 12 + 1
    return at.replace(year=year, month=month, day=min(at.day, calendar.monthrange(year, month)[1]))


def from_unix(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), timezone.utc) if value else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def notes_of(entity: dict | None) -> dict:
    notes = (entity or {}).get("notes")
    return notes if isinstance(notes, dict) else {}  # Razorpay sends [] when there are no notes


def sub_view(sub: dict | None) -> dict | None:
    if not sub:
        return None
    return {k: iso(sub.get(k)) for k in ("id", "status", "plan", "start_at", "paid_until", "cancel_at_cycle_end", "created_at")}


def is_member(sub: dict | None) -> bool:
    """A running Membership subscription the owner hasn't asked to end."""
    sub = sub or {}
    return sub.get("status") in LIVE_SUB and not sub.get("cancel_at_cycle_end")


async def business_name(user_id: str, fallback: str = "An owner you invited") -> str:
    b = await db().businesses.find_one({"owner_id": user_id}, {"name": 1}) or {}
    return b.get("name") or fallback


# ───────────────────────── one-time access ─────────────────────────
def access_from_payments(payments: list[dict]) -> dict:
    """Each paid one-time purchase grants its tier's access_days from paid_at; a purchase made while the same
    tier is still running starts when the earlier one ends (consecutive same-tier purchases stack)."""
    out: dict = {}
    for p in sorted(payments, key=lambda p: p["paid_at"]):
        days = plans.PLANS.get(p.get("tier"), {}).get("access_days")
        if not days or not p.get("paid_at"):
            continue
        start = max(out.get(p["tier"]) or p["paid_at"], p["paid_at"])
        out[p["tier"]] = start + timedelta(days=days)
    return out


async def _paid_one_time(user_id: str) -> list[dict]:
    return [p async for p in db().payments.find({"user_id": user_id, "status": "paid", "kind": {"$in": ["order", "dev"]},
                                                  "tier": {"$in": list(ONE_TIME)}})]


async def grant_access(user_id: str) -> None:
    """Extends (never shortens) each tier the owner has paid for. Safe to run any number of times."""
    derived = access_from_payments(await _paid_one_time(user_id))
    if derived:
        await db().users.update_one({"_id": user_id}, {"$max": {f"access.{t}": until for t, until in derived.items()}})


async def recompute_access(user_id: str) -> None:
    """After a refund: access is exactly what the remaining paid purchases give."""
    derived = access_from_payments(await _paid_one_time(user_id))
    await db().users.update_one({"_id": user_id}, {"$set": {"access": derived}})


# ───────────────────────── payments becoming paid ─────────────────────────
async def complete_payment(payment_id: str, rzp_payment_id: str | None = None) -> dict | None:
    """Marks a checkout payment (Razorpay order or dev test) paid, once, then grants what it bought.
    Granting and the commission are idempotent, so a retry after a crash finishes the job without doubling it."""
    paid_at = now()
    patch = {"status": "paid", "paid_at": paid_at, **({"rzp_payment_id": rzp_payment_id} if rzp_payment_id else {})}
    changed = await db().payments.update_one({"_id": payment_id, "status": "created"}, {"$set": patch})
    payment = await db().payments.find_one({"_id": payment_id})
    if not payment or payment["status"] != "paid":
        return payment
    if payment["tier"] in ONE_TIME:
        await grant_access(payment["user_id"])
    elif payment["tier"] == "lite" and payment["kind"] == "dev":
        await _dev_membership(payment)
    await add_commission(payment)
    if changed.modified_count:
        await track("payment_paid", payment["user_id"], tier=payment["tier"], amount=payment["amount"], kind=payment["kind"])
    if payment.get("rzp_payment_id") and await db().refunds.find_one({"rzp_payment_id": payment["rzp_payment_id"]}):
        payment = await settle_refunds(payment)  # the refund webhook arrived before this payment was recorded
    return payment


async def complete_order(order_id: str, rzp_payment_id: str | None, amount_seen: int | None = None) -> dict | None:
    """Webhook / verify for a Razorpay order we created. Returns None for orders that aren't ours
    (subscription invoices also come with an order id)."""
    payment = await db().payments.find_one({"rzp_order_id": order_id, "kind": "order"})
    if not payment:
        return None
    if amount_seen is not None and int(amount_seen) < payment["amount"]:
        log.error("Razorpay order %s paid %s, expected %s; not granting", order_id, amount_seen, payment["amount"])
        await track("payment_amount_mismatch", payment["user_id"], order=order_id, seen=int(amount_seen), expected=payment["amount"])
        return payment
    return await complete_payment(payment["_id"], rzp_payment_id)


async def _dev_membership(payment: dict) -> None:
    sub_id = f"dev_{payment['_id']}"
    paid_at = payment["paid_at"]
    await db().users.update_one({"_id": payment["user_id"], "sub.id": {"$ne": sub_id}}, {"$set": {"sub": {
        "id": sub_id, "status": "active", "plan": "lite", "start_at": paid_at, "paid_until": paid_at + timedelta(days=MEMBERSHIP_DAYS),
        "cancel_at_cycle_end": False, "created_at": paid_at}}})


# ───────────────────────── subscriptions ─────────────────────────
async def subscription_owner(entity: dict, charged: bool = False) -> tuple[dict | None, bool]:
    """The owner a Razorpay subscription belongs to, and whether it is (or should become) their current one.
    A subscription we don't hold yet (say, paid from a second browser tab) is adopted only while it is running
    and the owner has no running subscription of their own; an old, ended one never replaces the current one."""
    sub_id = str(entity.get("id") or "")
    if not sub_id:
        return None, False
    user = await db().users.find_one({"sub.id": sub_id})
    if user:
        return user, True
    uid = notes_of(entity).get("user_id")
    user = await db().users.find_one({"_id": str(uid)}) if uid else None
    if not user:
        return None, False
    if not charged and entity.get("status") not in LIVE_SUB:
        return user, False
    current = user.get("sub") or {}
    if current.get("status") in LIVE_SUB:
        log.warning("Subscription %s for %s ignored: the owner already has %s", sub_id, user["_id"], current.get("id"))
        await track("subscription_duplicate", user["_id"], sub=sub_id, current=current.get("id"))
        return user, False
    adopted = {"id": sub_id, "status": "created", "plan": "lite", "start_at": from_unix(entity.get("start_at")),
               "paid_until": current.get("paid_until"), "cancel_at_cycle_end": False, "created_at": now()}
    await db().users.update_one({"_id": user["_id"]}, {"$set": {"sub": adopted}})
    return await db().users.find_one({"_id": user["_id"]}), True


async def apply_subscription(entity: dict, charged: bool = False) -> tuple[dict | None, bool]:
    """Copies Razorpay's subscription status onto user.sub. paid_until only moves forward, and only from a
    cycle that is paid for (status active, or a charge event): a pending or halted cycle's end is never granted."""
    user, current = await subscription_owner(entity, charged)
    if not user or not current:
        return user, False
    sub = user.get("sub") or {}
    status = str(entity.get("status") or "")
    update: dict = {}
    if status and not (sub.get("status") in FINAL_SUB and status not in FINAL_SUB):  # a late event never revives an ended one
        update.setdefault("$set", {})["sub.status"] = status
    end = from_unix(entity.get("current_end"))
    if end and (charged or status == "active"):
        update["$max"] = {"sub.paid_until": end}
    if update:
        await db().users.update_one({"_id": user["_id"], "sub.id": entity["id"]}, update)
        if status and status != sub.get("status"):
            await track("subscription_status", user["_id"], sub=entity["id"], status=status)
    return await db().users.find_one({"_id": user["_id"]}), True


async def record_charge(user: dict, sub_id: str, pay: dict) -> tuple[dict | None, bool]:
    """One payments doc per Razorpay payment id, however many times the webhook is delivered."""
    pid = str(pay.get("id") or "")
    if not pid:
        return None, False
    at = now()
    doc = {"_id": f"rzp_{pid}", "user_id": user["_id"], "tier": "lite", "kind": "subscription", "amount": int(pay.get("amount") or 0),
           "currency": pay.get("currency", "INR"), "status": "paid", "rzp_payment_id": pid, "rzp_subscription_id": sub_id,
           "rzp_invoice_id": pay.get("invoice_id"), "paid_at": at, "created_at": at}
    try:
        await db().payments.insert_one(doc)
        new = True
    except DuplicateKeyError:
        new = False
    payment = await db().payments.find_one({"_id": doc["_id"]})
    if payment and payment["status"] == "paid":
        await add_commission(payment)
    if new:
        await track("payment_paid", user["_id"], tier="lite", amount=doc["amount"], kind="subscription")
        if await db().refunds.find_one({"rzp_payment_id": pid}):
            payment = await settle_refunds(payment)
    return payment, new


async def extend_without_cycle_end(user_id: str, sub_id: str, paid_at: datetime) -> None:
    """Fallback when a charge arrives without current_end: one more month from the later of now and paid_until."""
    user = await db().users.find_one({"_id": user_id, "sub.id": sub_id})
    if not user:
        return
    base = max((user.get("sub") or {}).get("paid_until") or paid_at, paid_at)
    await db().users.update_one({"_id": user_id, "sub.id": sub_id}, {"$max": {"sub.paid_until": base + timedelta(days=MEMBERSHIP_DAYS)}})


# ───────────────────────── refunds ─────────────────────────
async def apply_refund(entity: dict) -> dict | None:
    """refund.processed. Each refund id counts once; a refund that arrives before its payment is kept and
    applied when the payment is recorded."""
    pid = str(entity.get("payment_id") or "")
    amount = int(entity.get("amount") or 0)
    if not pid or amount <= 0:
        return None
    refund_id = str(entity.get("id") or f"rf_{pid}_{amount}")
    payment = await db().payments.find_one({"rzp_payment_id": pid})
    try:
        await db().refunds.insert_one({"_id": refund_id, "rzp_payment_id": pid, "payment_id": payment["_id"] if payment else None,
                                       "user_id": payment["user_id"] if payment else None, "amount": amount, "at": now()})
        await track("refund", payment["user_id"] if payment else None, payment=pid, amount=amount)
    except DuplicateKeyError:
        pass
    if not payment:
        log.warning("Refund %s for unknown payment %s kept for later", refund_id, pid)
        return None
    return await settle_refunds(payment)


async def settle_refunds(payment: dict) -> dict:
    """Derives the payment's refund state from its refunds, then revokes access and adjusts the commission."""
    refunded = 0
    async for r in db().refunds.find({"rzp_payment_id": payment["rzp_payment_id"]}):
        refunded += int(r.get("amount") or 0)
        if not r.get("payment_id"):
            await db().refunds.update_one({"_id": r["_id"]}, {"$set": {"payment_id": payment["_id"], "user_id": payment["user_id"]}})
    refunded = min(refunded, payment["amount"])
    full = refunded >= payment["amount"]
    patch = {"refunded_amount": refunded}
    if full and payment["status"] != "refunded":
        patch.update(status="refunded", refunded_at=now())
    await db().payments.update_one({"_id": payment["_id"]}, {"$set": patch})
    payment = await db().payments.find_one({"_id": payment["_id"]})
    if payment["tier"] in ONE_TIME and full:
        await recompute_access(payment["user_id"])
    elif payment["tier"] == "lite" and full:
        await _end_membership_after_refund(payment)
    await _commission_after_refund(payment)
    return payment


async def _end_membership_after_refund(payment: dict) -> None:
    """A fully refunded Membership charge ends Membership now and stops future charges."""
    user = await db().users.find_one({"_id": payment["user_id"]}, {"sub": 1})
    sub = (user or {}).get("sub") or {}
    if not sub or (payment.get("rzp_subscription_id") and payment["rzp_subscription_id"] != sub.get("id")):
        return  # a charge from an older subscription never ends the one running now
    patch = {"sub.status": "cancelled", "sub.paid_until": now(), "sub.cancel_at_cycle_end": False, "sub.refunded_at": now()}
    if configured() and str(sub.get("id", "")).startswith("sub_") and sub.get("status") not in ("cancelled", "completed", "expired"):
        try:
            await rzp("POST", f"/subscriptions/{sub['id']}/cancel", {"cancel_at_cycle_end": 0})
        except RazorpayError:
            patch["sub.needs_attention"] = "Refunded, but the subscription could not be cancelled in Razorpay. Cancel it in the dashboard."
    await db().users.update_one({"_id": payment["user_id"]}, {"$set": patch})


async def _commission_after_refund(payment: dict) -> None:
    cm = await db().commissions.find_one({"_id": f"cm_{payment['_id']}"})
    if not cm:
        return
    net = payment["amount"] - payment.get("refunded_amount", 0)
    due = percent_of(net, cm["percent"]) if payment["status"] != "refunded" else 0
    if cm["status"] in ("pending", "approved"):
        if due <= 0:
            await db().commissions.update_one({"_id": cm["_id"], "status": {"$in": ["pending", "approved"]}},
                                              {"$set": {"status": "void", "void_reason": "refunded", "voided_at": now()}})
        elif due < cm["amount"]:
            await db().commissions.update_one({"_id": cm["_id"], "status": {"$in": ["pending", "approved"]}},
                                              {"$set": {"amount": due, "adjusted_for_refund": True}})
    elif cm["status"] == "paid" and due < cm["amount"]:
        await db().commissions.update_one({"_id": cm["_id"], "status": "paid"},
                                          {"$set": {"clawback": True, "clawback_amount": cm["amount"] - due}})


# ───────────────────────── commissions ─────────────────────────
async def add_commission(payment: dict) -> dict | None:
    """30% (COMMISSION_PERCENT) of a referred owner's payment in their first COMMISSION_MONTHS, held for the
    refund window, then approved and paid out by an admin. One commission per payment."""
    if payment.get("status") != "paid" or int(payment.get("amount") or 0) <= 0:
        return None
    payer = await db().users.find_one({"_id": payment["user_id"]}, {"referred_by": 1, "created_at": 1})
    if not payer or not payer.get("referred_by") or not payer.get("created_at"):
        return None
    paid_at = payment.get("paid_at") or now()
    if paid_at >= add_months(payer["created_at"], settings.commission_months):
        return None
    referrer = await db().users.find_one({"_id": payer["referred_by"]}, {"_id": 1})
    if not referrer:
        return None
    cm = {"_id": f"cm_{payment['_id']}", "referrer_id": referrer["_id"], "friend_id": payer["_id"], "payment_id": payment["_id"],
          "tier": payment["tier"], "payment_amount": payment["amount"], "amount": percent_of(payment["amount"], settings.commission_percent),
          "percent": settings.commission_percent, "status": "pending", "available_at": paid_at + timedelta(days=settings.commission_hold_days),
          "created_at": now()}
    if cm["amount"] <= 0:
        return None
    try:
        await db().commissions.insert_one(cm)
    except DuplicateKeyError:
        return None
    who = await business_name(payer["_id"], "An owner you invited")
    await notify(referrer["_id"], f"You earned {inr(cm['amount'])} from {who}'s payment. "
                                  f"It's paid out after a {settings.commission_hold_days}-day refund window.")
    await track("commission_earned", referrer["_id"], friend_id=payer["_id"], amount=cm["amount"], tier=payment["tier"])
    return cm

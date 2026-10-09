"""
Running the Business automations: quote follow-ups, the customer desk (reorders, occasions, referrals, quiet customers)
and keeping Employz.ai in step with the hub's leads. Customer messages are written from fixed, polite wording (no AI run)
and wait in the Send list.
"""
from datetime import date, timedelta, timezone

from .. import connections, integrations
from ..db import IST, db, now
from ..services import new_id
from ..text import greeting_name
from . import catalog
from .approvals import create_approval
from .catalog import Skip
from .jobs import claim

QUOTE_DAYS = (2, 5, 10)
DESK_CAP = 30
SPACING_DAYS = 7


def _aware(dt):
    """Mongo hands back naive UTC datetimes; compare them as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def today_ist(at=None) -> date:
    return (at or now()).astimezone(IST).date()


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


async def _business(ws: str) -> dict:
    return await db().businesses.find_one({"owner_id": ws}) or {}


# ───────────────────────── customers from won leads ─────────────────────────
async def customer_from_lead(ws: str, lead: dict) -> None:
    """A won lead becomes (or updates) a customer, matched by phone number."""
    phone = lead.get("phone")
    if not phone:
        return
    today = today_ist().isoformat()
    value = float(lead.get("value") or 0)
    existing = await db().customers.find_one({"ws": ws, "phone": phone})
    if existing:
        await db().customers.update_one({"_id": existing["_id"]}, {"$set": {"last_purchase": today, "updated_at": now()},
                                                                   "$inc": {"purchases": 1, "total_value": value}})
    else:
        await db().customers.insert_one({"_id": new_id(), "ws": ws, "name": lead.get("name") or "Customer", "phone": phone, "tier": "",
                                         "total_value": value, "purchases": 1, "first_purchase": today, "last_purchase": today,
                                         "last_item": "", "reorder_days": None, "occasion": None, "source": "won lead",
                                         "lead_id": lead.get("_id"), "notes": "", "created_at": now(), "updated_at": now()})
    from ..routers.desk import retier
    await retier(ws)      # A, B and C follow the new value at once


# ───────────────────────── Employz.ai sync ─────────────────────────
async def crm_sync(owner: dict, lead_id: str) -> dict:
    ws = owner["_id"]
    conn = await connections.get(ws, "employz")
    if not connections.ready("employz", conn):
        return {"ok": False, "skipped": "not connected"}
    lead = await db().leads.find_one({"_id": lead_id, "owner_id": ws})
    if not lead:
        return {"ok": False, "skipped": "no lead"}
    b = await _business(ws)
    res = await integrations.employz_sync_lead(ws, conn, lead, b.get("name", ""))
    crm = {"contact_id": res.get("contact_id"), "opportunity_id": res.get("opportunity_id"), "synced_at": now(),
           "error": None if res.get("ok") else res.get("error")}
    await db().leads.update_one({"_id": lead_id}, {"$set": {"crm": crm}})
    return res


# ───────────────────────── quote follow-ups ─────────────────────────
def quote_text(name: str, business: str, number: str, n: int) -> str:
    hello = f"Hello {name}," if name and name != "there" else "Hello,"
    lines = {1: f"{hello} just checking that you received our quotation {number} from {business}. Happy to answer any question.",
             2: f"{hello} following up on quotation {number}. If anything needs changing to suit you, tell us and we'll update it.",
             3: f"{hello} a last note on quotation {number} from {business} — shall we go ahead, or would you like us to close it for now?"}
    return lines.get(n, lines[3])


async def quote_followup(owner: dict, run: dict):
    ws, at = owner["_id"], run["at"]
    today = today_ist(at)
    b = await _business(ws)
    made = 0
    async for q in db().quotes.find({"ws": ws, "kind": "quote", "status": "sent"}).limit(300):
        sent = _d(q.get("sent_on"))
        phone = (q.get("customer") or {}).get("phone")
        if not sent or not phone:
            continue
        age = (today - sent).days
        n = sum(1 for d in QUOTE_DAYS if age >= d)
        if n == 0 or n <= int(q.get("followups") or 0):
            continue
        if not await claim(f"quotefu:{q['_id']}:{n}", at):
            continue
        cust = q.get("customer") or {}
        name = greeting_name(cust.get("name", "")) or "there"
        await create_approval(owner, ws, "quote_followup", "quote", f"Follow-up {n} of {len(QUOTE_DAYS)} on quotation {q['number']} — {cust.get('name', '')}",
                              cust.get("name", ""), phone, quote_text(name, b.get("name") or "us", q["number"], n), quote_id=q["_id"], n=n)
        await db().quotes.update_one({"_id": q["_id"]}, {"$set": {"followups": n}})
        made += 1
    if not made:
        raise Skip("No open quotations need a follow-up today.")
    return f"{made} quotation follow-up{'s' if made != 1 else ''} ready in your Send list."


# ───────────────────────── the customer desk ─────────────────────────
def reorder_text(name, business, item):
    hello = f"Hello {name}," if name and name != "there" else "Hello,"
    what = f" for {item}" if item else ""
    return f"{hello} it's about time to reorder{what} from {business}. Shall we keep it ready for you? Just reply yes."


def occasion_text(name, business, label):
    hello = f"Dear {name}," if name and name != "there" else "Hello,"
    return f"{hello} warm wishes on your {label or 'special day'} from all of us at {business}!"


def referral_text(name, business):
    hello = f"Hello {name}," if name and name != "there" else "Hello,"
    return (f"{hello} thank you for choosing {business}! If you know someone who could use our help, could you share our number with them? "
            f"We'll take great care of them.")


def quiet_text(name, business):
    hello = f"Hello {name}," if name and name != "there" else "Hello,"
    return f"{hello} it's been a while! Just checking in from {business} — is there anything we can help you with this month?"


async def customer_desk(owner: dict, run: dict):
    ws, at = owner["_id"], run["at"]
    today = today_ist(at)
    b = await _business(ws)
    business = b.get("name") or "us"
    made = {"reorder": 0, "occasion": 0, "referral": 0, "quiet": 0}

    async def ask(c: dict, what: str, text: str, title: str, mark: dict) -> bool:
        if sum(made.values()) >= DESK_CAP or not await claim(f"desk:{what}:{c['_id']}:{today.isoformat()}", at):
            return False
        await create_approval(owner, ws, "customer_desk", "customer", title, c.get("name", ""), c["phone"], text, customer_id=c["_id"], desk=what)
        await db().customers.update_one({"_id": c["_id"]}, {"$set": {**mark, "last_contacted_at": at}})
        made[what] += 1
        return True

    async for c in db().customers.find({"ws": ws, "phone": {"$nin": [None, ""]}, "opted_out": {"$ne": True}}).limit(5000):
        name = greeting_name(c.get("name", "")) or "there"
        last = _d(c.get("last_purchase"))
        first = _d(c.get("first_purchase")) or last
        occ = c.get("occasion") or {}
        if occ.get("date") and occ["date"] == today.strftime("%m-%d") and c.get("occasion_wished") != today.year:
            if await ask(c, "occasion", occasion_text(name, business, occ.get("label", "")), f"Greeting to {c.get('name', '')}: {occ.get('label', '')}",
                         {"occasion_wished": today.year}):
                continue
        recent = c.get("last_contacted_at")
        if recent and _aware(recent) > at - timedelta(days=SPACING_DAYS):
            continue      # one message a week at most (a greeting on the day is the exception)
        if last and c.get("reorder_days") and c.get("reorder_asked_for") != c.get("last_purchase"):
            due = last + timedelta(days=int(c["reorder_days"]))
            if today >= due - timedelta(days=2):
                if await ask(c, "reorder", reorder_text(name, business, c.get("last_item", "")), f"Reorder reminder to {c.get('name', '')}",
                             {"reorder_asked_for": c.get("last_purchase")}):
                    continue
        if first and 7 <= (today - first).days <= 30 and not c.get("referral_asked_at"):
            if await ask(c, "referral", referral_text(name, business), f"Referral request to {c.get('name', '')}", {"referral_asked_at": now()}):
                continue
        quiet_since = (today - last).days if last else None
        if (quiet_since and quiet_since >= 90 and (int(c.get("purchases") or 0) >= 2 or c.get("reorder_days"))
                and (not recent or _aware(recent) < at - timedelta(days=60))):
            await ask(c, "quiet", quiet_text(name, business), f"Check-in with {c.get('name', '')} (quiet for {quiet_since} days)", {})
    total = sum(made.values())
    if not total:
        raise Skip("No reorders, occasions, referrals or quiet customers today.")
    parts = [f"{n} {label}" for label, n in (("reorder reminder" + ("s" if made["reorder"] != 1 else ""), made["reorder"]),
                                              ("greeting" + ("s" if made["occasion"] != 1 else ""), made["occasion"]),
                                              ("referral request" + ("s" if made["referral"] != 1 else ""), made["referral"]),
                                              ("check-in" + ("s" if made["quiet"] != 1 else ""), made["quiet"])) if n]
    return ", ".join(parts) + " ready in your Send list."


catalog.attach("quote_followup", quote_followup)
catalog.attach("customer_desk", customer_desk)


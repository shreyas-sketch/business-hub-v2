"""
Money campaigns (Growth Mentorship): one campaign a month to the owner's own past contacts — old-customer revival,
a festival offer or a referral drive. The owner approves it once; the hub then sends it from the owner's WhatsApp number
as an approved template, in working hours, at most CAMPAIGN_DAILY_CAP a day, once per number per campaign.
Messages go only to people who have dealt with the business (customers and past leads), never to bought lists.
"""
import logging
from datetime import timedelta

from . import connections, integrations, plans
from .config import settings
from .db import IST, db, now
from .services import notify
from .text import greeting_name

log = logging.getLogger("campaigns")
PER_TICK = 25


async def audience(ws: str, aud: dict) -> list[dict]:
    """Customers in the chosen tiers (and, optionally, past leads that never bought) — one entry per number."""
    tiers = [t for t in (aud.get("tiers") or ["A", "B", "C"]) if t in ("A", "B", "C", "")]
    quiet = int(aud.get("quiet_days") or 0)
    out, seen = [], set()
    q: dict = {"ws": ws, "phone": {"$nin": [None, ""]}, "opted_out": {"$ne": True}}
    if tiers:
        q["tier"] = {"$in": tiers + ([""] if "C" in tiers else [])}
    async for c in db().customers.find(q, {"name": 1, "phone": 1, "last_purchase": 1}).limit(20000):
        if quiet and c.get("last_purchase"):
            if c["last_purchase"] > (now().astimezone(IST).date() - timedelta(days=quiet)).isoformat():
                continue
        p = integrations.digits(c["phone"])
        if p not in seen:
            seen.add(p)
            out.append({"phone": p, "name": c.get("name", ""), "source": "customer"})
    if aud.get("include_leads"):
        older = now() - timedelta(days=int(aud.get("lead_days") or 30))
        async for l in db().leads.find({"owner_id": ws, "status": {"$in": ["new", "contacted", "lost"]}, "created_at": {"$lt": older}},
                                       {"name": 1, "phone": 1}).limit(20000):
            p = integrations.digits(l.get("phone", ""))
            if p and p not in seen:
                seen.add(p)
                out.append({"phone": p, "name": l.get("name", ""), "source": "lead"})
    return out


async def send_batch(c: dict, at=None) -> int:
    """Sends the next few messages of a running campaign. Returns how many went out."""
    ws = c["ws"]
    at = at or now()
    local = at.astimezone(IST)
    if not 10 <= local.hour < 19:
        return 0
    owner = await db().users.find_one({"_id": ws})
    if not owner or owner.get("disabled") or not plans.has(owner, "campaigns"):
        await db().campaigns.update_one({"_id": c["_id"]}, {"$set": {"status": "stopped", "note": "The plan no longer includes campaigns."}})
        return 0
    conn = await connections.get(ws, "whatsapp")
    if not connections.ready("whatsapp", conn) or not (c.get("template") or conn.get("tpl_campaign")):
        await db().campaigns.update_one({"_id": c["_id"]}, {"$set": {"note": "Waiting: connect your WhatsApp number and its campaign template."}})
        return 0
    day = local.strftime("%Y-%m-%d")
    sent_today = await db().campaign_sends.count_documents({"ws": ws, "status": "sent", "day": day})
    room = min(PER_TICK, max(settings.campaign_daily_cap - sent_today, 0))
    if room <= 0:
        return 0
    b = await db().businesses.find_one({"owner_id": ws}, {"name": 1}) or {}
    n = 0
    async for s in db().campaign_sends.find({"campaign_id": c["_id"], "status": "queued"}).limit(room):
        claimed = await db().campaign_sends.update_one({"_id": s["_id"], "status": "queued"}, {"$set": {"status": "sending"}})
        if not claimed.modified_count:
            continue
        res = await integrations.wa_template(ws, conn, s["phone"], c.get("template") or conn.get("tpl_campaign"),
                                             [greeting_name(s.get("name", "")) or "there", b.get("name") or "us", c["message"]], s.get("name", ""), "campaign")
        await db().campaign_sends.update_one({"_id": s["_id"]}, {"$set": {"status": "sent" if res.get("sent") else "failed",
                                                                          "error": res.get("error"), "at": now(), "day": day}})
        await db().campaigns.update_one({"_id": c["_id"]}, {"$inc": {"sent" if res.get("sent") else "failed": 1}})
        n += 1
    if not await db().campaign_sends.find_one({"campaign_id": c["_id"], "status": {"$in": ["queued", "sending"]}}, {"_id": 1}):
        done = await db().campaigns.find_one_and_update({"_id": c["_id"], "status": "running"}, {"$set": {"status": "done", "done_at": now()}})
        if done:
            await notify(ws, f"Your campaign “{c.get('title', '')}” has gone out to everyone ({done.get('sent', 0)} sent).")
    return n


async def tick(at=None) -> int:
    total = 0
    async for c in db().campaigns.find({"status": "running"}).limit(200):
        try:
            total += await send_batch(c, at)
        except Exception:  # noqa: BLE001
            log.exception("campaign %s batch failed", c.get("_id"))
    return total


async def ensure_indexes() -> None:
    await db().campaigns.create_index([("ws", 1), ("created_at", -1)])
    await db().campaigns.create_index("status")
    await db().campaign_sends.create_index([("campaign_id", 1), ("status", 1)])
    await db().campaign_sends.create_index([("ws", 1), ("status", 1), ("day", 1)])

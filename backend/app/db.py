"""MongoDB access. One client per process; collections are reached through `db()`."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
IST = ZoneInfo("Asia/Kolkata")


def connect(url: str | None = None, name: str | None = None) -> AsyncIOMotorDatabase:
    global _client, _db
    _client = AsyncIOMotorClient(url or settings.mongo_url, serverSelectionTimeoutMS=8000, tz_aware=True)
    _db = _client[name or settings.db_name]
    return _db


def db() -> AsyncIOMotorDatabase:
    if _db is None:
        connect()
    return _db  # type: ignore[return-value]


def now() -> datetime:
    return datetime.now(timezone.utc)


def month_key(at: datetime | None = None) -> str:
    """AI-run allowances reset on the 1st of each month, India time."""
    return (at or now()).astimezone(IST).strftime("%Y-%m")


async def ensure_indexes() -> None:
    d = db()
    await d.users.create_index("phone", unique=True)
    # Email login is optional, so only accounts that have an email take part in the unique index.
    await d.users.create_index("email", unique=True, partialFilterExpression={"email": {"$type": "string"}})
    await d.users.create_index("ref_code", unique=True)
    await d.users.create_index("referred_by")
    await d.businesses.create_index("owner_id", unique=True)
    await d.sites.create_index("slug", unique=True)
    await d.sites.create_index("owner_id", unique=True)
    await d.leads.create_index([("owner_id", 1), ("created_at", -1)])
    await d.usage.create_index([("user_id", 1), ("month", 1)], unique=True)
    await d.runs.create_index([("user_id", 1), ("created_at", -1)])
    await d.outputs.create_index([("user_id", 1), ("created_at", -1)])
    await d.otps.create_index("phone")
    await d.otp_attempts.create_index("phone")
    await d.ratelimits.create_index([("key", 1), ("at", -1)])
    try:  # MongoDB Atlas expires these automatically; other engines fall back to cleanup in rate_limit()
        await d.ratelimits.create_index("at", name="ratelimits_ttl", expireAfterSeconds=86400)
        await d.otps.create_index("expires_at", name="otps_ttl", expireAfterSeconds=0)
        await d.otp_attempts.create_index("at", name="otp_attempts_ttl", expireAfterSeconds=86400)
    except Exception:
        pass
    await d.events.create_index([("type", 1), ("at", -1)])
    await d.cohorts.create_index("code", unique=True)
    await d.referral_rewards.create_index([("referrer_id", 1), ("friend_id", 1)], unique=True)


def public(doc: dict | None, *drop: str) -> dict | None:
    """Mongo document → JSON-safe dict with `id` instead of `_id`."""
    if doc is None:
        return None
    out = {k: v for k, v in doc.items() if k != "_id" and k not in drop}
    out["id"] = str(doc["_id"])
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out

"""Phone login, sessions and rate limits."""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request, Response

from .config import settings
from .db import db, now

COOKIE = "ah_session"
SESSION_DAYS = 30
_DEV_SECRET = "development-only-secret-do-not-use-in-production-0000"


def _secret() -> str:
    return settings.jwt_secret or _DEV_SECRET


def normalise_phone(raw: str) -> str:
    """Accepts 98200 00000, +91 98200-00000, 919820000000 … returns +919820000000. Indian numbers by default."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10 and digits[0] in "6789":
        digits = "91" + digits
    elif len(digits) == 10 and not (raw or "").strip().startswith("+"):  # ten digits typed without a country code: an Indian mobile
        raise HTTPException(400, "Enter a valid 10-digit Indian mobile number")
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    if not (10 <= len(digits) <= 15):
        raise HTTPException(400, "Enter a valid mobile number")
    if digits.startswith("91") and (len(digits) != 12 or digits[2] not in "6789"):
        raise HTTPException(400, "Enter a valid 10-digit Indian mobile number")
    return "+" + digits


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(phone: str, code: str) -> str:
    return hmac.new(_secret().encode(), f"otp:{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(phone: str, code: str, stored: str) -> bool:
    return hmac.compare_digest(hash_otp(phone, code), stored)


def hash_password(password: str) -> str:
    """scrypt (standard library), with a random salt per password."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str | None) -> bool:
    try:
        scheme, salt, digest = (stored or "").split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.compare_digest(test.hex(), digest)


def issue_session(response: Response, user: dict) -> None:
    token = jwt.encode({"sub": user["_id"], "v": user.get("session_version", 0),
                        "exp": now() + timedelta(days=SESSION_DAYS)}, _secret(), algorithm="HS256")
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=settings.secure_cookies, path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


async def optional_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    user = await db().users.find_one({"_id": claims.get("sub")})
    if not user or user.get("session_version", 0) != claims.get("v") or user.get("disabled"):
        return None
    return user


async def current_user(user: dict | None = Depends(optional_user)) -> dict:
    if not user:
        raise HTTPException(401, "Please log in")
    return user


async def require_admin(user: dict = Depends(current_user)) -> dict:
    # ADMIN_PHONES is checked on every request, so removing a number revokes access at once
    if user.get("role") != "admin" or user.get("phone") not in settings.admin_phones:
        raise HTTPException(403, "Admins only")
    return user


async def rate_limit(key: str, limit: int, window_seconds: int, message: str) -> None:
    """Counts recent hits for a key; refuses once the window is full."""
    since = now() - timedelta(seconds=window_seconds)
    count = await db().ratelimits.count_documents({"key": key, "at": {"$gte": since}})
    if count >= limit:
        raise HTTPException(429, message)
    await db().ratelimits.insert_one({"key": key, "at": now()})
    if secrets.randbelow(200) == 0:  # occasional sweep, in case TTL indexes are unavailable
        await db().ratelimits.delete_many({"at": {"$lt": now() - timedelta(days=1)}})
        await db().otp_attempts.delete_many({"at": {"$lt": now() - timedelta(days=1)}})
        await db().otps.delete_many({"expires_at": {"$lt": now()}})


def client_ip(request: Request) -> str:
    """The visitor's address as seen by our own proxy. Entries to the left of the ones our proxies add
    are typed by the visitor and can't be trusted, so we count TRUSTED_PROXY_HOPS from the right."""
    hops = settings.trusted_proxy_hops
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if hops > 0 and parts:
        return parts[-hops] if len(parts) >= hops else parts[0]
    return request.client.host if request.client else "unknown"

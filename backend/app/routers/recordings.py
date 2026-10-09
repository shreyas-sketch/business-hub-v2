"""Recordings: programs → sections → call recordings with notes.

The admin builds each program in Admin → Recordings and pastes the link of every video (Vimeo, YouTube, Loom, Wistia,
Bunny Stream, Google Drive, a GoHighLevel / .mp4 file, or any page). Owners watch them in the hub: the video streams
from the service that hosts it. Who can watch a program: everyone on the plan it belongs to or a higher one, plus
owners the admin adds by hand (for offline sales or a program outside the ladder). Team members see a program only
when the admin allows it.

programs          {_id, title, description, tier: free…office | none, team, published, order, allowed: [owner ids]}
rec_sections      {_id, program_id, title, order}
recordings        {_id, program_id, section_id, title, link, video{provider, provider_name, kind, embed, url},
                   recorded_on YYYY-MM-DD | None, duration_min, notes, resources[{label, url}], published, order}
rec_progress      {_id "user:recording", user_id, program_id, recording_id, at}
"""
import re
from datetime import date, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field, field_validator

from .. import plans, video
from ..context import Ctx, get_ctx
from ..db import db, now, public
from ..security import normalise_phone, require_admin
from ..services import new_id, track

router = APIRouter(prefix="/api")
TIER_CHOICES = plans.TIERS + ["none"]
MAX_PROGRAMS, MAX_SECTIONS, MAX_RECORDINGS = 100, 60, 300


# ───────────────────────── input shapes ─────────────────────────
def _clean(v: str | None) -> str:
    return " ".join((v or "").split())


def _title(v: str | None, least: int, most: int) -> str | None:
    if v is None:
        return None
    v = _clean(v)
    if len(v) < least:
        raise ValueError(f"needs at least {least} character{'s' if least > 1 else ''}")
    return v[:most]


class ProgramIn(BaseModel):
    title: str = Field(max_length=140)
    description: str = Field(default="", max_length=1000)
    tier: str = Field(default="program")
    team: bool = False
    published: bool = False

    @field_validator("tier")
    @classmethod
    def tier_ok(cls, v):
        if v not in TIER_CHOICES:
            raise ValueError("Choose who can watch")
        return v

    @field_validator("title")
    @classmethod
    def title_ok(cls, v):
        return _title(v, 2, 140)


class ProgramPatch(BaseModel):
    title: str | None = Field(default=None, max_length=140)
    description: str | None = Field(default=None, max_length=1000)
    tier: str | None = None
    team: bool | None = None
    published: bool | None = None

    @field_validator("tier")
    @classmethod
    def tier_ok(cls, v):
        if v is not None and v not in TIER_CHOICES:
            raise ValueError("Choose who can watch")
        return v

    @field_validator("title")
    @classmethod
    def title_ok(cls, v):
        return _title(v, 2, 140)


class SectionIn(BaseModel):
    title: str = Field(max_length=100)

    @field_validator("title")
    @classmethod
    def title_ok(cls, v):
        return _title(v, 1, 100)


class Resource(BaseModel):
    label: str = Field(default="", max_length=80)
    url: str = Field(max_length=1000)


class RecordingIn(BaseModel):
    section_id: str = Field(max_length=40)
    title: str = Field(max_length=160)
    link: str = Field(min_length=4, max_length=1000)
    recorded_on: str | None = Field(default=None, max_length=10)
    duration_min: int | None = Field(default=None, ge=1, le=600)
    notes: str = Field(default="", max_length=20_000)
    resources: list[Resource] = Field(default_factory=list, max_length=8)
    published: bool = True

    @field_validator("recorded_on")
    @classmethod
    def date_ok(cls, v):
        return _date(v)

    @field_validator("title")
    @classmethod
    def title_ok(cls, v):
        return _title(v, 2, 160)


class RecordingPatch(BaseModel):
    section_id: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=160)
    link: str | None = Field(default=None, min_length=4, max_length=1000)
    recorded_on: str | None = Field(default=None, max_length=10)
    duration_min: int | None = Field(default=None, ge=1, le=600)
    notes: str | None = Field(default=None, max_length=20_000)
    resources: list[Resource] | None = Field(default=None, max_length=8)
    published: bool | None = None

    @field_validator("recorded_on")
    @classmethod
    def date_ok(cls, v):
        return _date(v)

    @field_validator("title")
    @classmethod
    def title_ok(cls, v):
        return _title(v, 2, 160)


class BulkIn(BaseModel):
    section_id: str = Field(max_length=40)
    lines: str = Field(min_length=4, max_length=30_000)


class MoveIn(BaseModel):
    dir: str = Field(pattern="^(up|down)$")


class LinkIn(BaseModel):
    link: str = Field(max_length=1000)


class GrantIn(BaseModel):
    phone: str = Field(max_length=24)


class WatchedIn(BaseModel):
    watched: bool = True


def _date(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    try:
        d = date.fromisoformat(v)
    except ValueError:
        raise ValueError("Use a date like 2026-10-08")
    if not 2000 <= d.year <= 2100:
        raise ValueError("Use a real date")
    if d > date.today() + timedelta(days=1):
        raise ValueError("can't be in the future — recordings are of calls that already happened")
    return d.isoformat()


def _video(link: str) -> dict:
    try:
        return video.parse(link)
    except video.BadLink as e:
        raise HTTPException(400, str(e))


def _resources(items) -> list[dict]:
    out = []
    for r in items or []:
        url = (r.url or "").strip()
        if not url:
            continue
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        try:
            u = urlparse(url)
        except ValueError:
            u = None
        if (not u or u.scheme.lower() != "https" or not u.hostname or "." not in u.hostname or "@" in u.netloc
                or re.search(r"\s", url) or len(url) > 1000):
            raise HTTPException(400, "Each resource needs a full https:// link.")
        out.append({"label": _clean(r.label)[:80] or "Link", "url": url})
    return out


# ───────────────────────── helpers ─────────────────────────
async def _program(pid: str) -> dict:
    p = await db().programs.find_one({"_id": pid})
    if not p:
        raise HTTPException(404, "Program not found")
    return p


async def _section(sid: str) -> dict:
    s = await db().rec_sections.find_one({"_id": sid})
    if not s:
        raise HTTPException(404, "Section not found")
    return s


async def _recording(rid: str) -> dict:
    r = await db().recordings.find_one({"_id": rid})
    if not r:
        raise HTTPException(404, "Recording not found")
    return r


async def _next_order(coll: str, scope: dict) -> int:
    last = await db()[coll].find_one(scope, sort=[("order", -1)])
    return (last or {}).get("order", 0) + 1


async def _move(coll: str, doc: dict, scope: dict, direction: str) -> None:
    """Swaps a row with its neighbour in `scope`. Orders are renumbered first, so gaps and ties never stick."""
    rows = [r async for r in db()[coll].find(scope, {"order": 1}).sort([("order", 1), ("_id", 1)])]
    ids = [r["_id"] for r in rows]
    i = ids.index(doc["_id"])
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
    for n, rid in enumerate(ids, 1):
        await db()[coll].update_one({"_id": rid}, {"$set": {"order": n}})


def _tier_name(tier: str) -> str:
    return "Only owners you add" if tier == "none" else plans.PLANS[tier]["name"]


def program_view(p: dict, **extra) -> dict:
    out = public(p, "allowed")
    out.update(tier_name=_tier_name(p.get("tier", "program")), allowed_count=len(p.get("allowed") or []), **extra)
    return out


def recording_view(r: dict, watched: bool | None = None) -> dict:
    """The admin's full view, or — with `watched` — what an owner sees: nothing internal, and the original link only
    when the video opens outside the hub."""
    if watched is None:
        return public(r)
    v = r.get("video") or {}
    return {"id": r["_id"], "section_id": r["section_id"], "title": r["title"], "recorded_on": r.get("recorded_on"),
            "duration_min": r.get("duration_min"), "notes": r.get("notes", ""), "resources": r.get("resources") or [], "watched": watched,
            "video": {"provider": v.get("provider"), "provider_name": v.get("provider_name"), "kind": v.get("kind"), "embed": v.get("embed"),
                      **({"url": v.get("url")} if v.get("kind") == "link" else {})}}


def unlocked(p: dict, owner: dict) -> bool:
    if owner["_id"] in (p.get("allowed") or []):
        return True
    tier = p.get("tier", "program")
    return tier != "none" and plans.rank(plans.effective_plan(owner)) >= plans.rank(tier)


def visible(p: dict, ctx: Ctx) -> bool:
    """Shown in the owner's list (possibly locked, as an upgrade). Private programs show only to owners added to them;
    team members see only programs the admin opened to teams that the business has unlocked."""
    if not p.get("published"):
        return False
    if ctx.role != "owner":
        return bool(p.get("team")) and unlocked(p, ctx.owner)
    return p.get("tier") != "none" or unlocked(p, ctx.owner)


# ───────────────────────── owners and their teams ─────────────────────────
@router.get("/recordings")
async def my_programs(ctx: Ctx = Depends(get_ctx)):
    progs = [p async for p in db().programs.find({"published": True}).sort([("order", 1), ("_id", 1)]) if visible(p, ctx)]
    ids = [p["_id"] for p in progs]
    live: dict = {}
    async for r in db().recordings.find({"program_id": {"$in": ids}, "published": True}, {"program_id": 1}):
        live.setdefault(r["program_id"], set()).add(r["_id"])
    watched: dict = {}
    async for w in db().rec_progress.find({"user_id": ctx.actor, "program_id": {"$in": ids}}, {"program_id": 1, "recording_id": 1}):
        if w["recording_id"] in live.get(w["program_id"], ()):  # drafts and deleted recordings never count
            watched[w["program_id"]] = watched.get(w["program_id"], 0) + 1
    out = []
    for p in progs:
        total = len(live.get(p["_id"], ()))
        if not total:
            continue  # a program shows once it has something to watch
        is_open = unlocked(p, ctx.owner)
        tier = p.get("tier", "program")
        by_plan = tier != "none" and plans.rank(plans.effective_plan(ctx.owner)) >= plans.rank(tier)
        out.append({"id": p["_id"], "title": p["title"], "description": p.get("description", ""), "tier": tier,
                    "tier_name": _tier_name(tier), "locked": not is_open, "added": is_open and not by_plan,
                    "recordings": total, "watched": watched.get(p["_id"], 0) if is_open else 0})
    return out


async def _open_program(pid: str, ctx: Ctx) -> dict:
    p = await db().programs.find_one({"_id": pid})
    if not p or not visible(p, ctx):
        raise HTTPException(404, "Program not found")
    if not unlocked(p, ctx.owner):
        tier = p.get("tier", "program")
        t = plans.PLANS[tier]
        raise HTTPException(403, {"code": "locked", "feature": "recordings", "label": p["title"], "tier": tier, "tier_name": t["name"],
                                  "price_minor": t["price_minor"], "period": t["period"],
                                  "message": f"The recordings of {p['title']} are part of {t['name']}."})
    return p


@router.get("/recordings/{pid}")
async def program_detail(pid: str, ctx: Ctx = Depends(get_ctx)):
    p = await _open_program(pid, ctx)
    sections = [s async for s in db().rec_sections.find({"program_id": pid}).sort([("order", 1), ("_id", 1)])]
    recs = [r async for r in db().recordings.find({"program_id": pid, "published": True}).sort([("order", 1), ("_id", 1)])]
    seen = {w["recording_id"] async for w in db().rec_progress.find({"user_id": ctx.actor, "program_id": pid}, {"recording_id": 1})}
    by_section: dict = {}
    for r in recs:
        by_section.setdefault(r["section_id"], []).append(recording_view(r, r["_id"] in seen))
    secs = [{"id": s["_id"], "title": s["title"], "recordings": by_section.get(s["_id"], [])} for s in sections]
    secs = [s for s in secs if s["recordings"]]
    total = sum(len(s["recordings"]) for s in secs)
    return {"id": p["_id"], "title": p["title"], "description": p.get("description", ""), "tier_name": _tier_name(p.get("tier", "program")),
            "sections": secs, "recordings": total, "watched": sum(1 for s in secs for r in s["recordings"] if r["watched"])}


@router.post("/recordings/item/{rid}/watched")
async def mark_watched(rid: str, body: WatchedIn, ctx: Ctx = Depends(get_ctx)):
    r = await _recording(rid)
    if not r.get("published"):
        raise HTTPException(404, "Recording not found")
    await _open_program(r["program_id"], ctx)
    key = f"{ctx.actor}:{rid}"
    if body.watched:
        doc = {"user_id": ctx.actor, "program_id": r["program_id"], "recording_id": rid, "at": now()}
        try:
            await db().rec_progress.update_one({"_id": key}, {"$set": doc}, upsert=True)
        except DuplicateKeyError:  # two taps at once: the other one already saved it
            await db().rec_progress.update_one({"_id": key}, {"$set": doc})
    else:
        await db().rec_progress.delete_one({"_id": key})
    return {"ok": True, "watched": body.watched}


# ───────────────────────── admin ─────────────────────────
@router.post("/admin/video-check")
async def video_check(body: LinkIn, _: dict = Depends(require_admin)):
    return _video(body.link)


@router.get("/admin/programs")
async def admin_programs(_: dict = Depends(require_admin)):
    progs = [p async for p in db().programs.find({}).sort([("order", 1), ("_id", 1)])]
    counts: dict = {}
    async for r in db().recordings.find({}, {"program_id": 1}):
        counts[r["program_id"]] = counts.get(r["program_id"], 0) + 1
    secs: dict = {}
    async for s in db().rec_sections.find({}, {"program_id": 1}):
        secs[s["program_id"]] = secs.get(s["program_id"], 0) + 1
    return [program_view(p, recordings=counts.get(p["_id"], 0), sections=secs.get(p["_id"], 0)) for p in progs]


@router.post("/admin/programs")
async def create_program(body: ProgramIn, admin: dict = Depends(require_admin)):
    if await db().programs.count_documents({}) >= MAX_PROGRAMS:
        raise HTTPException(400, f"Up to {MAX_PROGRAMS} programs.")
    doc = {"_id": new_id(), "title": _clean(body.title), "description": body.description.strip(), "tier": body.tier, "team": body.team,
           "published": body.published, "order": await _next_order("programs", {}), "allowed": [], "created_at": now(), "updated_at": now(),
           "created_by": admin["_id"]}
    await db().programs.insert_one(doc)
    await track("program_created", admin["_id"], program=doc["_id"])
    return program_view(doc, recordings=0, sections=0)


@router.get("/admin/programs/{pid}")
async def admin_program(pid: str, _: dict = Depends(require_admin)):
    p = await _program(pid)
    sections = [s async for s in db().rec_sections.find({"program_id": pid}).sort([("order", 1), ("_id", 1)])]
    recs = [r async for r in db().recordings.find({"program_id": pid}).sort([("order", 1), ("_id", 1)])]
    by_section: dict = {}
    for r in recs:
        by_section.setdefault(r["section_id"], []).append(recording_view(r))
    allowed = []
    if p.get("allowed"):
        users = {u["_id"]: u async for u in db().users.find({"_id": {"$in": p["allowed"]}}, {"phone": 1, "name": 1})}
        names = {b["owner_id"]: b.get("name", "") async for b in db().businesses.find({"owner_id": {"$in": p["allowed"]}}, {"owner_id": 1, "name": 1})}
        allowed = [{"id": uid, "phone": users.get(uid, {}).get("phone", ""), "name": users.get(uid, {}).get("name", ""), "business": names.get(uid, "")}
                   for uid in p["allowed"]]
    return {**program_view(p, recordings=len(recs), sections=len(sections)),
            "sections_list": [{"id": s["_id"], "title": s["title"], "recordings": by_section.get(s["_id"], [])} for s in sections],
            "allowed": allowed}


@router.patch("/admin/programs/{pid}")
async def update_program(pid: str, body: ProgramPatch, _: dict = Depends(require_admin)):
    await _program(pid)
    patch = {k: (_clean(v) if k == "title" else v.strip() if isinstance(v, str) else v) for k, v in body.model_dump(exclude_none=True).items()}
    patch["updated_at"] = now()
    await db().programs.update_one({"_id": pid}, {"$set": patch})
    return program_view(await _program(pid))


@router.delete("/admin/programs/{pid}")
async def delete_program(pid: str, admin: dict = Depends(require_admin)):
    await _program(pid)
    await db().recordings.delete_many({"program_id": pid})
    await db().rec_sections.delete_many({"program_id": pid})
    await db().rec_progress.delete_many({"program_id": pid})
    await db().programs.delete_one({"_id": pid})
    await track("program_deleted", admin["_id"], program=pid)
    return {"ok": True}


@router.post("/admin/programs/{pid}/move")
async def move_program(pid: str, body: MoveIn, _: dict = Depends(require_admin)):
    await _move("programs", await _program(pid), {}, body.dir)
    return {"ok": True}


@router.post("/admin/programs/{pid}/allowed")
async def grant(pid: str, body: GrantIn, _: dict = Depends(require_admin)):
    await _program(pid)
    try:
        phone = normalise_phone(body.phone)
    except HTTPException:
        raise HTTPException(400, "Enter the owner's 10-digit mobile number.")
    user = await db().users.find_one({"phone": phone})
    if not user:
        raise HTTPException(404, "No owner has logged in with this number yet. Ask them to log in to the hub once, then add them.")
    if user.get("team_of"):
        raise HTTPException(400, "This number is a team member in someone else's hub. Add the business owner's number instead.")
    await db().programs.update_one({"_id": pid}, {"$addToSet": {"allowed": user["_id"]}, "$set": {"updated_at": now()}})
    return await admin_program(pid)


@router.delete("/admin/programs/{pid}/allowed/{uid}")
async def revoke(pid: str, uid: str, _: dict = Depends(require_admin)):
    await _program(pid)
    await db().programs.update_one({"_id": pid}, {"$pull": {"allowed": uid}, "$set": {"updated_at": now()}})
    return await admin_program(pid)


@router.post("/admin/programs/{pid}/sections")
async def add_section(pid: str, body: SectionIn, _: dict = Depends(require_admin)):
    await _program(pid)
    if await db().rec_sections.count_documents({"program_id": pid}) >= MAX_SECTIONS:
        raise HTTPException(400, f"Up to {MAX_SECTIONS} sections in a program.")
    doc = {"_id": new_id(), "program_id": pid, "title": _clean(body.title), "order": await _next_order("rec_sections", {"program_id": pid}),
           "created_at": now()}
    await db().rec_sections.insert_one(doc)
    return {"id": doc["_id"], "title": doc["title"], "recordings": []}


@router.patch("/admin/sections/{sid}")
async def rename_section(sid: str, body: SectionIn, _: dict = Depends(require_admin)):
    await _section(sid)
    await db().rec_sections.update_one({"_id": sid}, {"$set": {"title": _clean(body.title)}})
    return {"ok": True}


@router.delete("/admin/sections/{sid}")
async def delete_section(sid: str, _: dict = Depends(require_admin)):
    s = await _section(sid)
    ids = [r["_id"] async for r in db().recordings.find({"section_id": sid}, {"_id": 1})]
    await db().rec_progress.delete_many({"recording_id": {"$in": ids}})
    await db().recordings.delete_many({"section_id": sid})
    await db().rec_sections.delete_one({"_id": sid})
    return {"ok": True, "program_id": s["program_id"], "deleted_recordings": len(ids)}


@router.post("/admin/sections/{sid}/move")
async def move_section(sid: str, body: MoveIn, _: dict = Depends(require_admin)):
    s = await _section(sid)
    await _move("rec_sections", s, {"program_id": s["program_id"]}, body.dir)
    return {"ok": True}


@router.post("/admin/recordings")
async def add_recording(body: RecordingIn, admin: dict = Depends(require_admin)):
    s = await _section(body.section_id)
    if await db().recordings.count_documents({"section_id": s["_id"]}) >= MAX_RECORDINGS:
        raise HTTPException(400, f"Up to {MAX_RECORDINGS} recordings in a section.")
    doc = {"_id": new_id(), "program_id": s["program_id"], "section_id": s["_id"], "title": _clean(body.title), "link": body.link.strip(),
           "video": _video(body.link), "recorded_on": body.recorded_on, "duration_min": body.duration_min, "notes": body.notes.strip(),
           "resources": _resources(body.resources), "published": body.published,
           "order": await _next_order("recordings", {"section_id": s["_id"]}), "created_at": now(), "updated_at": now(), "created_by": admin["_id"]}
    await db().recordings.insert_one(doc)
    return recording_view(doc)


@router.post("/admin/recordings/bulk")
async def add_many(body: BulkIn, admin: dict = Depends(require_admin)):
    """One recording per line: Title | link | date (optional, YYYY-MM-DD). Every line is checked before any is added."""
    s = await _section(body.section_id)
    rows, errors = [], []
    lines = [l for l in body.lines.splitlines() if l.strip()]
    if len(lines) > 100:
        raise HTTPException(400, "Up to 100 lines at a time.")
    for n, line in enumerate(lines, 1):
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2 or len(parts[0]) < 2:
            errors.append(f"Line {n}: write it as Title | link")
            continue
        try:
            v = video.parse(parts[1])
            day = _date(parts[2]) if len(parts) > 2 and parts[2] else None
        except (video.BadLink, ValueError) as e:
            errors.append(f"Line {n}: {e}")
            continue
        rows.append((_clean(parts[0])[:160], parts[1], v, day))
    if errors:
        raise HTTPException(400, " · ".join(errors[:5]) + (f" · and {len(errors) - 5} more" if len(errors) > 5 else ""))
    if await db().recordings.count_documents({"section_id": s["_id"]}) + len(rows) > MAX_RECORDINGS:
        raise HTTPException(400, f"Up to {MAX_RECORDINGS} recordings in a section.")
    order = await _next_order("recordings", {"section_id": s["_id"]})
    docs = [{"_id": new_id(), "program_id": s["program_id"], "section_id": s["_id"], "title": t, "link": link, "video": v, "recorded_on": day,
             "duration_min": None, "notes": "", "resources": [], "published": True, "order": order + i, "created_at": now(), "updated_at": now(),
             "created_by": admin["_id"]} for i, (t, link, v, day) in enumerate(rows)]
    if docs:
        await db().recordings.insert_many(docs)
    return {"added": len(docs)}


@router.patch("/admin/recordings/{rid}")
async def update_recording(rid: str, body: RecordingPatch, _: dict = Depends(require_admin)):
    r = await _recording(rid)
    data = body.model_dump(exclude_unset=True)
    patch: dict = {"updated_at": now()}
    if data.get("section_id") and data["section_id"] != r["section_id"]:
        s = await _section(data["section_id"])
        if s["program_id"] != r["program_id"]:
            raise HTTPException(400, "Move recordings only between sections of the same program.")
        if await db().recordings.count_documents({"section_id": s["_id"]}) >= MAX_RECORDINGS:
            raise HTTPException(400, f"Up to {MAX_RECORDINGS} recordings in a section.")
        patch.update(section_id=s["_id"], order=await _next_order("recordings", {"section_id": s["_id"]}))
    if data.get("title"):
        patch["title"] = _clean(data["title"])
    if data.get("link"):
        patch.update(link=data["link"].strip(), video=_video(data["link"]))
    if "recorded_on" in data:
        patch["recorded_on"] = data["recorded_on"]
    if "duration_min" in data:
        patch["duration_min"] = data["duration_min"]
    if data.get("notes") is not None:
        patch["notes"] = data["notes"].strip()
    if data.get("resources") is not None:
        patch["resources"] = _resources(body.resources)
    if data.get("published") is not None:
        patch["published"] = data["published"]
    await db().recordings.update_one({"_id": rid}, {"$set": patch})
    return recording_view(await _recording(rid))


@router.delete("/admin/recordings/{rid}")
async def delete_recording(rid: str, _: dict = Depends(require_admin)):
    await _recording(rid)
    await db().recordings.delete_one({"_id": rid})
    await db().rec_progress.delete_many({"recording_id": rid})
    return {"ok": True}


@router.post("/admin/recordings/{rid}/move")
async def move_recording(rid: str, body: MoveIn, _: dict = Depends(require_admin)):
    r = await _recording(rid)
    await _move("recordings", r, {"section_id": r["section_id"]}, body.dir)
    return {"ok": True}


async def ensure_indexes() -> None:
    d = db()
    await d.programs.create_index([("published", 1), ("order", 1)])
    await d.rec_sections.create_index([("program_id", 1), ("order", 1)])
    await d.recordings.create_index([("section_id", 1), ("order", 1)])
    await d.recordings.create_index([("program_id", 1), ("published", 1)])
    await d.rec_progress.create_index([("user_id", 1), ("program_id", 1)])

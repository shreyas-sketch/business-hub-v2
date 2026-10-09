"""
Goals (Action Program: financial, functional and learning goals with weekly check-ins), the funnel and performance
dashboard (Membership), and the daily website-view counter both rely on.
Every endpoint checks the plan feature and the role on the server. Days and weeks are India time.
"""
import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from ..ai import membership_tasks as mt
from ..context import Ctx, feature
from ..db import IST, db, now, public
from ..services import new_id, run_ai, track
from .hub import profile_of

log = logging.getLogger("hub")
router = APIRouter(prefix="/api")


# ───────────────────────── India-time helpers ─────────────────────────
def ist_today() -> date:
    return now().astimezone(IST).date()


def ist_midnight(d: date) -> datetime:
    """Start of an India-time day, as a UTC datetime for querying."""
    return datetime(d.year, d.month, d.day, tzinfo=IST).astimezone(timezone.utc)


def ist_day(at: datetime) -> date:
    return at.astimezone(IST).date()


def month_start(d: date) -> date:
    return d.replace(day=1)


def prev_month_start(d: date) -> date:
    return (month_start(d) - timedelta(days=1)).replace(day=1)


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


# ───────────────────────── Website views (used by the funnel, dashboard and goals) ─────────────────────────
async def record_view(site: dict) -> None:
    """One more view of a live website today (India time). Never breaks the page if counting fails."""
    try:
        day = now().astimezone(IST).strftime("%Y-%m-%d")
        key = f"{site['_id']}:{day}"
        update = {"$inc": {"n": 1}, "$setOnInsert": {"site_id": site["_id"], "ws": site["owner_id"], "day": day}}
        try:
            await db().site_views.update_one({"_id": key}, update, upsert=True)
        except DuplicateKeyError:  # two first views of the day at the same moment
            await db().site_views.update_one({"_id": key}, {"$inc": {"n": 1}})
    except Exception as e:  # noqa: BLE001
        log.warning("could not count a website view: %s", e)


async def _views(ws: str, first: date, last: date | None = None) -> dict[str, int]:
    q: dict = {"ws": ws, "day": {"$gte": first.isoformat()}}
    if last:
        q["day"]["$lte"] = last.isoformat()
    out: dict[str, int] = {}
    async for v in db().site_views.find(q, {"day": 1, "n": 1}):
        out[v["day"]] = out.get(v["day"], 0) + int(v.get("n", 0))
    return out


# ═════════════════════════ 1. Goals ═════════════════════════
METRICS = {"custom": "Your check-ins", "leads": "New inquiries", "won": "Customers won", "site_views": "Website views"}
KINDS = {"financial": "Financial", "functional": "Functional", "learning": "Learning"}
MAX_GOALS = 50
MAX_CHECKINS = 200


class GoalIn(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    kind: Literal["financial", "functional", "learning"] = "financial"
    area: str = Field(default="", max_length=40)          # functional goals: sales, marketing, operations, accounts, HR
    approach: Literal["aspirational", "limitation"] = "aspirational"
    metric: Literal["custom", "leads", "won", "site_views"] = "custom"
    target: float = Field(gt=0, le=1e12)
    unit: str = Field(default="", max_length=30)
    start: date
    end: date


class GoalPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=140)
    kind: Literal["financial", "functional", "learning"] | None = None
    area: str | None = Field(default=None, max_length=40)
    approach: Literal["aspirational", "limitation"] | None = None
    metric: Literal["custom", "leads", "won", "site_views"] | None = None
    target: float | None = Field(default=None, gt=0, le=1e12)
    unit: str | None = Field(default=None, max_length=30)
    start: date | None = None
    end: date | None = None


class CheckinIn(BaseModel):
    value: float = Field(ge=0, le=1e12)  # progress toward a target: never below zero
    note: str = Field(default="", max_length=300)


def _check_window(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(400, "The end date must be after the start date.")
    if (end - start).days > 3 * 366:
        raise HTTPException(400, "Keep a goal to three years or less. Break bigger ones into yearly goals.")


async def goal_current(ws: str, g: dict) -> float:
    start, end = date.fromisoformat(g["start"]), date.fromisoformat(g["end"])
    lo, hi = ist_midnight(start), ist_midnight(end + timedelta(days=1))
    if g["metric"] == "leads":
        return float(await db().leads.count_documents({"owner_id": ws, "created_at": {"$gte": lo, "$lt": hi}}))
    if g["metric"] == "won":
        return float(await db().leads.count_documents({"owner_id": ws, "status": "won", "created_at": {"$gte": lo, "$lt": hi}}))
    if g["metric"] == "site_views":
        return float(sum((await _views(ws, start, end)).values()))
    checkins = g.get("checkins") or []
    return float(max(checkins, key=lambda c: c["at"])["value"]) if checkins else 0.0


async def goal_view(ws: str, g: dict, today: date | None = None) -> dict:
    today = today or ist_today()
    start, end = date.fromisoformat(g["start"]), date.fromisoformat(g["end"])
    current = await goal_current(ws, g)
    total = (end - start).days + 1
    elapsed = min(max((today - start).days + 1, 0), total)
    expected = round(elapsed / total * 100, 1)
    pct = round(current / g["target"] * 100, 1) if g["target"] else 0.0
    status = "done" if current >= g["target"] else ("behind" if pct + 5 < expected else "on_track")
    out = public(g)
    out.setdefault("kind", "financial")
    out["kind_label"] = KINDS.get(out["kind"], "Financial")
    out.update(current=current, pct=pct, expected_pct=expected, status=status, metric_label=METRICS[g["metric"]],
               total_days=total, elapsed_days=elapsed, days_left=max((end - today).days, 0), ended=today > end,
               checkins=[{**c, "at": _iso(c["at"])} for c in g.get("checkins") or []])
    if g.get("coach"):
        out["coach"] = {**g["coach"], "at": _iso(g["coach"].get("at"))}
    return out


async def _goal(ctx: Ctx, goal_id: str) -> dict:
    g = await db().goals.find_one({"_id": goal_id, "ws": ctx.ws})
    if not g:
        raise HTTPException(404, "Goal not found")
    return g


@router.get("/goals")
async def list_goals(ctx: Ctx = Depends(feature("goals", "manager"))):
    today = ist_today()
    views = [await goal_view(ctx.ws, g, today) async for g in db().goals.find({"ws": ctx.ws}).limit(MAX_GOALS)]
    # Running goals first (soonest deadline first), then finished ones (most recent first)
    running = sorted([v for v in views if not v["ended"]], key=lambda v: (v["end"], v["created_at"]))
    ended = sorted([v for v in views if v["ended"]], key=lambda v: v["end"], reverse=True)
    return running + ended


@router.post("/goals")
async def create_goal(body: GoalIn, ctx: Ctx = Depends(feature("goals", "manager"))):
    _check_window(body.start, body.end)
    if await db().goals.count_documents({"ws": ctx.ws}) >= MAX_GOALS:
        raise HTTPException(400, f"You can keep up to {MAX_GOALS} goals. Delete an old one first.")
    g = {"_id": new_id(), "ws": ctx.ws, "title": body.title.strip(), "kind": body.kind, "area": body.area.strip(), "approach": body.approach,
         "metric": body.metric, "target": float(body.target),
         "unit": body.unit.strip(), "start": body.start.isoformat(), "end": body.end.isoformat(), "checkins": [],
         "created_by": ctx.actor, "created_at": now()}
    await db().goals.insert_one(g)
    await track("goal_created", ctx.ws, metric=body.metric)
    return await goal_view(ctx.ws, g)


@router.patch("/goals/{goal_id}")
async def update_goal(goal_id: str, body: GoalPatch, ctx: Ctx = Depends(feature("goals", "manager"))):
    g = await _goal(ctx, goal_id)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    for k in ("start", "end"):
        if k in patch:
            patch[k] = patch[k].isoformat()
    if "title" in patch:
        patch["title"] = patch["title"].strip()
    if "unit" in patch:
        patch["unit"] = patch["unit"].strip()
    if "area" in patch:
        patch["area"] = patch["area"].strip()
    merged = {**g, **patch}
    _check_window(date.fromisoformat(merged["start"]), date.fromisoformat(merged["end"]))
    if patch:
        await db().goals.update_one({"_id": g["_id"]}, {"$set": {**patch, "updated_at": now(), "updated_by": ctx.actor}})
    return await goal_view(ctx.ws, await db().goals.find_one({"_id": g["_id"]}))


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: str, ctx: Ctx = Depends(feature("goals", "manager"))):
    await db().goals.delete_one({"_id": goal_id, "ws": ctx.ws})
    return {"ok": True}


@router.post("/goals/{goal_id}/checkins")
async def add_checkin(goal_id: str, body: CheckinIn, ctx: Ctx = Depends(feature("goals", "manager"))):
    g = await _goal(ctx, goal_id)
    if g["metric"] != "custom":
        raise HTTPException(400, f"This goal counts {METRICS[g['metric']].lower()} by itself. No check-in needed.")
    checkins = (g.get("checkins") or []) + [{"at": now(), "value": float(body.value), "note": body.note.strip(), "by": ctx.actor}]
    await db().goals.update_one({"_id": g["_id"]}, {"$set": {"checkins": checkins[-MAX_CHECKINS:]}})
    return await goal_view(ctx.ws, await db().goals.find_one({"_id": g["_id"]}))


@router.post("/goals/{goal_id}/coach")
async def coach_goal(goal_id: str, ctx: Ctx = Depends(feature("goals", "manager"))):
    g = await _goal(ctx, goal_id)
    profile = await profile_of(ctx.ws)
    view = await goal_view(ctx.ws, g)
    result = await run_ai(ctx.owner, "goal_coach", mt.goal_coach(profile, view), f"Goal coach — {g['title']}", check=mt.coach_shape)
    await db().goals.update_one({"_id": g["_id"]}, {"$set": {"coach": {"actions": result["actions"], "at": now()}}})
    return await goal_view(ctx.ws, await db().goals.find_one({"_id": g["_id"]}))


# ═════════════════════════ 3. Funnel & performance dashboard ═════════════════════════
def _rate(n: int, d: int) -> float | None:
    return round(n / d * 100, 1) if d else None


@router.get("/insights/funnel")
async def funnel(days: int = 30, ctx: Ctx = Depends(feature("funnel", "manager"))):
    days = max(1, min(int(days), 365))
    first = ist_today() - timedelta(days=days - 1)
    since = ist_midnight(first)
    base = {"owner_id": ctx.ws, "created_at": {"$gte": since}}
    views = sum((await _views(ctx.ws, first)).values())
    leads = await db().leads.count_documents(base)
    contacted = await db().leads.count_documents({**base, "$or": [{"status": {"$ne": "new"}}, {"first_action_at": {"$exists": True}}]})
    won = await db().leads.count_documents({**base, "status": "won"})
    lost = await db().leads.count_documents({**base, "status": "lost"})
    steps = [{"key": "views", "label": "Website views", "n": views, "rate": None},
             {"key": "leads", "label": "Inquiries", "n": leads, "rate": _rate(leads, views)},
             {"key": "contacted", "label": "Contacted", "n": contacted, "rate": _rate(contacted, leads)},
             {"key": "won", "label": "Won", "n": won, "rate": _rate(won, contacted)}]
    return {"days": days, "from": first.isoformat(), "to": ist_today().isoformat(), "steps": steps, "lost": lost,
            "open": max(contacted - won - lost, 0), "waiting": max(leads - contacted, 0), "overall": _rate(won, leads)}


@router.get("/insights/dashboard")
async def dashboard(ctx: Ctx = Depends(feature("funnel", "manager"))):
    today = ist_today()
    this_monday = today - timedelta(days=today.weekday())
    first_monday = this_monday - timedelta(weeks=11)
    this_month, last_month = month_start(today), prev_month_start(today)
    first = min(first_monday, last_month)
    since = ist_midnight(first)

    weeks = [{"start": (first_monday + timedelta(weeks=i)).isoformat(), "leads": 0, "won": 0, "response": [], "views": 0, "runs": 0}
             for i in range(12)]
    months = {k: {"leads": 0, "won": 0, "response": [], "views": 0, "runs": 0} for k in ("this", "last")}

    def buckets(d: date):
        out = []
        if d >= first_monday:
            out.append(weeks[min((d - first_monday).days // 7, 11)])
        if d >= this_month:
            out.append(months["this"])
        elif d >= last_month:
            out.append(months["last"])
        return out

    async for lead in db().leads.find({"owner_id": ctx.ws, "created_at": {"$gte": since}},
                                      {"created_at": 1, "status": 1, "first_action_at": 1}).limit(50_000):
        for b in buckets(ist_day(lead["created_at"])):
            b["leads"] += 1
            b["won"] += lead.get("status") == "won"
            if lead.get("first_action_at"):
                b["response"].append(max((lead["first_action_at"] - lead["created_at"]).total_seconds(), 0) / 3600)
    for day, n in (await _views(ctx.ws, first)).items():
        for b in buckets(date.fromisoformat(day)):
            b["views"] += n
    async for run in db().runs.find({"user_id": ctx.ws, "status": "done", "created_at": {"$gte": since}}, {"created_at": 1}).limit(50_000):
        for b in buckets(ist_day(run["created_at"])):
            b["runs"] += 1

    def finish(b: dict) -> dict:
        out = {k: v for k, v in b.items() if k != "response"}
        out["response_hours"] = _median(b["response"])
        out["conversion"] = _rate(b["won"], b["leads"])
        return out

    return {"weeks": [finish(w) for w in weeks],
            "months": {"this": {"label": this_month.strftime("%B"), "so_far": True, **finish(months["this"])},
                       "last": {"label": last_month.strftime("%B"), "so_far": False, **finish(months["last"])}},
            "today": today.isoformat()}


async def ensure_indexes() -> None:
    d = db()
    await d.goals.create_index([("ws", 1), ("end", 1)])
    await d.site_views.create_index([("ws", 1), ("day", 1)])

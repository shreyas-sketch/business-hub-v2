"""
Team tools (Growth Mentorship and up): team logins with roles, team tasks, strategic and tactical meetings with the
meeting actions agent — plus voice-note transcription (for SOPs, meetings, onboarding, the English polisher, quotations).

Other modules add tasks through `create_task(ws, actor, title, assignee_id=None, due=None, note="", source=None)`.
"""
import logging
from datetime import date as Date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from .. import plans
from .. import transcribe as voice
from ..ai import team_tasks
from ..config import settings
from ..context import Ctx, feature, get_ctx
from ..db import db, now, public
from ..security import normalise_phone
from ..services import new_id, notify, refund_run, run_ai, runs_own_hub, spend_run, track
from ..text import greeting_name

router = APIRouter(prefix="/api")
log = logging.getLogger("hub")

DAY = r"^\d{4}-\d{2}-\d{2}$"
ROLE_LABEL = {"manager": "manager", "staff": "staff member", "owner": "owner"}


def _day(value) -> str | None:
    """'2026-10-31' → the same string if it is a real date, else None."""
    if not value:
        return None
    try:
        return Date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _nice_day(value: str | None) -> str:
    d = _day(value)
    return f"{Date.fromisoformat(d).day} {Date.fromisoformat(d):%b}" if d else ""


async def _business_name(ws: str) -> str:
    return (await db().businesses.find_one({"owner_id": ws}, {"name": 1}) or {}).get("name", "")


async def people_of(owner: dict) -> list[dict]:
    """The owner and every team member: everyone a task or a meeting action can go to."""
    out = [{"id": owner["_id"], "name": (owner.get("name") or "").strip() or "Owner", "role": "owner"}]
    async for u in db().users.find({"team_of": owner["_id"]}, {"name": 1, "team_role": 1, "phone": 1}).sort("created_at", 1):
        out.append({"id": u["_id"], "name": (u.get("name") or "").strip() or u["phone"], "role": u.get("team_role", "staff")})
    return out


async def _in_workspace(ws: str, user_id: str | None) -> bool:
    if not user_id:
        return False
    return user_id == ws or bool(await db().users.find_one({"_id": user_id, "team_of": ws}, {"_id": 1}))


# ───────────────────────── Team logins ─────────────────────────
class InviteIn(BaseModel):
    phone: str = Field(max_length=24)
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(default="staff", pattern="^(manager|staff)$")


class MemberPatch(BaseModel):
    role: str = Field(pattern="^(manager|staff)$")


def team_limit(owner: dict) -> int:
    """How many team logins the plan allows (set per plan in Admin → Plans & features)."""
    return plans.team_size(owner)


async def _team_used(ws: str) -> int:
    return (await db().users.count_documents({"team_of": ws})
            + await db().team_invites.count_documents({"owner_id": ws, "status": "pending"}))


def _local(phone: str) -> str:
    """+919820000000 → 98200 00000 (how people say their number)."""
    return f"{phone[3:8]} {phone[8:]}" if phone.startswith("+91") and len(phone) == 13 else phone


def _invite_view(inv: dict, business: str) -> dict:
    who = greeting_name(inv.get("name", "")) or "there"
    text = (f"Hi {who}, I've added you to {business or 'our business'} on the {settings.program_name}. "
            f"Log in at {settings.app_url}/login with this number ({_local(inv['phone'])}) to see your work.")
    return {**public(inv, "owner_id"), "message": text, "share_link": f"https://wa.me/{inv['phone'].lstrip('+')}?text={quote(text)}"}


@router.get("/team")
async def get_team(ctx: Ctx = Depends(feature("team_logins", "owner"))):
    business = await _business_name(ctx.ws)
    joined = {i.get("user_id"): i.get("joined_at") async for i in db().team_invites.find({"owner_id": ctx.ws, "status": "joined"})}
    members = []
    async for u in db().users.find({"team_of": ctx.ws}).sort("created_at", 1):
        at = joined.get(u["_id"]) or u.get("created_at")
        members.append({"id": u["_id"], "name": u.get("name", ""), "phone": u["phone"], "role": u.get("team_role", "staff"),
                        "joined_at": at.isoformat() if at else None,
                        "last_seen_at": u["last_seen_at"].isoformat() if u.get("last_seen_at") else None})
    invites = [_invite_view(i, business) async for i in db().team_invites.find({"owner_id": ctx.ws, "status": "pending"}).sort("created_at", -1)]
    return {"members": members, "invites": invites, "limit": team_limit(ctx.owner), "used": len(members) + len(invites),
            "login_url": f"{settings.app_url}/login"}


@router.post("/team/invites")
async def invite_member(body: InviteIn, ctx: Ctx = Depends(feature("team_logins", "owner"))):
    phone = normalise_phone(body.phone)
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(400, "Add the person's name.")
    if not any(phone.startswith("+" + cc) for cc in settings.otp_country_codes):
        raise HTTPException(400, "Please use an Indian mobile number.")
    if phone == ctx.owner["phone"]:
        raise HTTPException(400, "That's your own number. Add the number your team member uses.")
    existing = await db().users.find_one({"phone": phone})
    if existing:
        if existing.get("team_of") == ctx.ws:
            raise HTTPException(409, f"{existing.get('name') or 'This person'} is already on your team.")
        if existing.get("team_of"):
            raise HTTPException(409, "This number is already on another business's team. A number can be on one team only.")
        if await runs_own_hub(existing):
            raise HTTPException(409, "This number already runs its own business on the hub, so it can't join a team. Ask them for another number.")
    if await db().team_invites.find_one({"phone": phone, "status": "pending", "owner_id": {"$ne": ctx.ws}}, {"_id": 1}):
        raise HTTPException(409, "This number already has a team invite from another business. A number can be on one team only.")
    business = await _business_name(ctx.ws)
    mine = await db().team_invites.find_one({"phone": phone, "status": "pending", "owner_id": ctx.ws})
    if mine:  # inviting the same number again just updates the name and role
        await db().team_invites.update_one({"_id": mine["_id"]}, {"$set": {"name": name, "role": body.role, "updated_at": now()}})
        return _invite_view(await db().team_invites.find_one({"_id": mine["_id"]}), business)
    limit = team_limit(ctx.owner)
    if await _team_used(ctx.ws) >= limit:
        raise HTTPException(400, f"Your plan includes up to {limit} team logins. Remove someone or cancel an invite to add another.")
    await db().team_invites.update_one(
        {"owner_id": ctx.ws, "phone": phone, "status": "pending"},
        {"$setOnInsert": {"_id": new_id(), "name": name, "role": body.role, "created_at": now(), "invited_by": ctx.actor,
                          "user_id": None, "joined_at": None}}, upsert=True)
    await track("team_invite", ctx.ws, role=body.role)
    return _invite_view(await db().team_invites.find_one({"owner_id": ctx.ws, "phone": phone, "status": "pending"}), business)


@router.delete("/team/invites/{invite_id}")
async def revoke_invite(invite_id: str, ctx: Ctx = Depends(feature("team_logins", "owner"))):
    r = await db().team_invites.update_one({"_id": invite_id, "owner_id": ctx.ws, "status": "pending"},
                                           {"$set": {"status": "revoked", "revoked_at": now()}})
    if not r.matched_count:
        raise HTTPException(404, "Invite not found")
    return {"ok": True}


@router.patch("/team/members/{member_id}")
async def change_role(member_id: str, body: MemberPatch, ctx: Ctx = Depends(feature("team_logins", "owner"))):
    member = await db().users.find_one({"_id": member_id, "team_of": ctx.ws})
    if not member:
        raise HTTPException(404, "Team member not found")
    if member.get("team_role") != body.role:
        await db().users.update_one({"_id": member_id, "team_of": ctx.ws}, {"$set": {"team_role": body.role}})
        business = await _business_name(ctx.ws)
        await notify(member_id, f"You're now a {ROLE_LABEL[body.role]} on {business or 'the team'}'s hub.")
    return {"ok": True}


@router.delete("/team/members/{member_id}")
async def remove_member(member_id: str, ctx: Ctx = Depends(feature("team_logins", "owner"))):
    """Removes someone from the team and logs them out everywhere at once. Their open tasks go back to unassigned."""
    r = await db().users.update_one({"_id": member_id, "team_of": ctx.ws},
                                    {"$unset": {"team_of": "", "team_role": ""},
                                     "$set": {"team_removed_at": now(), "team_removed_from": ctx.ws},
                                     "$inc": {"session_version": 1}})
    if not r.matched_count:
        raise HTTPException(404, "Team member not found")
    await db().tasks.update_many({"ws": ctx.ws, "assignee_id": member_id, "status": "open"}, {"$set": {"assignee_id": None, "updated_at": now()}})
    await track("team_remove", ctx.ws, member=member_id)
    return {"ok": True}


@router.get("/team/people")
async def team_people(ctx: Ctx = Depends(get_ctx)):
    """Everyone in the workspace, for choosing who a task or a meeting action goes to."""
    if not (ctx.has("tasks") or ctx.has("meetings")):
        ctx.require("tasks")
    return await people_of(ctx.owner)


# ───────────────────────── Tasks ─────────────────────────
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=1000)
    due: str | None = Field(default=None, max_length=10)
    assignee_id: str | None = Field(default=None, max_length=64)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    due: str | None = Field(default=None, max_length=10)
    assignee_id: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, pattern="^(open|done)$")


SOURCES = ("meeting", "office", "manual")


async def _assigned_text(actor: str, title: str, due: str | None, source: dict) -> str:
    when = f" (due {_nice_day(due)})" if due else ""
    if source.get("kind") == "meeting":
        return f"New task from a team meeting: {title}{when}"
    if source.get("kind") == "office":
        return f"Your AI office added a task for you: {title}{when}"
    who = await db().users.find_one({"_id": actor}, {"name": 1}) if actor else None
    return f"{(who or {}).get('name') or 'Your team'} gave you a task: {title}{when}"


async def create_task(ws: str, actor: str, title: str, assignee_id: str | None = None, due: str | None = None,
                      note: str = "", source: dict | None = None) -> dict:
    """Adds a task to a workspace and tells the assignee (when someone else assigned it). Used by the API,
    the meeting actions agent and the office agents. An assignee outside the workspace or a bad date is dropped."""
    title = " ".join(str(title or "").split())[:200]
    if not title:
        raise HTTPException(400, "Give the task a title.")
    if assignee_id and not await _in_workspace(ws, assignee_id):
        assignee_id = None
    src = {"kind": (source or {}).get("kind") if (source or {}).get("kind") in SOURCES else "manual", "id": (source or {}).get("id")}
    doc = {"_id": new_id(), "ws": ws, "title": title, "note": str(note or "").strip()[:1000], "assignee_id": assignee_id or None,
           "due": _day(due), "status": "open", "source": src, "created_by": actor, "created_at": now(), "updated_at": now(), "done_at": None}
    await db().tasks.insert_one(doc)
    if doc["assignee_id"] and doc["assignee_id"] != actor:
        await notify(doc["assignee_id"], await _assigned_text(actor, title, doc["due"], src))
    await track("task_created", ws, kind=src["kind"])
    return public(doc)


def _task_view(t: dict, names: dict) -> dict:
    out = public(t)
    out["assignee_name"] = names.get(t.get("assignee_id"), "Former team member") if t.get("assignee_id") else ""
    out["created_by_name"] = names.get(t.get("created_by"), "")
    return out


@router.get("/tasks")
async def list_tasks(scope: str = "mine", status: str = "open", ctx: Ctx = Depends(feature("tasks"))):
    if scope not in ("mine", "all") or not ctx.at_least("manager"):
        scope = "mine"  # staff only ever see their own tasks
    q: dict = {"ws": ctx.ws}
    if status in ("open", "done"):
        q["status"] = status
    if scope == "mine":
        q["assignee_id"] = ctx.actor
    docs = [t async for t in db().tasks.find(q).sort("created_at", -1).limit(500)]
    # open first, then by due date (no date last); done ones newest first
    docs.sort(key=lambda t: (t["status"] == "done", t.get("due") is None, t.get("due") or ""))
    if status == "done":
        docs.sort(key=lambda t: t.get("done_at") or t["created_at"], reverse=True)
    names = {p["id"]: p["name"] for p in await people_of(ctx.owner)}
    return [_task_view(t, names) for t in docs]


@router.post("/tasks")
async def add_task(body: TaskIn, ctx: Ctx = Depends(feature("tasks"))):
    if body.due and not _day(body.due):
        raise HTTPException(400, "Choose a due date from the calendar.")
    if ctx.at_least("manager"):
        if body.assignee_id and not await _in_workspace(ctx.ws, body.assignee_id):
            raise HTTPException(400, "Choose someone from your team.")
        assignee = body.assignee_id or None
    else:
        if body.assignee_id and body.assignee_id != ctx.actor:
            raise HTTPException(403, "You can add tasks for yourself. Ask your manager to give tasks to others.")
        assignee = ctx.actor
    task = await create_task(ctx.ws, ctx.actor, body.title, assignee, body.due, body.note)
    names = {p["id"]: p["name"] for p in await people_of(ctx.owner)}
    return _task_view(await db().tasks.find_one({"_id": task["id"]}), names)


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskPatch, ctx: Ctx = Depends(feature("tasks"))):
    task = await db().tasks.find_one({"_id": task_id, "ws": ctx.ws})
    if not task:
        raise HTTPException(404, "Task not found")
    sent = body.model_fields_set
    if not ctx.at_least("manager"):
        if task.get("assignee_id") != ctx.actor:
            raise HTTPException(403, "You can only update your own tasks.")
        if sent - {"status"}:
            raise HTTPException(403, "Ask your manager to change this task. You can mark it done.")
    patch: dict = {}
    if "title" in sent:
        title = " ".join((body.title or "").split())
        if not title:
            raise HTTPException(400, "Give the task a title.")
        patch["title"] = title
    if "note" in sent:
        patch["note"] = (body.note or "").strip()
    if "due" in sent:
        if body.due and not _day(body.due):
            raise HTTPException(400, "Choose a due date from the calendar.")
        patch["due"] = _day(body.due)
    new_assignee = None
    if "assignee_id" in sent:
        if body.assignee_id and not await _in_workspace(ctx.ws, body.assignee_id):
            raise HTTPException(400, "Choose someone from your team.")
        patch["assignee_id"] = body.assignee_id or None
        if patch["assignee_id"] and patch["assignee_id"] != task.get("assignee_id") and patch["assignee_id"] != ctx.actor:
            new_assignee = patch["assignee_id"]
    if "status" in sent and body.status:
        patch["status"] = body.status
        patch["done_at"] = now() if body.status == "done" else None
    if patch:
        await db().tasks.update_one({"_id": task_id}, {"$set": {**patch, "updated_at": now(), "updated_by": ctx.actor}})
        if patch.get("status") == "done" and task.get("status") != "done":
            await track("task_done", ctx.ws)
    updated = await db().tasks.find_one({"_id": task_id})
    if new_assignee:
        await notify(new_assignee, await _assigned_text(ctx.actor, updated["title"], updated.get("due"), {"kind": "manual"}))
    return _task_view(updated, {p["id"]: p["name"] for p in await people_of(ctx.owner)})


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, ctx: Ctx = Depends(feature("tasks", "manager"))):
    r = await db().tasks.delete_one({"_id": task_id, "ws": ctx.ws})
    if not r.deleted_count:
        raise HTTPException(404, "Task not found")
    return {"ok": True}


# ───────────────────────── Strategic and tactical meetings ─────────────────────────
# (key, title, the question that guides the notes). Strategic: step back once a month or a quarter.
# Tactical: every week, check the goals person by person and set the next week's.
AGENDAS = {
    "strategic": [
        ("wins", "Wins since we last met",
         "What went well since the last strategic meeting? Share the good news so everyone sees the whole business."),
        ("setbacks", "What didn't go to plan",
         "The misses and the problems. Say them plainly — a team trusts a leader who shares both sides."),
        ("feedback", "Feedback round",
         "Each person hears from the others: what you're doing well, what isn't working, and what to do differently. "
         "Be specific — skills, effort or results. No sugar-coating, no venting."),
        ("goals", "Goals until the next strategic meeting",
         "From this year's goals, what will we achieve by the next strategic meeting? Cover money, customers, team, systems and "
         "learning — then each person's share. Remind everyone why it matters."),
        ("obstacles", "What could stop us",
         "List what could get in the way of these goals. For each new problem, keep asking why until you reach the real cause."),
        ("plan", "The plan, week by week",
         "Weekly milestones for sales and operations. Who builds which system or process, and by when. What each person will "
         "learn, and from whom. Any new situation to add to the culture charter: our way, not our way."),
        ("recognition", "Recognise the stars", "Name the people who made a difference, in front of everyone."),
        ("takeaways", "Close: one takeaway each", "Everyone shares their biggest takeaway from today in one line."),
    ],
    "tactical": [
        ("last_goals", "Last week's goals",
         "Put up the goals you set at the last meeting — money, customers, team, systems, learning. What got done and what didn't?"),
        ("checkins", "Each person's check-in",
         "One by one: my goal, what's done, what's not. For anything not done, ask \"What stopped you?\" rather than \"Why?\" — "
         "then: what was missing from my side, what I learned, where else this shows up. Close with what I'll do differently, "
         "what I'll finish, and by when."),
        ("applause", "Applause", "Who delivered this week? Say their name and give them a round of applause."),
        ("next_goals", "Goals for the coming week",
         "Adjust the plan: add what's pending, drop what isn't realistic. Clear, measurable goals for the team and for each person."),
        ("concerns", "Concerns and quick ideas",
         "Anyone stuck or worried about next week's goals? Quick ideas from the group. For a bigger problem, one person digs "
         "into the cause after the meeting."),
        ("takeaways", "Close: one lesson each", "Everyone shares one lesson from this week in a line."),
    ],
}
NOTES_MAX = 4000


class MeetingIn(BaseModel):
    type: str = Field(pattern="^(strategic|tactical)$")
    date: str = Field(pattern=DAY)
    title: str = Field(default="", max_length=120)
    attendees: list[str] = Field(default_factory=list, max_length=60)


class MeetingPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    date: str | None = Field(default=None, pattern=DAY)
    attendees: list[str] | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, pattern="^(open|closed)$")
    notes: dict[str, str] | None = None
    decisions: list[str] | None = Field(default=None, max_length=30)


def _default_title(kind: str, day: str) -> str:
    d = Date.fromisoformat(day)
    return f"{'Strategic meeting' if kind == 'strategic' else 'Weekly tactical'} — {d.day} {d:%b %Y}"


def _valid_attendees(ids: list[str], people: list[dict]) -> list[str]:
    known = {p["id"] for p in people}
    return list(dict.fromkeys(i for i in ids if i in known))


def _meeting_view(m: dict, names: dict) -> dict:
    out = public(m)
    out["attendee_names"] = [names.get(a, "Former team member") for a in m.get("attendees", [])]
    return out


def _meeting_row(m: dict) -> dict:
    return {"id": m["_id"], "type": m["type"], "title": m["title"], "date": m["date"], "status": m.get("status", "open"),
            "decisions": len(m.get("decisions") or []), "actions": len(m.get("actions") or []),
            "notes_filled": sum(1 for s in m.get("sections", []) if (s.get("notes") or "").strip()),
            "updated_at": m["updated_at"].isoformat() if m.get("updated_at") else None}


async def _meeting(ws: str, meeting_id: str) -> dict:
    m = await db().meetings.find_one({"_id": meeting_id, "ws": ws})
    if not m:
        raise HTTPException(404, "Meeting not found")
    return m


@router.get("/meetings")
async def list_meetings(ctx: Ctx = Depends(feature("meetings"))):
    return [_meeting_row(m) async for m in db().meetings.find({"ws": ctx.ws}).sort([("date", -1), ("created_at", -1)]).limit(200)]


@router.post("/meetings")
async def create_meeting(body: MeetingIn, ctx: Ctx = Depends(feature("meetings", "manager"))):
    if not _day(body.date):
        raise HTTPException(400, "Choose the meeting date from the calendar.")
    people = await people_of(ctx.owner)
    doc = {"_id": new_id(), "ws": ctx.ws, "type": body.type, "title": " ".join(body.title.split()) or _default_title(body.type, body.date),
           "date": body.date, "attendees": _valid_attendees(body.attendees, people),
           "sections": [{"key": k, "title": t, "prompt": p, "notes": ""} for k, t, p in AGENDAS[body.type]],
           "decisions": [], "actions": [], "status": "open", "created_by": ctx.actor, "created_at": now(), "updated_at": now()}
    await db().meetings.insert_one(doc)
    await track("meeting_created", ctx.ws, type=body.type)
    return _meeting_view(doc, {p["id"]: p["name"] for p in people})


@router.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: str, ctx: Ctx = Depends(feature("meetings"))):
    m = await _meeting(ctx.ws, meeting_id)
    return _meeting_view(m, {p["id"]: p["name"] for p in await people_of(ctx.owner)})


@router.patch("/meetings/{meeting_id}")
async def update_meeting(meeting_id: str, body: MeetingPatch, ctx: Ctx = Depends(feature("meetings", "manager"))):
    m = await _meeting(ctx.ws, meeting_id)
    people = await people_of(ctx.owner)
    patch: dict = {}
    if body.title is not None:
        title = " ".join(body.title.split())
        if not title:
            raise HTTPException(400, "Give the meeting a name.")
        patch["title"] = title
    if body.date is not None:
        if not _day(body.date):
            raise HTTPException(400, "Choose the meeting date from the calendar.")
        patch["date"] = body.date
    if body.attendees is not None:
        patch["attendees"] = _valid_attendees(body.attendees, people)
    if body.status is not None:
        patch["status"] = body.status
    if body.decisions is not None:
        patch["decisions"] = [" ".join(d.split())[:300] for d in body.decisions if d.strip()]
    if body.notes:
        index = {s["key"]: i for i, s in enumerate(m.get("sections", []))}
        for key, text in body.notes.items():
            if key not in index:
                continue
            if len(text) > NOTES_MAX:
                raise HTTPException(400, f"Notes for one section can be up to {NOTES_MAX:,} characters. Please shorten them.")
            patch[f"sections.{index[key]}.notes"] = text.strip()  # only the sections sent, so two editors don't overwrite each other
    if patch:
        await db().meetings.update_one({"_id": m["_id"]}, {"$set": {**patch, "updated_at": now(), "updated_by": ctx.actor}})
    return _meeting_view(await db().meetings.find_one({"_id": m["_id"]}), {p["id"]: p["name"] for p in people})


@router.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, ctx: Ctx = Depends(feature("meetings", "owner"))):
    r = await db().meetings.delete_one({"_id": meeting_id, "ws": ctx.ws})
    if not r.deleted_count:
        raise HTTPException(404, "Meeting not found")
    return {"ok": True}


def _same(text: str) -> str:
    return " ".join((text or "").lower().split()).rstrip(".")


@router.post("/meetings/{meeting_id}/actions")
async def pull_out_actions(meeting_id: str, ctx: Ctx = Depends(feature("meetings", "manager"))):
    """The meeting actions agent (one AI run): decisions and action items from the notes; a task for each new action."""
    m = await _meeting(ctx.ws, meeting_id)
    if not any((s.get("notes") or "").strip() for s in m.get("sections", [])):
        raise HTTPException(400, "Write some notes in the agenda first, then pull out the actions.")
    people = await people_of(ctx.owner)
    result = await run_ai(ctx.owner, "meeting_actions", team_tasks.meeting_actions(m, people, await _business_name(ctx.ws)),
                          f"Actions — {m['title']}", save_output=False, check=team_tasks.shape_actions)
    decisions = list(m.get("decisions") or [])
    seen = {_same(d) for d in decisions}
    for d in result["decisions"]:
        if _same(d) not in seen:
            seen.add(_same(d))
            decisions.append(d)
    actions = list(m.get("actions") or [])
    done = {_same(a["task"]) for a in actions}
    added = 0
    for a in result["actions"]:
        if _same(a["task"]) in done:  # pulling out actions again never doubles the tasks
            continue
        done.add(_same(a["task"]))
        person = team_tasks.match_person(a["owner"], people)
        due = _day(a["due"])
        task = await create_task(ctx.ws, ctx.actor, a["task"], person["id"] if person else None, due,
                                 note=f"From: {m['title']}", source={"kind": "meeting", "id": m["_id"]})
        actions.append({"task": task["title"], "owner_id": person["id"] if person else None, "owner_name": person["name"] if person else "",
                        "due": due, "task_id": task["id"]})
        added += 1
    await db().meetings.update_one({"_id": m["_id"]}, {"$set": {"decisions": decisions[:30], "actions": actions,
                                                                "actions_at": now(), "updated_at": now()}})
    out = _meeting_view(await db().meetings.find_one({"_id": m["_id"]}), {p["id"]: p["name"] for p in people})
    out["added"] = added
    return out


# ───────────────────────── Voice notes (SOP from a voice note) ─────────────────────────
VOICE_MAX = 10 * 1024 * 1024


# What a voice note is for → the plan feature and the lowest role that may send it
VOICE_USES = {"sop": ("voice_sop", "manager"), "meeting": ("meetings", "staff"), "onboarding": ("business_brain", "owner"),
              "polish": ("polish_voice", "staff"), "quote": ("quotations", "manager"), "gym": ("training_gym", "staff")}


@router.post("/voice/transcribe")
async def transcribe_voice(request: Request, ctx: Ctx = Depends(get_ctx)):
    """A voice note (multipart field "file", audio, up to 10 MB) → its transcript. Uses one AI run, refunded on failure.
    ?for= says what it is for (sop, meeting, onboarding, polish, quote, gym), which decides the plan and role needed."""
    use = request.query_params.get("for") or "sop"
    if use not in VOICE_USES:
        raise HTTPException(400, "Unknown voice note use")
    key, role = VOICE_USES[use]
    ctx.require(key)
    if not ctx.at_least(role):
        raise HTTPException(403, "Only the business owner can do this." if role == "owner" else "Ask your manager or the business owner to do this.")
    too_big = HTTPException(413, "That voice note is too big. Please keep it under 10 MB.")
    try:  # the size must be declared up front, so nothing big is ever read or buffered
        declared = int(request.headers.get("content-length") or "")
    except ValueError:
        raise HTTPException(411, "Please upload the voice note again.")
    if declared > VOICE_MAX + 256 * 1024:
        raise too_big
    if not voice.available():
        raise HTTPException(503, voice.NO_KEY)
    try:
        form = await request.form()
    except Exception:
        raise HTTPException(400, "Please send the voice note as a file.")
    try:
        f = form.get("file")
        if not isinstance(f, UploadFile):
            raise HTTPException(400, "Choose a voice note to upload.")
        ctype = (f.content_type or "").split(";")[0].strip().lower()
        if not (ctype.startswith("audio/") or ctype == "video/webm"):
            raise HTTPException(415, "That doesn't look like a voice note. Please send an audio file.")
        data = await f.read(VOICE_MAX + 1)
        filename = f.filename or "voice-note"
    finally:
        await form.close()
    if len(data) > VOICE_MAX:
        raise too_big
    if not data:
        raise HTTPException(400, "That voice note is empty. Please record it again.")
    run = await spend_run(ctx.owner, "voice_note")
    try:
        text = await voice.transcribe(data, filename, ctype)
    except HTTPException:
        await refund_run(run)
        raise
    except Exception as e:
        log.warning("voice note failed, run refunded: %s", str(e)[:300])
        await refund_run(run)
        raise HTTPException(502, "We couldn't read that voice note right now. Your run was not used — please try again.")
    text = (text or "").strip()[:8000]
    if not text:
        await refund_run(run)
        raise HTTPException(400, "We couldn't hear anything in that voice note. Try again a little closer to the phone.")
    await db().runs.update_one({"_id": run["_id"]}, {"$set": {"status": "done", "model": "speech"}})
    await track("run", ctx.ws, kind="voice_note")
    return {"text": text}


async def ensure_indexes() -> None:
    d = db()
    await d.team_invites.create_index([("phone", 1), ("status", 1)])
    await d.team_invites.create_index([("owner_id", 1), ("status", 1)])
    await d.users.create_index("team_of")
    await d.tasks.create_index([("ws", 1), ("status", 1), ("created_at", -1)])
    await d.tasks.create_index([("ws", 1), ("assignee_id", 1), ("status", 1)])
    await d.meetings.create_index([("ws", 1), ("date", -1)])

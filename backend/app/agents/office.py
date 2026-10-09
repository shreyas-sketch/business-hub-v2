"""
The AI office (LegacyWorkforce plan): the Chief of Staff and five departments — Marketing, Sales, Customer support,
Business intelligence, Operations & people — staffed by the 30 AI staff the owner picked from the 82 roles.

The Chief of Staff turns an instruction into a plan of steps using only the tools below. Each tool belongs to one
department and does real work in the hub: drafting follow-ups for waiting leads, writing posts, SOPs, hiring kits
and reports, creating team tasks, reminding customers who owe money — and any hired role can draft its own work
(role.draft). Anything that would message a customer goes to the Send list, unless the owner lets that department act
on its own (Sales and Customer support only; money messages always wait).

office_runs {_id, ws, instruction, by, status planning|running|done|partial|failed|stopped, summary,
             steps [{n, staff, tool, label, args, why, status queued|running|done|waiting|failed|skipped, note, refs}],
             created_at, finished_at, lease_until}
"""
import asyncio
import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

from .. import kits, plans
from ..ai import agent_tasks, office_tasks, tasks as ai_tasks
from ..db import IST, db, now, public
from ..services import new_id, notify, run_ai, track
from ..text import greeting_name
from . import catalog
from .approvals import create_approval
from .jobs import get_settings, record

log = logging.getLogger("office")

STAFF = {
    "chief":        {"title": "Chief of Staff", "what": "Plans every instruction, hands work to the right department, writes reports and the morning standup."},
    "marketing":    {"title": "Marketing", "what": "Be found, be trusted, be remembered: posts, scripts, website and Google, case studies."},
    "sales":        {"title": "Sales", "what": "Turn enquiries into orders: follow-ups, the pipeline, proposals, quotations."},
    "support":      {"title": "Customer support", "what": "Answer well and keep customers longer: replies, reviews, reorders, check-ins."},
    "intelligence": {"title": "Business intelligence", "what": "Decide from evidence: sales patterns, forecasts, pricing, competitors."},
    "operations":   {"title": "Operations & people", "what": "SOPs, team tasks, money owed, hiring and onboarding."},
}
CUSTOMER_FACING = {"sales", "support"}   # the departments whose messages may go out on their own (never money messages)
MAX_STEPS = 6


def agent_key(staff: str) -> str:
    return f"office_{staff}"


class Office:
    """What a tool gets: who it works for, the roles hired, and how to record what it made."""
    def __init__(self, owner: dict, profile: dict, run_id: str, hired: list[int] | None = None):
        self.owner, self.profile, self.run_id = owner, profile, run_id
        self.ws = owner["_id"]
        self.hired = hired or []


Tool = Callable[[Office, dict], Awaitable[tuple[str, dict]]]
TOOLS: dict[str, dict[str, Any]] = {}


def tool(name: str, staff: str, label: str, description: str, args: dict, uses_ai: bool):
    def deco(fn: Tool) -> Tool:
        TOOLS[name] = {"staff": staff, "label": label, "description": description, "args": args, "uses_ai": uses_ai, "fn": fn}
        return fn
    return deco


def _int(v, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _str(v, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit]


# ───────────────────────── Sales ─────────────────────────
@tool("sales.follow_up_leads", "sales", "Follow up waiting leads",
      "Drafts a WhatsApp follow-up for each lead that is new or contacted, at least a day old, and not followed up in the last 2 days.",
      {"max": "how many leads, 1–10 (default 5)"}, uses_ai=True)
async def follow_up_leads(o: Office, args: dict) -> tuple[str, dict]:
    limit = _int(args.get("max"), 5, 1, 10)
    cutoff, recent = now() - timedelta(days=1), now() - timedelta(days=2)
    made, sent, ids = 0, 0, []
    async for lead in db().leads.find({"owner_id": o.ws, "status": {"$in": ["new", "contacted"]}, "created_at": {"$lt": cutoff}}).sort("created_at", 1).limit(60):
        if made >= limit:
            break
        if not lead.get("phone") or (lead.get("last_followup_at") and lead["last_followup_at"] > recent):
            continue
        if await db().approvals.find_one({"ws": o.ws, "lead_id": lead["_id"], "status": "pending"}, {"_id": 1}):
            continue
        who = lead.get("name") or "a lead"
        text = await run_ai(o.owner, "followup", agent_tasks.followup(o.profile, lead, 1, 1), f"Office follow-up to {who}",
                            save_output=False, check=agent_tasks.followup_text)
        from .runners import has_link
        a = await create_approval(o.owner, o.ws, agent_key("sales"), "followup", f"Follow-up to {who} (Sales)",
                                  lead.get("name", ""), lead["phone"], text, allow_act=not has_link(text), lead_id=lead["_id"], office_run=o.run_id)
        made += 1
        sent += a["status"] == "sent"
        ids.append(a["_id"])
    if not made:
        waiting = [a["_id"] async for a in db().approvals.find({"ws": o.ws, "kind": "followup", "status": "pending"}, {"_id": 1})]
        if waiting:
            return f"No new follow-ups needed — {len(waiting)} already waiting in Approvals.", {"approvals": waiting}
        return "No leads need a follow-up right now.", {}
    if sent == made:
        return f"Sent {made} follow-up{'s' if made != 1 else ''} on WhatsApp.", {"approvals": ids}
    return f"Drafted {made} follow-up{'s' if made != 1 else ''}; {made - sent} waiting in Approvals.", {"approvals": ids}


@tool("sales.pipeline_summary", "intelligence", "Pipeline update", "Counts leads by status and lists who is waiting longest. No AI run.", {}, uses_ai=False)
async def pipeline_summary(o: Office, args: dict) -> tuple[str, dict]:
    counts = {}
    for s in ("new", "contacted", "won", "lost"):
        counts[s] = await db().leads.count_documents({"owner_id": o.ws, "status": s})
    oldest = [l.get("name") or "Unnamed" async for l in db().leads.find({"owner_id": o.ws, "status": "new"}).sort("created_at", 1).limit(3)]
    tail = f" Waiting longest: {', '.join(oldest)}." if oldest else ""
    return f"{counts['new']} new, {counts['contacted']} contacted, {counts['won']} won, {counts['lost']} lost.{tail}", {}


# ───────────────────────── Marketing ─────────────────────────
@tool("marketing.write_posts", "marketing", "Write a week of posts", "Writes seven social media posts, Monday to Sunday, saved to My outputs.",
      {"focus": "optional theme, e.g. an offer or festival"}, uses_ai=True)
async def write_posts(o: Office, args: dict) -> tuple[str, dict]:
    focus = _str(args.get("focus"), 120)
    result = await run_ai(o.owner, "posts", ai_tasks.social_posts(o.profile, focus), f"Week of posts{' — ' + focus if focus else ''} (Marketing)")
    out = await db().outputs.find_one({"user_id": o.ws, "kind": "posts"}, {"_id": 1}, sort=[("created_at", -1)])
    n = len((result or {}).get("posts", []))
    return f"Wrote {n} posts{' about ' + focus if focus else ''} — in My outputs.", {"outputs": [out["_id"]] if out else []}


# ───────────────────────── Operations ─────────────────────────
@tool("ops.write_sop", "operations", "Write an SOP", "Writes a step-by-step SOP for a process and saves it to the SOP library.",
      {"process": "the process, e.g. 'taking a new order'", "notes": "optional details"}, uses_ai=True)
async def write_sop(o: Office, args: dict) -> tuple[str, dict]:
    process = _str(args.get("process"), 300) or "our main process"
    doc = await kits.generate(o.owner, o.ws, "office", "sop", {"process": process if len(process) >= 3 else "our main process",
                                                               "notes": _str(args.get("notes"), 4000)}, o.profile,
                              extra={"by_agent": "Operations & people"})
    return f"Wrote the SOP “{doc['title']}” — in the SOP library.", {"kits": [doc["_id"]], "kit_kind": "sop"}


@tool("ops.create_tasks", "operations", "Create team tasks",
      "Creates tasks for the owner or named team members, each with a due date.",
      {"tasks": "list of {title, assignee (a team member's name or 'owner'), due_in_days}"}, uses_ai=False)
async def create_tasks(o: Office, args: dict) -> tuple[str, dict]:
    from ..routers.team import create_task, people_of
    people = await people_of(o.owner)
    by_name = {p["name"].lower(): p["id"] for p in people}
    items = args.get("tasks") if isinstance(args.get("tasks"), list) else []
    ids, names = [], []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        title = _str(item.get("title"), 200)
        if not title:
            continue
        who = _str(item.get("assignee"), 80).lower()
        assignee = o.ws if who in ("", "owner", "me", "boss") else by_name.get(who) or next((i for n, i in by_name.items() if who and who in n), o.ws)
        due = (now().astimezone(IST) + timedelta(days=_int(item.get("due_in_days"), 3, 0, 90))).strftime("%Y-%m-%d")
        t = await create_task(o.ws, "office", title, assignee, due, "Created by your AI office", {"kind": "office", "id": o.run_id})
        ids.append(t["id"])
        names.append(next((p["name"] for p in people if p["id"] == assignee), "you"))
    if not ids:
        return "No tasks to create.", {}
    return f"Created {len(ids)} task{'s' if len(ids) != 1 else ''} for {', '.join(sorted(set(names)))}.", {"tasks": ids}


# ───────────────────────── Accounts ─────────────────────────
@tool("accounts.remind_overdue", "operations", "Remind customers who owe money",
      "Prepares a polite WhatsApp reminder for every overdue amount in Money owed that has no reminder waiting. No AI run.", {}, uses_ai=False)
async def remind_overdue(o: Office, args: dict) -> tuple[str, dict]:
    from ..config import settings
    from .runners import MAX_REMINDERS, inr, ist_midnight, pretty_date, reminder_text
    today = now().astimezone(IST).strftime("%Y-%m-%d")
    cutoff = ist_midnight(now()) - timedelta(days=max(settings.reminder_gap_days - 1, 0))  # same spacing as the reminder agent
    b = await db().businesses.find_one({"owner_id": o.ws}) or {}
    business, how = b.get("name") or "us", (b.get("payment_note") or "").strip()
    made, sent, ids = 0, 0, []
    async for due in db().dues.find({"ws": o.ws, "status": "due", "due_date": {"$lt": today}, "reminders_sent": {"$lt": MAX_REMINDERS},
                                     "$or": [{"last_reminded_at": None}, {"last_reminded_at": {"$lt": cutoff}}]}).sort("due_date", 1).limit(30):
        if not due.get("phone") or await db().approvals.find_one({"ws": o.ws, "due_id": due["_id"], "status": "pending"}, {"_id": 1}):
            continue
        nth = due.get("reminders_sent", 0) + 1
        await db().dues.update_one({"_id": due["_id"]}, {"$inc": {"reminders_sent": 1}, "$set": {"last_reminded_at": now()}})
        name = greeting_name(due.get("customer", "")) or "there"
        amount, day = inr(due.get("amount", 0)), pretty_date(due.get("due_date", ""))
        a = await create_approval(o.owner, o.ws, agent_key("operations"), "reminder", f"Reminder to {due.get('customer', '')} — {amount} (Operations)",
                                  due.get("customer", ""), due["phone"], reminder_text(name, business, amount, day, how, due.get("invoice_no", "")),
                                  params=[name, business, amount, day, how or "Reply to this message and we'll share the details"],
                                  due_id=due["_id"], n=nth, office_run=o.run_id)
        made += 1
        sent += a["status"] == "sent"
        ids.append(a["_id"])
    if not made:
        waiting = [a["_id"] async for a in db().approvals.find({"ws": o.ws, "kind": "reminder", "status": "pending"}, {"_id": 1})]
        if waiting:
            return f"No new reminders due — {len(waiting)} already waiting in Approvals.", {"approvals": waiting}
        return "Nobody needs a payment reminder right now (each customer gets one every few days at most).", {}
    if sent == made:
        return f"Sent {made} payment reminder{'s' if made != 1 else ''}.", {"approvals": ids}
    return f"Prepared {made} payment reminder{'s' if made != 1 else ''}; {made - sent} waiting in Approvals.", {"approvals": ids}


@tool("accounts.money_summary", "operations", "Money owed update", "Totals what customers owe, what's overdue and what came in this month. No AI run.", {}, uses_ai=False)
async def money_summary(o: Office, args: dict) -> tuple[str, dict]:
    from .runners import inr
    today = now().astimezone(IST)
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    due = overdue = collected = 0
    async for d in db().dues.find({"ws": o.ws}, {"amount": 1, "status": 1, "due_date": 1, "paid_at": 1}):
        amt = int(d.get("amount") or 0)
        if d.get("status") == "due":
            due += amt
            overdue += amt if (d.get("due_date") or "9999") < today.strftime("%Y-%m-%d") else 0
        elif d.get("paid_at") and d["paid_at"] >= month_start:
            collected += amt
    return f"Owed {inr(due)} ({inr(overdue)} overdue); collected {inr(collected)} this month.", {}


# ───────────────────────── HR ─────────────────────────
@tool("hr.write_jd", "operations", "Write a hiring kit", "Writes a job post, interview questions and a scorecard for a role, saved to Hiring kits.",
      {"role": "the role, e.g. 'Sales executive'", "notes": "optional requirements"}, uses_ai=True)
async def write_jd(o: Office, args: dict) -> tuple[str, dict]:
    role = _str(args.get("role"), 80)
    doc = await kits.generate(o.owner, o.ws, "office", "jd", {"role": role if len(role) >= 2 else "Team member", "notes": _str(args.get("notes"), 2000)},
                              o.profile, extra={"by_agent": "Operations & people"})
    return f"Wrote the hiring kit for {doc['title']} — in Hiring kits.", {"kits": [doc["_id"]], "kit_kind": "jd"}


@tool("hr.role_clarity", "operations", "Write role clarity", "Writes a one-page role clarity document for a role, saved to Role clarity.",
      {"role": "the role", "person_name": "optional person in the role"}, uses_ai=True)
async def role_clarity(o: Office, args: dict) -> tuple[str, dict]:
    role = _str(args.get("role"), 80)
    doc = await kits.generate(o.owner, o.ws, "office", "role", {"role": role if len(role) >= 2 else "Team member",
                                                                "person_name": _str(args.get("person_name"), 80)}, o.profile,
                              extra={"by_agent": "Operations & people"})
    return f"Wrote role clarity for {doc['title']}.", {"kits": [doc["_id"]], "kit_kind": "role"}


# ───────────────────────── Any hired role ─────────────────────────
@tool("role.draft", "chief", "A hired role does its job", "One of your hired AI staff drafts its work (a document or messages), saved to My outputs.",
      {"role": "the role's name exactly as in the hired list", "brief": "what you want from them, in one or two lines"}, uses_ai=True)
async def role_draft(o: Office, args: dict) -> tuple[str, dict]:
    from .. import roles_catalog, tools
    name = _str(args.get("role"), 80).lower()
    hired = [roles_catalog.role(r) for r in getattr(o, "hired", [])]
    r = next((x for x in hired if x and x["name"].lower() == name), None) or next((x for x in hired if x and name and name in x["name"].lower()), None)
    if not r:
        return "That role isn't in your workforce — add it on the Workforce page.", {}
    brief = _str(args.get("brief"), 1500) or "Do your usual job for this business this week."
    res = await tools.run(o.owner, o.ws, "office", r["key"], {"brief": brief}, o.profile)
    return f"{r['name']} wrote “{res['title'][:80]}” — in My outputs.", {"outputs": [res["id"]], "role": r["id"], "department": r["department"]}


# ───────────────────────── Chief of Staff ─────────────────────────
@tool("chief.write_report", "chief", "Write a report", "Answers a question or makes a plan as a short written note from the hub's data, saved to My outputs.",
      {"topic": "what the owner wants to know or plan"}, uses_ai=True)
async def write_report(o: Office, args: dict) -> tuple[str, dict]:
    topic = _str(args.get("topic"), 1500) or "How is the business doing?"
    result = await run_ai(o.owner, "report", office_tasks.report(o.profile, topic, await snapshot(o.owner)), f"Report: {topic[:100]} (Chief of Staff)")
    out = await db().outputs.find_one({"user_id": o.ws, "kind": "report"}, {"_id": 1}, sort=[("created_at", -1)])
    return f"Wrote “{_str(result.get('title'), 80) or 'the report'}” — in My outputs.", {"outputs": [out["_id"]] if out else []}


@tool("chief.review_month", "chief", "Review the month so far", "Writes the monthly business review for the month so far, saved to Monthly reviews.", {}, uses_ai=True)
async def review_month(o: Office, args: dict) -> tuple[str, dict]:
    from .runners import review_now
    doc = await review_now(o.owner, "office", o.profile)
    return f"Wrote {doc['title']} — in Monthly reviews.", {"kits": [doc["_id"]], "kit_kind": "review"}


# ───────────────────────── the business at a glance ─────────────────────────
async def snapshot(owner: dict) -> dict:
    ws = owner["_id"]
    leads = {s: await db().leads.count_documents({"owner_id": ws, "status": s}) for s in ("new", "contacted", "won", "lost")}
    today = now().astimezone(IST).strftime("%Y-%m-%d")
    overdue = 0
    async for d in db().dues.find({"ws": ws, "status": "due", "due_date": {"$lt": today}}, {"amount": 1}):
        overdue += int(d.get("amount") or 0)
    return {"leads": {"waiting": leads["new"], "open": leads["new"] + leads["contacted"], "won": leads["won"], "lost": leads["lost"]},
            "money_overdue_rupees": overdue // 100,
            "tasks_open": await db().tasks.count_documents({"ws": ws, "status": "open"}),
            "approvals_waiting": await db().approvals.count_documents({"ws": ws, "status": "pending"}),
            "team_size": await db().users.count_documents({"team_of": ws})}


# ───────────────────────── staff settings ─────────────────────────
async def staff_settings(ws: str) -> dict[str, dict]:
    return {k: await get_settings(ws, agent_key(k)) for k in STAFF}


OWNER_TOOLS = {"hr.role_clarity", "chief.review_month"}  # they write documents only the owner may write


def available_tools(settings_by_staff: dict[str, dict], role: str = "owner", hired: list[int] | None = None) -> dict:
    from .. import roles_catalog
    out = {name: {"staff": t["staff"], "staff_title": STAFF[t["staff"]]["title"], "description": t["description"], "args": t["args"]}
           for name, t in TOOLS.items() if settings_by_staff.get(t["staff"], {}).get("on", True)
           and (role == "owner" or name not in OWNER_TOOLS) and name != "role.draft"}
    names = [roles_catalog.role(r) for r in (hired or [])]
    names = [r for r in names if r and settings_by_staff.get(r["department"], {}).get("on", True)]
    if names:
        out["role.draft"] = {"staff": "chief", "staff_title": "Your hired roles",
                             "description": TOOLS["role.draft"]["description"] + " Hired: " + "; ".join(f"{r['name']} ({r['summary']})" for r in names),
                             "args": TOOLS["role.draft"]["args"]}
    return out


async def hired_roles(ws: str) -> list[int]:
    doc = await db().workforce.find_one({"_id": ws}) or {}
    return [int(x) for x in doc.get("hired") or []]


def _clean_steps(raw: list, tools: dict) -> list[dict]:
    steps = []
    for item in (raw or [])[:MAX_STEPS]:
        if not isinstance(item, dict) or item.get("tool") not in tools:
            continue
        spec = TOOLS[item["tool"]]
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        staff, label = spec["staff"], spec["label"]
        if item["tool"] == "role.draft":
            from .. import roles_catalog
            r = next((x for x in roles_catalog.ROLES if x["name"].lower() == str(args.get("role", "")).lower()), None)
            if r:
                staff, label = r["department"], f"{r['name']}: {str(args.get('brief') or '')[:60]}"
        steps.append({"n": len(steps) + 1, "staff": staff, "tool": item["tool"], "label": label,
                      "args": {k: v for k, v in args.items() if k in spec["args"]}, "why": _str(item.get("why"), 200),
                      "status": "queued", "note": "", "refs": {}})
    return steps


# ───────────────────────── running an instruction ─────────────────────────
async def start(owner: dict, actor: str, instruction: str, profile: dict, role: str = "owner") -> dict:
    """Plans the instruction (one AI run) and saves the run. Execution is `execute(run_id)`."""
    instruction = " ".join(instruction.split())[:1500]
    settings_by_staff = await staff_settings(owner["_id"])
    if not settings_by_staff["chief"].get("on", True):
        raise HTTPException(400, "Your Chief of Staff is switched off. Switch them on to give the office instructions.")
    hired = await hired_roles(owner["_id"])
    tools = available_tools(settings_by_staff, role, hired)
    plan = await run_ai(owner, "office_plan", office_tasks.plan(profile, instruction, tools, await snapshot(owner), hired),
                        f"Office plan: {instruction[:100]}", save_output=False)
    steps = _clean_steps(plan.get("steps"), tools)
    if not steps:  # the planner found nothing usable: answer in writing instead of doing nothing
        steps = _clean_steps([{"tool": "chief.write_report", "args": {"topic": instruction}, "why": "A written answer to your instruction."}], tools)
    run = {"_id": new_id(), "ws": owner["_id"], "instruction": instruction, "by": actor, "status": "running",
           "summary": _str(plan.get("summary"), 200) or f"{len(steps)} steps", "steps": steps, "created_at": now(),
           "finished_at": None, "lease_until": now() + timedelta(minutes=10)}
    await db().office_runs.insert_one(run)
    await record(owner["_id"], agent_key("chief"), "done", f"Planned “{instruction[:80]}”: {run['summary']}", ref=run["_id"])
    await track("office_run", owner["_id"], steps=len(steps))
    return run


async def execute(run_id: str) -> dict:
    """Carries out each step in order. A step that runs out of AI runs stops the rest."""
    run = await db().office_runs.find_one({"_id": run_id})
    if not run:
        return {}
    owner = await db().users.find_one({"_id": run["ws"]})
    if not owner:
        return run
    from ..routers.hub import profile_of
    try:
        profile = await profile_of(run["ws"])
    except HTTPException:
        profile = {}
    office = Office(owner, profile, run_id, await hired_roles(run["ws"]))
    stop_note = "" if plans.has(owner, "agentic_office") else "Stopped: the AI office isn't part of the current plan."
    for step in run["steps"]:
        if step["status"] != "queued":
            continue
        if stop_note:
            step.update(status="skipped", note=stop_note)
            continue
        step["status"] = "running"
        await db().office_runs.update_one({"_id": run_id}, {"$set": {"steps": run["steps"], "lease_until": now() + timedelta(minutes=10)}})
        if not (await get_settings(run["ws"], agent_key(step["staff"]))).get("on", True):
            step.update(status="skipped", note=f"{STAFF[step['staff']]['title']} is switched off.")
            continue
        try:
            note, refs = await TOOLS[step["tool"]]["fn"](office, step["args"])
            waiting = bool(refs.get("approvals")) and "waiting" in note
            step.update(status="waiting" if waiting else "done", note=note, refs=refs)
            await record(run["ws"], agent_key(step["staff"]), "done", note, ref=run_id)
        except HTTPException as e:
            if e.status_code == 402:
                stop_note = "Stopped: this month's AI runs are used up."
                step.update(status="failed", note=stop_note)
            else:
                step.update(status="failed", note=e.detail if isinstance(e.detail, str) else "Couldn't finish this step.")
        except Exception:  # one broken step must not lose the rest of the run
            log.exception("office step failed")
            step.update(status="failed", note="Couldn't finish this step. Try again in a minute.")
    statuses = {s["status"] for s in run["steps"]}
    status = "failed" if statuses <= {"failed", "skipped"} else "partial" if "failed" in statuses else "done"
    await db().office_runs.update_one({"_id": run_id}, {"$set": {"steps": run["steps"], "status": status, "finished_at": now(), "lease_until": None}})
    done = sum(s["status"] in ("done", "waiting") for s in run["steps"])
    waiting = sum(s["status"] == "waiting" for s in run["steps"])
    await notify(run["ws"], f"Your AI office finished “{run['instruction'][:60]}”: {done} of {len(run['steps'])} steps done"
                            + (", messages waiting in your Send list." if waiting else "."))
    run.update(status=status)
    return run


async def resume_stale(at=None) -> int:
    """After a restart or deploy, an instruction that was mid-way carries on: the interrupted step is marked,
    the remaining steps run. Claimed, so only one worker resumes each run."""
    from .jobs import claim
    at = at or now()
    resumed = 0
    async for run in db().office_runs.find({"status": "running", "lease_until": {"$lt": at}}).limit(20):
        if not await claim(f"office-resume:{run['_id']}:{run['lease_until'].isoformat()}", at):
            continue
        steps = run["steps"]
        for st in steps:
            if st["status"] == "running":
                st.update(status="failed", note="Interrupted by an update to the hub. Give the instruction again if it's still needed.")
        await db().office_runs.update_one({"_id": run["_id"]}, {"$set": {"steps": steps, "lease_until": at + timedelta(minutes=10)}})
        await execute(run["_id"])
        resumed += 1
    return resumed


def run_view(run: dict) -> dict:
    out = public(run)
    if run.get("status") == "running" and run.get("lease_until") and run["lease_until"] < now() - timedelta(minutes=15):
        out["status"] = "stopped"  # the scheduler normally resumes it within a minute or two
    for s in out.get("steps", []):
        s["staff_title"] = STAFF[s["staff"]]["title"]
    return out


async def spawn(run_id: str) -> None:
    """Runs the steps in the background so the owner sees the plan at once and watches it progress."""
    async def go():
        try:
            await execute(run_id)
        except Exception:
            log.exception("office run failed")
            await db().office_runs.update_one({"_id": run_id}, {"$set": {"status": "failed", "finished_at": now()}})
    asyncio.create_task(go())


# ───────────────────────── the morning standup ─────────────────────────
async def standup_data(owner: dict, at) -> dict:
    from .runners import inr
    ws = owner["_id"]
    since = at - timedelta(days=1)
    yesterday = [e["text"] async for e in db().agent_log.find({"ws": ws, "at": {"$gte": since}, "status": "done"}).sort("at", -1).limit(12)]
    today = at.astimezone(IST).strftime("%Y-%m-%d")
    overdue = 0
    async for d in db().dues.find({"ws": ws, "status": "due", "due_date": {"$lt": today}}, {"amount": 1}):
        overdue += int(d.get("amount") or 0)
    return {"yesterday": yesterday, "approvals": await db().approvals.count_documents({"ws": ws, "status": "pending"}),
            "leads_waiting": await db().leads.count_documents({"owner_id": ws, "status": "new"}),
            "overdue_text": inr(overdue) if overdue else "", "tasks_today": await db().tasks.count_documents({"ws": ws, "status": "open", "due": today})}


async def write_standup(owner: dict, at, actor: str) -> dict:
    from ..routers.hub import profile_of
    profile = await profile_of(owner["_id"])
    data = await standup_data(owner, at)
    result = await run_ai(owner, "standup", office_tasks.standup(profile, data), f"Standup — {at.astimezone(IST).strftime('%d %b')}")
    await notify(owner["_id"], f"Morning standup from your Chief of Staff: {_str(result.get('headline'), 160)}")
    return result


async def standup_runner(owner: dict, run: dict):
    result = await write_standup(owner, run["at"], "agent")
    return f"Morning standup: {_str(result.get('headline'), 160)}"


catalog.register("office_standup", {
    "name": "Morning standup", "feature": "agentic_office", "trigger": "schedule",
    "what": "Your Chief of Staff sums up what the office did yesterday, what matters today and what needs you.",
    "when": "Every day at 9:30am", "schedule": {"every": "day", "at": "09:30", "grace_hours": 3}}, standup_runner)

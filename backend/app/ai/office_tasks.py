"""
AI jobs for the agentic office (LegacyWorkforce): the Chief of Staff's plan for an instruction, written reports,
and the daily standup. Same rules as every job; deterministic drafts when no AI key is set.
"""
import json
import re

from .provider import complete
from .tasks import RULES, _short, _v, profile_text


def _focus(instruction: str) -> str:
    """'Write next week's posts about our Diwali offer' → 'our Diwali offer'."""
    m = re.search(r"\b(?:about|on|for|around)\s+(.{3,80})$", instruction.strip().rstrip(".!?"), flags=re.I)
    return m.group(1).strip() if m else ""


def _after(instruction: str, words: tuple[str, ...]) -> str:
    """'Write an SOP for handling a new order' → 'handling a new order'."""
    low = instruction.strip().rstrip(".!?")
    for w in words:
        m = re.search(rf"\b{w}\b\s+(?:for|on|about|to|of)?\s*(.{{3,80}})", low, flags=re.I)
        if m:
            return re.sub(r"^(a|an|the)\s+", "", m.group(1).strip(), flags=re.I)
    return ""


def mock_plan(instruction: str, tools: dict, hired: list[int] | None = None) -> dict:
    """Keyword planner used without an AI key: maps an instruction to the office's tools, in a sensible order."""
    low = instruction.lower()
    steps = []
    if "role.draft" in tools and hired:
        from .. import roles_catalog
        for r in (roles_catalog.role(x) for x in hired):
            if r and (r["name"].lower() in low or any(w in low for w in r["name"].lower().split() if len(w) > 5 and w not in ("agent", "writer", "manager"))):
                steps.append({"tool": "role.draft", "args": {"role": r["name"], "brief": instruction[:300]}, "why": f"This is the {r['name']}'s job."})
                if len(steps) >= 3:
                    break

    def add(tool: str, args: dict, why: str):
        if tool in tools and all(s["tool"] != tool for s in steps):
            steps.append({"tool": tool, "args": args, "why": why})

    if any(w in low for w in ("follow", "lead", "inquir", "enquir", "pending customer", "prospect")):
        add("sales.follow_up_leads", {"max": 5}, "Leads that haven't become customers need a follow-up.")
    if any(w in low for w in ("pipeline", "how many leads", "sales update")):
        add("sales.pipeline_summary", {}, "You asked where the leads stand.")
    if any(w in low for w in ("post", "instagram", "social", "facebook", "marketing", "promot", "campaign")):
        add("marketing.write_posts", {"focus": _focus(instruction)}, "Posts keep customers hearing from you.")
    if any(w in low for w in ("sop", "process", "procedure", "checklist", "how we")):
        add("ops.write_sop", {"process": _after(instruction, ("sop", "process", "procedure", "checklist")) or "the process described"},
            "A written SOP lets the team do it the same way every time.")
    if any(w in low for w in ("task", "assign", "to-do", "todo", "team should", "remind the team")):
        add("ops.create_tasks", {"tasks": [{"title": instruction[:120], "assignee": "owner", "due_in_days": 2}]}, "Turn the instruction into a task with a date.")
    if any(w in low for w in ("owe", "payment", "collect", "overdue", "dues", "outstanding", "pending amount")):
        add("accounts.remind_overdue", {}, "Overdue amounts need a polite reminder.")
        add("accounts.money_summary", {}, "A quick look at what's owed.")
    if any(w in low for w in ("hire", "hiring", "recruit", "job post", "vacancy", "job description")):
        add("hr.write_jd", {"role": _after(instruction, ("hire", "hiring", "recruit")) or "Sales executive"}, "A clear hiring kit gets better candidates.")
    if "role" in low and "hire" not in low:
        add("hr.role_clarity", {"role": _after(instruction, ("role",)) or "Team member"}, "Everyone should know exactly what their role is.")
    if any(w in low for w in ("review", "how did", "how are we", "this month")) and "chief.review_month" in tools:
        add("chief.review_month", {}, "An honest look at the month so far.")
    if any(w in low for w in ("report", "summary", "analy", "plan for", "ideas", "suggest", "strategy")) or not steps:
        add("chief.write_report", {"topic": instruction[:200]}, "A short written answer you can act on.")
    return {"summary": f"{len(steps)} step{'s' if len(steps) != 1 else ''} to: {instruction[:120]}", "steps": steps[:6]}


async def plan(p: dict, instruction: str, tools: dict, snapshot: dict, hired: list[int] | None = None):
    tool_lines = "\n".join(f"- {name} ({t['staff_title']}): {t['description']} Args: {json.dumps(t['args'])}" for name, t in tools.items())

    return await complete(RULES + "\nYou are the Chief of Staff of a small AI office working for this business owner.", f"""{profile_text(p)}

THE BUSINESS RIGHT NOW (from the hub): {json.dumps(snapshot, default=str)[:3000]}

THE OWNER'S INSTRUCTION: \"\"\"{instruction[:1500]}\"\"\"

YOUR OFFICE CAN USE ONLY THESE TOOLS:
{tool_lines}

Plan the fewest steps (1–6) that carry out the instruction with these tools. Use only tools listed, with only their args.
role.draft hands a job to one of the owner's hired roles: use the role's name exactly as listed.
If the instruction asks for something no tool can do, use chief.write_report to give the owner a clear written answer or plan.
Never plan to contact customers unless the instruction is about following up, reminders or reviews.
JSON only: {{"summary": "one line: what the office will do", "steps": [{{"tool": "name", "args": {{}}, "why": "one short line"}}]}}""",
                          lambda: mock_plan(instruction, tools, hired), 1500)


async def report(p: dict, topic: str, snapshot: dict):
    def mock():
        n = snapshot.get("leads", {})
        return {"title": topic[:80] or "Report", "summary": f"{_v(p, 'name', 'The business')} has {n.get('waiting', 0)} leads waiting for a first reply and "
                                                            f"{n.get('open', 0)} still open.",
                "points": [f"Reply to the {n.get('waiting', 0)} waiting leads today — speed wins customers." if n.get("waiting") else "Every lead has had a first reply.",
                           f"Share your website on WhatsApp Status three times this week to bring in more {_short(_v(p, 'industry', 'inquiries')).lower()} inquiries.",
                           "Ask every happy customer for a review."],
                "next_steps": ["Pick one point above and do it today."]}

    return await complete(RULES + "\nYou are the Chief of Staff writing a short, practical note for the owner. Use ONLY the facts and numbers given.", f"""{profile_text(p)}

THE BUSINESS RIGHT NOW (from the hub): {json.dumps(snapshot, default=str)[:4000]}

THE OWNER ASKED: \"\"\"{topic[:1500]}\"\"\"

Write a short note that answers it: a 2–3 sentence summary, 3–6 specific points, and 1–3 next steps. Never invent numbers.
JSON only: {{"title": "...", "summary": "...", "points": ["..."], "next_steps": ["..."]}}""", mock, 2500)


async def standup(p: dict, data: dict):
    def mock():
        did = data.get("yesterday") or []
        return {"headline": f"{len(did)} thing{'s' if len(did) != 1 else ''} done yesterday · {data.get('approvals', 0)} waiting for you",
                "yesterday": did[:6] or ["A quiet day — no agent actions."],
                "today": [t for t in [
                    f"Follow up {data.get('leads_waiting', 0)} waiting leads" if data.get("leads_waiting") else "",
                    f"Collect {data.get('overdue_text')} overdue" if data.get("overdue_text") else "",
                    f"{data.get('tasks_today', 0)} team tasks due today" if data.get("tasks_today") else ""] if t] or ["Keep the rhythm: reply fast, post, follow up."],
                "needs_you": [f"{data.get('approvals')} messages are waiting for your approval"] if data.get("approvals") else []}

    return await complete(RULES + "\nYou are the Chief of Staff giving the owner a 30-second morning standup. Use ONLY the data given.", f"""{profile_text(p)}

DATA (JSON): {json.dumps(data, default=str)[:4000]}

Write the standup: what the office did yesterday, what matters today, and what needs the owner's decision.
JSON only: {{"headline": "one line", "yesterday": ["..."], "today": ["..."], "needs_you": ["..."]}} — at most 5 items per list.""", mock, 1200)

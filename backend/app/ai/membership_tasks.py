"""
AI job for goals: the goal coach's three actions.
Same rules as every other job: only the owner's facts, plain language, the owner's preferred language.
Numbers (progress, score changes) are worked out in Python and handed to the AI as facts, so it never does the maths.
Each job has a deterministic draft built from its inputs, for running without an AI key.
"""
import math
import re

from .provider import complete
from .tasks import RULES, _v, profile_text

def _num(x: float) -> str:
    """Indian grouping for whole numbers (1,85,000), one decimal place otherwise."""
    if x is None:
        return "0"
    neg, x = x < 0, round(abs(float(x)), 1)
    whole = int(x)
    tenth = int(round((x - whole) * 10))
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1]
        s = f"{head},{tail}"
    return ("-" if neg else "") + s + (f".{tenth}" if tenth else "")


def _amount(value: float, unit: str) -> str:
    unit = (unit or "").strip()
    if unit in ("₹", "Rs", "Rs.", "INR"):
        return f"₹{_num(value)}"
    return f"{_num(value)} {unit}".strip()


# ───────────────────────── Goal coach ─────────────────────────
def coach_shape(result: dict) -> dict:
    actions = []
    for a in (result or {}).get("actions") or []:
        if isinstance(a, dict) and str(a.get("action") or "").strip():
            actions.append({"action": str(a["action"]).strip()[:300], "why": str(a.get("why") or "").strip()[:300]})
        elif isinstance(a, str) and a.strip():
            actions.append({"action": a.strip()[:300], "why": ""})
    if not actions:
        raise ValueError("no actions")
    actions = actions[:3]
    text = "\n".join(f"{i + 1}. {a['action']}" + (f" — {a['why']}" if a["why"] else "") for i, a in enumerate(actions))
    return {"actions": actions, "answer": text}


async def goal_coach(p: dict, goal: dict):
    """`goal` is the goal as the API shows it: target, current, pct, expected_pct, days_left, status, check-ins."""
    target, current, unit = float(goal["target"]), float(goal["current"]), goal.get("unit", "")
    gap = max(target - current, 0)
    weeks_left = max(math.ceil(goal.get("days_left", 0) / 7), 1)
    per_week = gap / weeks_left
    per_week = round(per_week) if per_week >= 10 else round(per_week, 1)
    checkins = goal.get("checkins") or []
    recent = "\n".join(f"  - {c.get('at', '')[:10]}: {_amount(c.get('value', 0), unit)}" + (f" ({c['note']})" if c.get("note") else "")
                       for c in checkins[-5:]) or "  (none)"

    def mock():
        name = _v(p, "name", "your business")
        offers = [o["name"] for o in p.get("offers", []) if o.get("name")]
        first_offer = offers[0] if offers else "your main offer"
        pace = (f"You need {_amount(gap, unit)} more — about {_amount(per_week, unit)} a week for the next {weeks_left} weeks."
                if weeks_left > 1 else f"You need {_amount(gap, unit)} more this week.")
        if goal["status"] == "done":
            return {"actions": [
                {"action": "Write down what worked to reach this goal, in five lines, and share it with the team", "why": "So you can repeat it on purpose next time."},
                {"action": "Set the next goal now, a little higher, for the next 90 days", "why": "Momentum is easier to keep than to restart."},
                {"action": "Thank the people who made it happen, by name", "why": "Recognition makes the next push easier."}]}
        by_metric = {
            "leads": [
                {"action": "Share your website link on WhatsApp Status every day this week, with one line on " + first_offer, "why": pace},
                {"action": "Ask your five most recent happy customers to send your link to one friend each", "why": "Referrals from people who trust you turn into inquiries fastest."},
                {"action": "Add your website link to your Google Business listing and WhatsApp Business profile", "why": "People who are already searching will find the inquiry form."}],
            "won": [
                {"action": "Call every lead marked Contacted in the last 14 days and ask for a clear yes or no", "why": pace},
                {"action": "Send a written quote within 24 hours of every serious inquiry", "why": "A quick, clear quote wins more than a cheaper slow one."},
                {"action": "Follow up on day 1, 3 and 7 after the quote, then mark the lead Won or Lost", "why": "Most customers decide after the second follow-up."}],
            "site_views": [
                {"action": "Put your website link in your WhatsApp Business profile, Instagram bio and Google listing today", "why": pace},
                {"action": "Share the link in three local or industry WhatsApp groups with one helpful tip", "why": "A useful message gets clicks; an ad gets ignored."},
                {"action": "Add the link to the end of every customer reply and quote this week", "why": "Every conversation becomes a visit."}],
        }
        actions = by_metric.get(goal.get("metric"), [
            {"action": f"Break what's left into weekly targets: {_amount(per_week, unit)} a week", "why": pace},
            {"action": f"Pick the one activity that moves this number most at {name} and block time for it every day", "why": "A daily habit beats a big push at the end."},
            {"action": "Check in here every Monday with the latest number and one line on what you'll change", "why": "What gets reviewed weekly gets done."}])
        return {"actions": actions}

    prompt = f"""{profile_text(p)}

THE OWNER'S GOAL (numbers are already worked out — use them as given, do not recalculate)
Goal: {goal['title']}
Measured by: {goal.get('metric_label', goal.get('metric'))}
Target: {_amount(target, unit)} between {goal['start']} and {goal['end']}
So far: {_amount(current, unit)} ({goal['pct']}% done) with {goal['expected_pct']}% of the time gone, {goal.get('days_left', 0)} days left
Status: {goal['status'].replace('_', ' ')}
Still needed: {_amount(gap, unit)}, about {_amount(per_week, unit)} a week for {weeks_left} week(s)
Recent check-ins:
{recent}

Give exactly three concrete actions the owner can start in the next 7 days to hit this goal. Each action is one specific thing
(who does what, where, how often), fitted to this business and its customers. No generic advice like "improve marketing".
JSON: {{"actions": [{{"action": "max 25 words", "why": "one short sentence"}}]}}"""
    return await complete(RULES, prompt, mock, 1000)

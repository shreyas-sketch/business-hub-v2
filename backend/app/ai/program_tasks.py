"""
AI jobs for Membership's weekly rhythm and the Action Program's tools: the week's plan, the monthly content calendar,
the lead magnet guide, the offer ladder, and the fixes for a funnel leak. Numbers (targets, rates, leaks) are worked out in
Python and handed over as facts. Each job has a deterministic draft for running without an AI key.
"""
import json

from .provider import complete
from .tasks import RULES, _first, _lc, _short, _v, profile_text


# ───────────────────────── the week ─────────────────────────
def mock_week(p: dict, facts: dict) -> dict:
    posts = []
    name, what = _v(p, "name", "We"), _short(_v(p, "industry", "our work"))
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    hooks = ["A common mistake customers make", "What we actually do", "Customer question of the week", "Behind the scenes",
             "Why customers choose us", "A tip you can use today", "Plan your week"]
    for d, h in zip(days, hooks):
        posts.append({"day": d, "hook": h, "caption": f"{name}: {what.lower()}. Message us on WhatsApp for a clear quote.", "hashtags": []})
    actions = []
    if facts.get("inquiries_gap", 0) > 0:
        actions.append({"text": f"Bring in {facts['inquiries_gap']} more inquiries this week: share your website on WhatsApp Status every day",
                        "why": f"You need {facts.get('inquiries_week', 0)} a week to hit your Magic Number."})
    if facts.get("leads_waiting"):
        actions.append({"text": f"Reply to the {facts['leads_waiting']} inquiries still waiting", "why": "The fastest reply usually wins."})
    for fix in facts.get("fixes") or []:
        actions.append({"text": fix, "why": "Your biggest gap right now."})
    actions += [{"text": "Ask three happy customers for a Google review", "why": "Reviews bring the next customers."},
                {"text": "Call two past customers and ask how things are", "why": "Old customers buy again first."},
                {"text": "Follow up every quotation older than 3 days", "why": "Most deals are lost to silence, not price."}]
    return {"posts": posts, "actions": actions[:3]}


async def week_plan(p: dict, facts: dict):
    return await complete(RULES + "\nYou are the owner's weekly planner.", f"""{profile_text(p)}

THIS WEEK'S FACTS (worked out by the hub — use as given): {json.dumps(facts, default=str)[:3000]}

1. Write this week's 7 social media posts, Monday to Sunday (teach, show the work, answer a question, one soft offer).
2. Give exactly 3 actions for the owner this week — specific, doable in under an hour each, aimed at the numbers above
   (the Magic Number gap, waiting leads, the biggest gaps). Each with one line on why.
JSON only: {{"posts": [{{"day": "Monday", "hook": "max 10 words", "caption": "2-4 sentences", "hashtags": ["max 3"]}}],
"actions": [{{"text": "max 20 words", "why": "one line"}}]}}""", lambda: mock_week(p, facts), 3500)


# ───────────────────────── a month of posts ─────────────────────────
def mock_calendar(p: dict, slots: list[dict]) -> dict:
    name, what = _v(p, "name", "We"), _short(_v(p, "industry", "our work"))
    themes = ["Tip", "Behind the scenes", "Customer question", "Offer", "Story", "Why us"]
    out = []
    for i, s in enumerate(slots):
        if s.get("occasion"):
            out.append({"date": s["date"], "occasion": s["occasion"], "hook": f"Happy {s['occasion']} from {name}!",
                        "caption": f"Warm wishes from all of us at {name}. May this {s['occasion']} bring joy to your home and work.",
                        "hashtags": [s["occasion"].split(" ")[0].replace("'", "")]})
        else:
            t = themes[i % len(themes)]
            out.append({"date": s["date"], "occasion": "", "hook": f"{t}: {what}", "caption": f"{name} — {what.lower()}. "
                        + _first(_v(p, "why_us", ""), "We reply the same day") + ". Message us on WhatsApp.", "hashtags": []})
    return {"posts": out}


async def content_calendar(p: dict, month_label: str, slots: list[dict], focus: str):
    return await complete(RULES + "\nYou are the owner's content planner.", f"""{profile_text(p)}

MONTH: {month_label}
FOCUS FOR THE MONTH (may be empty): {focus}
POSTING DAYS (date, and the festival or occasion if any): {json.dumps(slots)}

Write one post for each posting day. On a festival or occasion day, the post is a warm greeting that fits the business
(no discounts unless the focus mentions an offer). Other days: mix tips, behind the scenes, customer questions, one soft offer a week.
JSON only: {{"posts": [{{"date": "YYYY-MM-DD", "occasion": "", "hook": "max 10 words", "caption": "2-4 sentences", "hashtags": ["max 3"]}}]}}
Exactly one post per posting day, same dates.""", lambda: mock_calendar(p, slots), 6000)


# ───────────────────────── lead magnet ─────────────────────────
def mock_magnet(p: dict, inputs: dict) -> dict:
    name, what = _v(p, "name", "Our business"), _short(_v(p, "industry", "the work"))
    problem = inputs.get("problem") or f"getting {what.lower()} done right"
    who = _v(p, "ideal_customer", "you").rstrip(".")
    return {"title": f"The {name} checklist: {problem[:60]}", "subtitle": f"What to check before you spend a rupee — for {_lc(who)}.",
            "promise": f"Avoid the 5 most expensive mistakes in {what.lower()}.",
            "intro": f"Most people find out about these mistakes after they've paid for them. This short guide from {name} shows you what to check first.",
            "sections": [{"heading": "Know exactly what you need", "text": "", "points": ["Write down what you want and what you don't", "Decide your budget range before you talk to anyone"]},
                         {"heading": "Ask for a written quote", "text": "", "points": ["Every item listed", "What's not included", "Payment stages"]},
                         {"heading": "Check the timeline", "text": "", "points": ["Ask who is responsible end to end", "Agree what happens if it's late"]},
                         {"heading": "See real work", "text": "", "points": ["Ask for photos of recent jobs", "Talk to one past customer"]},
                         {"heading": "Before you pay the final amount", "text": "", "points": ["Check against the quote", "Get the warranty in writing"]}],
            "cta": f"Want {name} to look at your requirement? Chat with us on WhatsApp — we'll reply the same day."}


async def lead_magnet(p: dict, inputs: dict):
    return await complete(RULES + "\nYou write a genuinely useful free guide (a lead magnet) for this business's ideal customers.", f"""{profile_text(p)}

THE PROBLEM THE GUIDE SOLVES: {inputs.get('problem') or '(choose the most common problem of their ideal customer)'}
FORMAT: {inputs.get('format') or 'checklist'}

Write a short guide a customer would happily trade their phone number for: useful on its own, specific to this kind of business,
no fake numbers or claims. It should naturally lead to contacting the business.
JSON only: {{"title": "max 12 words", "subtitle": "one line", "promise": "one line: what they'll avoid or get", "intro": "2-3 sentences",
"sections": [{{"heading": "...", "text": "optional 1-2 sentences", "points": ["..."]}}], "cta": "one or two sentences inviting them to WhatsApp"}}
5–7 sections, 2–5 points each.""", lambda: mock_magnet(p, inputs), 4000)


# ───────────────────────── offer ladder ─────────────────────────
def mock_ladder(p: dict, inputs: dict) -> dict:
    offers = [o for o in p.get("offers", []) if o.get("name")]
    def price(o):
        return " ".join(x for x in [o.get("price", ""), o.get("unit", "")] if x).strip()
    core = offers[0] if offers else {"name": _short(_v(p, "industry", "Our main service"))}
    premium = offers[1] if len(offers) > 1 else {"name": f"{core['name']} — complete package"}
    return {"heading": "Ways to work with us", "intro": "Start small, or go all the way. Every option comes with a clear quote.",
            "levels": [{"level": "Easy first step", "name": inputs.get("entry") or "Free consultation", "for_whom": "If you're still deciding",
                        "includes": ["A conversation about what you need", "Honest advice on budget and timeline"], "price": "Free", "why": "Lowers the risk of saying yes."},
                       {"level": "Main offer", "name": core["name"], "for_whom": _v(p, "ideal_customer", "Most of our customers"),
                        "includes": ["Everything planned and quoted in writing", "One person responsible"], "price": price(core), "why": "What most customers buy."},
                       {"level": "Premium", "name": premium["name"], "for_whom": "If you want it all handled for you",
                        "includes": ["Priority scheduling", "End-to-end handling"], "price": price(premium) if offers[1:] else "", "why": "For customers who value time over money."}]}


async def offer_ladder(p: dict, inputs: dict):
    return await complete(RULES + "\nYou design a 3-level offer ladder: an easy first offer, the main offer, and a premium offer.", f"""{profile_text(p)}

OWNER'S NOTES (may be empty): {inputs.get('notes', '')}
IDEA FOR THE EASY FIRST OFFER (may be empty): {inputs.get('entry', '')}

Build the ladder from the owner's own offers. Prices: copy exactly as given, or leave empty — never invent one.
The easy first offer is low-risk (a consultation, an audit, a sample, a starter pack). The premium one is the full, done-for-you version.
JSON only: {{"heading": "Ways to work with us", "intro": "one line", "levels": [{{"level": "Easy first step|Main offer|Premium", "name": "...",
"for_whom": "one line", "includes": ["max 4"], "price": "as given or empty", "why": "one line for the owner: why this level exists"}}]}}
Exactly 3 levels.""", lambda: mock_ladder(p, inputs), 2500)


# ───────────────────────── funnel leak fixes ─────────────────────────
def mock_leak(p: dict, facts: dict) -> dict:
    leak = facts.get("biggest_leak") or {}
    stage = leak.get("label", "your funnel")
    tips = {"inquiries": ["Put a Chat on WhatsApp button and the inquiry form at the top of every page", "Publish a lead magnet so visitors leave their number"],
            "meetings": ["Call every inquiry within the hour", "Offer two specific meeting times instead of asking when they're free"],
            "proposals": ["Send the proposal within 24 hours of the meeting", "Use the Proposal writer so every proposal answers their worry first"],
            "won": ["Follow up on day 2, 5 and 10 after the proposal", "Add an easy first offer for people who aren't ready for the full one"]}
    return {"summary": f"Your biggest leak is at {stage}: {leak.get('rate', '?')}% against the {leak.get('target', '?')}% you aim for.",
            "fixes": [{"stage": stage, "action": t, "why": "Plugs the biggest leak first."} for t in tips.get(leak.get("key"), ["Check this stage every week"])]
            + [{"stage": "Every stage", "action": "Track these numbers every Monday in the hub", "why": "What gets measured gets fixed."}]}


async def leak_fixes(p: dict, facts: dict):
    return await complete(RULES + "\nYou are a sales funnel optimiser for a small Indian business.", f"""{profile_text(p)}

THE FUNNEL (worked out by the hub — use as given): {json.dumps(facts, default=str)[:3000]}

Explain the biggest leak in one or two sentences, then give 3–5 specific fixes, starting with the biggest leak. Fit them to this business.
JSON only: {{"summary": "...", "fixes": [{{"stage": "...", "action": "max 25 words", "why": "one line"}}]}}""", lambda: mock_leak(p, facts), 1500)


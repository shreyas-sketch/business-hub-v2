"""
Ready-made AI tools, and the 82 LegacyWorkforce roles, on one engine.

A tool is a spec — what it's called, which plan feature unlocks it, what the owner tells it, what it produces — run
through one AI job that always returns the same shape:
    {"title", "summary", "sections": [{"heading", "text", "points"}], "messages": [{"label", "text"}]}
`messages` are ready-to-send texts (tap to send from the owner's WhatsApp). Every draft is saved to My outputs.
Tools that a dedicated page does better (quotations, the content calendar...) carry a `route` to that page.
"""
from dataclasses import dataclass, field

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from . import plans, roles_catalog
from .ai import tool_tasks
from .db import db, now
from .services import new_id, run_ai


def I(key, label, type="text", required=False, placeholder="", options=None, hint=""):  # noqa: E743
    return {"key": key, "label": label, "type": type, "required": required, "placeholder": placeholder,
            "options": options or [], "hint": hint}


@dataclass
class Tool:
    key: str
    name: str
    desk: str
    feature: str
    what: str
    inputs: list
    produce: str
    example: dict = field(default_factory=dict)
    minutes: int = 20
    role: str = "staff"
    risk: str = "internal"
    route: str | None = None
    role_id: int | None = None

    def view(self, owner: dict, hired: set | None = None) -> dict:
        locked = not plans.has(owner, self.feature)
        out = {"key": self.key, "name": self.name, "desk": self.desk, "what": self.what, "inputs": self.inputs, "example": self.example,
               "minutes": self.minutes, "role": self.role, "risk": self.risk, "route": self.route, "feature": self.feature,
               "locked": locked, "tier": plans.tier_of(self.feature), "tier_name": plans.PLANS[plans.tier_of(self.feature)]["name"]}
        if self.role_id is not None:
            r = roles_catalog.role(self.role_id)
            out.update(role_id=self.role_id, department=r["department"], conn=r["conn"], hero=r["hero"],
                       hired=bool(hired and self.role_id in hired))
        return out


DESKS = ["Marketing", "Sales", "Strategy", "Customers", "Money", "Operations"]

TOOLS: dict[str, Tool] = {}


def _add(t: Tool) -> None:
    TOOLS[t.key] = t


# ───────────────────────── Membership ─────────────────────────
_add(Tool("content", "Content Agent", "Marketing", "tool_content", "A month of posts and reel scripts in your voice",
          [I("focus", "Theme, offer or festival for this month", placeholder="e.g. Diwali home makeover offer"),
           I("platform", "Where you post most", "select", options=["Instagram and Facebook", "WhatsApp Status", "LinkedIn", "All of them"])],
          "a month of content: 4 weekly themes, 12 posts (hook, caption, up to 4 local hashtags), 4 reel scripts (hook in the first 3 seconds, "
          "5–7 short spoken lines, on-screen text) and 2 carousel outlines (slide by slide)",
          {"focus": "Diwali home makeover offer", "platform": "Instagram and Facebook"}, minutes=120))
_add(Tool("video", "Video scripts", "Marketing", "tool_video", "Hook, script and captions, ready to shoot on a phone",
          [I("topic", "What is the video about?", required=True, placeholder="e.g. 3 mistakes people make when choosing a modular kitchen"),
           I("length", "Length", "select", options=["30 seconds", "60 seconds", "90 seconds"])],
          "one short video: a hook for the first 3 seconds, the script in short spoken lines with timings, a 5-shot storyboard a phone can "
          "shoot, on-screen text, and the caption", {"topic": "3 mistakes people make when choosing a modular kitchen", "length": "60 seconds"}, minutes=30))
_add(Tool("google", "Google profile & reviews", "Marketing", "tool_google", "Your Google Business description, posts and review replies",
          [I("reviews", "Reviews to reply to (optional)", "textarea", placeholder="Paste one or more Google reviews"),
           I("focus", "What you want more of", placeholder="e.g. more calls from Thane West")],
          "a Google Business profile pack: a 750-character business description, 4 Google posts with a call to action, 5 photo ideas, and a "
          "calm, thankful reply to each review pasted (never arguing; problems are invited offline)",
          {"reviews": "Very good work, finished on time. — Priya", "focus": "more calls from Thane West"}, minutes=30))
_add(Tool("proposal", "Proposal writer", "Sales", "tool_proposal", "A proposal shaped to what this customer needs",
          [I("customer", "Who is it for?", required=True, placeholder="e.g. Mr. Shah, 3BHK in Hiranandani Estate"),
           I("need", "What do they need?", "textarea", required=True, placeholder="Paste their message or your meeting notes"),
           I("offer", "Which offer and price?", placeholder="e.g. Full interiors, ₹6,40,000")],
          "a proposal: the customer's situation in their own words, the recommended offer, what's included and not included, the timeline, "
          "the investment (only the price the owner gave), why us, and the next step; plus a short WhatsApp message to send with it",
          {"customer": "Mr. Shah, 3BHK in Hiranandani Estate", "need": "Wants kitchen + wardrobes done before Diwali, worried about delays",
           "offer": "Modular kitchen + 3 wardrobes, ₹4,20,000"}, minutes=45, risk="customer"))
_add(Tool("case_study", "Case study writer", "Marketing", "tool_case_study", "A happy customer's result turned into a story you can share",
          [I("customer", "Which customer?", required=True, placeholder="Name or description"),
           I("before", "What was the problem?", "textarea", required=True),
           I("after", "What changed? Facts you can show", "textarea", required=True)],
          "a case study in Situation → Complication → Question → Answer order, a 2-line testimonial quote for the customer to approve, a "
          "LinkedIn/Instagram post version, and a WhatsApp message asking the customer's consent to publish",
          {"customer": "The Mehta family, Thane", "before": "Old kitchen with no storage; two contractors had let them down",
           "after": "Kitchen done in 21 days as promised; storage doubled"}, minutes=40, risk="customer"))

# ───────────────────────── Action Program ─────────────────────────
_add(Tool("persona", "Persona builder", "Strategy", "tool_persona", "Your ideal customer described from evidence",
          [I("customers", "Describe 2–3 of your best customers", "textarea", required=True, placeholder="Who they are, what they bought, why they chose you")],
          "a customer persona: who they are (by who they are, never by what they buy), their needs, desires and problems, what they value, "
          "where to find them, the words they use, what makes them buy, and what makes them hesitate",
          {"customers": "Working couples in Thane who just got possession of a 2BHK; want it done fast and without chasing contractors"}, minutes=40))
_add(Tool("sales_roles", "Sales role map", "Sales", "tool_sales_roles", "Who opens doors and who closes deals",
          [I("team", "Who sells today, and what do they do?", "textarea", required=True),
           I("channels", "Your sales channels", placeholder="direct, digital, distribution")],
          "a sales role map: door-opener jobs and deal-closer jobs for this business, who should do each, what each needs (scripts, targets, "
          "tools), the weekly numbers to track, and the next hire if there is a gap",
          {"team": "I meet every client myself; one assistant answers calls", "channels": "direct, digital"}, minutes=40))
_add(Tool("telecalling", "Telecalling script", "Sales", "tool_telecalling", "A calling script with objection branches — for a person or a voice agent",
          [I("who", "Who will be called?", required=True, placeholder="e.g. people who filled the website form"),
           I("goal", "Goal of the call", required=True, placeholder="e.g. book a site visit"),
           I("objections", "Objections you hear", "textarea")],
          "a calling script: opening line, permission question, 3 discovery questions, the 30-second pitch, 5 objections each with a reply "
          "branch, the close, and the same script written as instructions for an AI voice agent",
          {"who": "people who filled the website form", "goal": "book a free site visit", "objections": "Too expensive\nWill call later"}, minutes=45))
_add(Tool("marketing_plan", "30-day marketing plan", "Marketing", "tool_marketing_plan", "Content, strategies, channels and systems for 30 days",
          [I("goal", "What do you want from marketing in the next 30 days?", required=True), I("budget", "Monthly budget (optional)")],
          "a 30-day marketing plan on the 4 elements of marketing — content (themes and posts), strategies, channels, systems (the weekly "
          "routine and who does it) — then a week-by-week plan and the 3 numbers to watch",
          {"goal": "20 site-visit bookings", "budget": "₹15,000"}, minutes=60))

# ───────────────────────── LegacyWorkforce: the 82 roles ─────────────────────────
for _r in roles_catalog.ROLES:
    _add(Tool(_r["key"], _r["name"], _r["department"].capitalize(), "workforce", _r["summary"],
              [I("brief", _r["ask"], "textarea", required=True)], _r["produce"], {}, minutes=_r["minutes"], role="manager",
              risk=_r["risk"], route=_r["route"], role_id=_r["id"]))


def get(key: str) -> Tool:
    if key not in TOOLS:
        raise HTTPException(404, "No such tool")
    return TOOLS[key]


def kind_label(kind: str) -> str | None:
    if kind.startswith("tool:") and kind[5:] in TOOLS:
        return TOOLS[kind[5:]].name
    return None


# ───────────────────────── the output shape ─────────────────────────
class Section(BaseModel):
    heading: str = Field(default="", max_length=160)
    text: str = Field(default="", max_length=4000)
    points: list[str] = Field(default_factory=list, max_length=24)


class Message(BaseModel):
    label: str = Field(default="Message", max_length=80)
    text: str = Field(max_length=2000)


class Output(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    summary: str = Field(default="", max_length=1200)
    sections: list[Section] = Field(default_factory=list, max_length=14)
    messages: list[Message] = Field(default_factory=list, max_length=10)


def shape(raw: dict) -> dict:
    """AI answers get trimmed to the shape instead of failing on one over-long item."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    data = {"title": str(raw.get("title") or "Draft")[:160], "summary": str(raw.get("summary") or "")[:1200], "sections": [], "messages": []}
    for s in (raw.get("sections") or [])[:14]:
        if isinstance(s, dict):
            pts = [str(p)[:600] for p in (s.get("points") or []) if p not in (None, "")][:24]
            data["sections"].append({"heading": str(s.get("heading") or "")[:160], "text": str(s.get("text") or "")[:4000], "points": pts})
    for m in (raw.get("messages") or [])[:10]:
        if isinstance(m, dict) and str(m.get("text") or "").strip():
            data["messages"].append({"label": str(m.get("label") or "Message")[:80], "text": str(m["text"])[:2000]})
    try:
        return Output.model_validate(data).model_dump()
    except ValidationError as e:
        raise ValueError(str(e)) from e


def clean_inputs(t: Tool, raw: dict) -> dict:
    out = {}
    for i in t.inputs:
        v = str((raw or {}).get(i["key"]) or "").strip()[:6000]
        if i["type"] == "select" and v and i["options"] and v not in i["options"]:
            v = i["options"][0]
        if i["required"] and len(v) < 2:
            raise HTTPException(400, f"Please fill in: {i['label']}")
        out[i["key"]] = v
    return out


async def run(owner: dict, ws: str, actor: str, key: str, raw_inputs: dict, profile: dict, context: str = "") -> dict:
    """One AI run → a saved draft in My outputs. Returns {id, output}."""
    t = get(key)
    inputs = clean_inputs(t, raw_inputs)
    first = next((v for v in inputs.values() if v), "")
    title = f"{t.name}" + (f" — {first[:70]}" if first else "")
    result = await run_ai(owner, f"tool:{key}", tool_tasks.draft(t, profile, inputs, context), title, save_output=False, check=shape)
    doc = {"_id": new_id(), "user_id": ws, "kind": f"tool:{key}", "title": result.get("title") or title, "content": result,
           "inputs": inputs, "by": actor, "minutes": t.minutes, "created_at": now()}
    await db().outputs.insert_one(doc)
    return {"id": doc["_id"], "output": result, "title": doc["title"]}

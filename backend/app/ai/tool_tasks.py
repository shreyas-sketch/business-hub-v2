"""
The one AI job behind every ready-made tool and every LegacyWorkforce role. The tool says what to produce; the job adds
the house rules, the Business Brain, the Company Brain extracts (Growth Mentorship and up) and the owner's input.
Without an AI key each tool returns a deterministic draft built from the profile and the input, so the hub can be
demonstrated end to end.
"""
import re

from .provider import complete
from .tasks import RULES, _lc, _short, _v, profile_text

SHAPE = ('JSON only: {"title": "...", "summary": "2-3 sentences", "sections": [{"heading": "...", "text": "optional short paragraph", '
         '"points": ["..."]}], "messages": [{"label": "who/what it is for", "text": "ready to send on WhatsApp, plain text"}]}')


def _offers(p: dict) -> list[str]:
    return [o["name"] + (f" ({o['price']}{' ' + o['unit'] if o.get('unit') else ''})" if o.get("price") else "")
            for o in p.get("offers", []) if o.get("name")] or [_short(_v(p, "industry", "our service"))]


def _lines(text: str, n: int = 8) -> list[str]:
    return [l.strip(" -•\t") for l in re.split(r"[\n;]", text or "") if l.strip(" -•\t")][:n]


# ───────────────────────── deterministic drafts (no AI key) ─────────────────────────
def mock(tool, p: dict, inputs: dict) -> dict:
    name, what = _v(p, "name", "Your business"), _short(_v(p, "industry", "your work"))
    who = _v(p, "ideal_customer", "your customers").rstrip(".")
    city = _v(p, "city", "")
    offers = _offers(p)
    why = _lines(p.get("why_us", ""), 3) or ["We reply the same day", "Clear quote before we start"]
    k = tool.key
    if k == "content":
        focus = inputs.get("focus") or what
        themes = [f"Week 1 — Why {what.lower()} goes wrong (and how to avoid it)", f"Week 2 — Inside a real job at {name}",
                  f"Week 3 — {focus}", "Week 4 — Questions customers ask before they buy"]
        posts = [f"Post {i + 1}: {h}" for i, h in enumerate([
            "The 3 questions to ask before you choose anyone", f"What {offers[0]} really includes", "A day at our workshop",
            f"Why {_lc(why[0])}", "Customer question of the week", f"{focus}: what's different this month",
            "Before and after — what changed", "The one mistake that costs the most", "How we work, step by step",
            "Meet the team", f"Who we're best for: {_lc(who)}", "Plan your next month with us"])]
        reels = [f"Reel {i + 1}: hook — “{h}” · 5 short lines · on-screen text: the key number or tip" for i, h in enumerate([
            "Stop! Don't sign that quote yet", f"30 seconds on {_lc(offers[0])}", "Watch this before you start", "What ₹1 lakh really buys"])]
        return {"title": f"Content for the month — {focus}", "summary": f"Four weekly themes for {name}, 12 posts, 4 reel scripts and 2 carousels. Copy, adjust and post.",
                "sections": [{"heading": "Weekly themes", "points": themes}, {"heading": "12 posts", "points": posts},
                             {"heading": "4 reel scripts", "points": reels},
                             {"heading": "2 carousels", "points": ["Carousel 1: 5 slides — the checklist before you start", "Carousel 2: 6 slides — a real job, start to finish"]}],
                "messages": []}
    if k == "video":
        topic = inputs.get("topic") or what
        return {"title": f"Video script — {topic}", "summary": f"A {inputs.get('length') or '60 seconds'} video you can shoot on a phone today.",
                "sections": [{"heading": "Hook (first 3 seconds)", "text": f"“If you're thinking about {_lc(topic)}, watch this before you spend a rupee.”"},
                             {"heading": "Script", "points": ["0–5s: the problem in one line", "5–20s: mistake one — and what it costs",
                                                              "20–35s: mistake two", "35–50s: what we do instead at " + name,
                                                              "50–60s: “Message us on WhatsApp — link in bio.”"]},
                             {"heading": "Shots", "points": ["You, to camera", "Close-up of the work", "Before photo", "After photo", "You, with the WhatsApp number on screen"]},
                             {"heading": "Caption", "text": f"{topic} — save this for later. {name}{', ' + city if city else ''}."}], "messages": []}
    if k == "google":
        reviews = _lines(inputs.get("reviews", ""), 6)
        return {"title": f"Google profile pack — {name}", "summary": "A description, four posts and replies to your reviews.",
                "sections": [{"heading": "Business description", "text": f"{name} — {what.lower()} for {_lc(who)}{' in ' + city if city else ''}. "
                                                                      + " ".join(w.rstrip('.') + "." for w in why)},
                             {"heading": "4 Google posts", "points": [f"This week: {offers[0]} — message us for a clear quote",
                                                                      "Customer question: how long does it take?", "Behind the scenes: our process",
                                                                      inputs.get("focus") or "Book a free consultation"]},
                             {"heading": "Photo ideas", "points": ["The team at work", "A finished job", "Your shop or office front", "A happy customer (with consent)", "Before and after"]}],
                "messages": [{"label": f"Reply to review {i + 1}", "text": f"Thank you so much for your kind words! It was a pleasure working with you. — Team {name}"}
                             for i, _ in enumerate(reviews)]}
    if k == "proposal":
        cust = inputs.get("customer") or "the customer"
        offer = inputs.get("offer") or offers[0]
        return {"title": f"Proposal for {cust}", "summary": f"A proposal for {cust}, built on what they told you.",
                "sections": [{"heading": "Your situation", "text": inputs.get("need", "")},
                             {"heading": "What we recommend", "text": offer},
                             {"heading": "What's included", "points": ["Site visit and measurements", "Design and a written quote", "Execution by our own team", "Handover with a checklist"]},
                             {"heading": "Why us", "points": why},
                             {"heading": "Next step", "text": "Confirm on WhatsApp and we'll book the site visit."}],
                "messages": [{"label": f"WhatsApp to {cust}", "text": f"Hello, thank you for your time. As discussed, here's our proposal for {_lc(offer)}. Shall we book the site visit this week? — {name}"}]}
    if k == "case_study":
        cust = inputs.get("customer") or "Our customer"
        return {"title": f"Case study — {cust}", "summary": "A short story in Situation → Complication → Question → Answer order.",
                "sections": [{"heading": "Situation", "text": f"{cust} came to {name}."}, {"heading": "Complication", "text": inputs.get("before", "")},
                             {"heading": "Question", "text": "How do you get it done right, without chasing anyone?"},
                             {"heading": "Answer", "text": inputs.get("after", "")},
                             {"heading": "Quote to confirm", "text": "“They did exactly what they promised, on time.”"}],
                "messages": [{"label": f"Consent request to {cust}", "text": f"Hello! We'd love to share your story on our page. Here's what we'd write: {inputs.get('after', '')[:160]} — is that okay with you? — {name}"}]}
    if k == "persona":
        return {"title": f"Persona — {who[:60]}", "summary": "Your ideal customer, from what you wrote. Check it against real customers.",
                "sections": [{"heading": "Who they are", "text": inputs.get("customers", who)},
                             {"heading": "Needs", "points": ["A clear price before anything starts", "One person responsible"]},
                             {"heading": "Desires", "points": ["To be proud of the result", "To not waste weekends chasing people"]},
                             {"heading": "Problems", "points": ["Contractors who disappear", "Hidden costs"]},
                             {"heading": "Where to find them", "points": ["Society WhatsApp groups", "Instagram", "Referrals from past customers"]},
                             {"heading": "What makes them buy", "points": why}], "messages": []}
    if k == "sales_roles":
        return {"title": "Sales role map", "summary": "Separate opening doors from closing deals so neither waits for the other.",
                "sections": [{"heading": "Door openers", "points": ["Reply to every inquiry within the hour", "Call website leads the same day", "Book the meeting or site visit"]},
                             {"heading": "Deal closers", "points": ["Run the meeting", "Send the proposal within 24 hours", "Follow up on day 2, 5 and 10"]},
                             {"heading": "Today", "text": inputs.get("team", "")},
                             {"heading": "Numbers to track weekly", "points": ["Inquiries", "Meetings booked", "Proposals sent", "Won"]}], "messages": []}
    if k == "telecalling":
        objections = _lines(inputs.get("objections", ""), 5) or ["It's too expensive", "I'll call you later", "I'm talking to others"]
        return {"title": f"Calling script — {inputs.get('goal', 'book a meeting')}", "summary": f"For calls to {inputs.get('who', 'leads')}.",
                "sections": [{"heading": "Opening", "text": f"“Hello, this is from {name}. You'd asked about {_lc(what)} — is this a good time for two minutes?”"},
                             {"heading": "Discovery questions", "points": ["What made you look for this now?", "When would you like it done?", "What matters most to you?"]},
                             {"heading": "30-second pitch", "text": f"We help {_lc(who)}. {' '.join(w.rstrip('.') + '.' for w in why)}"},
                             {"heading": "Objections", "points": [f"“{o}” → acknowledge, ask one question, offer the next small step" for o in objections]},
                             {"heading": "Close", "text": f"“Shall we {inputs.get('goal', 'book a time')} this week — Thursday or Saturday?”"},
                             {"heading": "As instructions for a voice agent", "text": f"You are calling on behalf of {name}. Be polite and brief. Goal: {inputs.get('goal', '')}. Never quote a price that isn't listed."}],
                "messages": []}
    if k == "marketing_plan":
        return {"title": f"30-day marketing plan — {inputs.get('goal', '')}", "summary": "The 4 elements of marketing, then week by week.",
                "sections": [{"heading": "Content", "points": ["3 posts a week from the Content Agent", "1 reel a week", "1 customer story"]},
                             {"heading": "Strategies", "points": ["Lead magnet on your website", "Referral ask to every happy customer"]},
                             {"heading": "Channels", "points": ["WhatsApp Status", "Instagram", "Google profile"]},
                             {"heading": "Systems", "points": ["Monday: plan the week", "Daily: reply within the hour", "Friday: check the numbers"]},
                             {"heading": "Week by week", "points": ["Week 1: set up and post", "Week 2: launch the lead magnet", "Week 3: referral drive", "Week 4: review and repeat"]}],
                "messages": []}
    # LegacyWorkforce roles and anything else: a structured draft from the role's job
    brief = inputs.get("brief", "")
    parts = [x.strip() for x in re.split(r",|\band\b", tool.produce) if len(x.strip()) > 3][:6]
    msgs = []
    if tool.risk == "customer":
        msgs = [{"label": "Draft message", "text": f"Hello! This is {name}. {brief[:200]} — could you reply with a good time to talk?"}]
    return {"title": f"{tool.name} — {brief[:60] or name}", "summary": f"{tool.name} for {name}: {tool.what[:1].lower() + tool.what[1:]}",
            "sections": [{"heading": "What I worked from", "points": [f"{name}: {what}", f"Customers: {who}", f"Your brief: {brief[:300]}"]},
                         {"heading": "Draft", "points": [p[:1].upper() + p[1:] for p in parts]},
                         {"heading": "Next steps", "points": ["Check the facts marked [add: …]", "Approve, then use it this week"]}],
            "messages": msgs}


async def draft(tool, p: dict, inputs: dict, context: str = ""):
    given = "\n".join(f"- {i['label']}: {inputs.get(i['key']) or '(not given)'}" for i in tool.inputs)
    docs = f"\nFROM THE OWNER'S DOCUMENTS (price list, FAQs, past quotations — use these facts):\n{context[:6000]}\n" if context else ""
    customer_rule = ("\nAnything a customer will read goes in \"messages\": WhatsApp-ready, plain text, no markdown, short."
                     if tool.risk in ("customer", "financial") or "message" in tool.produce else "")
    prompt = f"""{profile_text(p)}
{docs}
YOU ARE: {tool.name} — {tool.what}
PRODUCE: {tool.produce}

WHAT THE OWNER TOLD YOU:
{given}

Use only facts from the profile, the documents and the owner's input. Where a needed fact is missing, write [add: …] instead of guessing.
Never invent prices, numbers, client names, results or reviews.{customer_rule}
{SHAPE}
3–8 sections; points are short and specific to this business."""
    return await complete(RULES, prompt, lambda: mock(tool, p, inputs), 4000)

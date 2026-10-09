"""AI jobs for Growth Mentorship: the money campaign's message and answering the team from the Company Brain."""
from .provider import complete
from .tasks import RULES, _short, _v, profile_text

TYPES = {"revival": "bring back customers who haven't bought in a while", "festival": "a festival or season offer",
         "referral": "ask happy customers to refer a friend", "custom": "the owner's own idea"}


def mock_campaign(p: dict, kind: str, notes: str) -> dict:
    name, what = _v(p, "name", "us"), _short(_v(p, "industry", "our work")).lower()
    msgs = {"revival": f"It's been a while! We'd love to help you again with {what}. {notes or 'Reply to this message and we will call you.'}",
            "festival": f"This season, {notes or f'plan your {what} with us — reply to know more'}.",
            "referral": f"Thank you for being our customer! If a friend or family member needs {what}, share our number — we'll take great care of them. {notes}".strip(),
            "custom": notes or f"An update from {name}: reply to this message to know more."}
    return {"title": {"revival": "Old-customer revival", "festival": "Festival offer", "referral": "Referral drive", "custom": "Campaign"}[kind],
            "message": msgs.get(kind, msgs["custom"])[:600]}


async def campaign_message(p: dict, kind: str, notes: str):
    return await complete(RULES + "\nYou write one WhatsApp campaign message for a small Indian business's own customers.", f"""{profile_text(p)}

CAMPAIGN: {TYPES.get(kind, TYPES['custom'])}
THE OWNER'S NOTES (offer, dates, conditions — use exactly, never add an offer they didn't give): {notes or '(none)'}

The message is filled into an approved template that already says hello with the customer's name and the business name, so
write only the middle: warm, specific, under 60 words, one clear thing to do (reply, call or visit). No links, no emojis unless the
owner's notes use them, no invented discounts or deadlines.
JSON only: {{"title": "a short name for the campaign", "message": "..."}}""", lambda: mock_campaign(p, kind, notes), 600)


def mock_answer(question: str, context: str) -> dict:
    if not context:
        return {"answer": "I couldn't find this in the Company Brain documents. Add the price list, FAQs or the SOP that covers it, and ask again.",
                "found": False}
    first = context.split("\n---\n")[0]
    return {"answer": f"From your documents:\n{first[:600]}", "found": True}


async def answer(p: dict, question: str, context: str):
    return await complete(RULES + "\nYou answer the team's question using ONLY the owner's documents below. If they don't cover it, say so.",
                          f"""{profile_text(p)}

THE OWNER'S DOCUMENTS (most relevant parts):
{context[:7000] or '(nothing relevant found)'}

THE TEAM MEMBER ASKS: \"\"\"{question[:1000]}\"\"\"

Answer in under 120 words, practically. If the documents don't answer it, set found=false and say what to add.
JSON only: {{"answer": "...", "found": true}}""", lambda: mock_answer(question, context), 800)

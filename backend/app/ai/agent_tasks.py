"""
AI jobs the agents run on their own. Same rules as every other job (only the owner's facts, plain language,
the owner's language), each with a deterministic draft for running without an AI key.
"""
import re

from ..text import greeting_name
from .provider import complete
from .tasks import RULES, profile_text


def _topic(message: str) -> str:
    """'Need a modular kitchen for our new 2BHK. Budget?' → 'a modular kitchen for our new 2BHK'."""
    first = re.split(r"[.?!\n]", (message or "").strip())[0].strip()
    first = re.sub(r"^(hi|hello|hey|namaste)[,! ]+", "", first, flags=re.I)
    first = re.sub(r"^(i|we)\s+(need|want|am looking for|are looking for|would like)\s+", "", first, flags=re.I)
    first = re.sub(r"^(need|want|looking for|enquiry about|inquiry about|interested in)\s+", "", first, flags=re.I)
    words = first.split()
    return " ".join(words[:10]) if len(words) >= 2 else ""


async def followup(p: dict, lead: dict, n: int, of: int):
    """Follow-up number n (of `of`) to a lead who has not become a customer yet. Returns {"message": "..."}."""
    name = greeting_name(lead.get("name", ""))
    business = (p.get("name") or "us").strip()
    topic = _topic(lead.get("message", ""))

    def mock():
        hello = f"Hello {name}," if name else "Hello,"
        about = f"your message about {topic}" if topic else "your inquiry"
        if n <= 1:
            text = (f"{hello} this is {business} following up on {about}. Could you share a few more details about what you need "
                    f"and when? We'll reply with a clear plan and quote.")
        elif n < of:
            text = (f"{hello} just checking in from {business} about {about}. Do you have any questions we can answer, "
                    f"or would a quick call suit you better?")
        else:
            text = (f"{hello} one last note from {business} about {about}. If it's still on your list, just reply here and we'll take "
                    f"it from there. If you've already sorted it out, no problem at all — thank you for considering us.")
        return {"message": text}

    return await complete(RULES, f"""{profile_text(p)}

A customer sent this inquiry from the business's website:
Name: {lead.get('name', '') or 'unknown'}
Message: \"\"\"{(lead.get('message') or '(no message)')[:1500]}\"\"\"

They have not become a customer yet. Write follow-up number {n} of {of} that the owner will send on WhatsApp.
- Short and polite: 2–3 sentences, under 350 characters, one paragraph, no line breaks.
- Greet them by first name ({name or 'no name — just say Hello'}), mention what they asked about, and end with one easy question.
- {'First follow-up: offer to help and ask for the details you need.' if n <= 1 else 'Last follow-up: a friendly final check-in, no pressure.' if n >= of else 'A gentle check-in; do not repeat the first follow-up.'}
- Never invent offers, discounts, prices, deadlines or availability that are not in the profile.
JSON: {{"message": "..."}}""", mock, 600)


def followup_text(result: dict) -> str:
    """Shapes the AI draft into one WhatsApp-safe paragraph; raises when it is unusable (the run is refunded)."""
    text = re.sub(r"\s+", " ", str((result or {}).get("message") or "")).strip()
    if len(text) < 15:
        raise ValueError("empty follow-up")
    return text[:900]

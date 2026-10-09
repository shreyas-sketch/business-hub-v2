"""
AI jobs for getting started: reading a website or a voice note into the Business Brain, and the English polisher.
Same house rules: only facts that are actually there; when something isn't said, leave it empty.
"""
import re

from .provider import complete
from .tasks import RULES, profile_text

CITIES = ["Navi Mumbai", "Mumbai", "Thane", "Kalyan", "Pune", "New Delhi", "Delhi", "Gurugram", "Gurgaon", "Noida", "Bengaluru", "Bangalore",
          "Hyderabad", "Chennai", "Kolkata", "Ahmedabad", "Surat", "Vadodara", "Rajkot", "Jaipur", "Indore", "Bhopal", "Nagpur", "Nashik",
          "Lucknow", "Kanpur", "Chandigarh", "Ludhiana", "Kochi", "Coimbatore", "Madurai", "Visakhapatnam", "Patna", "Ranchi", "Guwahati",
          "Bhubaneswar", "Goa", "Mysuru", "Aurangabad", "Jalgaon", "Halol", "Gandhinagar", "Dehradun", "Raipur", "Vijayawada"]

BRAIN_JSON = ('{"name": "", "city": "", "industry": "what the business does, one line", "offers": [{"name": "", "price": "as written or empty", '
              '"unit": ""}], "ideal_customer": "", "why_us": "one reason per line", "proof": "", "whatsapp": "", "email": "", "language": "English"}')


def _clean_name(title: str) -> str:
    head = re.split(r"\s+[|–—-]\s+|\s*\|\s*", title or "")[0].strip()
    return head[:80]


def _city(text: str) -> str:
    for c in CITIES:
        if re.search(rf"\b{re.escape(c)}\b", text or "", flags=re.I):
            return c
    return ""


def mock_from_site(facts) -> dict:
    name = _clean_name(facts.title) or (facts.headings[0] if facts.headings else "")
    industry = (facts.description or (facts.headings[0] if facts.headings else "")).split(".")[0][:200]
    skip = {"home", "about us", "contact us", "contact", "about", "our services", "services", "testimonials", "faq", "why choose us", "get in touch"}
    offers = [{"name": h[:80], "price": "", "unit": ""} for h in facts.headings[1:] if h.lower().strip(" :") not in skip and 3 <= len(h) <= 60][:6]
    why = [h for h in facts.headings if any(w in h.lower() for w in ("why", "years", "trusted", "quality", "experience", "guarantee"))][:3]
    return {"name": name, "city": _city(facts.text), "industry": industry or name, "offers": offers,
            "ideal_customer": "", "why_us": "\n".join(why), "proof": "",
            "whatsapp": facts.whatsapp[-10:] if facts.whatsapp else (facts.phones[0] if facts.phones else ""),
            "email": facts.emails[0] if facts.emails else "", "language": "English"}


async def brain_from_site(facts):
    material = f"""WEBSITE: {facts.url}
TITLE: {facts.title}
DESCRIPTION: {facts.description}
HEADINGS: {' | '.join(facts.headings[:25])}
PHONES: {', '.join(facts.phones)}  WHATSAPP: {facts.whatsapp}  EMAILS: {', '.join(facts.emails)}
PAGE TEXT (home, about, services, contact):
{facts.text[:14000]}"""
    return await complete(RULES, f"""{material}

Fill in this business's profile from its own website. Copy names, offers and prices exactly as the site writes them.
Only what the site actually says: leave a field empty if the site doesn't say it. Never invent prices, years, awards or clients.
- industry: one plain line on what they do and for whom.
- offers: their main products or services (up to 8), price only if the site shows one.
- ideal_customer: who the site is written for, if it's clear.
- why_us: the reasons the site gives for choosing them, one per line.
- proof: real proof the site shows (years, numbers of customers, certifications), word for word.
- whatsapp: the WhatsApp or mobile number shown, digits only.
- language: the language the site is written in.
JSON only: {BRAIN_JSON}""", lambda: mock_from_site(facts), 2000)


def mock_from_words(text: str) -> dict:
    first = (text or "").split(".")[0]
    m = re.search(r"(?i:my business is|our business is|we are|i run|this is)\s+([A-Z][\w&' ]{2,60})", text or "")
    return {"name": (m.group(1).strip() if m else "")[:80], "city": _city(text), "industry": first[:200], "offers": [],
            "ideal_customer": "", "why_us": "", "proof": "", "whatsapp": "", "email": "", "language": "English"}


async def brain_from_words(text: str):
    return await complete(RULES, f"""The owner described their business in their own words (a voice note transcript or typed text, may be in
Hindi, Hinglish or another Indian language):
\"\"\"{text[:8000]}\"\"\"

Fill in the business profile from what they said, in English. Only what they actually said — leave anything else empty.
JSON only: {BRAIN_JSON}""", lambda: mock_from_words(text), 1500)


# ───────────────────────── English polisher ─────────────────────────
KINDS = {"whatsapp": "a WhatsApp message", "email": "an email with a subject line", "letter": "a formal letter", "post": "a social media post"}
TONES = {"warm": "warm and friendly", "firm": "polite but firm", "formal": "formal and respectful"}


def mock_polish(text: str, kind: str, tone: str, p: dict) -> dict:
    body = " ".join((text or "").split())
    body = body[:1].upper() + body[1:]
    if body and body[-1] not in ".!?":
        body += "."
    sign = p.get("name") or ""
    if kind == "email":
        return {"subject": "Following up", "text": f"Dear Sir/Madam,\n\n{body}\n\nKind regards,\n{sign}".strip()}
    if kind == "letter":
        return {"subject": "", "text": f"To,\nThe Concerned Person\n\nSubject: Request\n\nRespected Sir/Madam,\n\n{body}\n\nYours sincerely,\n{sign}".strip()}
    return {"subject": "", "text": f"Hello, {body}" + (f"\n— {sign}" if sign else "")}


async def polish(text: str, kind: str, tone: str, p: dict):
    return await complete(RULES, f"""{profile_text(p)}

The owner wrote or said this, possibly in Hindi, Hinglish, Gujarati, Marathi or rough English:
\"\"\"{text[:6000]}\"\"\"

Rewrite it as {KINDS.get(kind, KINDS['whatsapp'])} in clear, correct, professional English that commands respect. Tone: {TONES.get(tone, TONES['warm'])}.
Keep every fact, name, number and date exactly. Add nothing new. Sign off with the business name where it fits.
JSON only: {{"subject": "only for an email, else empty", "text": "the polished text"}}""", lambda: mock_polish(text, kind, tone, p), 1500)

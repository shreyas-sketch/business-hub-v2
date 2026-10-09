"""
The Business AI Score: 10 questions on the silent killers and the growth basics, plus (when the owner has a website)
8 checks on that website. Worked out by code, never by the AI, so the same answers always give the same score.

    no website: the 10 questions, 10 points each (yes 10 · partly 5 · no 0)
    website:    the questions count for 60, the 8 website checks for 40 (5 each)
The three biggest gaps become the top 3 fixes, each pointing at the part of the hub that helps.
"""
# (key, area, question, fix, the hub feature that helps)
QUESTIONS = [
    ("focus", "Customer focus", "Do you know which customers bring you the most profit for the least effort?",
     "Find your Amazing customers — high return, low effort — and aim most of your goal at them.", "customer_portfolio"),
    ("margins", "Margins", "Do you know your profit margin on each main product or service?",
     "Work out the margin on your top 5 products this week. Re-price or drop anything that doesn't pay.", "revenue_levers"),
    ("sales", "Steady inquiries", "Do new inquiries come in every week — not only from referrals?",
     "Pick one channel that brings inquiries every week, and set a weekly inquiry target.", "lead_magnet"),
    ("payments", "Getting paid on time", "Do customers pay on time, without you chasing them?",
     "Take an advance, put a due date on every bill, and send a polite reminder on the day it's due.", "money_owed"),
    ("offers", "Offer ladder", "Do you have an easy first offer, a main offer and a premium offer?",
     "Build an offer ladder: an easy first offer, your main offer and a premium one.", "offer_ladder"),
    ("reply", "Reply speed", "Does every inquiry get a reply within an hour?",
     "Reply to every inquiry within the hour. The fastest reply usually wins the customer.", "leads"),
    ("followup", "Follow-up", "Do you follow up every lead until you get a clear yes or no?",
     "Follow up on day 1, 3 and 7 until you get a clear yes or no.", "follow_up_agent"),
    ("content", "Posting regularly", "Do you post about your business at least 3 times a week?",
     "Post 3 times a week. The AI Writer writes a week of posts in a minute.", "ai_writer"),
    ("process", "Written processes", "Are your main jobs written down, so someone else can do them?",
     "Write your most common job as an SOP, so it gets done the same way without you.", "sop_library"),
    ("numbers", "Weekly numbers", "Do you check your numbers — leads, sales, money owed — every week?",
     "Every Monday, check four numbers: inquiries, sales, money owed and money in.", "magic_number"),
]
ANSWER_POINTS = {"yes": 10, "partly": 5, "no": 0}

WEBSITE_CHECKS = [
    ("https", "Secure address (https)", "Switch on https so browsers don't warn your visitors."),
    ("mobile", "Works on phones", "Make the site work on phones — most of your visitors are on one."),
    ("title", "Title and description for Google", "Add a clear page title and description so Google shows what you do."),
    ("contact", "Phone or email visible", "Put your phone number at the top of every page."),
    ("whatsapp", "Chat on WhatsApp button", "Add a Chat on WhatsApp button — it's how most customers want to reach you."),
    ("form", "Inquiry form", "Add a short inquiry form, so visitors can reach you even at night."),
    ("proof", "Reviews or testimonials", "Show three customer reviews with names (with their consent)."),
    ("light", "Opens fast", "Make the page lighter (smaller images) so it opens fast on mobile data."),
]


def compute(answers: dict, website: dict | None) -> dict:
    q_points = sum(ANSWER_POINTS.get(answers.get(k, "no"), 0) for k, *_ in QUESTIONS)   # out of 100
    gaps = []  # (lost points out of the total, fix, label, feature)
    if website and website.get("checks") is not None:
        checks = website["checks"]
        w_points = sum(5 for k, *_ in WEBSITE_CHECKS if checks.get(k))
        score = round(q_points * 0.6 + w_points)
        for k, label, fix in WEBSITE_CHECKS:
            if not checks.get(k):
                gaps.append((5, fix, label, "website"))
        q_weight = 0.6
        parts = {"questions": round(q_points * 0.6), "questions_out_of": 60, "website": w_points, "website_out_of": 40}
    else:
        score = q_points
        q_weight = 1.0
        parts = {"questions": q_points, "questions_out_of": 100, "website": None, "website_out_of": None}
    for k, area, _q, fix, feature in QUESTIONS:
        lost = (10 - ANSWER_POINTS.get(answers.get(k, "no"), 0)) * q_weight
        if lost:
            gaps.append((lost, fix, area, feature))
    gaps.sort(key=lambda g: -g[0])
    fixes = [{"fix": fix, "about": label, "feature": feature} for _, fix, label, feature in gaps[:3]]
    band = "Strong" if score >= 75 else "Getting there" if score >= 50 else "Needs attention"
    return {"score": max(0, min(100, score)), "band": band, "parts": parts, "fixes": fixes}

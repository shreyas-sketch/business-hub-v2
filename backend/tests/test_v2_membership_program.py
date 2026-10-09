"""v2 — Membership (the weekly rhythm, calendar, member call, cohort board, tools, Magic Number, Gaps scan) and the
Action Program (lead magnet, offer ladder, revenue levers, customer portfolio, Football Field, leak finder, end goals)."""
from datetime import timedelta

from app import festivals
from app.agents import rhythm
from app.db import IST, db, now
from tests.conftest import PROFILE, go_live, new_owner

ADMIN = "9999900000"


async def owner_on(phone: str, plan: str = "lite", live: bool = True, **extra):
    c = await new_owner(phone, **extra)
    site = await go_live(c) if live else None
    if not live:
        assert (await c.put("/api/business", json=PROFILE)).status_code == 200
    uid = (await c.get("/api/me")).json()["user"]["id"]
    if plan != "free":
        admin = await new_owner(ADMIN)
        assert (await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})).status_code == 200
    return c, uid, site


# ═════════════════════════ Membership ═════════════════════════
async def test_weekly_rhythm_plan_daily_action_streak_and_friday_score(client):
    free, _, _ = await owner_on("9838000001", "free", live=False)
    r = await free.get("/api/week")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "locked"

    c, uid, site = await owner_on("9838000002")
    d = (await c.get("/api/week")).json()
    assert d["week"] is None and d["today"]["text"] and d["streak"]["current"] == 0
    w = (await c.post("/api/week/plan")).json()
    assert len(w["posts"]) == 7 and len(w["actions"]) == 3 and w["score"] == 0
    assert all(p["hook"] and p["caption"] for p in w["posts"])

    # a new inquiry makes today's action "reply to it"
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Neha Joshi", "phone": "98340 00001", "message": "Kitchen price?"})
    await db().weeks.update_one({"_id": w["id"]}, {"$set": {"days": {}}})
    d = (await c.get("/api/week")).json()
    assert "inquiry" in d["today"]["text"] and d["today"]["link"] == "/leads" and d["today_post"]

    s = (await c.post("/api/week/today/done")).json()
    assert s["streak"] == {"current": 1, "best": 1, "done_today": True}
    assert (await c.post("/api/week/today/done")).json()["streak"]["current"] == 1     # once a day
    # yesterday was done too → the streak grows; a missed day resets it
    yesterday = (rhythm.today_ist() - timedelta(days=1)).isoformat()
    await db().streaks.update_one({"_id": uid}, {"$set": {"last_day": yesterday, "current": 4, "best": 4}})
    assert (await c.post("/api/week/today/done")).json()["streak"]["current"] == 5
    await db().streaks.update_one({"_id": uid}, {"$set": {"last_day": (rhythm.today_ist() - timedelta(days=3)).isoformat()}})
    assert (await c.get("/api/week")).json()["streak"]["current"] == 0

    for n in range(3):
        w = (await c.post(f"/api/week/actions/{n}")).json()
    assert all(a["done"] for a in w["actions"])
    assert (await c.post("/api/week/actions/7")).status_code == 404
    w = (await c.post("/api/week/checkin", json={"leads": 6, "sales": 2, "revenue": 185000, "wins": "Closed the Shah kitchen"})).json()
    assert w["checkin"]["revenue"] == 185000
    assert w["score"] == 40 + round(40 * 1 / 6) + 20    # 3 actions, 1 day of 6, check-in
    hist = (await c.get("/api/week/history")).json()
    assert hist[0]["score"] == w["score"]


async def test_week_score_counts_actions_days_and_checkin():
    assert rhythm.week_score(None) == 0
    full = {"actions": [{"done": True}] * 3, "days": {str(i): {"done": True} for i in range(6)}, "checkin": {"leads": 1}}
    assert rhythm.week_score(full) == 100
    assert rhythm.week_score({"actions": [{"done": True}, {"done": False}, {"done": False}], "days": {}, "checkin": None}) == 13


async def test_content_calendar_with_festivals_and_posting_days(client):
    c, _, _ = await owner_on("9838000003")
    t = rhythm.today_ist()
    month = t.strftime("%Y-%m")
    r = await c.post("/api/calendar", json={"month": month, "focus": "Diwali makeover"})
    assert r.status_code == 200, r.text
    cal = r.json()["calendar"]
    slots = rhythm.posting_days(t.year, t.month)
    assert len(cal["posts"]) == len(slots) and all(p["caption"] for p in cal["posts"])
    for f in festivals.in_month(t.year, t.month):
        assert any(p["date"] == f["date"] and p["occasion"] == f["name"] for p in cal["posts"])
    day = cal["posts"][0]["date"]
    assert (await c.post(f"/api/calendar/{month}/posted/{day}")).status_code == 200
    assert (await c.get(f"/api/calendar/{month}")).json()["calendar"]["posts"][0]["posted"] is True
    # only this month or the next two
    far = (t.replace(day=1) + timedelta(days=130)).strftime("%Y-%m")
    assert (await c.post("/api/calendar", json={"month": far})).status_code == 400
    past = (t.replace(day=1) - timedelta(days=2)).strftime("%Y-%m")
    assert (await c.post("/api/calendar", json={"month": past})).status_code == 400


def test_posting_days_are_mon_wed_fri_plus_festivals():
    days = rhythm.posting_days(2026, 11)
    dates = {d["date"]: d["occasion"] for d in days}
    assert dates.get("2026-11-08") == "Diwali" or "Diwali" in dates.get("2026-11-08", "")
    from datetime import date
    for d in days:
        x = date.fromisoformat(d["date"])
        assert x.weekday() in (0, 2, 4) or d["occasion"]


async def test_member_call_questions_and_admin_schedule(client):
    admin = await new_owner(ADMIN)
    c, _, _ = await owner_on("9838000004")
    free, _, _ = await owner_on("9838000005", "free", live=False)
    starts = (now() + timedelta(days=3)).astimezone(IST).replace(tzinfo=None).isoformat()
    r = await admin.post("/api/admin/member-calls", json={"title": "Pricing for festive season", "starts_at": starts, "join_link": "https://meet.example/abc"})
    assert r.status_code == 200, r.text
    call = r.json()
    assert call["tier_name"] == "Membership"
    up = (await c.get("/api/member-call")).json()["upcoming"]
    assert [x["id"] for x in up] == [call["id"]]
    for i in range(3):
        assert (await c.post(f"/api/member-call/{call['id']}/questions", json={"text": f"Question number {i + 1} about pricing"})).status_code == 200
    r = await c.post(f"/api/member-call/{call['id']}/questions", json={"text": "One more question please"})
    assert r.status_code == 400 and "3 questions" in r.json()["detail"]
    assert (await free.get("/api/member-call")).status_code == 403
    listed = (await admin.get("/api/admin/member-calls")).json()
    assert len(listed[0]["questions"]) == 3 and listed[0]["questions"][0]["business"] == PROFILE["name"]
    # a call for a higher plan isn't shown to members
    r = await admin.post("/api/admin/member-calls", json={"title": "Growth mentees only", "starts_at": starts, "tier": "growth"})
    assert len((await c.get("/api/member-call")).json()["upcoming"]) == 1
    assert (await c.post(f"/api/member-call/{r.json()['id']}/questions", json={"text": "Can I join this one?"})).status_code == 404


async def test_cohort_board_ranks_by_week_score_and_owner_can_hide(client):
    admin = await new_owner(ADMIN)
    assert (await admin.post("/api/admin/cohorts", json={"code": "PUNE-OCT", "name": "Pune, October"})).status_code == 200
    a, ua, _ = await owner_on("9838000006", cohort="PUNE-OCT")
    b, ub, _ = await owner_on("9838000007", cohort="pune-oct")      # codes are matched in capitals
    await a.post("/api/week/plan")
    await a.post("/api/week/checkin", json={"leads": 1})
    board = (await b.get("/api/board")).json()
    assert board["cohort"]["name"] == "Pune, October" and [r["score"] for r in board["rows"]] == [20, 0]
    assert board["rows"][0]["me"] is False and board["me"]["rank"] == 2
    assert (await a.post("/api/board/visibility", json={"hide": True})).json()["hidden"] is True
    assert len((await b.get("/api/board")).json()["rows"]) == 1


async def test_ready_made_tools_by_plan(client):
    c, _, _ = await owner_on("9838000008")
    lib = (await c.get("/api/tools")).json()
    by = {t["key"]: t for t in lib["tools"]}
    assert not by["content"]["locked"] and by["persona"]["locked"] and by["persona"]["tier_name"] == "Action Program"
    assert lib["roles"] == []
    r = await c.post("/api/tools/content/run", json={"inputs": {"focus": "Diwali makeover", "platform": "Instagram and Facebook"}})
    assert r.status_code == 200, r.text
    out = r.json()["output"]
    assert out["title"] and len(out["sections"]) >= 3
    assert (await c.post("/api/tools/video/run", json={"inputs": {}})).status_code == 400          # topic is required
    assert (await c.post("/api/tools/persona/run", json={"inputs": {"customers": "Young couples"}})).status_code == 403
    assert (await c.post("/api/tools/role:7/run", json={"inputs": {"brief": "x y z"}})).status_code == 403
    hist = (await c.get("/api/tools/content/history")).json()
    assert len(hist) == 1 and hist[0]["minutes"] == 120
    outputs = (await c.get("/api/outputs")).json()
    assert any(o.get("kind_label") == "Content Agent" for o in outputs)


async def test_magic_number_and_gaps_scan(client):
    c, uid, site = await owner_on("9838000009")
    r = await c.put("/api/magic", json={"monthly_target": 1000000, "avg_sale": 100000, "close_rate": 20, "meeting_rate": 50})
    res = r.json()["result"]
    assert res["customers_month"] == 10 and res["inquiries_month"] == 50 and res["inquiries_week"] == 12 and res["meetings_month"] == 25
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Ravi", "phone": "98340 00002", "message": "Hi"})
    prog = (await c.get("/api/magic")).json()["progress"]
    assert prog["inquiries"] == 1 and prog["inquiries_pct"] == 2
    assert (await c.put("/api/magic", json={"monthly_target": 0, "avg_sale": 1, "close_rate": 1})).status_code == 422

    qs = (await c.get("/api/gaps")).json()["questions"]
    assert len(qs) == 12
    bad = await c.post("/api/gaps", json={"answers": {q["key"]: 3 for q in qs[:5]}})
    assert bad.status_code == 400
    answers = {q["key"]: 5 for q in qs}
    answers.update(pay1=1, pay2=2, focus1=3)
    g = (await c.post("/api/gaps", json={"answers": answers})).json()
    assert g["areas"]["Payments"] == round(((1 + 2) / 2 - 1) / 4 * 100) and g["areas"]["Margins"] == 100
    assert [f["area"] for f in g["fixes"]] == ["Payments", "Payments", "Strategic focus"] and g["change"] is None
    assert g["silent_killers"]["Payments"] == 12
    g2 = (await c.post("/api/gaps", json={"answers": {q["key"]: 5 for q in qs}})).json()
    assert g2["score"] == 100 and g2["change"] == 100 - g["score"]
    # the week's plan picks up the gaps
    facts = await rhythm.week_facts({"_id": uid})
    assert facts["inquiries_week"] == 12 and facts["leads_waiting"] == 1


# ═════════════════════════ Action Program ═════════════════════════
async def test_lead_magnet_published_on_the_website_brings_leads(client):
    lite, _, _ = await owner_on("9838000010")
    assert (await lite.get("/api/lead-magnet")).status_code == 403
    c, uid, site = await owner_on("9838000011", "program")
    r = await c.post("/api/lead-magnet/generate", json={"problem": "Choosing a modular kitchen without overpaying", "format": "checklist"})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["guide"]["content"]["title"] and len(g["guide"]["content"]["sections"]) >= 2 and g["url"].endswith("/guide")
    assert (await client.get(f"/s/{site['slug']}/guide")).status_code == 404      # not published yet
    content = {**g["guide"]["content"], "title": "The 7-point kitchen checklist"}
    assert (await c.put("/api/lead-magnet", json={"content": content})).json()["guide"]["content"]["title"] == "The 7-point kitchen checklist"
    assert (await c.put("/api/lead-magnet", json={"content": {"title": "x", "sections": []}})).status_code == 400
    assert (await c.post("/api/lead-magnet/publish", json={"published": True})).json()["guide"]["published"] is True

    page = await client.get(f"/s/{site['slug']}/guide")
    assert page.status_code == 200 and "The 7-point kitchen checklist" in page.text
    home = await client.get(f"/s/{site['slug']}")
    assert "/guide" in home.text
    r = await client.post(f"/s/{site['slug']}/guide/get", data={"name": "Meera Iyer", "phone": "98340 00003"})
    assert r.status_code == 200 and content["sections"][1]["heading"] in r.text
    lead = await db().leads.find_one({"owner_id": uid, "source": "guide"})
    assert lead and lead["name"] == "Meera Iyer" and lead["stage"] == "identification"
    stats = (await c.get("/api/lead-magnet")).json()["stats"]
    assert stats == {"views": 1, "leads": 1}
    # a bad number gets the form back, not a lead
    r = await client.post(f"/s/{site['slug']}/guide/get", data={"name": "Bot", "phone": "123"}, follow_redirects=False)
    assert r.status_code == 303 and "err=phone" in r.headers["location"]


async def test_offer_ladder_shows_on_the_website(client):
    c, _, site = await owner_on("9838000012", "program")
    assert (await c.post("/api/offers/show", json={"show": True})).status_code == 404
    lad = (await c.post("/api/offers/generate", json={"notes": "", "entry": "Free site visit"})).json()["ladder"]
    levels = lad["content"]["levels"]
    assert len(levels) == 3 and lad["show"] is False
    assert "Ways to work with us" not in (await client.get(f"/s/{site['slug']}")).text
    await c.post("/api/offers/show", json={"show": True})
    home = (await client.get(f"/s/{site['slug']}")).text
    assert levels[2]["name"] in home and 'id="ways"' in home
    bad = {**lad["content"], "levels": levels[:2]}
    assert (await c.put("/api/offers", json={"content": bad})).status_code == 400


async def test_revenue_levers_portfolio_leaks_and_end_goals(client):
    c, _, _ = await owner_on("9838000013", "program")
    lv = (await c.put("/api/levers", json={"customers": 100, "avg_value": 50000, "frequency": 1.2,
                                           "funnel": {"leads": "Lead magnet", "junk": "x"}, "pledge": "10×10×10 by March"})).json()["levers"]
    assert lv["result"]["revenue"] == 6000000 and lv["result"]["growth_pct"] == 33.1 and lv["pledged_at"]
    assert lv["funnel"] == {"leads": "Lead magnet"}

    segs = [{"name": "New 2BHK families", "ticket": 300000, "margin": 30, "repeat": "maybe", "effort": 3},
            {"name": "Builders", "ticket": 2000000, "margin": 15, "repeat": "yes", "collect_days": 90, "effort": 8, "kind": "B2B"},
            {"name": "Small repairs", "ticket": 15000, "margin": 40, "repeat": "no", "effort": 2},
            {"name": "Show-flat designers", "ticket": 50000, "margin": 10, "repeat": "no", "effort": 9, "kind": "B2B"}]
    pf = (await c.put("/api/portfolio", json={"goal": 12000000, "amazing_share": 75, "segments": segs})).json()["portfolio"]
    letters = {s["name"]: s["letter"] for s in pf["segments"]}
    assert letters == {"New 2BHK families": "A", "Builders": "B", "Small repairs": "C", "Show-flat designers": "D"}
    a = next(s for s in pf["segments"] if s["letter"] == "A")
    assert a["target"] == 9000000 and a["customers_needed"] == 30 and a["leads_needed"] == 150
    segs[2]["letter"] = "A"   # the owner overrules the hub
    pf = (await c.put("/api/portfolio", json={"goal": 0, "segments": segs})).json()["portfolio"]
    assert next(s for s in pf["segments"] if s["name"] == "Small repairs")["auto"] is False

    lk = (await c.put("/api/leaks", json={"numbers": {"visitors": 2000, "inquiries": 60, "meetings": 12, "proposals": 9, "won": 3},
                                          "avg_sale": 200000})).json()
    leak = lk["saved"]["result"]["biggest_leak"]
    assert leak["key"] == "meetings" and leak["rate"] == 20.0
    assert lk["saved"]["result"]["if_fixed"]["extra_customers"] > 0
    fx = (await c.post("/api/leaks/fixes")).json()
    assert fx["saved"]["fixes"]["fixes"]

    eg = (await c.put("/api/end-goals", json={"identity": {"text": "Known as Thane's most reliable interior firm", "by": "2028"},
                                              "income": {"text": "₹3 lakh a month"}})).json()
    assert eg["goals"]["identity"]["by"] == "2028" and len(eg["prompts"]) == 4


async def test_football_field_stages_and_goal_kinds(client):
    c, uid, site = await owner_on("9838000014", "program")
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Asha", "phone": "98340 00004", "message": "Wardrobes"})
    lead = await db().leads.find_one({"owner_id": uid})
    assert lead["stage"] == "identification"
    r = await c.patch(f"/api/leads/{lead['_id']}", json={"stage": "pain", "value": 240000})
    assert r.status_code == 200, r.text
    lead = await db().leads.find_one({"_id": lead["_id"]})
    assert lead["stage"] == "pain" and lead["value"] == 240000 and lead.get("stage_at")
    assert (await c.patch(f"/api/leads/{lead['_id']}", json={"stage": "maybe"})).status_code == 422
    leaks = (await c.get("/api/leaks")).json()["from_hub"]
    assert leaks["inquiries"] == 1 and leaks["meetings"] == 1 and leaks["proposals"] == 0

    t = rhythm.today_ist()
    r = await c.post("/api/goals", json={"title": "Hire a site supervisor", "kind": "functional", "area": "operations", "target": 1,
                                         "start": t.isoformat(), "end": (t + timedelta(days=60)).isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "functional" and r.json()["kind_label"]

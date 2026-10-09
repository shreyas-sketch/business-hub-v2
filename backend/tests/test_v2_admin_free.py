"""v2: the admin's feature manager, and the free plan — reading a website into the Business Brain (safely), the Business AI
Score and its share card, websites at <name>.<SITES_DOMAIN>, Chat on WhatsApp, the visiting card and the English polisher."""
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import fetch, plans
from app.config import settings
from app.db import db
from tests.conftest import PROFILE, go_live, login, new_owner

ADMIN = "9999900000"


async def owner_on(phone: str, plan: str = "free", live: bool = True):
    c = await new_owner(phone)
    site = await go_live(c) if live else None
    uid = (await c.get("/api/me")).json()["user"]["id"]
    if plan != "free":
        admin = await new_owner(ADMIN)
        assert (await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})).status_code == 200
    return c, uid, site


# ───────────────────────── Admin → Plans & features ─────────────────────────
async def test_admin_moves_switches_renames_and_undoes_features(client):
    owner, uid, _ = await owner_on("9837000001", "lite", live=False)
    admin = await new_owner(ADMIN)
    assert (await owner.get("/api/admin/config")).status_code == 403
    cfg = (await admin.get("/api/admin/config")).json()
    assert [t["tier"] for t in cfg["tiers"]] == plans.TIERS and len(cfg["features"]) == len(plans.META)
    assert next(f for f in cfg["features"] if f["key"] == "week")["tier"] == "lite"

    # move the content calendar down to Free: a free owner now has it, and the menu shows it unlocked
    free, free_uid, _ = await owner_on("9837000002", live=False)
    assert not (await free.get("/api/me")).json()["features"]["content_calendar"]
    r = await admin.patch("/api/admin/config/features/content_calendar", json={"tier": "free", "label": "Festival posts"})
    assert r.status_code == 200 and r.json()["tier"] == "free" and r.json()["label"] == "Festival posts"
    me = (await free.get("/api/me")).json()
    assert me["features"]["content_calendar"] and me["feature_info"]["content_calendar"]["label"] == "Festival posts"
    item = next(i for g in me["menu"] for i in g["items"] if i["key"] == "content_calendar")
    assert item["label"] == "Festival posts" and not item["locked"]

    # switch the week off for everyone: even a member loses it, and the API says it is off (not "upgrade")
    assert (await admin.patch("/api/admin/config/features/week", json={"on": False})).status_code == 200
    r = await owner.get("/api/week")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "off"
    assert not any(i["key"] == "week" for g in (await owner.get("/api/me")).json()["menu"] for i in g["items"])
    # the core pages can't be switched off or moved
    assert (await admin.patch("/api/admin/config/features/home", json={"on": False})).status_code == 400
    assert (await admin.patch("/api/admin/config/features/business_brain", json={"tier": "lite"})).status_code == 400
    assert (await admin.patch("/api/admin/config/features/leads", json={"group": "Nowhere"})).status_code == 400

    # a locked page can be hidden instead of shown as a teaser
    assert any(i["key"] == "workforce" for g in (await free.get("/api/me")).json()["menu"] for i in g["items"])
    await admin.patch("/api/admin/config/features/workforce", json={"teaser": False})
    assert not any(i["key"] == "workforce" for g in (await free.get("/api/me")).json()["menu"] for i in g["items"])

    # drag the menu: Leads first in Start
    r = await admin.put("/api/admin/config/menu", json={"groups": {"Start": ["leads", "home"]}})
    assert r.status_code == 200 and r.json()["moved"] == 2
    start = next(g for g in (await owner.get("/api/me")).json()["menu"] if g["group"] == "Start")
    assert [i["key"] for i in start["items"]][:2] == ["leads", "home"]

    # every change is logged, and undo puts it back
    changes = (await admin.get("/api/admin/config/changes")).json()
    assert [c["kind"] for c in changes][:3] == ["menu", "feature", "feature"]
    week_change = next(c for c in changes if c["target"] == "week")
    assert (await admin.post(f"/api/admin/config/changes/{week_change['id']}/undo")).status_code == 200
    assert (await owner.get("/api/week")).status_code == 200
    assert (await admin.post(f"/api/admin/config/changes/{week_change['id']}/undo")).status_code == 409
    menu_change = next(c for c in changes if c["kind"] == "menu")
    await admin.post(f"/api/admin/config/changes/{menu_change['id']}/undo")
    start = next(g for g in (await owner.get("/api/me")).json()["menu"] if g["group"] == "Start")
    assert start["items"][0]["key"] == "home"
    assert (await admin.post("/api/admin/config/features/content_calendar/reset")).json()["tier"] == "lite"


async def test_admin_changes_plans_and_grants_one_owner_a_feature(client):
    owner, uid, _ = await owner_on("9837000003", live=False)
    admin = await new_owner(ADMIN)
    r = await admin.patch("/api/admin/config/plans/program", json={"price_minor": 1_200_000, "runs": 350, "name": "Action Program Plus"})
    assert r.status_code == 200 and plans.PLANS["program"]["price_minor"] == 1_200_000
    ladder = (await owner.get("/api/plans")).json()["ladder"]
    assert ladder[2]["name"] == "Action Program Plus" and ladder[2]["price_minor"] == 1_200_000 and ladder[2]["runs"] == 350
    assert (await admin.patch("/api/admin/config/plans/free", json={"price_minor": 100})).status_code == 400
    assert (await admin.patch("/api/admin/config/plans/lite", json={"access_days": 30})).status_code == 400
    r = await admin.patch("/api/admin/config/plans/lite", json={"price_minor": 249_900})
    assert r.status_code == 400 and "Razorpay plan" in r.json()["detail"]
    r = await admin.patch("/api/admin/config/plans/lite", json={"price_minor": 249_900, "razorpay_plan_id": "plan_NEWPRICE123"})
    assert r.status_code == 200 and plans.PLANS["lite"]["razorpay_plan_id"] == "plan_NEWPRICE123"
    assert (await admin.patch("/api/admin/config/plans/growth", json={"team_size": 15})).json()["team_size"] == 15

    # a grant: one owner gets the lead magnet for 30 days, without changing plan
    assert (await owner.get("/api/lead-magnet")).status_code == 403
    r = await admin.post("/api/admin/config/grants", json={"user_id": uid, "feature": "lead_magnet", "days": 30, "note": "workshop winner"})
    assert r.status_code == 200
    assert (await owner.get("/api/lead-magnet")).status_code == 200
    me = (await owner.get("/api/me")).json()
    assert me["features"]["lead_magnet"] and me["user"]["effective_plan"] == "free"
    assert any("Lead magnet" in n["text"] for n in me["notices"])
    grants = (await admin.get("/api/admin/config/grants")).json()
    assert grants[0]["feature"] == "lead_magnet" and grants[0]["active"]
    detail = (await admin.get(f"/api/admin/owners/{uid}")).json()
    assert detail["grants"][0]["feature"] == "lead_magnet" and next(f for f in detail["features"] if f["key"] == "lead_magnet")["has"]
    # switched off for everyone beats a grant
    await admin.patch("/api/admin/config/features/lead_magnet", json={"on": False})
    assert (await owner.get("/api/lead-magnet")).status_code == 403
    await admin.patch("/api/admin/config/features/lead_magnet", json={"on": True})
    assert (await admin.delete(f"/api/admin/config/grants/{uid}/lead_magnet")).status_code == 200
    assert (await owner.get("/api/lead-magnet")).status_code == 403
    undo = next(c for c in (await admin.get("/api/admin/config/changes")).json() if c["kind"] == "grant" and c["after"] is None)
    await admin.post(f"/api/admin/config/changes/{undo['id']}/undo")
    assert (await owner.get("/api/lead-magnet")).status_code == 200


# ───────────────────────── reading the owner's website ─────────────────────────
PAGES = {
    "/": """<html><head><title>Sharma Modular Kitchens | Pune</title><meta name="description" content="Modular kitchens and wardrobes in Pune, designed and fitted in 21 days.">
           <meta name="viewport" content="width=device-width"><meta name="theme-color" content="#7a1f1f"></head>
           <body><img class="site-logo" src="/img/logo.png" alt="Sharma logo"><h1>Kitchens that work as hard as you do</h1>
           <h2>Modular kitchens</h2><h2>Wardrobes</h2><h2>Why choose us</h2><h3>15 years of trusted work</h3>
           <a href="/about-us">About us</a><a href="/contact">Contact</a><a href="https://wa.me/919876543210">WhatsApp</a>
           <p>Call us on 98765 43210. Serving Pune and PCMC. Read our customer reviews.</p></body></html>""",
    "/about-us": "<html><body><h1>About</h1><p>Family business since 2011, own factory in Pune.</p></body></html>",
    "/contact": "<html><body><form><input name=n></form><a href='mailto:hello@sharmakitchens.in'>mail</a></body></html>",
    "/old": None,
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/old":
            self.send_response(301)
            self.send_header("Location", "/")
            self.end_headers()
            return
        body = PAGES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


@contextmanager
def site_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


async def test_onboarding_reads_the_owners_website_into_the_business_brain(client):
    c = await new_owner("9837000010")
    with site_server() as base:
        r = await c.post("/api/onboarding/website", json={"url": base + "/old"})   # follows the redirect
    assert r.status_code == 200, r.text
    d = r.json()
    p = d["profile"]
    assert p["name"] == "Sharma Modular Kitchens" and p["city"] == "Pune" and p["whatsapp"] == "9876543210"
    assert p["email"] == "hello@sharmakitchens.in" and {o["name"] for o in p["offers"]} >= {"Modular kitchens", "Wardrobes"}
    assert "15 years of trusted work" in p["why_us"] and d["colour"] == "#7a1f1f" and d["logo"].endswith("/img/logo.png")
    checks = d["checks"]
    assert checks["mobile"] and checks["title"] and checks["contact"] and checks["whatsapp"] and checks["form"] and checks["proof"]
    assert not checks["https"]
    assert (await c.get("/api/me")).json()["runs"]["used"] == 1
    # the owner checks the draft and saves it as their Business Brain
    profile = {**PROFILE, **{k: v for k, v in p.items() if v}, "offers": p["offers"][:4]}
    assert (await c.put("/api/business", json=profile)).status_code == 200


async def test_reading_a_website_refuses_private_and_odd_addresses(client, monkeypatch):
    for bad in ("", "ftp://example.com", "https://user:pw@example.com", "https://example.com:8443/", "javascript:alert(1)"):
        with pytest.raises(fetch.FetchError):
            fetch.normalise_url(bad)
    monkeypatch.setattr(type(settings), "fetch_private_ok", property(lambda s: False))
    c = await new_owner("9837000011")
    with site_server() as base:
        r = await c.post("/api/onboarding/website", json={"url": base})
    assert r.status_code == 400 and "public website" in r.json()["detail"]
    for ip in ("127.0.0.1", "10.0.0.7", "169.254.169.254", "::1", "192.168.1.5", "::ffff:10.0.0.1"):
        assert fetch._blocked(ip), ip
    assert not fetch._blocked("8.8.8.8")
    assert (await c.get("/api/me")).json()["runs"]["used"] == 0   # nothing was read, no run used


async def test_voice_or_typed_words_fill_the_brain(client):
    c = await new_owner("9837000012")
    r = await c.post("/api/onboarding/words", json={"text": "My business is Kapoor Dental Clinic. We do family dentistry in Thane, braces and implants."})
    assert r.status_code == 200 and r.json()["profile"]["name"] == "Kapoor Dental Clinic" and r.json()["profile"]["city"] == "Thane"


# ───────────────────────── Business AI Score ─────────────────────────
async def test_business_score_share_card_and_monthly_recheck(client):
    c, uid, _ = await owner_on("9837000020", live=False)
    await c.put("/api/business", json=PROFILE)
    q = (await c.get("/api/score")).json()
    assert len(q["questions"]) == 10 and q["latest"] is None and q["can_retake"]
    answers = {x["key"]: "yes" for x in q["questions"]}
    answers.update(followup="no", payments="no", content="partly")
    assert (await c.post("/api/score", json={"answers": {"focus": "maybe"}})).status_code == 400
    s = (await c.post("/api/score", json={"answers": answers})).json()
    assert s["score"] == 75 and s["band"] == "Strong" and s["parts"]["website"] is None
    assert [f["about"] for f in s["fixes"]] == ["Getting paid on time", "Follow-up", "Posting regularly"]
    assert s["share_url"].startswith("https://hub.example.in/score/")

    page = await client.get(s["share_url"].replace("https://hub.example.in", ""))
    assert page.status_code == 200 and "scored 75/100" in page.text and "src=score" in page.text and "Follow-up" in page.text
    assert await db().events.count_documents({"type": "invite_visit", "meta.src": "score"}) == 1
    assert (await client.get("/score/not-a-token")).status_code == 404

    r = await c.post("/api/score", json={"answers": answers})   # the monthly re-check is Membership
    assert r.status_code == 403 and r.json()["detail"]["feature"] == "score_recheck"
    admin = await new_owner(ADMIN)
    await admin.patch(f"/api/admin/users/{uid}", json={"plan": "lite"})
    # with a website scan, the website counts for 40 of the 100
    await db().site_scans.insert_one({"_id": uid, "url": "https://x.in", "checks": {k: True for k in ("https", "mobile", "title", "contact")},
                                      "logo": "", "colour": "", "at": s["at"] and __import__("app.db", fromlist=["now"]).now()})
    s2 = (await c.post("/api/score", json={"answers": {k: "yes" for k in answers}})).json()
    assert s2["score"] == 80 and s2["parts"] == {"questions": 60, "questions_out_of": 60, "website": 20, "website_out_of": 40}
    assert s2["change"] == 5 and s2["fixes"][0]["about"] == "Chat on WhatsApp button"
    assert len((await c.get("/api/score")).json()["history"]) == 2


# ───────────────────────── websites at <name>.employz.ai ─────────────────────────
@pytest.fixture
def sites_domain():
    old = settings.sites_domain
    object.__setattr__(settings, "sites_domain", "employz.ai")
    yield "employz.ai"
    object.__setattr__(settings, "sites_domain", old)


async def test_every_website_lives_at_its_own_employz_address(client, sites_domain):
    c, uid, site = await owner_on("9837000030")
    assert site["url"] == "https://shree-ganesh-interiors.employz.ai" and site["card_url"].endswith(".employz.ai/card")
    host = "https://shree-ganesh-interiors.employz.ai"
    page = await client.get(f"{host}/")
    assert page.status_code == 200 and "Shree Ganesh Interiors" in page.text
    assert 'action="/inquiry"' in page.text and 'href="/wa"' in page.text   # links on the site's own address
    form = await client.post(f"{host}/inquiry", data={"name": "Neha Joshi", "phone": "98330 00000", "message": "Kitchen"})
    assert form.status_code == 303 and form.headers["location"] == "/?sent=1#contact"
    assert (await db().leads.find_one({"owner_id": uid}))["source"] == "website"
    tap = await client.get(f"{host}/wa", follow_redirects=False)
    assert tap.status_code == 302 and tap.headers["location"].startswith("https://wa.me/919820000000")
    views = await db().site_views.find_one({"ws": uid})
    assert views["n"] == 1 and views["wa"] == 1

    # the hub never answers on a website's address, and nobody else's pages do either
    assert (await client.get(f"{host}/api/me")).status_code == 404
    assert (await client.get(f"{host}/s/someone-else")).status_code == 404
    assert (await client.get("https://nobody-here.employz.ai/")).status_code == 404
    # reserved names (the hub, app, www...) are never websites
    assert (await client.get("https://app.employz.ai/api/health")).json() == {"ok": True}
    assert (await c.put("/api/site", json={"content": (await c.get("/api/site")).json()["content"], "slug": "app"})).status_code == 400


async def test_visiting_card_and_contact_file(client):
    c, uid, site = await owner_on("9837000031")
    card = await client.get(f"/s/{site['slug']}/card")
    assert card.status_code == 200 and "Shree Ganesh Interiors" in card.text and "Save contact" in card.text and "src=card" in card.text
    vcf = await client.get(f"/s/{site['slug']}/card.vcf")
    assert vcf.status_code == 200 and vcf.headers["content-type"].startswith("text/vcard")
    assert "FN:Shree Ganesh Interiors" in vcf.text and "TEL;TYPE=CELL:+919820000000" in vcf.text
    assert (await client.get("/s/nope/card")).status_code == 404


# ───────────────────────── AI Writer: the English polisher ─────────────────────────
async def test_english_polisher_free_for_whatsapp_membership_for_letters(client):
    c, uid, _ = await owner_on("9837000040", live=False)
    await c.put("/api/business", json=PROFILE)
    r = await c.post("/api/studio/polish", json={"text": "sir payment pending hai 2 month se, please clear karo", "kind": "whatsapp"})
    assert r.status_code == 200 and r.json()["text"].startswith("Hello, Sir payment pending")
    r = await c.post("/api/studio/polish", json={"text": "sir payment pending hai", "kind": "email", "tone": "firm"})
    assert r.status_code == 403 and r.json()["detail"]["feature"] == "polish_voice"
    admin = await new_owner(ADMIN)
    await admin.patch(f"/api/admin/users/{uid}", json={"plan": "lite"})
    r = await c.post("/api/studio/polish", json={"text": "sir payment pending hai", "kind": "email", "tone": "firm"})
    assert r.status_code == 200 and r.json()["text"].startswith("Dear Sir/Madam") and r.json()["subject"]
    assert (await c.get("/api/outputs?kind=polish")).json()[0]["kind"] == "polish"


async def test_admin_numbers_have_every_feature_unlocked(client):
    from app import plans
    from app.config import settings
    await login(client, "+919999900000")
    me = (await client.get("/api/me")).json()
    assert me["user"]["role"] == "admin" and me["user"]["effective_plan"] == "office"
    assert all(me["features"][k] for k, m in plans.META.items() if m["on"])
    assert me["runs"]["allowance"] == plans.PLANS["office"]["runs"]
    old = settings.admin_phones
    object.__setattr__(settings, "admin_phones", ())
    try:  # taken off the list: back to the plan on the account, at once
        me = (await client.get("/api/me")).json()
        assert me["user"]["effective_plan"] == "free"
    finally:
        object.__setattr__(settings, "admin_phones", old)


async def test_admin_numbers_automations_run_once_they_have_a_business(client):
    from app.agents import scheduler
    admin = await login(client, "+919999900000")
    ids = lambda owners: {o["_id"] for o in owners}  # noqa: E731
    me = (await client.get("/api/me")).json()["user"]["id"]
    assert me not in ids(await scheduler.candidate_owners())  # managing the hub only: no automations about an empty hub
    assert (await admin.put("/api/business", json=PROFILE)).status_code == 200
    assert me in ids(await scheduler.candidate_owners())  # their own business set up: everything runs, like the top plan

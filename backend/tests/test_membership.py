"""Goals (Action Program), funnel & dashboard (Membership), daily website views, and own domains (Growth Mentorship)."""
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.db import IST, db, now
from app.routers import domains, membership
from app.services import new_id
from tests.conftest import PROFILE, go_live, new_owner

async def member(phone: str, plan: str = "lite"):
    c = await new_owner(phone)
    uid = (await c.get("/api/me")).json()["user"]["id"]
    admin = await new_owner("9999900000")
    assert (await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})).status_code == 200
    return c, uid


async def teammate(phone: str, owner_id: str, role: str):
    c = await new_owner(phone)
    uid = (await c.get("/api/me")).json()["user"]["id"]
    await db().users.update_one({"_id": uid}, {"$set": {"team_of": owner_id, "team_role": role}})
    return c, uid


async def runs_used(c) -> int:
    return (await c.get("/api/me")).json()["runs"]["used"]


async def add_lead(ws: str, at: datetime, status: str = "new", first_action_at: datetime | None = None, site_id: str = "x"):
    lead = {"_id": new_id(), "owner_id": ws, "site_id": site_id, "name": "Test Lead", "phone": "+919833000000", "message": "",
            "status": status, "source": "website", "created_at": at}
    if first_action_at:
        lead["first_action_at"] = first_action_at
    await db().leads.insert_one(lead)


# ───────────────────────── plan and role checks ─────────────────────────
async def test_free_owner_is_locked_out_of_every_paid_tool(client):
    c = await new_owner("9831000001")
    await go_live(c)
    today = membership.ist_today()
    checks = [
        ("get", "/api/goals", None, "goals"),
        ("post", "/api/goals", {"title": "More leads", "metric": "leads", "target": 10, "start": str(today), "end": str(today)}, "goals"),
        ("get", "/api/week", None, "week"),
        ("get", "/api/magic", None, "magic_number"),
        ("get", "/api/gaps", None, "gaps_scan"),
        ("get", f"/api/calendar/{today:%Y-%m}", None, "content_calendar"),
        ("get", "/api/insights/funnel?days=30", None, "funnel"),
        ("get", "/api/insights/dashboard", None, "funnel"),
        ("get", "/api/tools/content/history", None, "tool_content"),
        ("get", "/api/site/domain", None, "custom_domain"),
        ("post", "/api/site/domain", {"domain": "www.mybiz.in"}, "custom_domain"),
    ]
    for method, path, body, key in checks:
        r = await getattr(c, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (path, r.text)
        assert r.json()["detail"]["code"] == "locked" and r.json()["detail"]["feature"] == key, path
    assert await runs_used(c) == 2  # brand + site only


async def test_roles_staff_cannot_plan_managers_can(client):
    owner, oid = await member("9831000002", plan="growth")  # team logins need Growth Mentorship
    await owner.put("/api/business", json=PROFILE)
    staff, _ = await teammate("9831000003", oid, "staff")
    manager, _ = await teammate("9831000004", oid, "manager")
    today = membership.ist_today()
    goal = {"title": "Revenue this quarter", "kind": "financial", "metric": "custom", "target": 500000, "unit": "₹", "start": str(today),
            "end": str(today + timedelta(days=30))}

    assert (await staff.get("/api/goals")).status_code == 403
    assert (await staff.get("/api/insights/funnel")).status_code == 403
    assert (await staff.get("/api/week")).status_code == 403
    assert (await manager.post("/api/goals", json=goal)).status_code == 200
    listed = (await owner.get("/api/goals")).json()
    assert len(listed) == 1 and listed[0]["kind_label"] == "Financial"
    assert (await manager.get("/api/insights/dashboard")).status_code == 200
    assert (await manager.get("/api/gaps")).status_code == 403   # the owner's own scan
    assert (await owner.get("/api/gaps")).status_code == 200
    assert (await staff.post("/api/tools/content/run", json={"inputs": {}})).status_code == 200   # staff use the writing tools
    assert (await manager.post("/api/site/domain", json={"domain": "www.mybiz.in"})).status_code == 403


# ───────────────────────── 1. goals ─────────────────────────
async def test_goals_auto_metrics_progress_and_status(client):
    c, uid = await member("9831000010", "program")
    site = await go_live(c)
    today = membership.ist_today()
    window = {"start": str(today - timedelta(days=9)), "end": str(today + timedelta(days=10))}  # 20 days, 10 gone

    for name in ("Neha Joshi", "Ravi Shah", "Amit Rao"):
        r = await client.post(f"/s/{site['slug']}/inquiry", json={"name": name, "phone": "9833000000"})
        assert r.status_code == 200
    await add_lead(uid, now() - timedelta(days=60))  # outside the window
    leads = (await c.get("/api/leads")).json()
    await c.patch(f"/api/leads/{leads[0]['id']}", json={"status": "won"})
    await c.get(f"/s/{site['slug']}")
    await c.get(f"/s/{site['slug']}")

    mk = lambda **kw: c.post("/api/goals", json={**window, **kw})  # noqa: E731
    g_leads = (await mk(title="Inquiries this month", metric="leads", target=10, unit="inquiries")).json()
    g_won = (await mk(title="Customers won", metric="won", target=1, unit="customers")).json()
    g_views = (await mk(title="Website visits", metric="site_views", target=4, unit="views")).json()
    g_rev = (await mk(title="Revenue", metric="custom", target=500000, unit="₹")).json()
    g_learn = (await mk(title="Learn GST filing", kind="learning", metric="custom", target=4, unit="sessions")).json()
    assert g_learn["kind"] == "learning" and g_learn["kind_label"] == "Learning" and g_rev["kind"] == "financial"

    assert g_leads["current"] == 3 and g_leads["pct"] == 30.0 and g_leads["expected_pct"] == 50.0 and g_leads["status"] == "behind"
    assert g_leads["days_left"] == 10 and g_leads["metric_label"] == "New inquiries"
    assert g_won["current"] == 1 and g_won["status"] == "done"
    assert g_views["current"] == 2 and g_views["pct"] == 50.0 and g_views["status"] == "on_track"
    assert g_rev["current"] == 0 and g_rev["status"] == "behind"

    r = await c.post(f"/api/goals/{g_rev['id']}/checkins", json={"value": 200000, "note": "Two kitchens"})
    r = await c.post(f"/api/goals/{g_rev['id']}/checkins", json={"value": 260000, "note": ""})
    g = r.json()
    assert g["current"] == 260000 and g["pct"] == 52.0 and g["status"] == "on_track" and len(g["checkins"]) == 2
    assert (await c.post(f"/api/goals/{g_leads['id']}/checkins", json={"value": 5})).status_code == 400  # counts itself

    edited = (await c.patch(f"/api/goals/{g_leads['id']}", json={"target": 3, "title": "Three inquiries"})).json()
    assert edited["status"] == "done" and edited["title"] == "Three inquiries"
    bad = await c.patch(f"/api/goals/{g_leads['id']}", json={"end": str(today - timedelta(days=30))})
    assert bad.status_code == 400 and "end date" in bad.json()["detail"]

    listed = (await c.get("/api/goals")).json()
    assert len(listed) == 5 and {x["id"] for x in listed} == {g_leads["id"], g_won["id"], g_views["id"], g_rev["id"], g_learn["id"]}
    assert (await c.delete(f"/api/goals/{g_won['id']}")).json() == {"ok": True}
    assert len((await c.get("/api/goals")).json()) == 4

    other, _ = await member("9831000011", "program")
    assert (await other.post(f"/api/goals/{g_rev['id']}/checkins", json={"value": 1})).status_code == 404  # another hub's goal


async def test_goal_coach_uses_one_run_and_gives_three_actions(client):
    c, _ = await member("9831000012", "program")
    await c.put("/api/business", json=PROFILE)
    today = membership.ist_today()
    g = (await c.post("/api/goals", json={"title": "Revenue", "metric": "custom", "target": 300000, "unit": "₹",
                                         "start": str(today), "end": str(today + timedelta(days=27))})).json()
    before = await runs_used(c)
    r = await c.post(f"/api/goals/{g['id']}/coach")
    assert r.status_code == 200, r.text
    coach = r.json()["coach"]
    assert len(coach["actions"]) == 3 and all(a["action"] for a in coach["actions"])
    assert coach["actions"][0]["why"] == "You need ₹3,00,000 more — about ₹75,000 a week for the next 4 weeks."  # built from the goal's own numbers, Indian format
    assert await runs_used(c) == before + 1
    out = (await c.get("/api/outputs?kind=goal_coach")).json()
    assert len(out) == 1 and out[0]["content"]["answer"].startswith("1. ")
    assert (await c.get("/api/goals")).json()[0]["coach"]["actions"] == coach["actions"]


# ───────────────────────── 3. website views, funnel and dashboard ─────────────────────────
async def test_record_view_counts_daily_views_but_not_previews(client):
    c, uid = await member("9831000030")
    site = await go_live(c)
    for _ in range(3):
        assert (await client.get(f"/s/{site['slug']}")).status_code == 200
    await c.get(f"/s/{site['slug']}?preview=1")
    day = now().astimezone(IST).strftime("%Y-%m-%d")
    doc = await db().site_views.find_one({"_id": f"{site['id']}:{day}"})
    assert doc["n"] == 3 and doc["ws"] == uid and doc["day"] == day and doc["site_id"] == site["id"]
    assert (await db().sites.find_one({"_id": site["id"]}))["views"] == 3
    await membership.record_view({"_id": site["id"], "owner_id": uid})
    assert (await db().site_views.find_one({"_id": f"{site['id']}:{day}"}))["n"] == 4


async def test_funnel_counts_each_step_with_conversion(client):
    c, uid = await member("9831000031")
    site = await go_live(c)
    for _ in range(10):
        await client.get(f"/s/{site['slug']}")
    t = now()
    await add_lead(uid, t - timedelta(hours=1))                                                   # waiting
    await add_lead(uid, t - timedelta(hours=2), "contacted", t - timedelta(hours=1))
    await add_lead(uid, t - timedelta(days=2), "won", t - timedelta(days=2))
    await add_lead(uid, t - timedelta(days=3), "lost", t - timedelta(days=3))
    await add_lead(uid, t - timedelta(days=20), "won", t - timedelta(days=20))                   # only in 30 days
    await add_lead(uid, t - timedelta(days=200), "won")                                           # outside every window

    f7 = (await c.get("/api/insights/funnel?days=7")).json()
    assert [s["n"] for s in f7["steps"]] == [10, 4, 3, 1]
    assert [s["rate"] for s in f7["steps"]] == [None, 40.0, 75.0, 33.3]
    assert f7["lost"] == 1 and f7["waiting"] == 1 and f7["open"] == 1 and f7["overall"] == 25.0 and f7["days"] == 7
    f30 = (await c.get("/api/insights/funnel?days=30")).json()
    assert [s["n"] for s in f30["steps"]] == [10, 5, 4, 2]


async def test_dashboard_weeks_and_month_comparison(client, monkeypatch):
    c, uid = await member("9831000032")
    fixed = datetime(2026, 10, 7, 12, 0, tzinfo=IST)  # a Wednesday, India time
    monkeypatch.setattr(membership, "now", lambda: fixed)
    utc = lambda d: d.astimezone(IST)  # noqa: E731
    # this week (Mon 5 Oct onwards)
    await add_lead(uid, utc(fixed - timedelta(hours=5)), "won", utc(fixed - timedelta(hours=3)))       # 2 h
    await add_lead(uid, utc(fixed - timedelta(hours=8)), "contacted", utc(fixed - timedelta(hours=4)))  # 4 h
    await add_lead(uid, utc(fixed - timedelta(hours=9)), "contacted", utc(fixed - timedelta(hours=3)))  # 6 h
    await add_lead(uid, utc(fixed - timedelta(hours=1)))
    # last week, and September
    await add_lead(uid, datetime(2026, 9, 30, 10, 0, tzinfo=IST), "won", datetime(2026, 9, 30, 20, 0, tzinfo=IST))  # 10 h
    await add_lead(uid, datetime(2026, 9, 2, 10, 0, tzinfo=IST))
    await add_lead(uid, datetime(2026, 6, 1, 10, 0, tzinfo=IST))  # before the 12 weeks
    for day, n in (("2026-10-06", 7), ("2026-09-29", 5), ("2026-09-03", 2)):
        await db().site_views.insert_one({"_id": f"s:{day}", "site_id": "s", "ws": uid, "day": day, "n": n})
    for at in (fixed - timedelta(hours=2), datetime(2026, 9, 29, 9, 0, tzinfo=IST)):
        await db().runs.insert_one({"_id": new_id(), "user_id": uid, "kind": "posts", "status": "done", "created_at": at})
    await db().runs.insert_one({"_id": new_id(), "user_id": uid, "kind": "posts", "status": "refunded", "created_at": fixed})

    d = (await c.get("/api/insights/dashboard")).json()
    weeks = d["weeks"]
    assert len(weeks) == 12 and weeks[-1]["start"] == "2026-10-05" and weeks[0]["start"] == "2026-07-20"
    assert weeks[-1] == {"start": "2026-10-05", "leads": 4, "won": 1, "views": 7, "runs": 1, "response_hours": 4.0, "conversion": 25.0}
    assert weeks[-2]["start"] == "2026-09-28" and weeks[-2]["leads"] == 1 and weeks[-2]["response_hours"] == 10.0 and weeks[-2]["views"] == 5
    assert sum(w["leads"] for w in weeks) == 6 and sum(w["runs"] for w in weeks) == 2
    this, last = d["months"]["this"], d["months"]["last"]
    assert this["label"] == "October" and this["so_far"] and this["leads"] == 4 and this["views"] == 7 and this["runs"] == 1
    assert last["label"] == "September" and last["leads"] == 2 and last["won"] == 1 and last["views"] == 7 and last["runs"] == 1
    assert last["response_hours"] == 10.0 and last["conversion"] == 50.0


# ───────────────────────── 5. own domain ─────────────────────────
async def test_domain_validation_and_uniqueness(client, direct):
    c, _ = await member("9831000050", "growth")
    assert (await c.post("/api/site/domain", json={"domain": "www.mybiz.in"})).status_code == 400  # no website yet
    await go_live(c)
    bad = ["mybiz", "www.mybiz.in/contact", "www.mybiz.in:8080", "192.168.1.10", "my_biz.in", "-mybiz.in", "hub.example.in",
           "shop.example.in", "example.in", "localhost", "a" * 64 + ".in", "user@mybiz.in", "www.my biz.in"]
    for name in bad:
        r = await c.post("/api/site/domain", json={"domain": name})
        assert r.status_code == 400, name
    r = await c.post("/api/site/domain", json={"domain": "  HTTPS://WWW.MyBiz.in/ "})
    assert r.status_code == 200, r.text
    d = r.json()["domain"]
    assert d["name"] == "www.mybiz.in" and d["status"] == "pending" and d["url"] == "https://www.mybiz.in"
    assert d["records"][0] == {"type": "CNAME", "name": "www", "host": "www.mybiz.in", "value": "hub.example.in"}
    assert (await c.get("/api/site/domain")).json()["domain"]["name"] == "www.mybiz.in"
    apex = (await c.post("/api/site/domain", json={"domain": "shop.mybiz.co.in"})).json()["domain"]
    assert apex["records"][0]["name"] == "shop" and not apex["apex"]
    apex = (await c.post("/api/site/domain", json={"domain": "mybiz.in"})).json()["domain"]
    assert apex["records"][0]["name"] == "@" and apex["apex"]

    other, _ = await member("9831000051", "growth")
    await go_live(other, {**PROFILE, "name": "Kapoor Dental Clinic"})
    r = await other.post("/api/site/domain", json={"domain": "mybiz.in"})
    assert r.status_code == 409
    assert (await c.delete("/api/site/domain")).json() == {"ok": True}
    assert (await c.get("/api/site/domain")).json()["domain"] is None
    assert (await other.post("/api/site/domain", json={"domain": "mybiz.in"})).status_code == 200  # free again


@pytest.fixture
def direct():
    """Direct mode: every owner points a CNAME at CUSTOM_DOMAIN_TARGET and proves the domain with the hub's TXT record."""
    old = settings.custom_domain_target
    object.__setattr__(settings, "custom_domain_target", "hub.example.in")
    yield
    object.__setattr__(settings, "custom_domain_target", old)


def proof_of(d: dict) -> dict:
    return next(r for r in d["records"] if r["type"] == "TXT")


async def test_dns_check_cname_a_records_and_mismatch(client, monkeypatch, direct):
    c, _ = await member("9831000052", "growth")
    await go_live(c)
    records: dict = {}

    async def fake_resolve(name, rdtype):
        if records.get("down"):
            raise domains.DnsUnavailable("timeout")
        return records.get((name, rdtype), [])
    monkeypatch.setattr(domains, "resolve", fake_resolve)

    assert (await c.post("/api/site/domain/check")).status_code == 400  # nothing added yet
    added = (await c.post("/api/site/domain", json={"domain": "www.mybiz.in"})).json()["domain"]
    proof = proof_of(added)
    assert proof["type"] == "TXT" and proof["name"] == "_actionhub.www" and proof["host"] == "_actionhub.www.mybiz.in"
    assert proof["value"].startswith("actionhub-verify=") and len(proof["value"]) > 30

    records[("www.mybiz.in", "CNAME")] = ["hub.example.in"]  # pointing the domain is not enough: the TXT proof comes first
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "pending" and "TXT record" in d["note"] and d["checked_at"]
    records[("_actionhub.www.mybiz.in", "TXT")] = ['"actionhub-verify=someone-elses-token"']
    assert (await c.post("/api/site/domain/check")).json()["domain"]["status"] == "pending"

    records[("_actionhub.www.mybiz.in", "TXT")] = [f'"{proof["value"]}"']
    records[("www.mybiz.in", "CNAME")] = []
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "pending" and "can't see a record" in d["note"]

    records[("www.mybiz.in", "CNAME")] = ["shops.otherhost.com"]
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "pending" and "shops.otherhost.com" in d["note"] and "hub.example.in" in d["note"]

    records[("www.mybiz.in", "CNAME")] = ["hub.example.in"]
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "verified" and "https" in d["note"]

    records["down"] = True
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "verified" and "couldn't check" in d["note"]  # a DNS hiccup never undoes a verified domain
    records.pop("down")

    records[("www.mybiz.in", "CNAME")] = []
    records[("www.mybiz.in", "A")] = ["9.9.9.9"]
    records[("hub.example.in", "A")] = ["1.2.3.4"]
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "pending" and "another server" in d["note"]  # moved away: back to pending

    root = (await c.post("/api/site/domain", json={"domain": "mybiz.in"})).json()["domain"]
    assert proof_of(root)["name"] == "_actionhub" and proof_of(root)["value"] != proof["value"]  # a new claim gets a new token
    records[("mybiz.in", "A")] = ["1.2.3.4"]
    assert (await c.post("/api/site/domain/check")).json()["domain"]["status"] == "pending"
    records[("_actionhub.mybiz.in", "TXT")] = [proof_of(root)["value"]]
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "verified"  # root domain whose A records match the hub's


async def test_domain_claims_cannot_be_squatted_and_removal_is_released(client, monkeypatch, direct):
    a, _ = await member("9831000054", "growth")
    await go_live(a)
    b, _ = await member("9831000055", "growth")
    await go_live(b)
    first = (await a.post("/api/site/domain", json={"domain": "www.sharedname.in"})).json()["domain"]
    assert (await b.post("/api/site/domain", json={"domain": "www.sharedname.in"})).status_code == 409
    # an unproven claim older than a week expires, so nobody can park someone else's domain for ever
    await db().sites.update_one({"domain.name": "www.sharedname.in"}, {"$set": {"domain.added_at": now() - timedelta(days=8)}})
    taken = (await b.post("/api/site/domain", json={"domain": "www.sharedname.in"})).json()["domain"]
    assert taken["name"] == "www.sharedname.in" and proof_of(taken)["value"] != proof_of(first)["value"]
    assert (await a.get("/api/site/domain")).json()["domain"] is None

    async def fake_resolve(name, rdtype):
        if (name, rdtype) == ("_actionhub.www.sharedname.in", "TXT"):
            return [proof_of(taken)["value"]]
        return ["hub.example.in"] if (name, rdtype) == ("www.sharedname.in", "CNAME") else []
    monkeypatch.setattr(domains, "resolve", fake_resolve)
    assert (await b.post("/api/site/domain/check")).json()["domain"]["status"] == "verified"
    assert (await a.post("/api/site/domain", json={"domain": "www.sharedname.in"})).status_code == 409  # proven: never expires

    admin = await new_owner("9999900000")
    await b.delete("/api/site/domain")
    rows = (await admin.get("/api/admin/domains")).json()
    released = [r for r in rows if r["status"] == "released"]
    assert len(released) == 1 and released[0]["name"] == "www.sharedname.in" and "Railway" in released[0]["note"]
    assert rows[0]["status"] == "released"  # listed first so the admin removes it from Railway
    assert (await admin.delete("/api/admin/domains/released/www.sharedname.in")).status_code == 200
    assert not [r for r in (await admin.get("/api/admin/domains")).json() if r["status"] == "released"]


async def test_own_domain_serves_the_site_and_admin_marks_it_live(client, monkeypatch, direct):
    c, uid = await member("9831000053", "growth")
    site = await go_live(c)
    added = (await c.post("/api/site/domain", json={"domain": "www.ganeshinteriors.in"})).json()["domain"]
    host = "https://www.ganeshinteriors.in"

    assert (await client.get(f"{host}/")).status_code == 404  # pending: not served yet

    async def fake_resolve(name, rdtype):
        if (name, rdtype) == ("_actionhub.www.ganeshinteriors.in", "TXT"):
            return [proof_of(added)["value"]]
        return ["hub.example.in"] if (name, rdtype) == ("www.ganeshinteriors.in", "CNAME") else []
    monkeypatch.setattr(domains, "resolve", fake_resolve)
    assert (await c.post("/api/site/domain/check")).json()["domain"]["status"] == "verified"
    assert (await client.get(f"{host}/")).status_code == 404  # verified is not enough: served only once the admin marks it live
    assert (await client.post(f"{host}/s/{site['slug']}/inquiry", data={"name": "Neha Joshi", "phone": "98330 00000"})).status_code == 404

    admin = await new_owner("9999900000")
    assert (await c.get("/api/admin/domains")).status_code == 403
    rows = (await admin.get("/api/admin/domains")).json()
    assert len(rows) == 1 and rows[0]["name"] == "www.ganeshinteriors.in" and rows[0]["status"] == "verified"
    assert rows[0]["business"] == "Shree Ganesh Interiors" and rows[0]["phone"] == "+919831000053"
    r = await admin.post(f"/api/admin/domains/{site['id']}/live")
    assert r.status_code == 200 and r.json()["status"] == "live"
    me = (await c.get("/api/me")).json()
    assert any("https://www.ganeshinteriors.in" in n["text"] for n in me["notices"])

    page = await client.get(f"{host}/")
    assert page.status_code == 200 and "Shree Ganesh Interiors" in page.text and "/inquiry" in page.text
    day = now().astimezone(IST).strftime("%Y-%m-%d")
    assert (await db().site_views.find_one({"_id": f"{site['id']}:{day}"}))["n"] == 1  # counted like any visit
    assert (await client.get(f"{host}/about")).status_code == 404
    assert (await client.get(f"{host}/api/me")).status_code == 404  # the hub is never reachable on an owner's domain
    assert (await client.get(f"{host}/s/someone-elses-site")).status_code == 404  # nor anyone else's pages
    form = await client.post(f"{host}/inquiry", data={"name": "Neha Joshi", "phone": "98330 00000"})
    assert form.status_code == 303 and form.headers["location"] == "/?sent=1#contact"  # the website's own form, on its own address
    assert len((await c.get("/api/leads")).json()) == 1
    unknown = await client.get("https://someone-else.example.org/")
    assert "Shree Ganesh Interiors" not in unknown.text  # hosts nobody claimed get the hub as usual

    assert (await admin.post(f"/api/admin/domains/{site['id']}/live", json={"live": False})).json()["status"] == "verified"
    assert (await client.get(f"{host}/")).status_code == 404
    assert (await admin.post("/api/admin/domains/nope/live")).status_code == 404
    await admin.post(f"/api/admin/domains/{site['id']}/live")

    await c.post("/api/site/unpublish")
    assert (await client.get(f"{host}/")).status_code == 404  # taken offline
    await c.post("/api/site/publish")
    await admin.patch(f"/api/admin/users/{uid}", json={"plan": "free"})
    r = await client.get(f"{host}/")
    assert r.status_code == 302 and r.headers["location"] == f"https://hub.example.in/s/{site['slug']}"  # plan lapsed


async def test_hosted_mode_admin_pastes_the_hosting_records_for_the_owner(client, monkeypatch):
    """The default on Railway: each domain is added in Railway, which shows its own CNAME target and TXT record."""
    c, uid = await member("9831000056", "growth")
    site = await go_live(c)
    d = (await c.post("/api/site/domain", json={"domain": "www.kapoordental.in"})).json()["domain"]
    assert d["mode"] == "hosted" and d["status"] == "setup" and d["records"] == []
    looked_up = []

    async def fake_resolve(name, rdtype):
        looked_up.append((name, rdtype))
        return records.get((name, rdtype), [])
    records: dict = {}
    monkeypatch.setattr(domains, "resolve", fake_resolve)
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "setup" and "preparing" in d["note"] and not looked_up  # nothing to check until the records exist

    admin = await new_owner("9999900000")
    rows = (await admin.get("/api/admin/domains")).json()
    assert rows[0]["name"] == "www.kapoordental.in" and rows[0]["status"] == "setup"
    assert (await c.put(f"/api/admin/domains/{site['id']}/records", json={"cname": "x1.up.railway.app"})).status_code == 403
    bad = await admin.put(f"/api/admin/domains/{site['id']}/records", json={"cname": "not a host"})
    assert bad.status_code == 400
    half = await admin.put(f"/api/admin/domains/{site['id']}/records", json={"cname": "g05ns7.up.railway.app", "txt_name": "_railway-verify.www"})
    assert half.status_code == 400
    r = await admin.put(f"/api/admin/domains/{site['id']}/records",
                        json={"cname": "G05NS7.up.railway.app.", "txt_name": "_railway-verify.www", "txt_value": '"railway-verify=abc123"'})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    d = (await c.get("/api/site/domain")).json()["domain"]
    assert d["records"] == [
        {"type": "CNAME", "name": "www", "host": "www.kapoordental.in", "value": "g05ns7.up.railway.app"},
        {"type": "TXT", "name": "_railway-verify.www", "host": "_railway-verify.www.kapoordental.in", "value": "railway-verify=abc123"}]
    assert any("www.kapoordental.in is ready to connect" in n["text"] for n in (await c.get("/api/me")).json()["notices"])

    records[("www.kapoordental.in", "CNAME")] = ["g05ns7.up.railway.app"]
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "pending" and "TXT record" in d["note"]
    records[("_railway-verify.www.kapoordental.in", "TXT")] = ['"railway-verify=abc123"']
    d = (await c.post("/api/site/domain/check")).json()["domain"]
    assert d["status"] == "verified"
    assert (await client.get("https://www.kapoordental.in/")).status_code == 404  # not until marked live
    await admin.post(f"/api/admin/domains/{site['id']}/live")
    assert (await client.get("https://www.kapoordental.in/")).status_code == 200


@pytest.mark.parametrize("raw,clean", [("WWW.Example.COM", "www.example.com"), ("http://shop.mybiz.in", "shop.mybiz.in"),
                                       ("mybiz.in.", "mybiz.in"), ("बिज़.भारत", "xn--81b5axck.xn--h2brj9c")])
async def test_clean_domain_normalises(raw, clean):
    assert domains.clean_domain(raw) == clean

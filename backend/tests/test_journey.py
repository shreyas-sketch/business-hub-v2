from app.db import db
from tests.conftest import PROFILE, go_live, login, new_owner


async def test_login_wrong_code_then_right(client):
    r = await client.post("/api/auth/otp", json={"phone": "98200 11111"})
    assert r.json()["via"] == "dev-whatsapp" and len(r.json()["dev_code"]) == 6
    bad = await client.post("/api/auth/verify", json={"phone": "+919820011111", "code": "000000" if r.json()["dev_code"] != "000000" else "111111"})
    assert bad.status_code == 400
    ok = await client.post("/api/auth/verify", json={"phone": "9820011111", "code": r.json()["dev_code"]})
    assert ok.json() == {"ok": True, "new": True}
    me = (await client.get("/api/me")).json()
    assert me["user"]["phone"] == "+919820011111" and me["user"]["effective_plan"] == "free"
    assert me["runs"] == {"allowance": 10, "used": 0, "bonus": 0, "left": 10, "month": me["runs"]["month"]}
    assert me["features"]["website"] and not me["features"]["badge_off"]
    await client.post("/api/auth/logout")
    assert (await client.get("/api/me")).status_code == 401


async def test_invalid_phone_rejected(client):
    assert (await client.post("/api/auth/otp", json={"phone": "12345"})).status_code == 400
    assert (await client.post("/api/auth/otp", json={"phone": "+91 5820011111"})).status_code == 400


async def test_free_owner_goes_live_and_gets_a_lead(client):
    await login(client, "9820022222")
    site = await go_live(client)
    assert site["status"] == "live" and site["badge"] is True and site["slug"] == "shree-ganesh-interiors"
    page = await client.get(f"/s/{site['slug']}")
    assert page.status_code == 200
    html = page.text
    assert "Shree Ganesh Interiors" in html and "₹1,85,000 onwards" in html
    assert "Built free with" in html and "src=badge" in html
    assert f'href="/s/{site['slug']}/wa"' in html and "Chat on WhatsApp" in html
    tap = await client.get(f"/s/{site['slug']}/wa", follow_redirects=False)   # counted, then the owner's own WhatsApp opens
    assert tap.status_code == 302 and tap.headers["location"].startswith("https://wa.me/919820000000?text=Hi%20Shree%20Ganesh%20Interiors")

    form = await client.post(f"/s/{site['slug']}/inquiry", data={"name": "Neha Joshi", "phone": "98330 00000", "message": "Kitchen for 2BHK"})
    assert form.status_code == 303 and "sent=1" in form.headers["location"]
    leads = (await client.get("/api/leads")).json()
    assert len(leads) == 1 and leads[0]["name"] == "Neha Joshi" and leads[0]["alert"]["sent"]
    assert "instant_reply" not in leads[0]  # replies from the owner's own number are Growth Mentorship
    alert = await db().outbox.find_one({"kind": "lead_alert"})
    assert alert["to"] == "+919820022222" and alert["params"][1] == "Neha Joshi"

    me = (await client.get("/api/me")).json()
    assert me["progress"] == {"profile": True, "brand": True, "site_live": True, "first_lead": True}
    assert me["runs"]["used"] == 2  # brand + site

    draft = (await client.post(f"/api/leads/{leads[0]['id']}/reply")).json()
    assert "Neha" in draft["reply"] and draft["whatsapp_link"].startswith("https://wa.me/919833000000?text=")
    outputs = (await client.get("/api/outputs")).json()
    assert {o["kind"] for o in outputs} == {"brand", "site", "reply"}


async def test_publish_needs_whatsapp(client):
    await login(client, "9820033333")
    await client.put("/api/business", json={**PROFILE, "whatsapp": ""})
    await client.post("/api/site/generate")
    r = await client.post("/api/site/publish")
    assert r.status_code == 400 and "WhatsApp" in r.json()["detail"]


async def test_studio_jobs(client):
    await login(client, "9820044444")
    await client.put("/api/business", json=PROFILE)
    posts = (await client.post("/api/studio/posts", json={"focus": "Diwali kitchen offers"})).json()["posts"]
    assert len(posts) == 7 and posts[0]["day"] == "Monday"
    assert "Neha" in (await client.post("/api/studio/reply", json={"message": "Price for kitchen?", "customer_name": "Neha"})).json()["reply"]
    assert "Structure" in (await client.post("/api/studio/ask", json={"question": "How do I get more referrals?"})).json()["answer"]
    assert len((await client.get("/api/outputs?kind=posts")).json()) == 1


async def test_draft_site_is_private_and_preview_is_owner_only(client):
    await login(client, "9820055555")
    await client.put("/api/business", json=PROFILE)
    site = (await client.post("/api/site/generate")).json()
    assert (await client.get(f"/s/{site['slug']}")).status_code == 404
    assert (await client.get(f"/s/{site['slug']}?preview=1")).status_code == 200
    other = await new_owner("9820055556")
    assert (await other.get(f"/s/{site['slug']}?preview=1")).status_code == 404
    assert (await other.post(f"/s/{site['slug']}/inquiry", data={"name": "X Y", "phone": "9833000000"})).status_code == 404

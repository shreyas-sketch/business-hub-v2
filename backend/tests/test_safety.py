from app.db import db
from tests.conftest import PROFILE, go_live, login, new_owner


async def test_site_content_is_escaped(client):
    await login(client, "9823011111")
    site = await go_live(client)
    content = site["content"] | {"headline": "<script>alert(1)</script> Best kitchens", "about": "<img src=x onerror=alert(1)>"}
    assert (await client.put("/api/site", json={"content": content, "accent": site["accent"]})).status_code == 200
    html = (await client.get(f"/s/{site['slug']}")).text
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html and "<img src=x" not in html


async def test_inquiry_spam_controls(client):
    await login(client, "9823022222")
    site = await go_live(client)
    await client.post(f"/s/{site['slug']}/inquiry", data={"name": "Bot", "phone": "9833000000", "website": "http://spam"})
    assert await db().leads.count_documents({}) == 0
    assert (await client.post(f"/s/{site['slug']}/inquiry", json={"name": "A", "phone": "123"})).status_code == 400
    codes = [(await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Real Person", "phone": "9833000000"})).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


async def test_owners_cannot_touch_each_others_data(client):
    a = await new_owner("9823033333")
    site = await go_live(a)
    await client.post(f"/s/{site['slug']}/inquiry", json={"name": "Neha Joshi", "phone": "9833000000"})
    lead_id = (await a.get("/api/leads")).json()[0]["id"]
    b = await new_owner("9823044444")
    assert (await b.get("/api/leads")).json() == []
    assert (await b.patch(f"/api/leads/{lead_id}", json={"status": "won"})).status_code == 404
    assert (await b.post(f"/api/leads/{lead_id}/reply")).status_code == 404
    out = (await a.get("/api/outputs")).json()[0]["id"]
    await b.delete(f"/api/outputs/{out}")
    assert len((await a.get("/api/outputs")).json()) == 2


async def test_web_address_rules(client):
    a = await new_owner("9823055555")
    site = await go_live(a)
    b = await new_owner("9823066666")
    other = await go_live(b, {**PROFILE, "name": "Arora Traders"})
    body = {"content": other["content"], "accent": other["accent"]}
    assert (await b.put("/api/site", json={**body, "slug": site["slug"]})).status_code == 409
    assert (await b.put("/api/site", json={**body, "slug": "admin"})).status_code == 400
    assert (await b.put("/api/site", json={**body, "slug": "Bad Slug!"})).status_code == 400
    assert (await b.put("/api/site", json={**body, "slug": "arora-traders-thane"})).json()["slug"] == "arora-traders-thane"
    assert (await client.get("/s/arora-traders-thane")).status_code == 200


async def test_same_business_name_gets_unique_address(client):
    a = await new_owner("9823077777")
    b = await new_owner("9823088888")
    assert (await go_live(a))["slug"] == "shree-ganesh-interiors"
    assert (await go_live(b))["slug"] == "shree-ganesh-interiors-2"


async def test_otp_attempt_and_rate_limits(client):
    r = await client.post("/api/auth/otp", json={"phone": "9823099999"})
    real = r.json()["dev_code"]
    wrong = "123456" if real != "123456" else "654321"
    for _ in range(5):
        await client.post("/api/auth/verify", json={"phone": "9823099999", "code": wrong})
    assert (await client.post("/api/auth/verify", json={"phone": "9823099999", "code": real})).status_code == 429
    for _ in range(4):
        await client.post("/api/auth/otp", json={"phone": "9823099999"})
    assert (await client.post("/api/auth/otp", json={"phone": "9823099999"})).status_code == 429

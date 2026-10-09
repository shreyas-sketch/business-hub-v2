"""Recordings: the admin builds programs → sections → recordings; owners watch what their plan (or the admin) unlocks."""
import pytest

from app import video
from app.db import db
from tests.conftest import PROFILE, new_owner

ADMIN = "9999900000"


async def owner_on(phone: str, plan: str | None, admin=None):
    c = await new_owner(phone, name="Harsh Mehta")
    assert (await c.put("/api/business", json=PROFILE)).status_code == 200
    uid = (await c.get("/api/me")).json()["user"]["id"]
    admin = admin or await new_owner(ADMIN)
    if plan:
        assert (await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})).status_code == 200
    return c, uid, admin


async def build(admin, title="Action Program", tier="program", published=True, team=False):
    p = (await admin.post("/api/admin/programs", json={"title": title, "description": "Weekly live calls", "tier": tier,
                                                        "published": published, "team": team})).json()
    s1 = (await admin.post(f"/api/admin/programs/{p['id']}/sections", json={"title": "Week 1 · Kickstart"})).json()
    s2 = (await admin.post(f"/api/admin/programs/{p['id']}/sections", json={"title": "Live calls"})).json()
    r1 = (await admin.post("/api/admin/recordings", json={"section_id": s1["id"], "title": "Kickstart call", "link": "https://vimeo.com/123456789/abcdef1234",
                                                          "recorded_on": "2026-09-11", "duration_min": 92, "notes": "Homework: fill the Business Brain.\nSlides: https://example.com/slides",
                                                          "resources": [{"label": "Slides", "url": "example.com/slides.pdf"}]})).json()
    r2 = (await admin.post("/api/admin/recordings", json={"section_id": s2["id"], "title": "Q&A call 1", "link": "https://youtu.be/aqz-KE-bpKQ"})).json()
    return p, s1, s2, r1, r2


@pytest.mark.parametrize("raw,provider,kind,embed", [
    ("https://vimeo.com/76979871", "vimeo", "iframe", "https://player.vimeo.com/video/76979871?title=0&byline=0&portrait=0&dnt=1"),
    ("vimeo.com/123456789/abcdef1234", "vimeo", "iframe", "https://player.vimeo.com/video/123456789?h=abcdef1234&title=0&byline=0&portrait=0&dnt=1"),
    ("https://player.vimeo.com/video/123456789?h=9f8e7d6c5b&badge=0", "vimeo", "iframe", "https://player.vimeo.com/video/123456789?h=9f8e7d6c5b&title=0&byline=0&portrait=0&dnt=1"),
    ("https://vimeo.com/event/1234567", "vimeo", "iframe", "https://vimeo.com/event/1234567/embed"),
    ("https://www.youtube.com/watch?v=aqz-KE-bpKQ&t=10s", "youtube", "iframe", "https://www.youtube-nocookie.com/embed/aqz-KE-bpKQ?rel=0&modestbranding=1"),
    ("https://youtu.be/aqz-KE-bpKQ", "youtube", "iframe", "https://www.youtube-nocookie.com/embed/aqz-KE-bpKQ?rel=0&modestbranding=1"),
    ("https://www.youtube.com/live/aqz-KE-bpKQ", "youtube", "iframe", "https://www.youtube-nocookie.com/embed/aqz-KE-bpKQ?rel=0&modestbranding=1"),
    ("https://www.loom.com/share/0123456789abcdef0123456789abcdef", "loom", "iframe", "https://www.loom.com/embed/0123456789abcdef0123456789abcdef"),
    ("https://acme.wistia.com/medias/abcde12345", "wistia", "iframe", "https://fast.wistia.net/embed/iframe/abcde12345"),
    ("https://iframe.mediadelivery.net/play/12345/0a1b2c3d-1111-2222-3333-444455556666", "bunny", "iframe",
     "https://iframe.mediadelivery.net/embed/12345/0a1b2c3d-1111-2222-3333-444455556666?autoplay=false&preload=true"),
    ("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing", "gdrive", "iframe", "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/preview"),
    ("https://assets.cdn.filesafe.space/loc1/media/Call 1.mp4", "file", "video", "https://assets.cdn.filesafe.space/loc1/media/Call%201.mp4"),
    ("http://storage.googleapis.com/msgsndr/abc/video.MP4?token=x", "file", "video", "https://storage.googleapis.com/msgsndr/abc/video.MP4?token=x"),
    ("https://app.gohighlevel.com/courses/abc", "link", "link", "https://app.gohighlevel.com/courses/abc"),
    ("https://youtube.com/watch?v=short", "link", "link", "https://youtube.com/watch?v=short"),  # not a real video id: opens as a link
])
def test_video_links(raw, provider, kind, embed):
    v = video.parse(raw)
    assert (v["provider"], v["kind"], v["embed"]) == (provider, kind, embed)


@pytest.mark.parametrize("raw", ["", "javascript:alert(1)", "https://user:pw@evil.com/a.mp4", "ftp://x.com/a.mp4", "notalink", "https://x/" + "a" * 1000])
def test_bad_video_links(raw):
    with pytest.raises(video.BadLink):
        video.parse(raw)


async def test_admin_builds_a_program_and_owners_watch_by_plan(client):
    admin = await new_owner(ADMIN)
    p, s1, s2, r1, r2 = await build(admin)
    assert r1["video"]["provider"] == "vimeo" and r1["resources"] == [{"label": "Slides", "url": "https://example.com/slides.pdf"}]
    assert r2["video"]["embed"].startswith("https://www.youtube-nocookie.com/embed/")

    free, _, _ = await owner_on("9837000001", None, admin)
    lst = (await free.get("/api/recordings")).json()
    assert len(lst) == 1 and lst[0]["locked"] and lst[0]["tier_name"] == "Action Program" and lst[0]["recordings"] == 2
    r = await free.get(f"/api/recordings/{p['id']}")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "locked" and r.json()["detail"]["tier"] == "program"
    assert (await free.post(f"/api/recordings/item/{r1['id']}/watched", json={"watched": True})).status_code == 403

    for n, plan in enumerate(("program", "running", "growth", "office")):  # the plan it belongs to, and every plan above it
        c, _, _ = await owner_on(f"983700011{n}", plan, admin)
        d = (await c.get(f"/api/recordings/{p['id']}")).json()
        assert [s["title"] for s in d["sections"]] == ["Week 1 · Kickstart", "Live calls"] and d["recordings"] == 2 and d["watched"] == 0
    member, _, _ = await owner_on("9837000002", "lite", admin)
    assert (await member.get(f"/api/recordings/{p['id']}")).status_code == 403

    c, uid, _ = await owner_on("9837000003", "program", admin)
    d = (await c.get(f"/api/recordings/{p['id']}")).json()
    rec = d["sections"][0]["recordings"][0]
    assert rec["title"] == "Kickstart call" and rec["recorded_on"] == "2026-09-11" and rec["duration_min"] == 92 and rec["watched"] is False
    assert "Homework" in rec["notes"] and rec["video"]["kind"] == "iframe"
    assert (await c.post(f"/api/recordings/item/{r1['id']}/watched", json={"watched": True})).json()["watched"]
    assert (await c.get(f"/api/recordings/{p['id']}")).json()["watched"] == 1
    assert (await c.get("/api/recordings")).json()[0]["watched"] == 1
    await c.post(f"/api/recordings/item/{r1['id']}/watched", json={"watched": False})
    assert (await c.get(f"/api/recordings/{p['id']}")).json()["watched"] == 0


async def test_drafts_and_unpublished_programs_stay_hidden(client):
    admin = await new_owner(ADMIN)
    p, s1, _, r1, _ = await build(admin, published=False)
    c, _, _ = await owner_on("9837000010", "office", admin)
    assert (await c.get("/api/recordings")).json() == []
    assert (await c.get(f"/api/recordings/{p['id']}")).status_code == 404
    await admin.patch(f"/api/admin/programs/{p['id']}", json={"published": True})
    draft = (await admin.post("/api/admin/recordings", json={"section_id": s1["id"], "title": "Not ready", "link": "https://youtu.be/aqz-KE-bpKQ",
                                                             "published": False})).json()
    d = (await c.get(f"/api/recordings/{p['id']}")).json()
    assert d["recordings"] == 2 and all(r["title"] != "Not ready" for s in d["sections"] for r in s["recordings"])
    assert (await c.post(f"/api/recordings/item/{draft['id']}/watched", json={})).status_code == 404
    empty = (await admin.post(f"/api/admin/programs/{p['id']}/sections", json={"title": "Coming soon"})).json()
    assert all(s["id"] != empty["id"] for s in (await c.get(f"/api/recordings/{p['id']}")).json()["sections"])  # empty sections are hidden


async def test_private_program_for_owners_the_admin_adds(client):
    admin = await new_owner(ADMIN)
    p, *_ = await build(admin, title="Inner circle · ₹60,000", tier="none")
    c, uid, _ = await owner_on("9837000020", "office", admin)
    assert (await c.get("/api/recordings")).json() == []  # private programs are not advertised
    assert (await c.get(f"/api/recordings/{p['id']}")).status_code == 404
    assert (await admin.post(f"/api/admin/programs/{p['id']}/allowed", json={"phone": "12"})).status_code == 400
    assert (await admin.post(f"/api/admin/programs/{p['id']}/allowed", json={"phone": "98370 00099"})).status_code == 404
    d = (await admin.post(f"/api/admin/programs/{p['id']}/allowed", json={"phone": "98370 00020"})).json()
    assert d["allowed_count"] == 1 and d["allowed"][0]["business"] == "Shree Ganesh Interiors"
    assert (await c.get(f"/api/recordings/{p['id']}")).status_code == 200
    assert (await c.get("/api/recordings")).json()[0]["locked"] is False
    # adding someone also works for plan-based programs: a free owner who bought offline
    p2, *_ = await build(admin, title="Action Program", tier="program")
    free, fid, _ = await owner_on("9837000021", None, admin)
    await admin.post(f"/api/admin/programs/{p2['id']}/allowed", json={"phone": "9837000021"})
    assert (await free.get(f"/api/recordings/{p2['id']}")).status_code == 200
    await admin.delete(f"/api/admin/programs/{p2['id']}/allowed/{fid}")
    assert (await free.get(f"/api/recordings/{p2['id']}")).status_code == 403


async def test_team_members_see_only_programs_opened_to_teams(client):
    admin = await new_owner(ADMIN)
    owner, _, _ = await owner_on("9837000030", "growth", admin)
    assert (await owner.post("/api/team/invites", json={"phone": "9837000031", "name": "Ravi Kumar", "role": "staff"})).status_code == 200
    staff = await new_owner("9837000031")
    closed, *_ = await build(admin, title="Owner calls", tier="program")
    opened, _, _, r1, _ = await build(admin, title="Team training", tier="program", team=True)
    lst = (await staff.get("/api/recordings")).json()
    assert [x["title"] for x in lst] == ["Team training"]
    assert (await staff.get(f"/api/recordings/{closed['id']}")).status_code == 404
    assert (await staff.get(f"/api/recordings/{opened['id']}")).status_code == 200
    await staff.post(f"/api/recordings/item/{r1['id']}/watched", json={"watched": True})
    assert (await owner.get(f"/api/recordings/{opened['id']}")).json()["watched"] == 0  # progress is per person
    above, *_ = await build(admin, title="Legacy calls", tier="office", team=True)
    assert all(x["title"] != "Legacy calls" for x in (await staff.get("/api/recordings")).json())  # no upsell shown to staff


async def test_admin_only_validation_order_moves_and_deletes(client):
    admin = await new_owner(ADMIN)
    c, _, _ = await owner_on("9837000040", "office", admin)
    assert (await c.get("/api/admin/programs")).status_code == 403
    assert (await c.post("/api/admin/programs", json={"title": "x" * 5})).status_code == 403
    assert (await admin.post("/api/admin/programs", json={"title": "A program", "tier": "gold"})).status_code == 422
    p, s1, s2, r1, r2 = await build(admin)
    bad = await admin.post("/api/admin/recordings", json={"section_id": s1["id"], "title": "Bad", "link": "javascript:alert(1)"})
    assert bad.status_code == 400
    assert (await admin.post("/api/admin/recordings", json={"section_id": s1["id"], "title": "Bad date", "link": "https://youtu.be/aqz-KE-bpKQ",
                                                            "recorded_on": "11/10/2026"})).status_code == 422
    assert (await admin.post("/api/admin/recordings", json={"section_id": s1["id"], "title": "Future", "link": "https://youtu.be/aqz-KE-bpKQ",
                                                            "recorded_on": "2099-01-01"})).status_code == 422
    assert (await admin.post("/api/admin/recordings", json={"section_id": s1["id"], "title": "Bad res", "link": "https://youtu.be/aqz-KE-bpKQ",
                                                            "resources": [{"label": "x", "url": "not a link"}]})).status_code == 400
    assert (await admin.post("/api/admin/video-check", json={"link": "https://www.loom.com/share/0123456789abcdef0123456789abcdef"})).json()["provider"] == "loom"

    # bulk add: every line checked first
    bulk = await admin.post("/api/admin/recordings/bulk", json={"section_id": s2["id"], "lines": "Call 2 | https://youtu.be/aqz-KE-bpKQ\nbroken line"})
    assert bulk.status_code == 400 and "Line 2" in bulk.json()["detail"]
    ok = await admin.post("/api/admin/recordings/bulk", json={"section_id": s2["id"], "lines": "Call 2 | https://youtu.be/aqz-KE-bpKQ | 2026-09-18\n\nCall 3 | vimeo.com/76979871"})
    assert ok.json() == {"added": 2}
    d = (await admin.get(f"/api/admin/programs/{p['id']}")).json()
    live = next(s for s in d["sections_list"] if s["id"] == s2["id"])
    assert [r["title"] for r in live["recordings"]] == ["Q&A call 1", "Call 2", "Call 3"] and live["recordings"][1]["recorded_on"] == "2026-09-18"

    # reorder recordings and sections, move a recording, edit it
    await admin.post(f"/api/admin/recordings/{live['recordings'][2]['id']}/move", json={"dir": "up"})
    await admin.post(f"/api/admin/sections/{s2['id']}/move", json={"dir": "up"})
    d = (await admin.get(f"/api/admin/programs/{p['id']}")).json()
    assert [s["title"] for s in d["sections_list"]] == ["Live calls", "Week 1 · Kickstart"]
    assert [r["title"] for r in d["sections_list"][0]["recordings"]] == ["Q&A call 1", "Call 3", "Call 2"]
    moved = await admin.patch(f"/api/admin/recordings/{r2['id']}", json={"section_id": s1["id"], "title": "Q&A call one", "notes": "", "duration_min": None})
    assert moved.status_code == 200 and moved.json()["section_id"] == s1["id"] and moved.json()["title"] == "Q&A call one"
    other, os1, *_ = await build(admin, title="Other")
    assert (await admin.patch(f"/api/admin/recordings/{r2['id']}", json={"section_id": os1["id"]})).status_code == 400

    # program order, rename, delete section (with its recordings) and program
    await admin.post(f"/api/admin/programs/{other['id']}/move", json={"dir": "up"})
    assert [x["title"] for x in (await admin.get("/api/admin/programs")).json()] == ["Other", "Action Program"]
    await c.post(f"/api/recordings/item/{r1['id']}/watched", json={"watched": True})
    gone = (await admin.delete(f"/api/admin/sections/{s1['id']}")).json()
    assert gone["deleted_recordings"] == 2 and await db().rec_progress.count_documents({}) == 0
    assert (await admin.delete(f"/api/admin/programs/{p['id']}")).json() == {"ok": True}
    assert await db().recordings.count_documents({"program_id": p["id"]}) == 0
    assert (await c.get(f"/api/recordings/{p['id']}")).status_code == 404


@pytest.mark.parametrize("raw,provider,embed", [
    ("https://vimeo.com/showcase/10234567", "link", "https://vimeo.com/showcase/10234567"),
    ("https://vimeo.com/showcase/10234567/video/123456789", "vimeo", "https://player.vimeo.com/video/123456789?title=0&byline=0&portrait=0&dnt=1"),
    ("https://www.youtube.com/playlist?list=PLabcdefghij123", "youtube", "https://www.youtube-nocookie.com/embed/videoseries?list=PLabcdefghij123&rel=0&modestbranding=1"),
    ("https://www.youtube.com/embed/videoseries", "link", "https://www.youtube.com/embed/videoseries"),
])
def test_playlists_and_showcases(raw, provider, embed):
    v = video.parse(raw)
    assert (v["provider"], v["embed"]) == (provider, embed)


async def test_review_fixes_for_recordings(client):
    admin = await new_owner(ADMIN)
    for odd in ("[Call 1](https://vimeo.com/123456789)", "https://a.com℀x/v.mp4", "https://vimeo.com:99999/1"):
        r = await admin.post("/api/admin/video-check", json={"link": odd})
        assert r.status_code == 400, (odd, r.text)  # a clear message, never a crash
    assert (await admin.post("/api/admin/programs", json={"title": "   "})).status_code == 422
    p, s1, s2, r1, r2 = await build(admin)
    assert (await admin.post(f"/api/admin/programs/{p['id']}/sections", json={"title": "  "})).status_code == 422
    assert (await admin.patch(f"/api/admin/recordings/{r1['id']}", json={"title": " \t "})).status_code == 422
    sneaky = await admin.post("/api/admin/recordings", json={"section_id": s1["id"], "title": "Sneaky", "link": "https://youtu.be/aqz-KE-bpKQ",
                                                            "resources": [{"label": "Slides", "url": "good.com@evil.com/a"}]})
    assert sneaky.status_code == 400

    c, uid, _ = await owner_on("9837000050", "program", admin)
    rec = (await c.get(f"/api/recordings/{p['id']}")).json()["sections"][0]["recordings"][0]
    assert not {"created_by", "link", "published", "order", "program_id"} & set(rec) and "url" not in rec["video"]
    # watched marks on a recording that later becomes a draft stop counting everywhere
    await c.post(f"/api/recordings/item/{r2['id']}/watched", json={"watched": True})
    await admin.patch(f"/api/admin/recordings/{r2['id']}", json={"published": False})
    item = (await c.get("/api/recordings")).json()[0]
    assert item["recordings"] == 1 and item["watched"] == 0
    assert (await c.get(f"/api/recordings/{p['id']}")).json()["watched"] == 0
    # a published program with nothing to watch isn't listed yet
    empty = (await admin.post("/api/admin/programs", json={"title": "Coming soon", "tier": "free", "published": True})).json()
    assert all(x["id"] != empty["id"] for x in (await c.get("/api/recordings")).json())
    # an owner added by hand to a program above their plan sees it as added for them
    top, *_ = await build(admin, title="Legacy calls", tier="office")
    await admin.post(f"/api/admin/programs/{top['id']}/allowed", json={"phone": "9837000050"})
    listed = {x["title"]: x for x in (await c.get("/api/recordings")).json()}
    assert listed["Legacy calls"]["added"] is True and listed["Legacy calls"]["locked"] is False and listed["Action Program"]["added"] is False


async def test_owner_added_to_a_program_is_never_folded_into_a_team(client):
    admin = await new_owner(ADMIN)
    p, *_ = await build(admin, tier="none")
    buyer = await new_owner("9837000060")  # logged in once, no business profile yet
    await admin.post(f"/api/admin/programs/{p['id']}/allowed", json={"phone": "9837000060"})
    owner, _, _ = await owner_on("9837000061", "growth", admin)
    r = await owner.post("/api/team/invites", json={"phone": "9837000060", "name": "Kapil", "role": "staff"})
    assert r.status_code == 409
    me = (await (await new_owner("9837000060")).get("/api/me")).json()
    assert me["workspace"]["is_team"] is False and (await buyer.get(f"/api/recordings/{p['id']}")).status_code == 200

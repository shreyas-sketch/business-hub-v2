"""Team logins, tasks, strategic/tactical meetings with the actions agent, and voice-note transcription."""
import json
from contextlib import contextmanager
from datetime import date

import httpx

from app import transcribe
from app.ai import team_tasks
from app.config import settings
from app.db import db
from app.routers.team import create_task
from tests.conftest import PROFILE, new_owner

REAL_CLIENT = httpx.AsyncClient


async def owner_on(phone: str, plan: str | None = "growth", name: str = "Harsh Mehta", admin=None):
    """An owner with a business profile, on `plan` (set by the admin). Returns (client, user id, admin client)."""
    c = await new_owner(phone, name=name)
    assert (await c.put("/api/business", json=PROFILE)).status_code == 200
    uid = (await c.get("/api/me")).json()["user"]["id"]
    admin = admin or await new_owner("9999900000")
    if plan:
        assert (await admin.patch(f"/api/admin/users/{uid}", json={"plan": plan})).status_code == 200
    return c, uid, admin


async def join(owner, phone: str, name: str, role: str = "staff"):
    """Owner invites a number; that person logs in and lands in the owner's team. Returns (client, user id)."""
    r = await owner.post("/api/team/invites", json={"phone": phone, "name": name, "role": role})
    assert r.status_code == 200, r.text
    member = await new_owner(phone)
    me = (await member.get("/api/me")).json()
    assert me["workspace"]["role"] == role and me["workspace"]["is_team"]
    return member, me["user"]["id"]


@contextmanager
def setting(**values):
    old = {k: getattr(settings, k) for k in values}
    for k, v in values.items():
        object.__setattr__(settings, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            object.__setattr__(settings, k, v)


class FakeHTTP:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def __call__(self, *a, **k):
        def respond(req):
            self.calls.append(req)
            return self.handler(req)
        return REAL_CLIENT(transport=httpx.MockTransport(respond), timeout=5)


async def runs_used(c) -> int:
    return (await c.get("/api/me")).json()["runs"]["used"]


# ───────────────────────── plans and roles ─────────────────────────
async def test_team_tools_locked_below_growth(client):
    owner, _, _ = await owner_on("9832000010", plan="program")
    for method, path, body in (("GET", "/api/team", None), ("POST", "/api/team/invites", {"phone": "9832000011", "name": "Ravi"}),
                               ("GET", "/api/tasks", None), ("POST", "/api/tasks", {"title": "Call bank"}),
                               ("GET", "/api/meetings", None), ("POST", "/api/meetings", {"type": "tactical", "date": "2026-10-05"}),
                               ("GET", "/api/team/people", None)):
        r = await owner.request(method, path, json=body)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "locked", (path, r.text)
    free, _, _ = await owner_on("9832000012", plan=None)
    r = await free.post("/api/voice/transcribe", files={"file": ("n.webm", b"abc", "audio/webm")})
    assert r.status_code == 403 and r.json()["detail"]["feature"] == "voice_sop"


# ───────────────────────── team logins ─────────────────────────
async def test_invite_login_and_team_member_access(client):
    owner, owner_id, _ = await owner_on("9832000020")
    r = await owner.post("/api/team/invites", json={"phone": "98320 00021", "name": "Ravi Kumar", "role": "staff"})
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["phone"] == "+919832000021" and inv["status"] == "pending"
    assert inv["share_link"].startswith("https://wa.me/919832000021?text=")
    assert "https://hub.example.in/login" in inv["message"] and "98320 00021" in inv["message"] and "Hi Ravi" in inv["message"]
    team = (await owner.get("/api/team")).json()
    assert team["used"] == 1 and team["limit"] == 10 and len(team["invites"]) == 1 and team["members"] == []

    member = await new_owner("9832000021")  # a brand-new number logs in with the normal OTP flow
    me = (await member.get("/api/me")).json()
    assert me["workspace"] == {"role": "staff", "owner_name": "Harsh Mehta", "is_team": True}
    assert me["business_name"] == PROFILE["name"] and me["user"]["name"] == "Ravi Kumar" and me["features"]["tasks"]
    assert (await member.get("/api/leads")).status_code == 200
    assert (await member.put("/api/business", json=PROFILE)).status_code == 403
    assert (await member.post("/api/team/invites", json={"phone": "9832000022", "name": "X"})).status_code == 403
    assert (await member.get("/api/team")).status_code == 403

    team = (await owner.get("/api/team")).json()
    assert [m["name"] for m in team["members"]] == ["Ravi Kumar"] and team["invites"] == [] and team["used"] == 1
    assert (await db().team_invites.find_one({"phone": "+919832000021"}))["status"] == "joined"
    people = (await owner.get("/api/team/people")).json()
    assert [(p["name"], p["role"]) for p in people] == [("Harsh Mehta", "owner"), ("Ravi Kumar", "staff")]
    assert people[0]["id"] == owner_id


async def test_invite_refusals(client):
    owner, _, admin = await owner_on("9832000030")
    other, _, _ = await owner_on("9832000031", admin=admin)
    bad = lambda r, code, word: r.status_code == code and word in r.json()["detail"]  # noqa: E731
    assert bad(await owner.post("/api/team/invites", json={"phone": "+91 98320 00030", "name": "Me"}), 400, "own number")
    assert bad(await owner.post("/api/team/invites", json={"phone": "9832000031", "name": "Other owner"}), 409, "own business")
    assert (await owner.post("/api/team/invites", json={"phone": "12345", "name": "Bad"})).status_code == 400

    # someone already in another team
    await join(other, "9832000032", "Neha")
    assert bad(await owner.post("/api/team/invites", json={"phone": "9832000032", "name": "Neha"}), 409, "another business")
    # a pending invite from another business
    assert (await other.post("/api/team/invites", json={"phone": "9832000033", "name": "Amit"})).status_code == 200
    assert bad(await owner.post("/api/team/invites", json={"phone": "9832000033", "name": "Amit"}), 409, "another business")
    # inviting the same number again updates the invite
    first = (await owner.post("/api/team/invites", json={"phone": "9832000034", "name": "Sunil", "role": "staff"})).json()
    again = (await owner.post("/api/team/invites", json={"phone": "9832000034", "name": "Sunil Patil", "role": "manager"})).json()
    assert again["id"] == first["id"] and again["role"] == "manager" and again["name"] == "Sunil Patil"
    assert await db().team_invites.count_documents({"owner_id": {"$exists": True}, "phone": "+919832000034"}) == 1
    # already on this team
    await new_owner("9832000034")
    assert bad(await owner.post("/api/team/invites", json={"phone": "9832000034", "name": "Sunil"}), 409, "already on your team")
    # revoking an invite
    inv = (await owner.post("/api/team/invites", json={"phone": "9832000035", "name": "Kiran"})).json()
    assert (await owner.delete(f"/api/team/invites/{inv['id']}")).status_code == 200
    assert (await owner.delete(f"/api/team/invites/{inv['id']}")).status_code == 404
    kiran = await new_owner("9832000035")  # a revoked invite no longer brings them into the team
    assert not (await kiran.get("/api/me")).json()["workspace"]["is_team"]


async def test_team_limit_growth_then_office(client):
    owner, uid, admin = await owner_on("9832000040")
    for i in range(10):
        r = await owner.post("/api/team/invites", json={"phone": f"98321000{i:02d}", "name": f"Person {i}"})
        assert r.status_code == 200, r.text
    r = await owner.post("/api/team/invites", json={"phone": "9832100010", "name": "One more"})
    assert r.status_code == 400 and "up to 10" in r.json()["detail"]
    # updating an existing invite is not a new seat
    assert (await owner.post("/api/team/invites", json={"phone": "9832100003", "name": "Person 3", "role": "manager"})).status_code == 200
    first = (await owner.get("/api/team")).json()["invites"][-1]
    assert (await owner.delete(f"/api/team/invites/{first['id']}")).status_code == 200
    assert (await owner.post("/api/team/invites", json={"phone": "9832100010", "name": "One more"})).status_code == 200
    await admin.patch(f"/api/admin/users/{uid}", json={"plan": "office"})
    assert (await owner.get("/api/team")).json()["limit"] == 25
    assert (await owner.post("/api/team/invites", json={"phone": "9832100011", "name": "Office plan"})).status_code == 200


async def test_role_change_and_removal_logs_member_out(client):
    owner, _, _ = await owner_on("9832000050")
    member, mid = await join(owner, "9832000051", "Ravi Kumar", "staff")
    task = (await owner.post("/api/tasks", json={"title": "Call the 5 pending leads", "assignee_id": mid})).json()
    assert (await member.get("/api/team/people")).status_code == 200

    assert (await owner.patch(f"/api/team/members/{mid}", json={"role": "manager"})).status_code == 200
    me = (await member.get("/api/me")).json()
    assert me["workspace"]["role"] == "manager" and any("manager" in n["text"] for n in me["notices"])
    assert (await owner.patch(f"/api/team/members/{mid}", json={"role": "owner"})).status_code == 422
    assert (await member.patch(f"/api/team/members/{mid}", json={"role": "staff"})).status_code == 403
    assert (await member.delete(f"/api/team/members/{mid}")).status_code == 403

    assert (await owner.delete(f"/api/team/members/{mid}")).status_code == 200
    assert (await member.get("/api/me")).status_code == 401  # logged out at once
    assert (await member.get("/api/leads")).status_code == 401
    user = await db().users.find_one({"_id": mid})
    assert "team_of" not in user and "team_role" not in user and user["team_removed_at"] and user["session_version"] == 1
    assert (await db().tasks.find_one({"_id": task["id"]}))["assignee_id"] is None
    assert (await owner.get("/api/team")).json()["members"] == []
    assert (await owner.delete(f"/api/team/members/{mid}")).status_code == 404


# ───────────────────────── tasks ─────────────────────────
async def test_tasks_staff_and_manager_rules(client):
    owner, owner_id, admin = await owner_on("9832000060")
    manager, mid = await join(owner, "9832000061", "Priya Shah", "manager")
    staff, sid = await join(owner, "9832000062", "Ravi Kumar", "staff")
    outsider, outsider_id, _ = await owner_on("9832000063", admin=admin)

    t1 = (await owner.post("/api/tasks", json={"title": "Send quotation to Mr. Joshi", "assignee_id": sid, "due": "2026-10-10"})).json()
    assert t1["assignee_name"] == "Ravi Kumar" and t1["source"] == {"kind": "manual", "id": None} and t1["status"] == "open"
    notices = (await staff.get("/api/me")).json()["notices"]
    assert any(n["text"] == "Harsh Mehta gave you a task: Send quotation to Mr. Joshi (due 10 Oct)" for n in notices)

    # staff: own tasks only, status only
    own = (await staff.post("/api/tasks", json={"title": "Clean the display shelf"})).json()
    assert own["assignee_id"] == sid
    assert not any("Clean the display" in n["text"] for n in (await staff.get("/api/me")).json()["notices"])  # no notice to yourself
    assert (await staff.post("/api/tasks", json={"title": "Call bank", "assignee_id": mid})).status_code == 403
    t2 = (await manager.post("/api/tasks", json={"title": "Check stock", "assignee_id": mid})).json()
    listed = (await staff.get("/api/tasks?scope=all")).json()
    assert {t["id"] for t in listed} == {t1["id"], own["id"]}
    assert (await staff.patch(f"/api/tasks/{t1['id']}", json={"title": "Changed"})).status_code == 403
    assert (await staff.patch(f"/api/tasks/{t2['id']}", json={"status": "done"})).status_code == 403
    assert (await staff.delete(f"/api/tasks/{own['id']}")).status_code == 403
    assert (await staff.get("/api/me")).json()["my_open_tasks"] == 2
    done = await staff.patch(f"/api/tasks/{t1['id']}", json={"status": "done"})
    assert done.status_code == 200 and done.json()["status"] == "done" and done.json()["done_at"]
    assert [t["id"] for t in (await staff.get("/api/tasks?status=done")).json()] == [t1["id"]]
    assert (await staff.get("/api/me")).json()["my_open_tasks"] == 1

    # manager: assigns anyone in the workspace, including the owner; edits and deletes
    t3 = (await manager.post("/api/tasks", json={"title": "Meet the bank", "assignee_id": owner_id})).json()
    assert t3["assignee_name"] == "Harsh Mehta"
    assert any("Priya Shah gave you a task: Meet the bank" == n["text"] for n in (await owner.get("/api/me")).json()["notices"])
    assert (await manager.post("/api/tasks", json={"title": "Outsider", "assignee_id": outsider_id})).status_code == 400
    assert (await manager.post("/api/tasks", json={"title": "Bad date", "due": "2026-13-45"})).status_code == 400
    r = await manager.patch(f"/api/tasks/{t3['id']}", json={"assignee_id": sid, "due": "2026-10-12", "note": "Carry the file"})
    assert r.status_code == 200 and r.json()["assignee_name"] == "Ravi Kumar" and r.json()["due"] == "2026-10-12"
    assert any("Meet the bank" in n["text"] for n in (await staff.get("/api/me")).json()["notices"])
    cleared = (await manager.patch(f"/api/tasks/{t3['id']}", json={"due": None})).json()
    assert cleared["due"] is None and cleared["note"] == "Carry the file"
    all_open = (await manager.get("/api/tasks?scope=all")).json()
    assert {t["id"] for t in all_open} == {own["id"], t2["id"], t3["id"]}
    assert [t["id"] for t in (await manager.get("/api/tasks")).json()] == [t2["id"]]  # "mine" by default
    assert (await manager.delete(f"/api/tasks/{t2['id']}")).status_code == 200
    assert (await manager.delete(f"/api/tasks/{t2['id']}")).status_code == 404
    # other workspaces can't see or touch these tasks
    await admin.patch(f"/api/admin/users/{outsider_id}", json={"plan": "growth"})
    assert (await outsider.get("/api/tasks?scope=all")).json() == []
    assert (await outsider.patch(f"/api/tasks/{own['id']}", json={"status": "done"})).status_code == 404


async def test_create_task_helper_for_other_modules(client):
    owner, owner_id, admin = await owner_on("9832000070")
    _, other_id, _ = await owner_on("9832000071", admin=admin)
    t = await create_task(owner_id, "office", "Follow up with the 3 quotes sent last week", assignee_id=other_id, due="not a date",
                          source={"kind": "office", "id": "job-1"})
    assert t["assignee_id"] is None and t["due"] is None and t["source"] == {"kind": "office", "id": "job-1"} and t["id"]
    t = await create_task(owner_id, "office", "Post Diwali offer", assignee_id=owner_id, due="2026-10-20", source={"kind": "office"})
    notices = (await owner.get("/api/me")).json()["notices"]
    assert any(n["text"] == "Your AI office added a task for you: Post Diwali offer (due 20 Oct)" for n in notices)
    assert len((await owner.get("/api/tasks")).json()) == 1


# ───────────────────────── meetings ─────────────────────────
async def test_meetings_agenda_roles_and_actions_agent(client):
    owner, owner_id, _ = await owner_on("9832000080")
    manager, mid = await join(owner, "9832000081", "Priya Shah", "manager")
    staff, sid = await join(owner, "9832000082", "Ravi Kumar", "staff")

    r = await manager.post("/api/meetings", json={"type": "tactical", "date": "2026-10-05", "attendees": [owner_id, sid, "someone-else"]})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["title"] == "Weekly tactical — 5 Oct 2026" and m["status"] == "open" and m["attendees"] == [owner_id, sid]
    assert [s["key"] for s in m["sections"]] == ["last_goals", "checkins", "applause", "next_goals", "concerns", "takeaways"]
    assert all(s["prompt"] and s["notes"] == "" for s in m["sections"])
    strategic = (await owner.post("/api/meetings", json={"type": "strategic", "date": "2026-10-01", "title": "October review"})).json()
    assert strategic["title"] == "October review" and len(strategic["sections"]) == 8
    assert {"wins", "setbacks", "feedback", "goals", "obstacles", "plan", "recognition", "takeaways"} == {s["key"] for s in strategic["sections"]}

    # staff read only
    assert len((await staff.get("/api/meetings")).json()) == 2
    assert (await staff.get(f"/api/meetings/{m['id']}")).json()["attendee_names"] == ["Harsh Mehta", "Ravi Kumar"]
    assert (await staff.post("/api/meetings", json={"type": "tactical", "date": "2026-10-05"})).status_code == 403
    assert (await staff.patch(f"/api/meetings/{m['id']}", json={"notes": {"applause": "Me"}})).status_code == 403
    assert (await staff.post(f"/api/meetings/{m['id']}/actions")).status_code == 403

    # no notes → no AI run spent
    used = await runs_used(owner)
    r = await manager.post(f"/api/meetings/{strategic['id']}/actions")
    assert r.status_code == 400 and await runs_used(owner) == used

    notes = {"checkins": "- Ravi will call the 5 pending leads by Friday\n- Priya to send the new price list tomorrow\n- Decided: start Sunday deliveries",
             "next_goals": "Harsh will meet the bank on 2026-10-20", "unknown": "ignored"}
    r = await manager.patch(f"/api/meetings/{m['id']}", json={"notes": notes, "status": "closed"})
    assert r.status_code == 200
    saved = {s["key"]: s["notes"] for s in r.json()["sections"]}
    assert saved["checkins"].startswith("- Ravi will call") and saved["next_goals"] and saved["applause"] == "" and r.json()["status"] == "closed"
    # a second editor saving another section does not wipe the first
    await owner.patch(f"/api/meetings/{m['id']}", json={"notes": {"applause": "Ravi — 3 orders closed"}})
    saved = {s["key"]: s["notes"] for s in (await staff.get(f"/api/meetings/{m['id']}")).json()["sections"]}
    assert saved["checkins"].startswith("- Ravi") and saved["applause"] == "Ravi — 3 orders closed"
    assert (await manager.patch(f"/api/meetings/{m['id']}", json={"notes": {"concerns": "x" * 4001}})).status_code == 400

    r = await manager.post(f"/api/meetings/{m['id']}/actions")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["added"] == 3 and out["decisions"] == ["Start Sunday deliveries"]
    by_owner = {a["owner_name"]: a for a in out["actions"]}
    assert by_owner["Ravi Kumar"]["owner_id"] == sid and by_owner["Ravi Kumar"]["due"] == "2026-10-09"
    assert by_owner["Ravi Kumar"]["task"] == "Call the 5 pending leads by Friday"
    assert by_owner["Priya Shah"]["owner_id"] == mid and by_owner["Priya Shah"]["due"] == "2026-10-06"
    assert by_owner["Harsh Mehta"]["owner_id"] == owner_id and by_owner["Harsh Mehta"]["due"] == "2026-10-20"
    assert await runs_used(owner) == used + 1

    tasks = (await owner.get("/api/tasks?scope=all")).json()
    assert len(tasks) == 3 and all(t["source"] == {"kind": "meeting", "id": m["id"]} for t in tasks)
    assert {a["task_id"] for a in out["actions"]} == {t["id"] for t in tasks}
    ravi = (await staff.get("/api/tasks")).json()
    assert [t["title"] for t in ravi] == ["Call the 5 pending leads by Friday"] and ravi[0]["due"] == "2026-10-09"
    assert any(n["text"].startswith("New task from a team meeting: Call the 5 pending leads") for n in (await staff.get("/api/me")).json()["notices"])

    # pulling out actions again does not double the tasks or decisions
    again = (await manager.post(f"/api/meetings/{m['id']}/actions")).json()
    assert again["added"] == 0 and len(again["actions"]) == 3 and again["decisions"] == ["Start Sunday deliveries"]
    assert len((await owner.get("/api/tasks?scope=all")).json()) == 3

    rows = (await owner.get("/api/meetings")).json()
    assert rows[0]["id"] == m["id"] and rows[0]["actions"] == 3 and rows[0]["notes_filled"] == 3
    assert (await manager.delete(f"/api/meetings/{m['id']}")).status_code == 403
    assert (await owner.delete(f"/api/meetings/{m['id']}")).status_code == 200
    assert (await owner.get(f"/api/meetings/{m['id']}")).status_code == 404


async def test_actions_agent_helpers():
    people = [{"id": "o", "name": "Harsh Mehta", "role": "owner"}, {"id": "r", "name": "Ravi Kumar", "role": "staff"},
              {"id": "r2", "name": "Ravi Patel", "role": "staff"}, {"id": "p", "name": "Priya Shah", "role": "manager"}]
    assert team_tasks.match_person("priya shah", people)["id"] == "p"
    assert team_tasks.match_person("Priya", people)["id"] == "p"
    assert team_tasks.match_person("Ravi", people) is None  # two Ravis: leave it unassigned
    assert team_tasks.match_person("Ravi Patel", people)["id"] == "r2"
    assert team_tasks.match_person("Owner", people)["id"] == "o"
    assert team_tasks.match_person("Suresh", people) is None and team_tasks.match_person("", people) is None
    monday = date(2026, 10, 5)
    assert team_tasks.due_from("by Friday", monday) == "2026-10-09"
    assert team_tasks.due_from("by Monday", monday) == "2026-10-12"
    assert team_tasks.due_from("next week", monday) == "2026-10-12"
    assert team_tasks.due_from("no date here", monday) == ""
    shaped = team_tasks.shape_actions({"decisions": ["  Open on Sunday ", 5], "actions": ["Call Ravi", {"task": "", "owner": "x"}, {"task": "Pay rent", "owner": None}]})
    assert shaped == {"decisions": ["Open on Sunday"], "actions": [{"task": "Call Ravi", "owner": "", "due": ""}, {"task": "Pay rent", "owner": "", "due": ""}]}


# ───────────────────────── voice notes ─────────────────────────
AUDIO = b"\x1aE\xdf\xa3" + bytes(2048)


async def test_voice_transcription_in_test_mode(client):
    owner, _, _ = await owner_on("9832000090", plan="program")
    used = await runs_used(owner)
    with setting(openai_api_key="", gemini_api_key=""):
        r = await owner.post("/api/voice/transcribe", files={"file": ("voice.webm", AUDIO, "audio/webm;codecs=opus")})
        assert r.status_code == 200, r.text
        assert r.json()["text"] == transcribe.SAMPLE
        assert await runs_used(owner) == used + 1
        assert (await db().runs.find_one({"kind": "voice_note"}))["status"] == "done"

        bad = await owner.post("/api/voice/transcribe", files={"file": ("notes.txt", b"hello", "text/plain")})
        assert bad.status_code == 415
        empty = await owner.post("/api/voice/transcribe", files={"file": ("voice.webm", b"", "audio/webm")})
        assert empty.status_code == 400
        missing = await owner.post("/api/voice/transcribe", data={"x": "1"})
        assert missing.status_code == 400
        big = await owner.post("/api/voice/transcribe", files={"file": ("big.mp3", b"\0" * (10 * 1024 * 1024 + 1), "audio/mpeg")})
        assert big.status_code == 413 and "10 MB" in big.json()["detail"]
        assert await runs_used(owner) == used + 1  # refused uploads never spend a run
        exactly = await owner.post("/api/voice/transcribe", files={"file": ("ok.mp3", b"\0" * (10 * 1024 * 1024), "audio/mpeg")})
        assert exactly.status_code == 200

    with setting(openai_api_key="", gemini_api_key="", env="production"):  # a real deployment with no speech key
        r = await owner.post("/api/voice/transcribe", files={"file": ("voice.webm", AUDIO, "audio/webm")})
        assert r.status_code == 503 and r.json()["detail"] == "Voice notes need an OpenAI or Gemini key."
    assert await runs_used(owner) == used + 2


async def test_voice_needs_manager_on_a_team(client):
    owner, _, _ = await owner_on("9832000091")
    staff, _ = await join(owner, "9832000092", "Ravi Kumar", "staff")
    manager, _ = await join(owner, "9832000093", "Priya Shah", "manager")
    with setting(openai_api_key="", gemini_api_key=""):
        assert (await staff.post("/api/voice/transcribe", files={"file": ("v.webm", AUDIO, "audio/webm")})).status_code == 403
        assert (await manager.post("/api/voice/transcribe", files={"file": ("v.webm", AUDIO, "audio/webm")})).status_code == 200


async def test_voice_engines_against_fake_servers(client, monkeypatch):
    owner, _, _ = await owner_on("9832000094", plan="program")
    used = await runs_used(owner)

    def whisper(req):
        assert req.url == "https://api.openai.com/v1/audio/transcriptions" and req.headers["authorization"] == "Bearer sk-voice"
        body = req.content
        assert b'name="model"' in body and b"whisper-1" in body and b'filename="blob.webm"' in body
        return httpx.Response(200, json={"text": " Pehle order book mein naam likho. "})
    fake = FakeHTTP(whisper)
    monkeypatch.setattr(transcribe.httpx, "AsyncClient", fake)
    with setting(openai_api_key="sk-voice", gemini_api_key=""):
        r = await owner.post("/api/voice/transcribe", files={"file": ("blob", AUDIO, "audio/webm;codecs=opus")})
        assert r.status_code == 200 and r.json() == {"text": "Pehle order book mein naam likho."} and len(fake.calls) == 1

    def gemini(req):
        body = json.loads(req.content)
        assert req.url.path == "/v1beta/models/gemini-2.5-flash:generateContent" and req.headers["x-goog-api-key"] == "g-key"
        part = body["contents"][0]["parts"][0]["inlineData"]
        assert part["mimeType"] == "audio/mp4" and part["data"]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Step one, check the stock."}]}}]})
    monkeypatch.setattr(transcribe.httpx, "AsyncClient", FakeHTTP(gemini))
    with setting(openai_api_key="", gemini_api_key="g-key", ai_model="claude-haiku-5-5"):
        r = await owner.post("/api/voice/transcribe", files={"file": ("note.m4a", AUDIO, "audio/mp4")})
        assert r.status_code == 200 and r.json()["text"] == "Step one, check the stock."
    assert await runs_used(owner) == used + 2

    # the engine fails: plain message, run refunded
    monkeypatch.setattr(transcribe.httpx, "AsyncClient", FakeHTTP(lambda req: httpx.Response(500, json={"error": "down"})))
    with setting(openai_api_key="sk-voice", gemini_api_key=""):
        r = await owner.post("/api/voice/transcribe", files={"file": ("v.webm", AUDIO, "audio/webm")})
        assert r.status_code == 502 and "not used" in r.json()["detail"]
    # silence: nothing heard, run refunded
    monkeypatch.setattr(transcribe.httpx, "AsyncClient", FakeHTTP(lambda req: httpx.Response(200, json={"text": "  "})))
    with setting(openai_api_key="sk-voice", gemini_api_key=""):
        assert (await owner.post("/api/voice/transcribe", files={"file": ("v.webm", AUDIO, "audio/webm")})).status_code == 400
    assert await runs_used(owner) == used + 2

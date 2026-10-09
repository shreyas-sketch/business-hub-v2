"""Screenshot sweep: every page for each plan and role (desktop and phone), collecting console, page and server errors and
any page that scrolls sideways on a phone. Run against the seeded demo hub (see e2e.py):  python3 qa/screens.py /tmp/screens
"""
import json
import re
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
OUT = sys.argv[1]
FREE = ["home", "score", "writer", "launch-kit", "website", "leads", "brand", "outputs", "invite", "plans", "recordings"]
MEMBER = ["week", "calendar", "member-call", "board", "tools", "magic", "gaps", "sops", "insights"]
PROGRAM = ["approvals", "agents", "lead-magnet", "offers", "goals", "levers", "portfolio", "pipeline", "leaks", "end-goals", "decisions", "hiring"]
RUNNING = ["crm", "customers", "money", "quotes"]
GROWTH = ["setup", "control", "staff", "chats", "connections", "company-brain", "campaigns", "gym", "results", "team", "roles", "culture",
          "competence", "meetings", "tasks", "reviews"]
OFFICE = ["workforce", "office"]
ALL = FREE + MEMBER + PROGRAM + RUNNING + GROWTH + OFFICE
problems = []


def watch(page, label):
    page.on("pageerror", lambda e: problems.append(f"[{label}] page error: {e}"))
    page.on("console", lambda m: m.type == "error" and not re.search(r"status of (400|401|402|403|404)", m.text)
            and problems.append(f"[{label}] console: {m.text[:200]}"))
    page.on("response", lambda r: r.status >= 500 and problems.append(f"[{label}] {r.status} {r.url}"))
    page.on("dialog", lambda d: d.accept())


def login(page, phone):
    page.goto(f"{BASE}/login")
    page.fill("input[inputmode=tel]", phone)
    page.click("button:has-text('Send code')")
    page.wait_for_selector(".prompt")
    code = re.search(r"(\d{6})", page.inner_text(".prompt")).group(1)
    page.fill("input[autocomplete=one-time-code]", code)
    page.click("button:has-text('Log in')")
    page.wait_for_timeout(1200)


def sweep(b, label, phone, pages, vw, vh, full=True):
    ctx = b.new_context(viewport={"width": vw, "height": vh})
    pg = ctx.new_page()
    watch(pg, label)
    login(pg, phone)
    for p in pages:
        pg.goto(f"{BASE}/{p}")
        pg.wait_for_timeout(1100)
        if vw < 500:
            wide = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            if wide > 2:
                problems.append(f"[{label}] /{p} scrolls sideways by {wide}px")
        pg.screenshot(path=f"{OUT}/{label}_{p.replace('/', '-')}.png", full_page=full)
    ctx.close()


with sync_playwright() as p:
    b = p.chromium.launch()
    sweep(b, "office", "9820000001", ALL, 1366, 900)
    sweep(b, "officem", "9820000001", ALL, 390, 844)
    sweep(b, "growth", "9820000006", FREE[:2] + GROWTH[:9] + ["approvals", "pipeline", "customers", "workforce"], 1366, 900)
    sweep(b, "growthm", "9820000006", ["chats", "staff", "campaigns", "gym", "control"], 390, 844)
    sweep(b, "running", "9820000005", ["home", "customers", "quotes", "money", "crm", "approvals", "staff"], 1366, 900)
    sweep(b, "runningm", "9820000005", ["customers", "quotes", "approvals"], 390, 844)
    sweep(b, "program", "9820000003", ["home", "offers", "levers", "end-goals", "pipeline", "customers", "plans"], 1366, 900)
    sweep(b, "member", "9820000002", ["home", "week", "calendar", "member-call", "board", "tools", "magic", "gaps", "score", "lead-magnet", "plans"], 1366, 900)
    sweep(b, "memberm", "9820000002", ["home", "week", "calendar", "tools", "gaps"], 390, 844)
    sweep(b, "free", "9820000004", ["home", "score", "writer", "launch-kit", "week", "approvals", "office", "plans"], 1366, 900)
    sweep(b, "freem", "9820000004", ["home", "score", "writer", "launch-kit"], 390, 844)
    sweep(b, "staff", "9820000012", ["home", "leads", "tasks", "sops", "meetings", "pipeline", "chats", "gym", "tools", "roles", "outputs"], 1366, 900)
    sweep(b, "manager", "9820000011", ["home", "approvals", "money", "quotes", "control", "week", "office", "outputs"], 1366, 900)
    sweep(b, "admin", "9999900000", ["admin", "admin/features", "admin/calls", "admin/recordings"], 1366, 900)
    sweep(b, "adminm", "9999900000", ["admin", "admin/features", "admin/calls"], 390, 844)
    b.close()
print(json.dumps(problems, indent=1) if problems else "No console, page or server errors, and nothing scrolls sideways on a phone.")

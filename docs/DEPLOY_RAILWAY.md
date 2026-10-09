# Deploy a test hub on Railway (about 15 minutes)

This puts the hub online with the demo data, so anyone can open it and log in with a demo number. No WhatsApp, SMS,
Razorpay or AI keys are needed. The full production setup (Atlas, the hub's WhatsApp, `*.employz.ai`, payments) is in
*Action Hub v2 - Developer Guide.pdf*.

## 1. Create the project

1. railway.com → **New Project** → **Deploy from GitHub repo** → pick `business-hub-v2`.
   If the code is still on a branch, open the service → **Settings → Source** and choose that branch.
   Railway finds `railway.json` and the `Dockerfile`; the first build takes 3–5 minutes.
2. In the same project: **+ Create → Database → MongoDB**. Railway starts a MongoDB service next to the hub.
3. Hub service → **Settings → Networking → Generate Domain** (port 8000 if asked). You get an address like
   `business-hub-v2-production.up.railway.app`. The hub uses it automatically when `APP_URL` is blank.
4. Hub service → **Settings → Region**: Southeast Asia (Singapore), and put the MongoDB service in the same region.

## 2. Variables

Hub service → **Variables → Raw Editor**, paste, then fill in the two keys (commands below):

```
APP_ENV=production
MONGO_URL=${{MongoDB.MONGO_URL}}
DB_NAME=action_hub
JWT_SECRET=
CONNECTIONS_KEY=
ADMIN_PHONES=+919999900000
AI_PROVIDER=mock
SEED_DEMO=true
DEMO_PHONES=9999900000,9820000001,9820000002,9820000003,9820000004,9820000005,9820000006,9820000011,9820000012
```

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                    # JWT_SECRET
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"       # CONNECTIONS_KEY
```

Save → Railway redeploys. On the first start the demo hub is loaded into the empty database (about 30 seconds, see
**Deploy Logs**: `Demo ready.`), then the hub starts. Later restarts skip it, because the database is no longer empty.

`AI_PROVIDER=mock` returns fixed demo text. For real AI answers, set `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`
(and an `OPENAI_API_KEY` or `GEMINI_API_KEY` for voice notes).

## 3. Test it

Open `https://<your domain>/api/health` → `{"ok":true}`. Then open the domain and log in. With a demo number the code is
shown on the login screen.

| Number | Who |
|---|---|
| 9820000001 | Shree Ganesh Interiors — LegacyWorkforce (everything) |
| 9820000011 / 9820000012 | Priya Nair (manager) / Suresh Yadav (staff) on that team |
| 9820000006 | Sharma Modular Kitchens — Growth Mentorship |
| 9820000005 | Patel Sweets & Farsan — Running the Business |
| 9820000003 | Arora Traders — Action Program |
| 9820000002 | Kapoor Dental Clinic — Membership |
| 9820000004 | Mehta Engineering Works — Free |
| 9999900000 | Admin (Pulse, Features & plans, member calls, recordings) |

Owners' websites are at `https://<your domain>/s/<name>`, e.g. `/s/shree-ganesh-interiors`.

On a deployed hub the demo WhatsApp and Telecaller connections show as *not connected*: they only "send" on a laptop.
Everything else works as on a laptop.

## Before real owners use it

- Clear `DEMO_PHONES` and `SEED_DEMO` — anyone who knows a demo number can log in as it, including the demo admin.
- Use a fresh database (new `DB_NAME`, or MongoDB Atlas M10 as in the guide), set your real `ADMIN_PHONES`, and a login
  channel (AiSensy and/or MSG91). Keep `CONNECTIONS_KEY` unchanged from then on.

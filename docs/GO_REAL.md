# Make the hub real for the demo

Everything below is configuration in Railway and in the outside accounts — the code for each integration is already
built and tested. Work top to bottom: the first three steps take minutes, the WhatsApp steps wait on Meta.

## 1. Real AI (5 minutes)

1. console.anthropic.com → **API keys → Create key**. Add credits under **Billing**, and set a monthly limit.
2. Railway → hub service → **Variables**:
   ```
   AI_PROVIDER=anthropic
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   The default model is `claude-haiku-5-5` (fast and cheap for a room). For richer writing set `AI_MODEL=claude-sonnet-5-5`.
3. **Voice notes** (onboarding by voice, English polisher, Sales Training Gym, SOPs) need speech-to-text from OpenAI or
   Google: add `OPENAI_API_KEY=sk-...` (platform.openai.com → API keys) or `GEMINI_API_KEY=...` (aistudio.google.com).

Test: log in → **AI Writer → Write this week's posts**. The posts are written for that business, different every time.

## 1b. Photos on owners' websites (2 minutes)

pexels.com/api → **Your API key** (free, instant). Railway → Variables → `PEXELS_API_KEY=...`. New websites get
professional stock photos matching the business; existing ones get them on their next visit. Owners can upload their
own photos in **Website → Photos** at any time — those always win over stock photos.

## 2. Logins without codes on screen (2 minutes)

Remove `DEMO_PHONES`, and add a password for the demo accounts:

```
DEMO_PASSWORD=<at least 8 characters>
```

After the redeploy the speaker logs in on the **Email** tab:

| Email | Business |
|---|---|
| legacy@demo.hub | Shree Ganesh Interiors — LegacyWorkforce (everything) |
| growth@demo.hub | Sharma Modular Kitchens — Growth Mentorship |
| running@demo.hub | Patel Sweets & Farsan — Running the Business |
| program@demo.hub | Arora Traders — Action Program |
| member@demo.hub | Kapoor Dental Clinic — Membership |
| free@demo.hub | Mehta Engineering Works — Free |
| manager@demo.hub / staff@demo.hub | Priya / Suresh on Shree Ganesh's team |
| admin@demo.hub | Admin |

Anyone in the room can create their own hub on **Log in → Email → Create a free account**, or with their mobile number
once WhatsApp codes work (step 4).

## 3. Websites at name.employz.ai (about 1 hour, mostly waiting)

1. Railway → hub service → **Settings → Networking → Custom Domain** → `*.employz.ai`.
2. Railway shows two records. At the DNS provider of employz.ai add exactly those: a **CNAME** for `*` and the
   `_acme-challenge` CNAME. On Cloudflare set both to **DNS only** (grey cloud).
3. When Railway shows the certificate as issued, add `SITES_DOMAIN=employz.ai` in Variables.
4. Open `https://shree-ganesh-interiors.employz.ai` — the website loads with a valid padlock.

Sub-domains Employz.ai already uses keep working: a specific DNS record always wins over the wildcard. If one of them is
also a name an owner could pick, add it to `RESERVED_SUBDOMAINS`.

## 4. The hub's WhatsApp on AiSensy (1 hour of work, then Meta approval — up to 48 h)

The hub's own number only ever messages **owners**: login codes, new-inquiry alerts, the morning digest, owner alerts.

1. AiSensy → **Manage → Templates → New**. Create these four (body text can be reworded; the order of `{{n}}` can't):

   | Name | Category | Body |
   |---|---|---|
   | `hub_login_code` | **Authentication** | `{{1}} is your verification code. For your security, do not share this code.` + *Copy code* button |
   | `hub_new_inquiry` | Utility | `New inquiry for {{1}}` / `Name: {{2}}` / `Phone: {{3}}` / `Message: {{4}}` / `Reply from your Leads inbox in the Action Hub.` |
   | `hub_digest` | Utility | `Good morning from your Action Hub, {{1}}.` / `{{2}}` / `Open the hub for details.` |
   | `hub_owner_alert` | Utility | `Update for {{1}}:` / `{{2}}` / `Open the Action Hub to see it.` |

2. When each is **Approved**: **Campaigns → Launch → API Campaign** → pick the template → **Live**. Note each campaign's name.
3. AiSensy → **Manage → API key**. Then in Railway:
   ```
   AISENSY_API_KEY=...
   AISENSY_OTP_CAMPAIGN=<login code campaign name>
   AISENSY_OTP_BUTTON=true
   AISENSY_LEAD_ALERT_CAMPAIGN=<new inquiry campaign name>
   AISENSY_DIGEST_CAMPAIGN=<digest campaign name>
   AISENSY_OWNER_ALERT_CAMPAIGN=<owner alert campaign name>
   ```
4. Test: log in on the **Mobile number** tab with your own phone — the code arrives on WhatsApp within seconds. Send an
   inquiry from a demo website — the owner's number gets the alert. (The demo businesses use made-up numbers; to see an
   alert yourself, sign up your own business and send yourself an inquiry.)

Until the templates are approved, nothing breaks: logins work by email, and alerts still appear inside the hub.

## 5. A Growth Mentorship owner on their own accounts (per owner)

Admin → **Pulse** → the owner → **Connections**. Each connection has **Save** and **Test**, and its own webhook address
with a copy button. The full steps are DG-13 to DG-15 in the developer guide; in short:

- **WhatsApp (their own AiSensy number)** — six templates (`tpl_instant`, `tpl_followup`, `tpl_reminder`, `tpl_review`,
  `tpl_customer`, `tpl_campaign`) launched as API campaigns, the API key, and for two-way AI chat the project id and
  project API password. Paste the connection's webhook address into AiSensy's webhook settings.
- **Employz.ai CRM** — a sub-account from the Football Field snapshot: Location ID, a private integration token
  (`contacts.write`, `contacts.readonly`, `opportunities.write`, `opportunities.readonly`), pipeline id and the five
  stage ids. **Test** lists the pipelines it can see.
- **AI Telecaller (ElevenLabs)** — an agent built from the hub's *Telecalling script* tool, a Twilio number or SIP trunk
  assigned to it, the API key, agent id, phone number id and calling hours. Add the connection's webhook address as a
  post-call webhook in ElevenLabs and paste its secret back.

The demo business *Sharma Modular Kitchens* (growth@demo.hub) has placeholder connections; replace them with a real
owner's accounts to show live AI replies and calls.

## Not set up yet

- **Payments (Razorpay)** — without keys, *Upgrade* opens *Talk to us* and the request appears on Admin → Pulse. Steps:
  DG-09 in the developer guide.
- **SMS backup for login codes (MSG91)** — needs DLT registration (2–7 days).

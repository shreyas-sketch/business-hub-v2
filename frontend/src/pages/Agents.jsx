import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ago, api } from "../api.js";
import { Busy, Field, Gate, Sheet, Switch, canAct, useHub, useLoad } from "../ui.jsx";

// The fields PUT /api/business accepts; everything else on the business record is left as it is.
const BUSINESS_FIELDS = ["name", "city", "industry", "offers", "ideal_customer", "why_us", "proof", "whatsapp", "email", "language", "review_link", "payment_note"];

const when = (iso) => new Date(iso).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
const STATE = { done: "done", paused: "wait", skipped: "wait", failed: "fail" };

function AgentCard({ a, data, owner, onChange }) {
  const { upgrade, toast } = useHub();
  const working = a.available && a.on && !a.info_only;
  const set = async (body) => { await api(`/agents/${a.key}`, { method: "PATCH", body }); onChange(); };
  return (
    <div className={`panel ${working ? "active" : ""}`}>
      <div className="row between">
        <h3>{a.name}</h3>
        <span className={`token ${working ? "" : "grey"}`}>{!a.available ? a.tier_name : a.info_only ? "Meetings" : a.on ? "On" : "Off"}</span>
      </div>
      <p className="small">{a.what}</p>
      <span className="small muted">{a.when}</span>

      {!a.available ? (
        <div className="row between">
          <span className="small muted">Unlocks with <b>{a.tier_name}</b></span>
          {owner ? <button className="btn sm money" onClick={() => upgrade(a.tier, a.feature)}>See {a.tier_name}</button>
            : <span className="small muted">Ask the owner to upgrade.</span>}
        </div>
      ) : a.info_only ? (
        <span className="small muted">It runs when you process a meeting's notes. <Link to="/meetings">Go to Meetings</Link></span>
      ) : (
        <>
          <Switch checked={a.on} disabled={!owner} label={a.on ? "Switched on" : "Switched off"} onChange={(v) => set({ on: v }).catch((e) => { if (!e.handled) toast(e.message, "err"); })} />
          {a.approvals ? (
            <div className="stack" style={{ gap: 8 }}>
              <span className="label">Before it messages a customer</span>
              {owner ? (
                <div className="row">
                  <Busy className={`btn sm ${a.autonomy === "ask" ? "primary" : "ghost"}`} run={() => set({ autonomy: "ask" })}>Ask first</Busy>
                  <Busy className={`btn sm ${a.autonomy === "act" ? "primary" : "ghost"}`} disabled={!data.can_act} run={() => set({ autonomy: "act" })}>Act on its own</Busy>
                </div>
              ) : <span className="token grey">{a.autonomy === "act" ? "Acts on its own" : "Asks first"}</span>}
              {!data.can_act && (
                <span className="hint">Acting on its own, without waiting for you, is part of {data.act_tier_name}.{" "}
                  {owner && <button className="btn sm ghost" onClick={() => upgrade(data.act_tier, "agents_act")}>See {data.act_tier_name}</button>}
                </span>
              )}
            </div>
          ) : a.customer_facing ? <span className="hint">Sends on its own: one approved welcome message from the hub's WhatsApp.</span> : null}
          <span className="small muted">
            {a.last_run_at ? <>Last run {ago(a.last_run_at)}{a.last_note ? `: ${a.last_note}` : ""}</> : "Hasn't run yet."}
            {a.on && a.next_run_at ? <> · Next {when(a.next_run_at)}</> : null}
          </span>
        </>
      )}
    </div>
  );
}

function Needs() {
  const { toast } = useHub();
  const [b, setB] = useState(null);
  useEffect(() => { api("/business").then(setB).catch(() => setB({})); }, []);
  if (!b) return null;
  const save = async () => {
    const body = Object.fromEntries(BUSINESS_FIELDS.filter((k) => b[k] !== undefined && b[k] !== null).map((k) => [k, b[k]]));
    const saved = await api("/business", { method: "PUT", body });
    setB(saved);
    toast("Saved. Your agents will use these from now on.");
  };
  return (
    <div className="panel">
      <span className="label">What your agents need</span>
      <div className="grid2">
        <Field label="Your review link" hint="Where happy customers leave a review, e.g. your Google review link. The review request agent sends it.">
          <input className="input" maxLength={300} placeholder="https://g.page/r/…/review" value={b.review_link || ""} onChange={(e) => setB({ ...b, review_link: e.target.value })} />
        </Field>
        <Field label="How customers pay you" hint="Goes into every payment reminder, e.g. a UPI ID or bank details.">
          <input className="input" maxLength={200} placeholder="Pay by UPI to yourname@okicici" value={b.payment_note || ""} onChange={(e) => setB({ ...b, payment_note: e.target.value })} />
        </Field>
      </div>
      <div><Busy className="btn primary" disabled={!b.name} run={save}>Save</Busy></div>
    </div>
  );
}

function Activity({ list }) {
  if (!list) return null;
  return (
    <div className="panel flat">
      <span className="label">Recent activity</span>
      {!list.length ? <span className="small muted">Nothing yet. Your agents' work will show up here.</span> : (
        <div className="timeline">
          {list.map((e) => (
            <div key={e.id} className={STATE[e.status] || ""}>
              <span className="small muted">{e.agent_name} · {ago(e.at)}</span>
              <span className="small">{e.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentsInner() {
  const { me } = useHub();
  const [data, reload] = useLoad("/agents");
  const [activity, reloadActivity] = useLoad("/agents/activity");
  const owner = canAct(me, "owner");
  const working = (data?.agents || []).filter((a) => a.available && a.on && !a.info_only).length;
  const title = !data ? <>Your AI <em>agents</em>.</>
    : working ? <>{working} {working === 1 ? "agent is" : "agents are"} <em>working</em> for you.</>
    : <>Agents that do the routine <em>work</em>.</>;
  return (
    <Sheet kicker="Agents" id="AG-01" pillar="Scale" title={title}
      sub="Each agent does one routine job on its own. Anything that goes to a customer waits in Approvals until you send it — unless you let it act on its own.">
      {data && (
        <div className="grid2">
          {data.agents.map((a) => <AgentCard key={a.key} a={a} data={data} owner={owner} onChange={() => { reload(); reloadActivity(); }} />)}
        </div>
      )}
      {owner && <Needs />}
      <Activity list={activity} />
    </Sheet>
  );
}

export default function Agents() {
  return (
    <Gate role="manager" kicker="Agents" id="AG-01">
      <AgentsInner />
    </Gate>
  );
}

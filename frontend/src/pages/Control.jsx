import React from "react";
import { Link } from "react-router-dom";
import { inr, rs } from "../api.js";
import { Sheet, Stat, useHub, useLoad } from "../ui.jsx";
import { Loading } from "../v2.jsx";
import "./running.css";

const STAGES = [
  ["identification", "Identification", "New, not yet qualified"], ["logic", "Logic", "Reason to buy found"], ["pain", "Pain", "Cost of waiting clear"],
  ["vision", "Vision", "Solution shown"], ["close", "Close", "Asked for the order"],
];
const n = (x) => new Intl.NumberFormat("en-IN").format(x || 0);

/** How far through the month we are today, as a percentage: where an even pace would put the sales. */
function evenPace() {
  const now = new Date();
  const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  return Math.round(((now.getDate() - 1 + now.getHours() / 24) / days) * 100);
}

export default function Control() {
  const { me } = useHub();
  const [d] = useLoad("/control");
  const title = !d ? <>Your business on one <em>screen</em>.</>
    : d.target ? <>{d.target_pct}% of this month's <em>target</em>.</>
    : <>Your business on one <em>screen</em>.</>;
  const maxN = d ? Math.max(1, ...STAGES.map(([k]) => d.pipeline?.[k]?.n || 0)) : 1;
  const open = d ? STAGES.reduce((s, [k]) => s + (d.pipeline?.[k]?.n || 0), 0) : 0;
  const pace = evenPace();
  return (
    <Sheet kicker="Start · Control Room" id="GM-02" pillar="Start" money title={title}
      sub="Sales against target, the pipeline, this week's chats and calls, and the money still owed — on one screen.">
      {!d ? <Loading /> : (
        <>
          <div className="rb-ceo">
            <span className="label">This week in one line</span>
            <p>{d.ceo_line}</p>
            <span className="small muted">Every Monday morning the CEO report sends you this line on WhatsApp.</span>
          </div>

          <div className="grid2" style={{ alignItems: "stretch" }}>
            <div className="panel">
              <span className="label">Sales this month</span>
              <div className="row" style={{ alignItems: "baseline", gap: 10 }}>
                <span className="num money">{rs(d.won_value)}</span>
                {d.target > 0 && <span className="muted">of {rs(d.target)} target</span>}
              </div>
              {d.target > 0 ? (
                <>
                  <div className="meter lg money" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, d.target_pct || 0)} aria-label="Sales against target">
                    <i style={{ width: `${Math.min(100, d.target_pct || 0)}%` }} />
                  </div>
                  <span className="small muted">
                    {d.won} {d.won === 1 ? "deal" : "deals"} won · {d.days_left} {d.days_left === 1 ? "day" : "days"} left · an even pace would be {pace}% today
                  </span>
                </>
              ) : (
                <span className="small muted">
                  {d.won} {d.won === 1 ? "deal" : "deals"} won this month. Set a monthly target{me.features?.magic_number ? <> in <Link to="/magic">Magic number</Link></> : ""} to see how far along you are.
                </span>
              )}
            </div>
            <div className="panel">
              <span className="label">Money</span>
              <div className="stack" style={{ gap: 8 }}>
                <div className="row between"><span className="muted">Owed to you</span><span className="money">{inr(d.money?.owed)}</span></div>
                <div className="row between"><span className="muted">Overdue</span><span className="money">{inr(d.money?.overdue)}</span></div>
                <div className="row between"><span className="muted">Collected this month</span><span className="money">{inr(d.money?.collected)}</span></div>
              </div>
              {me.features?.money_owed && <Link className="small" to="/money">See who owes what</Link>}
            </div>
          </div>

          <div className="panel">
            <div className="row between">
              <span className="label">Open pipeline · {n(open)} {open === 1 ? "deal" : "deals"}</span>
              <span className="money">{rs(d.open_value)}</span>
            </div>
            <div className="rb-stages">
              {STAGES.map(([k, label, what]) => {
                const s = d.pipeline?.[k] || { n: 0, value: 0 };
                return (
                  <div key={k} className="rb-stage" title={`${label}: ${n(s.n)} ${s.n === 1 ? "deal" : "deals"}, ${rs(s.value)}`}>
                    <div className="stack" style={{ gap: 0 }}><span className="small">{label}</span><span className="small muted">{what}</span></div>
                    <div className="track" aria-hidden="true"><i style={{ width: s.n ? `${Math.max(2, (s.n / maxN) * 100)}%` : 0 }} /></div>
                    <span className="nums small">{n(s.n)} · <span className="money">{rs(s.value)}</span></span>
                  </div>
                );
              })}
            </div>
            {me.features?.pipeline && <Link className="small" to="/pipeline">Open the pipeline</Link>}
          </div>

          <span className="label">This week</span>
          <div className="statgrid">
            <Stat label="New leads" value={n(d.new_leads_week)} />
            <Stat label="WhatsApp chats" value={n(d.chats?.this_week)} note={d.chats?.waiting_for_person ? `${d.chats.waiting_for_person} need you` : "None need you"} />
            <Stat label="AI replies" value={n(d.chats?.ai_replies)} note="on your WhatsApp" />
            <Stat label="Calls" value={n(d.calls?.this_week)} note={`${n(d.calls?.connected)} connected`} />
            <Stat label="AI staff actions" value={n(d.ai_actions_week)} />
            <Stat label="In your Send list" value={n(d.send_list)} note="waiting for one tap" />
          </div>
          <div className="row small">
            {me.features?.whatsapp_ai && <Link to="/chats">Open chats</Link>}
            {me.features?.approvals && <Link to="/approvals">Open the Send list</Link>}
            {me.features?.ai_staff && <Link to="/staff">See your AI staff</Link>}
          </div>
        </>
      )}
    </Sheet>
  );
}

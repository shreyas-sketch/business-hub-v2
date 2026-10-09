import React from "react";
import { Link } from "react-router-dom";
import { day } from "../api.js";
import { Sheet, useHub, useLoad } from "../ui.jsx";
import { Loading, Pill } from "../v2.jsx";
import "./running.css";

// Where to see each step once it's done: [path, the feature that opens it].
const SEE = {
  m1_employz: ["/crm", "crm_sync"], m1_domain: ["/website", "website"], m1_whatsapp: ["/chats", "whatsapp_ai"], m1_brain: ["/company-brain", "company_brain"],
  m1_customers: ["/customers", "customers"], m2_sales: ["/staff", "ai_staff"], m3_voice: ["/staff", "ai_staff"], m4_content: ["/calendar", "content_calendar"],
  m5_cash: ["/staff", "ai_staff"], m6_team: ["/team", "team_logins"],
};
const MONTH_MS = 30.44 * 864e5;

export default function Setup() {
  const { me } = useHub();
  const [d] = useLoad("/setup");
  const title = !d ? <>Your setup, done <em>for you</em>.</>
    : d.done >= d.total ? <>Your setup is <em>complete</em>.</>
    : <>{d.done} of {d.total} steps <em>done</em>.</>;
  const start = d?.started_at ? new Date(d.started_at) : null;
  const monthFrom = (m) => { const x = new Date(start); x.setMonth(x.getMonth() + m - 1); return x.toISOString(); };
  const current = start ? Math.min(6, Math.max(1, Math.floor((Date.now() - start) / MONTH_MS) + 1)) : null;
  const months = [1, 2, 3, 4, 5, 6].map((m) => ({ m, steps: (d?.steps || []).filter((s) => s.month === m) })).filter((x) => x.steps.length);
  const next = (d?.steps || []).find((s) => !s.done);
  return (
    <Sheet kicker="Start · Your setup" id="GM-01" pillar="Start" title={title}
      sub="Our team sets these up for you over the first six months. Each step is ticked here the day it's done — there's nothing for you to tick.">
      {!d ? <Loading /> : (
        <>
          <div className="panel">
            <div className="row between">
              <span className="label">Progress</span>
              <span className="small muted">{Math.round((d.done / Math.max(d.total, 1)) * 100)}% · {d.total - d.done} to go</span>
            </div>
            <div className="meter lg" role="progressbar" aria-valuemin={0} aria-valuemax={d.total} aria-valuenow={d.done} aria-label="Setup steps done">
              <i style={{ width: `${(d.done / Math.max(d.total, 1)) * 100}%` }} />
            </div>
            {next && <p className="small">Next up: <b>{next.label}</b> <span className="muted">· month {next.month}</span></p>}
            {start && <p className="small muted">Your setup started on {day(d.started_at)}.</p>}
          </div>
          <div className="rb-months">
            {months.map(({ m, steps }) => {
              const done = steps.every((s) => s.done);
              return (
                <div key={m} className={`rb-month ${current === m && !done ? "now" : ""}`}>
                  <div className="when">
                    <span className="label">Month</span>
                    <b>{m}</b>
                    {start && <span className="small muted">from {day(monthFrom(m))}</span>}
                    {done ? <span><Pill kind="on">Done</Pill></span> : current === m ? <span><Pill>Now</Pill></span> : null}
                  </div>
                  <div>
                    {steps.map((s) => {
                      const see = SEE[s.key];
                      return (
                        <div key={s.key} className="rb-step">
                          <span className={`rb-tick ${s.done ? "done" : ""}`} role="img" aria-label={s.done ? "Done" : "Not done yet"}>{s.done ? "✓" : ""}</span>
                          <div className="stack" style={{ gap: 2 }}>
                            <span style={{ color: s.done ? "var(--paper)" : "var(--grey)" }}>{s.label}</span>
                            {s.note && <span className="small muted">{s.note}</span>}
                            {s.done && (
                              <span className="small muted">
                                {s.done_at ? `Done ${day(s.done_at)}` : "Done"}
                                {see && me.features?.[see[1]] && <> · <Link to={see[0]}>See it</Link></>}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </Sheet>
  );
}

import React from "react";
import { inr, rs } from "../api.js";
import { Sheet, Stat, useLoad } from "../ui.jsx";
import { Empty, Loading } from "../v2.jsx";
import "./running.css";

const n = (x) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 }).format(x || 0);
const hrs = (h) => `${n(h)} h`;

export default function Results() {
  const [d] = useLoad("/results");
  const m = d?.this_month;
  const title = !m ? <>What your AI staff <em>did</em>.</>
    : m.hours_saved >= 1 ? <>{n(m.hours_saved)} hours <em>saved</em> this month.</>
    : <>What your AI staff <em>did</em>.</>;
  return (
    <Sheet kicker="AI team · AI results" id="GM-05" pillar="AI team" money title={title}
      sub="Every month: the hours your AI staff saved you, the leads and chats they handled, the calls they made and the money that came in.">
      {!d ? <Loading /> : (
        <>
          <span className="label">{m.label}</span>
          <div className="statgrid">
            <Stat label="Hours saved" value={hrs(m.hours_saved)} note="time a person would have spent" />
            <Stat label="Leads handled" value={n(m.leads_handled)} note="replied, followed up or called" />
            <Stat label="AI WhatsApp replies" value={n(m.ai_replies)} note={`in ${n(m.chats)} ${m.chats === 1 ? "chat" : "chats"}`} />
            <Stat label="Calls made" value={n(m.calls)} note="by the AI Telecaller" />
            <Stat label="Messages sent" value={n(m.messages_sent)} note="from your Send list" />
            <Stat label="Drafts written" value={n(m.drafts)} note="posts, replies, quotations…" />
            <Stat label="Deals won after AI follow-up" value={n(m.deals_touched)} note={m.revenue_touched ? `worth ${rs(m.revenue_touched)}` : "None yet this month"} />
            <Stat label="Money collected" value={inr(m.money_collected)} money note="marked paid in Money owed" />
          </div>
          <p className="small muted">{n(m.actions)} AI staff {m.actions === 1 ? "action" : "actions"} this month. On the 1st of every month, last month's report is saved here and a note appears in your hub.</p>

          <span className="label">Past months</span>
          {!d.past?.length ? <Empty>Your first monthly report is saved here on the 1st.</Empty> : (
            <table className="t cards">
              <thead><tr><th>Month</th><th>Hours saved</th><th>Leads handled</th><th>Calls</th><th>Deals won</th><th>Collected</th></tr></thead>
              <tbody>{d.past.map((p) => (
                <tr key={p.month}>
                  <td><b>{p.label || p.month}</b></td>
                  <td data-l="Hours saved">{hrs(p.hours_saved)}</td>
                  <td data-l="Leads handled">{n(p.leads_handled)}</td>
                  <td data-l="Calls">{n(p.calls)}</td>
                  <td data-l="Deals won">{n(p.deals_touched)}{p.revenue_touched ? <span className="money small"> · {rs(p.revenue_touched)}</span> : null}</td>
                  <td data-l="Collected"><span className="money">{inr(p.money_collected)}</span></td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </>
      )}
    </Sheet>
  );
}

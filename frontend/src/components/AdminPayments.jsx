// Admin payments desk: revenue, payments, and referral commissions (approve → pay by UPI → mark paid with the UTR).
// Sits inside the admin page; it brings its own data and needs no props.
import React, { useState } from "react";
import { api, day, localPhone } from "../api.js";
import { paise } from "../billing.js";
import { Busy, Copy, Field, Modal, Stat, useHub, useLoad } from "../ui.jsx";

const CM_TABS = [["pending", "Pending"], ["approved", "Approved"], ["paid", "Paid"], ["void", "Void"], ["", "All"]];
const PAY_TABS = [["paid", "Paid"], ["refunded", "Refunded"], ["created", "Not completed"], ["", "All"]];

function cmState(c) {
  if (c.status === "pending") return c.ready ? ["Ready to approve", ""] : [`Held until ${day(c.available_at)}`, "grey"];
  if (c.status === "approved") return ["Approved · to pay", ""];
  if (c.status === "paid") return [`Paid ${day(c.paid_at)}`, ""];
  return [`Void${c.void_reason ? ` · ${c.void_reason}` : ""}`, "grey"];
}

function MarkPaid({ items, onClose, onDone }) {
  const [reference, setReference] = useState("");
  const total = items.reduce((s, c) => s + c.amount, 0);
  const upis = [...new Set(items.map((c) => c.referrer.upi_id).filter(Boolean))];
  return (
    <Modal onClose={onClose}>
      <span className="kicker">Commission payout</span>
      <h2>Mark <em>paid</em>.</h2>
      <p className="sub">{items.length} {items.length === 1 ? "commission" : "commissions"} · <span className="money">{paise(total)}</span>.
        Send the money first, then enter the UPI or bank reference (UTR). The owner gets a note with it.</p>
      {upis.length > 0 && <div className="row">{upis.map((u) => <span key={u} className="row" style={{ gap: 6 }}><span className="mono">{u}</span><Copy text={u} className="btn sm ghost" /></span>)}</div>}
      {upis.length > 1 && <p className="small muted">These go to different UPI IDs. Mark each owner's payout separately so each gets the right reference.</p>}
      <Field label="UPI / bank reference (UTR)"><input className="input mono" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. 428917365012" /></Field>
      <div className="row">
        <Busy className="btn primary" disabled={reference.trim().length < 3} run={async () => {
          const r = await api("/admin/commissions/mark-paid", { method: "POST", body: { ids: items.map((c) => c.id), reference: reference.trim() } });
          onDone(r);
        }}>Mark paid</Busy>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function Commissions({ reloadRevenue }) {
  const { toast } = useHub();
  const [status, setStatus] = useState("pending");
  const [data, reload] = useLoad(`/admin/commissions?status=${status}`, [status]);
  const [picked, setPicked] = useState([]);
  const [paying, setPaying] = useState(null);
  const rows = data?.commissions || [];
  const chosen = rows.filter((c) => picked.includes(c.id));
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const after = () => { setPicked([]); reload(); reloadRevenue(); };
  const report = (done, skipped, verb) => toast(`${done.length} ${verb}${skipped.length ? ` · ${skipped.length} skipped (${[...new Set(skipped.map((s) => s.reason))].join(", ")})` : ""}`, skipped.length && !done.length ? "err" : "ok");

  const approve = async (ids) => {
    const r = await api("/admin/commissions/approve", { method: "POST", body: { ids } });
    report(r.approved, r.skipped, "approved");
    after();
  };
  const voidOne = async (c) => {
    const reason = window.prompt(`Void ${paise(c.amount)} for ${c.referrer.business}? Reason (optional):`, "");
    if (reason === null) return;
    await api(`/admin/commissions/${c.id}/void`, { method: "POST", body: { reason } });
    toast("Commission voided");
    after();
  };

  return (
    <div className="panel">
      <div className="row between">
        <span className="label">Referral commissions</span>
        <div className="tabs">{CM_TABS.map(([k, l]) => <button key={k || "all"} className={status === k ? "on" : ""} onClick={() => { setStatus(k); setPicked([]); }}>{l}</button>)}</div>
      </div>
      {chosen.length > 0 && (
        <div className="notice">
          <span className="small">{chosen.length} selected · <span className="money">{paise(chosen.reduce((s, c) => s + c.amount, 0))}</span></span>
          <div className="row">
            {chosen.some((c) => c.ready) && <Busy className="btn sm" run={() => approve(chosen.filter((c) => c.ready).map((c) => c.id))}>Approve</Busy>}
            {chosen.some((c) => c.status === "approved") && <button className="btn sm money" onClick={() => setPaying(chosen.filter((c) => c.status === "approved"))}>Mark paid</button>}
          </div>
        </div>
      )}
      {!data ? <p className="muted">Loading…</p> : rows.length ? (
        <table className="t cards">
          <thead><tr><th></th><th>Earned by</th><th>From</th><th>Amount</th><th>Status</th><th></th></tr></thead>
          <tbody>{rows.map((c) => {
            const [label, tone] = cmState(c);
            const selectable = c.ready || c.status === "approved";
            return (
              <tr key={c.id}>
                <td>{selectable && <input type="checkbox" aria-label="Select" checked={picked.includes(c.id)} onChange={() => toggle(c.id)} />}</td>
                <td><b>{c.referrer.business}</b><div className="small muted mono">{localPhone(c.referrer.phone)}</div>
                  {c.referrer.upi_id ? <div className="row" style={{ gap: 6 }}><span className="mono">{c.referrer.upi_id}</span><Copy text={c.referrer.upi_id} className="btn sm ghost" /></div>
                    : <div className="small muted">No UPI ID yet</div>}
                  {c.referrer.payout_name && <div className="small muted">{c.referrer.payout_name}</div>}</td>
                <td data-l="From"><div>{c.friend}</div><div className="small muted">{c.tier_name} · <span className="money">{paise(c.payment_amount)}</span> · {day(c.created_at)}</div></td>
                <td data-l={`${c.percent}%`}><span className="money">{paise(c.amount)}</span>
                  {c.clawback && <div className="small muted">Refunded after payout: recover <span className="money">{paise(c.clawback_amount)}</span></div>}</td>
                <td data-l="Status"><span className={`token ${tone}`}>{label}</span>
                  {c.reference && <div className="small muted mono">Ref {c.reference}</div>}
                  {c.payment_status === "refunded" && c.status !== "void" && <div className="small muted">Payment refunded</div>}</td>
                <td><div className="row">
                  {c.ready && <Busy className="btn sm" run={() => approve([c.id])}>Approve</Busy>}
                  {c.status === "approved" && <button className="btn sm money" onClick={() => setPaying([c])}>Mark paid</button>}
                  {(c.status === "pending" || c.status === "approved") && <Busy className="btn sm ghost" run={() => voidOne(c)}>Void</Busy>}
                </div></td>
              </tr>
            );
          })}</tbody>
        </table>
      ) : <div className="empty"><p className="muted">Nothing here.</p></div>}
      {paying && <MarkPaid items={paying} onClose={() => setPaying(null)} onDone={(r) => { setPaying(null); report(r.paid, r.skipped, "marked paid"); after(); }} />}
    </div>
  );
}

function Payments({ days }) {
  const [status, setStatus] = useState("paid");
  const [rows] = useLoad(`/admin/payments?status=${status}&days=${days}`, [status, days]);
  return (
    <div className="panel">
      <div className="row between">
        <span className="label">Payments · {days} days</span>
        <div className="tabs">{PAY_TABS.map(([k, l]) => <button key={k || "all"} className={status === k ? "on" : ""} onClick={() => setStatus(k)}>{l}</button>)}</div>
      </div>
      {!rows ? <p className="muted">Loading…</p> : rows.length ? (
        <table className="t cards">
          <thead><tr><th>Owner</th><th>Plan</th><th>Amount</th><th>Status</th><th>Date</th></tr></thead>
          <tbody>{rows.map((p) => (
            <tr key={p.id}>
              <td><b>{p.business}</b><div className="small muted mono">{localPhone(p.phone)}</div></td>
              <td data-l="Plan">{p.tier_name}<div className="small muted">{p.kind === "subscription" ? "monthly charge" : p.kind === "dev" ? "test payment" : "one-time"}</div></td>
              <td data-l="Amount"><span className="money">{paise(p.amount)}</span>
                {p.refunded_amount ? <div className="small muted"><span className="money">{paise(p.refunded_amount)}</span> refunded</div> : null}</td>
              <td data-l="Status"><span className={`token ${p.status === "paid" ? "" : "grey"}`}>{p.status === "created" ? "not completed" : p.status}</span></td>
              <td data-l="Date" className="small muted">{day(p.paid_at || p.created_at)}<div className="mono">{p.rzp_payment_id || p.rzp_order_id || ""}</div></td>
            </tr>
          ))}</tbody>
        </table>
      ) : <div className="empty"><p className="muted">No payments in this period.</p></div>}
    </div>
  );
}

export default function AdminPayments() {
  const [days, setDays] = useState(30);
  const [rev, reloadRevenue] = useLoad(`/admin/revenue?days=${days}`, [days]);
  return (
    <div className="stack">
      <div className="row between">
        <span className="label">Revenue</span>
        <div className="tabs">{[7, 30, 90].map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d} days</button>)}</div>
      </div>
      {rev && (
        <>
          <div className="statgrid">
            <Stat label={`Paid · ${days} days`} value={paise(rev.paid_total)} money note={`${rev.payments} ${rev.payments === 1 ? "payment" : "payments"}`} />
            <Stat label="Members" value={rev.members_active} note="Membership active now" />
            <Stat label="Monthly recurring" value={paise(rev.mrr)} money note="Memberships that renew" />
            <Stat label={`Refunds · ${days} days`} value={paise(rev.refunds)} money />
            <Stat label="Commissions to approve" value={paise(rev.commissions.pending)} money note="Pending, all time" />
            <Stat label="Commissions to pay" value={paise(rev.commissions.approved)} money note={`${paise(rev.commissions.paid)} paid so far`} />
          </div>
          {Object.keys(rev.by_tier).length > 0 && (
            <div className="row">{Object.entries(rev.by_tier).map(([t, v]) => <span key={t} className="token grey">{t} · <span className="money">{paise(v)}</span></span>)}</div>
          )}
          {rev.clawbacks > 0 && <div className="notice"><span className="small">{rev.clawbacks} paid {rev.clawbacks === 1 ? "commission was" : "commissions were"} later refunded. Recover them from the owner's next payout.</span></div>}
        </>
      )}
      <Commissions reloadRevenue={reloadRevenue} />
      <Payments days={days} />
    </div>
  );
}

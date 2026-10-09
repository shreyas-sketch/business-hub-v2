import React, { useState } from "react";
import { Link } from "react-router-dom";
import { api, day, localPhone } from "../api.js";
import { paise as inr } from "../billing.js";
import { Busy, Field, Gate, Sheet, Stat, useHub, useLoad } from "../ui.jsx";

const today = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local time
const blank = () => ({ customer: "", phone: "", amount: "", due_date: today(), invoice_no: "", note: "" });

function AddForm({ onAdded }) {
  const { toast } = useHub();
  const [f, setF] = useState(blank());
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const ready = f.customer.trim().length >= 2 && Number(f.amount) > 0 && f.due_date;
  return (
    <div className="panel active">
      <span className="label">Add money owed</span>
      <div className="grid3">
        <Field label="Customer"><input className="input" maxLength={80} value={f.customer} onChange={set("customer")} placeholder="Ramesh Patel" /></Field>
        <Field label="Amount (₹)"><input className="input" type="number" min="1" step="any" inputMode="decimal" value={f.amount} onChange={set("amount")} placeholder="12500" /></Field>
        <Field label="Due date"><input className="input" type="date" value={f.due_date} onChange={set("due_date")} /></Field>
        <Field label="WhatsApp number (for reminders)"><input className="input" inputMode="tel" maxLength={24} value={f.phone} onChange={set("phone")} placeholder="98200 12345" /></Field>
        <Field label="Invoice no. (optional)"><input className="input" maxLength={40} value={f.invoice_no} onChange={set("invoice_no")} /></Field>
        <Field label="Note (optional)"><input className="input" maxLength={300} value={f.note} onChange={set("note")} placeholder="Kitchen balance payment" /></Field>
      </div>
      <div>
        <Busy className="btn primary" disabled={!ready} run={async () => {
          await api("/money", { method: "POST", body: { ...f, amount: Number(f.amount) } });
          setF(blank());
          toast("Added");
          onAdded();
        }}>Add</Busy>
      </div>
    </div>
  );
}

function MoneyInner() {
  const { me, toast } = useHub();
  const [data, reload] = useLoad("/money");
  const t = data?.totals;
  const patch = async (id, body, msg) => { await api(`/money/${id}`, { method: "PATCH", body }); toast(msg); reload(); };
  const title = !t ? <>Know who owes you <em>what</em>.</>
    : t.overdue ? <>{inr(t.overdue)} is <em>overdue</em>.</>
    : t.due ? <>Nothing overdue. <em>Good</em>.</>
    : <>Know who owes you <em>what</em>.</>;
  return (
    <Sheet kicker="Systems · Money owed" id="SY-04" pillar="Systems" money title={title}
      sub="Write down every payment a customer still owes you, with the date it's due. Mark it paid when the money comes in.">
      {t && (
        <div className="statgrid">
          <Stat label="Owed to you" value={inr(t.due)} money note={`${t.count_due} unpaid`} />
          <Stat label="Overdue" value={inr(t.overdue)} money note={t.count_overdue ? `${t.count_overdue} past the due date` : "None past the due date"} />
          <Stat label="Collected this month" value={inr(t.collected_month)} money />
        </div>
      )}
      {me.features.reminder_agent
        ? <p className="small muted">The payment reminder automation drafts a polite reminder at 10am for anything past its due date — every few days, up to 4 times — and puts it in your <Link to="/approvals">Send list</Link>. Add how customers pay you on the <Link to="/agents">Automations</Link> page.</p>
        : null}
      {me.features.quotations && <p className="small muted">Invoices you make from a quotation in <Link to="/quotes">Quotations &amp; invoices</Link> appear here on their own.</p>}
      <AddForm onAdded={reload} />
      {data && !data.items.length && <div className="empty"><p className="muted">Nothing owed yet. Add the first payment a customer still has to make.</p></div>}
      {data?.items.length > 0 && (
        <table className="t cards">
          <thead><tr><th>Customer</th><th>Amount</th><th>Due</th><th>Reminders</th><th /></tr></thead>
          <tbody>{data.items.map((d) => (
            <tr key={d.id}>
              <td>
                <b>{d.customer}</b>{d.invoice_no && <span className="small muted"> · {d.invoice_no}</span>}
                {d.phone && <div className="small muted mono">{localPhone(d.phone)}</div>}
                {d.invoice_id && me.features.quotations && (
                  <div className="small"><a href={`/api/quotes/${d.invoice_id}/print`} target="_blank" rel="noreferrer">View invoice{d.invoice_no ? ` ${d.invoice_no}` : ""}</a></div>
                )}
                {d.note && <div className="small muted">{d.note}</div>}
              </td>
              <td data-l="Amount"><span className="money" style={{ fontFamily: "var(--head)", fontSize: 18 }}>{inr(d.amount)}</span></td>
              <td data-l="Due">
                <div className="stack" style={{ gap: 4 }}>
                  <span className="small">{day(d.due_date)}</span>
                  {d.status === "paid" ? <span className="token grey">Paid {day(d.paid_at)}</span>
                    : d.overdue ? <span className="token">Overdue · {d.days_overdue} {d.days_overdue === 1 ? "day" : "days"}</span> : null}
                </div>
              </td>
              <td data-l="Reminders" className="small muted">{d.reminders_sent ? `Reminder ${d.reminders_sent} of 4` : d.status === "due" && !d.phone ? "No number" : "None yet"}</td>
              <td>
                <div className="row">
                  {d.status === "due"
                    ? <Busy className="btn sm primary" run={() => patch(d.id, { status: "paid" }, `Marked ${inr(d.amount)} paid`)}>Mark paid</Busy>
                    : <Busy className="btn sm ghost" run={() => patch(d.id, { status: "due" }, "Marked unpaid")}>Mark unpaid</Busy>}
                  <Busy className="btn sm ghost" run={async () => {
                    if (!window.confirm(`Remove ${d.customer}'s ${inr(d.amount)}?`)) return;
                    await api(`/money/${d.id}`, { method: "DELETE" });
                    toast("Removed");
                    reload();
                  }}>Delete</Busy>
                </div>
              </td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </Sheet>
  );
}

export default function Money() {
  return (
    <Gate feature="money_owed" role="manager" kicker="Systems · Money owed" id="SY-04"
      what="Track every payment a customer owes you, see what's overdue, and let the payment reminder automation chase it politely.">
      <MoneyInner />
    </Gate>
  );
}

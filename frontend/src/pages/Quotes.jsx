import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, day, localPhone, rs, waLink } from "../api.js";
import { Busy, Copy, Field, FormError, Modal, Sheet, canAct, useHub, useLoad } from "../ui.jsx";
import { Empty, Loading, Num, Pill, Tabs } from "../v2.jsx";
import VoiceNote from "../components/VoiceNote.jsx";
import "./running.css";

const GST_RATES = [0, 5, 12, 18, 28];
const MODES = [["intra", "Same state — CGST + SGST"], ["inter", "Another state — IGST"], ["none", "No GST"]];
const Q_STATUS = { draft: ["Draft", "off"], sent: ["Sent", "on"], accepted: ["Accepted", "on"], lost: ["Lost", "off"] };
const todayIso = () => new Date().toLocaleDateString("en-CA");

/** The same sums as the server (desk.py totals): each line rounded to paise, GST per line, CGST/SGST split from the total GST. */
const r2 = (x) => Math.round((x + Number.EPSILON) * 100) / 100;
function totals(items, mode) {
  let sub = 0;
  let gst = 0;
  const amounts = items.map((i) => {
    const amt = r2((Number(i.qty) || 0) * (Number(i.rate) || 0));
    sub += amt;
    gst += mode === "none" ? 0 : r2((amt * (Number(i.gst) || 0)) / 100);
    return amt;
  });
  sub = r2(sub);
  gst = r2(gst);
  const out = { amounts, subtotal: sub, gst, total: r2(sub + gst), cgst: 0, sgst: 0, igst: 0 };
  if (mode === "intra") { out.cgst = r2(gst / 2); out.sgst = r2(gst - out.cgst); }
  else if (mode === "inter") out.igst = gst;
  return out;
}

const blankItem = () => ({ name: "", qty: "1", unit: "nos", rate: "", gst: 18 });
const blankForm = () => ({ customer: { name: "", phone: "", gstin: "", address: "" }, items: [blankItem()], gst_mode: "intra", notes: "", terms: "", valid_days: 15, lead_id: "" });
const fromQuote = (q) => ({
  customer: { name: q.customer?.name || "", phone: q.customer?.phone ? localPhone(q.customer.phone) : "", gstin: q.customer?.gstin || "", address: q.customer?.address || "" },
  items: (q.items || []).map((i) => ({ name: i.name, qty: String(i.qty), unit: i.unit || "nos", rate: i.rate ? String(i.rate) : "", gst: i.gst })),
  gst_mode: q.gst_mode || "intra", notes: q.notes || "", terms: q.terms || "", valid_days: q.valid_days || 15, lead_id: q.lead_id || "",
});

function DraftBox({ onDraft }) {
  const { me, refresh } = useHub();
  const [brief, setBrief] = useState("");
  const [err, setErr] = useState("");
  return (
    <div className="panel flat">
      <span className="label">Draft from a voice note or a few lines</span>
      <textarea className="textarea" maxLength={6000} value={brief} onChange={(e) => setBrief(e.target.value)} aria-label="What the quotation is for"
        placeholder="Kitchen for Mr Shah, Thane: 10 ft modular kitchen, chimney, installation included" />
      <div className="rb-voice">
        <VoiceNote purpose="quote" onText={(t) => setBrief((b) => (b.trim() ? `${b.trim()}\n${t}` : t))} />
        {me.features?.voice_sop && <span className="small muted">Say who it's for and what they want — items, sizes, quantities and any rates you know. Up to 5 minutes; the voice note uses one AI run.</span>}
      </div>
      <FormError msg={err} />
      <div className="row">
        <Busy className="btn" disabled={brief.trim().length < 5} onError={setErr} run={async () => {
          const r = await api("/quotes/draft", { method: "POST", body: { brief: brief.trim() } });
          onDraft(r);
          refresh();
        }}>Draft the quotation</Busy>
        <span className="hint">Drafting uses 1 AI run.{me.features?.company_brain ? " Rates come from your Company Brain where it has them." : ""} Nothing is saved until you press Save.</span>
      </div>
    </div>
  );
}

function Editor({ quote, onClose, onSaved }) {
  const { toast } = useHub();
  const edit = !!quote;
  const [f, setF] = useState(() => (edit ? fromQuote(quote) : blankForm()));
  const [leads, setLeads] = useState([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (edit) return;
    api("/leads").then((l) => setLeads((l || []).filter((x) => x.status === "new" || x.status === "contacted"))).catch(() => {});
  }, [edit]);
  const t = totals(f.items, f.gst_mode);
  const setC = (k) => (e) => setF({ ...f, customer: { ...f.customer, [k]: e.target.value } });
  const setI = (i, k) => (e) => setF({ ...f, items: f.items.map((it, j) => (j === i ? { ...it, [k]: e.target.value } : it)) });
  const named = f.items.filter((i) => i.name.trim());
  const zero = named.filter((i) => !(Number(i.rate) > 0)).length;
  const pickLead = (id) => {
    const l = leads.find((x) => x.id === id);
    setF({ ...f, lead_id: id, customer: l && !f.customer.name.trim() ? { ...f.customer, name: l.name || "", phone: l.phone ? localPhone(l.phone) : "" } : f.customer });
  };
  const fill = (r) => {
    const items = (r.items || []).map((i) => ({ name: i.name, qty: String(i.qty || 1), unit: i.unit || "nos", rate: i.rate ? String(i.rate) : "", gst: GST_RATES.includes(i.gst) ? i.gst : 18 }));
    setF((cur) => ({ ...cur, items: items.length ? items : cur.items, notes: r.notes || cur.notes,
      customer: { ...cur.customer, name: r.customer?.name || cur.customer.name, phone: r.customer?.phone || cur.customer.phone } }));
    toast(r.missing_rates ? `Drafted. ${r.missing_rates} ${r.missing_rates === 1 ? "line needs" : "lines need"} a rate` : "Drafted. Check every line, then save");
  };
  const save = async () => {
    if (f.customer.name.trim().length < 2) throw new Error("Add the customer's name.");
    if (!named.length) throw new Error("Add at least one line with a name.");
    if (named.some((i) => !(Number(i.qty) > 0))) throw new Error("Every line needs a quantity above 0.");
    if (zero && !window.confirm(`${zero} ${zero === 1 ? "line has" : "lines have"} no rate (₹0). Save anyway?`)) return;
    const body = {
      customer: { name: f.customer.name.trim(), phone: f.customer.phone.trim(), gstin: f.customer.gstin.trim().toUpperCase(), address: f.customer.address.trim() },
      items: named.map((i) => ({ name: i.name.trim(), qty: Number(i.qty), unit: i.unit.trim() || "nos", rate: Number(i.rate) || 0, gst: Number(i.gst) })),
      gst_mode: f.gst_mode, notes: f.notes.trim(), terms: f.terms.trim(), valid_days: Number(f.valid_days) || 15, lead_id: f.lead_id || null,
    };
    const q = await api(edit ? `/quotes/${quote.id}` : "/quotes", { method: edit ? "PUT" : "POST", body });
    toast(edit ? `Saved ${q.number}` : `Saved ${q.number} as a draft`);
    onSaved(q);
  };
  return (
    <div className="panel active">
      <div className="row between">
        <h2>{edit ? <>Edit <em>{quote.number}</em></> : <>New <em>quotation</em></>}</h2>
        <button className="btn sm ghost" onClick={onClose}>Cancel</button>
      </div>
      {!edit && <DraftBox onDraft={fill} />}

      <span className="label">Customer</span>
      <div className="grid2">
        <Field label="Name"><input className="input" maxLength={120} value={f.customer.name} onChange={setC("name")} placeholder="Rohit Shah" /></Field>
        <Field label="WhatsApp number"><input className="input" inputMode="tel" maxLength={24} value={f.customer.phone} onChange={setC("phone")} placeholder="98200 12345" /></Field>
        <Field label="Customer GSTIN (optional)"><input className="input mono" maxLength={15} value={f.customer.gstin} onChange={setC("gstin")} placeholder="27ABCDE1234F1Z5" /></Field>
        <Field label="Address (optional)"><input className="input" maxLength={300} value={f.customer.address} onChange={setC("address")} placeholder="Thane West" /></Field>
      </div>
      {!edit && leads.length > 0 && (
        <Field label="Inquiry this is for (optional)" hint="When the quotation is accepted or lost, this lead is marked won or lost.">
          <select className="select" value={f.lead_id} onChange={(e) => pickLead(e.target.value)}>
            <option value="">None</option>
            {leads.map((l) => <option key={l.id} value={l.id}>{l.name}{l.phone ? ` · ${localPhone(l.phone)}` : ""}</option>)}
          </select>
        </Field>
      )}

      <span className="label">Items</span>
      <div className="rb-lines">
        <div className="rb-line head" aria-hidden="true"><span>Item</span><span>Qty</span><span>Unit</span><span>Rate ₹</span><span>GST</span><span style={{ textAlign: "right" }}>Amount</span><span /></div>
        {f.items.map((it, i) => (
          <div key={i} className={`rb-line ${it.name.trim() && !(Number(it.rate) > 0) ? "zero" : ""}`}>
            <label className="rb-cell"><span>Item</span><input className="input" maxLength={160} value={it.name} onChange={setI(i, "name")} aria-label={`Line ${i + 1}: item`} placeholder="Modular kitchen 10 ft" /></label>
            <label className="rb-cell"><span>Qty</span><input className="input" type="number" min="0" step="any" inputMode="decimal" value={it.qty} onChange={setI(i, "qty")} aria-label={`Line ${i + 1}: quantity`} /></label>
            <label className="rb-cell"><span>Unit</span><input className="input" maxLength={20} value={it.unit} onChange={setI(i, "unit")} aria-label={`Line ${i + 1}: unit`} /></label>
            <label className="rb-cell"><span>Rate ₹</span><input className="input rate" type="number" min="0" step="any" inputMode="decimal" value={it.rate} onChange={setI(i, "rate")} aria-label={`Line ${i + 1}: rate in rupees`} placeholder={it.name.trim() ? "Add rate" : ""} /></label>
            <label className="rb-cell"><span>GST</span>
              <select className="select" value={it.gst} disabled={f.gst_mode === "none"} onChange={(e) => setF({ ...f, items: f.items.map((x, j) => (j === i ? { ...x, gst: Number(e.target.value) } : x)) })} aria-label={`Line ${i + 1}: GST rate`}>
                {GST_RATES.map((g) => <option key={g} value={g}>{g}%</option>)}
              </select>
            </label>
            <span className="amt money small">{rs(t.amounts[i])}</span>
            <button className="rb-x" type="button" aria-label={`Remove line ${i + 1}`} disabled={f.items.length === 1} onClick={() => setF({ ...f, items: f.items.filter((_, j) => j !== i) })}>×</button>
          </div>
        ))}
      </div>
      <div className="row between">
        <button className="btn sm" type="button" disabled={f.items.length >= 60} onClick={() => setF({ ...f, items: [...f.items, blankItem()] })}>Add a line</button>
        {zero > 0 && <span className="small" style={{ color: "var(--amber)" }}>{zero} {zero === 1 ? "line needs" : "lines need"} a rate</span>}
      </div>

      <div className="grid2" style={{ alignItems: "start" }}>
        <Field label="GST">
          <select className="select" value={f.gst_mode} onChange={(e) => setF({ ...f, gst_mode: e.target.value })}>
            {MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <div className="rb-totals" aria-live="polite">
          <div><span className="muted">Subtotal</span><span className="money">{rs(t.subtotal)}</span></div>
          {f.gst_mode === "intra" && <><div><span className="muted">CGST</span><span className="money">{rs(t.cgst)}</span></div><div><span className="muted">SGST</span><span className="money">{rs(t.sgst)}</span></div></>}
          {f.gst_mode === "inter" && <div><span className="muted">IGST</span><span className="money">{rs(t.igst)}</span></div>}
          <div className="grand"><span>Total</span><span className="money">{rs(t.total)}</span></div>
        </div>
      </div>

      <div className="grid2">
        <Field label="Valid for (days)"><Num min="1" max="365" step="1" value={f.valid_days} onChange={(v) => setF({ ...f, valid_days: v })} /></Field>
        <Field label="Notes (optional)"><input className="input" maxLength={1000} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="Delivery in 3 weeks" /></Field>
      </div>
      <Field label="Terms (optional)" hint="Leave empty to use the usual terms from your business details.">
        <textarea className="textarea" maxLength={1500} value={f.terms} onChange={(e) => setF({ ...f, terms: e.target.value })} placeholder="50% advance, balance on installation" />
      </Field>
      <FormError msg={err} />
      <div className="row">
        <Busy className="btn primary" onError={setErr} run={save}>{edit ? "Save changes" : "Save quotation"}</Busy>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}

function Settings({ onClose }) {
  const { me, toast } = useHub();
  const [s] = useLoad("/quotes/settings");
  const [f, setF] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { if (s && !f) setF({ gstin: s.gstin || "", address: s.address || "", payment: s.payment || "", terms: s.terms || "" }); }, [s, f]);
  const owner = canAct(me, "owner");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="panel">
      <div className="row between"><span className="label">Your business details on every quotation</span><button className="btn sm ghost" onClick={onClose}>Close</button></div>
      {!f ? <Loading /> : (
        <>
          <div className="grid2">
            <Field label="Your GSTIN"><input className="input mono" maxLength={15} value={f.gstin} onChange={set("gstin")} disabled={!owner} placeholder="27ABCDE1234F1Z5" /></Field>
            <Field label="How customers pay you" hint="UPI id or bank details, printed on quotations and invoices."><input className="input" maxLength={300} value={f.payment} onChange={set("payment")} disabled={!owner} placeholder="UPI shreeganesh@okicici" /></Field>
          </div>
          <Field label="Business address"><textarea className="textarea" style={{ minHeight: 70 }} maxLength={300} value={f.address} onChange={set("address")} disabled={!owner} /></Field>
          <Field label="Usual terms" hint="Used on a quotation when its own terms are left empty."><textarea className="textarea" maxLength={1500} value={f.terms} onChange={set("terms")} disabled={!owner} placeholder="50% advance. Prices valid for 15 days." /></Field>
          <FormError msg={err} />
          {owner ? (
            <div><Busy className="btn primary" onError={setErr} run={async () => {
              await api("/quotes/settings", { method: "PUT", body: { ...f, gstin: f.gstin.trim().toUpperCase(), address: f.address.trim(), payment: f.payment.trim(), terms: f.terms.trim() } });
              toast("Business details saved");
              onClose();
            }}>Save details</Busy></div>
          ) : <p className="small muted">Only the business owner can change these.</p>}
        </>
      )}
    </div>
  );
}

function InvoiceModal({ q, onClose, onDone }) {
  const { me, toast } = useHub();
  const [days, setDays] = useState(7);
  const [err, setErr] = useState("");
  return (
    <Modal onClose={onClose}>
      <span className="kicker">Invoice from {q.number}</span>
      <h2>Make the <em>invoice</em>.</h2>
      <p className="sub">{q.customer?.name} · <span className="money">{rs(q.totals?.total)}</span>. The quotation is marked accepted{me.features?.money_owed ? ", and the invoice is added to Money owed so payment reminders can follow it" : ""}.</p>
      <Field label="Payment due in (days)"><Num min="0" max="365" step="1" value={days} onChange={setDays} /></Field>
      <FormError msg={err} />
      <div className="row">
        <Busy className="btn primary" onError={setErr} run={async () => {
          const inv = await api(`/quotes/${q.id}/invoice`, { method: "POST", body: { due_in_days: Number(days) || 0 } });
          toast(`Invoice ${inv.number} made`);
          onDone(inv);
        }}>Make invoice</Busy>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

const sendLink = (q) => q.whatsapp_link || waLink(q.share_text);

function QuoteCard({ q, onEdit, onInvoice, reload, showInvoices }) {
  const { toast } = useHub();
  const [label, kind] = Q_STATUS[q.status] || [q.status, ""];
  const setStatus = async (status, msg) => { await api(`/quotes/${q.id}/status`, { method: "POST", body: { status } }); toast(msg); reload(); };
  const open = q.status === "draft" || q.status === "sent";
  return (
    <div className="panel" style={{ padding: "16px 18px", gap: 10 }}>
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div className="stack rb-wrap" style={{ gap: 2 }}>
          <span><b>{q.number}</b> · {q.customer?.name}</span>
          <span className="small muted">
            {(q.items || []).length} {(q.items || []).length === 1 ? "line" : "lines"} · made {day(q.created_at)}
            {q.sent_on ? ` · sent ${day(q.sent_on)}` : ""}{q.status === "sent" && q.followups ? ` · follow-up ${q.followups} of 3` : ""}
            {!q.customer?.phone ? " · no number" : ""}
          </span>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <span className="money" style={{ fontFamily: "var(--head)", fontSize: 20 }}>{rs(q.totals?.total)}</span>
          <Pill kind={kind}>{label}</Pill>
        </div>
      </div>
      <div className="row" style={{ gap: 8 }}>
        {open && (
          <a className="btn sm primary" href={sendLink(q)} target="_blank" rel="noreferrer"
            onClick={() => { if (q.status === "draft") setStatus("sent", "Marked as sent").catch(() => {}); }}>
            {q.status === "sent" ? "Send again on WhatsApp" : "Send on WhatsApp"}
          </a>
        )}
        {q.status === "draft" && <Busy className="btn sm" run={() => setStatus("sent", "Marked as sent")}>Mark sent</Busy>}
        {open && <Busy className="btn sm" run={() => setStatus("accepted", `${q.number} accepted`)}>Accepted</Busy>}
        {open && <Busy className="btn sm ghost" run={() => setStatus("lost", `${q.number} marked lost`)}>Lost</Busy>}
        {!q.invoice_id && q.status !== "lost" && <button className="btn sm" onClick={() => onInvoice(q)}>Make invoice</button>}
        {q.invoice_id && <button className="btn sm ghost" onClick={showInvoices}>See the invoice</button>}
        <a className="btn sm ghost" href={`/api/quotes/${q.id}/print`} target="_blank" rel="noreferrer">Print / PDF</a>
        <Copy text={q.share_text} label="Copy text" className="btn sm ghost" />
        {open && <button className="btn sm ghost" onClick={() => onEdit(q)}>Edit</button>}
        {q.status === "draft" && (
          <Busy className="btn sm ghost" run={async () => {
            if (!window.confirm(`Delete draft ${q.number}?`)) return;
            await api(`/quotes/${q.id}`, { method: "DELETE" });
            toast("Deleted");
            reload();
          }}>Delete</Busy>
        )}
      </div>
    </div>
  );
}

function InvoiceRow({ inv, from }) {
  const { me } = useHub();
  const overdue = inv.status === "due" && inv.due_date && inv.due_date < todayIso();
  return (
    <div className="panel" style={{ padding: "16px 18px", gap: 10 }}>
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div className="stack rb-wrap" style={{ gap: 2 }}>
          <span><b>{inv.number}</b> · {inv.customer?.name}</span>
          <span className="small muted">{from ? `From ${from} · ` : ""}{inv.due_date ? `due ${day(inv.due_date)}` : ""}{inv.status === "paid" && inv.paid_at ? ` · paid ${day(inv.paid_at)}` : ""}</span>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <span className="money" style={{ fontFamily: "var(--head)", fontSize: 20 }}>{rs(inv.totals?.total)}</span>
          {inv.status === "paid" ? <Pill kind="on">Paid</Pill> : <Pill kind="money">{overdue ? "Overdue" : "Unpaid"}</Pill>}
        </div>
      </div>
      <div className="row" style={{ gap: 8 }}>
        {inv.status !== "paid" && <a className="btn sm primary" href={sendLink(inv)} target="_blank" rel="noreferrer">Send on WhatsApp</a>}
        <a className="btn sm" href={`/api/quotes/${inv.id}/print`} target="_blank" rel="noreferrer">Print / PDF</a>
        <Copy text={inv.share_text} label="Copy text" className="btn sm ghost" />
        {me.features?.money_owed && <Link className="btn sm ghost" to="/money">{inv.status === "paid" ? "See in Money owed" : "Mark paid in Money owed"}</Link>}
      </div>
    </div>
  );
}

export default function Quotes() {
  const { me } = useHub();
  const [tab, setTab] = useState("quote");
  const [quotes, reloadQ] = useLoad("/quotes?kind=quote");
  const [invoices, reloadI] = useLoad("/quotes?kind=invoice");
  const [editing, setEditing] = useState(null);   // null | "new" | a quotation
  const [settings, setSettings] = useState(false);
  const [invoiceFor, setInvoiceFor] = useState(null);
  const numberOf = Object.fromEntries((quotes || []).map((q) => [q.id, q.number]));
  const waiting = (quotes || []).filter((q) => q.status === "sent").length;
  const title = waiting ? <>{waiting} {waiting === 1 ? "quotation is" : "quotations are"} waiting for a <em>yes</em>.</> : <>GST quotations in <em>minutes</em>.</>;
  const top = () => window.scrollTo({ top: 0, behavior: "smooth" });
  return (
    <Sheet kicker="Systems · Quotations & invoices" id="RB-02" pillar="Systems" money title={title}
      sub="Speak or type what the customer wants; the hub writes the quotation and works out the GST. Send it on WhatsApp, then turn it into an invoice when they say yes."
      actions={!editing && <>
        <button className="btn" onClick={() => setSettings(!settings)}>Business details</button>
        <button className="btn primary" onClick={() => { setEditing("new"); setSettings(false); }}>New quotation</button>
      </>}>
      {me.features?.quote_followup && <p className="small muted">Quote follow-ups on day 2, 5 and 10 after you send a quotation wait in your <Link to="/approvals">Send list</Link>.</p>}
      {settings && !editing && <Settings onClose={() => setSettings(false)} />}
      {editing && (
        <Editor key={editing === "new" ? "new" : editing.id} quote={editing === "new" ? null : editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); setTab("quote"); reloadQ(); top(); }} />
      )}
      {!editing && (
        <>
          <Tabs tabs={[["quote", `Quotations${quotes ? ` · ${quotes.length}` : ""}`], ["invoice", `Invoices${invoices ? ` · ${invoices.length}` : ""}`]]} value={tab} onChange={setTab} />
          {tab === "quote" && (!quotes ? <Loading /> : !quotes.length ? (
            <div className="empty">
              <h2>No quotations yet.</h2>
              <p className="muted">Start with the next customer who asks for a price. Type a few lines or record a voice note — the hub fills in the lines and the GST.</p>
              <button className="btn primary" onClick={() => setEditing("new")}>Write my first quotation</button>
            </div>
          ) : (
            <div className="stack">
              {quotes.map((q) => (
                <QuoteCard key={q.id} q={q} reload={reloadQ} onEdit={(x) => { setEditing(x); top(); }} onInvoice={setInvoiceFor} showInvoices={() => setTab("invoice")} />
              ))}
            </div>
          ))}
          {tab === "invoice" && (!invoices ? <Loading /> : !invoices.length ? (
            <Empty>No invoices yet. When a customer says yes, press Make invoice on their quotation.</Empty>
          ) : (
            <div className="stack">{invoices.map((inv) => <InvoiceRow key={inv.id} inv={inv} from={numberOf[inv.quote_id]} />)}</div>
          ))}
        </>
      )}
      {invoiceFor && (
        <InvoiceModal q={invoiceFor} onClose={() => setInvoiceFor(null)} onDone={() => { setInvoiceFor(null); reloadQ(); reloadI(); setTab("invoice"); }} />
      )}
    </Sheet>
  );
}

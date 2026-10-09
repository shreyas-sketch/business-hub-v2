import React, { useEffect, useState } from "react";
import { ago, api, day, rs } from "../api.js";
import { Busy, Field, FormError, Sheet, Stat, useHub, useLoad } from "../ui.jsx";
import { Loading, Num } from "../v2.jsx";
import "./program.css";

const n = (x) => Number(x) || 0;
const pct = (x) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 }).format(x);
const BLANK = { customers: "", avg_value: "", frequency: "", grow_customers: 10, grow_value: 10, grow_frequency: 10, funnel: {}, pledge: "" };
const KEYS = Object.keys(BLANK);
const HINTS = {
  leads: "e.g. Publish the lead magnet and post 3 times a week",
  conversion: "e.g. Reply within 10 minutes; follow up on day 1, 3 and 7",
  value: "e.g. Offer a premium package with installation",
  retention: "e.g. A service reminder every 6 months",
  referral: "e.g. Ask every happy customer for one name",
};

/** The same maths as the server, so the numbers move while you type. */
function calc(f) {
  const today = n(f.customers) * n(f.avg_value) * n(f.frequency);
  const factor = (1 + n(f.grow_customers) / 100) * (1 + n(f.grow_value) / 100) * (1 + n(f.grow_frequency) / 100);
  return { revenue: Math.round(today), new_revenue: Math.round(today * factor), growth_pct: Math.round((factor - 1) * 1000) / 10, extra: Math.round(today * factor - today) };
}

function Lever({ title, label, value, onValue, grow, onGrow, growLabel, step = "any" }) {
  return (
    <div className="panel pg-lever">
      <span className="label">{title}</span>
      <Field label={label}><Num min="0" step={step} value={value} onChange={onValue} /></Field>
      <div className="grow">
        <span className="small muted">{growLabel}</span>
        <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
          <span className="small muted">+</span>
          <Num min="0" max="500" step="1" style={{ width: 76 }} aria-label={`${growLabel} (%)`} value={grow} onChange={onGrow} />
          <span className="small muted">%</span>
        </div>
      </div>
    </div>
  );
}

export default function Levers() {
  const { toast } = useHub();
  const [loaded] = useLoad("/levers");
  const [f, setF] = useState(BLANK);
  const [saved, setSaved] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!loaded) return;
    setSaved(loaded.levers);
    if (loaded.levers) setF(Object.fromEntries(KEYS.map((k) => [k, loaded.levers[k] ?? BLANK[k]])));
  }, [loaded]);

  const head = { kicker: "Structure · Revenue levers", id: "PR-03", pillar: "Structure", money: true };
  const sub = "Revenue = customers × average value × how often they buy. Grow each a little and the total grows a lot.";
  if (!loaded) return <Sheet {...head} title={<>Three small levers, one big <em>jump</em>.</>} sub={sub}><Loading /></Sheet>;

  const r = calc(f);
  const set = (k) => (v) => setF({ ...f, [k]: v });
  const setStage = (k, v) => setF({ ...f, funnel: { ...f.funnel, [k]: v } });
  const hasNumbers = r.revenue > 0;
  const pledgeText = () => `I pledge to grow my customers by ${pct(n(f.grow_customers))}%, my average sale by ${pct(n(f.grow_value))}% and how often customers buy by ${pct(n(f.grow_frequency))}%` +
    (hasNumbers ? ` — from ${rs(r.revenue)} to ${rs(r.new_revenue)} a year.` : ` — ${pct(r.growth_pct)}% more revenue.`);
  const save = async () => {
    const body = {
      customers: n(f.customers), avg_value: n(f.avg_value), frequency: n(f.frequency),
      grow_customers: n(f.grow_customers), grow_value: n(f.grow_value), grow_frequency: n(f.grow_frequency),
      funnel: Object.fromEntries(Object.entries(f.funnel || {}).map(([k, v]) => [k, String(v || "").trim()]).filter(([, v]) => v)),
      pledge: f.pledge.trim(),
    };
    const d = await api("/levers", { method: "PUT", body });
    setSaved(d.levers);
    toast("Saved");
  };

  return (
    <Sheet {...head} sub={sub}
      title={<>{pct(r.growth_pct)}% more revenue from three small <em>levers</em>.</>}>
      <div className="pg-formula">
        <Lever title="Customers" label="Customers a year" value={f.customers} onValue={set("customers")}
          grow={f.grow_customers} onGrow={set("grow_customers")} growLabel="More customers" step="1" />
        <span className="op" aria-hidden="true">×</span>
        <Lever title="Average value" label="Average sale (₹)" value={f.avg_value} onValue={set("avg_value")}
          grow={f.grow_value} onGrow={set("grow_value")} growLabel="Bigger sale" />
        <span className="op" aria-hidden="true">×</span>
        <Lever title="Frequency" label="Purchases a year, each" value={f.frequency} onValue={set("frequency")}
          grow={f.grow_frequency} onGrow={set("grow_frequency")} growLabel="More often" step="0.1" />
      </div>

      <div className="pg-stats" aria-live="polite">
        <Stat label="Revenue today" value={hasNumbers ? rs(r.revenue) : "—"} money note="a year" />
        <Stat label="New revenue" value={hasNumbers ? rs(r.new_revenue) : "—"} money note="a year, with the growth above" />
        <div className="stat"><span className="label">Growth</span><span className="num aqua">{pct(r.growth_pct)}%</span><span className="small muted">10% on each lever ≈ 33.1%</span></div>
        <Stat label="Extra a year" value={hasNumbers ? `+${rs(r.extra)}` : "—"} money />
      </div>
      {!hasNumbers && <p className="small muted">Fill in the three numbers for last year to see your revenue in rupees.</p>}

      <div className="panel">
        <div className="stack" style={{ gap: 4 }}>
          <span className="label">Your 5-stage funnel</span>
          <p className="small muted">For each stage, one thing you'll do this quarter to pull its lever — and which AI tool helps.</p>
        </div>
        <div>
          {loaded.stages.map((s, i) => (
            <div key={s.key} className="pg-stage">
              <span className="n">{i + 1}</span>
              <Field label={s.label}>
                <textarea className="textarea" maxLength={400} placeholder={HINTS[s.key] || "What we'll do"} value={f.funnel?.[s.key] || ""} onChange={(e) => setStage(s.key, e.target.value)} />
              </Field>
            </div>
          ))}
        </div>
      </div>

      <div className="panel active">
        <div className="row between">
          <span className="label">The 10×10×10 pledge</span>
          {saved?.pledged_at && <span className="small muted">Pledged on {day(saved.pledged_at)}</span>}
        </div>
        <p className="small muted">Write it in your own words. Saying it out loud, with a date, is what makes it real.</p>
        <textarea className="textarea" maxLength={600} value={f.pledge} placeholder="I pledge to grow my customers, average sale and frequency by 10% each by 31 March."
          aria-label="Your pledge" onChange={(e) => setF({ ...f, pledge: e.target.value })} />
        {!f.pledge.trim() && <div><button className="btn sm ghost" onClick={() => setF({ ...f, pledge: pledgeText() })}>Start from my numbers</button></div>}
      </div>

      <FormError msg={err} />
      <div className="row">
        <Busy className="btn primary" onError={setErr} run={save}>Save my levers</Busy>
        {saved?.updated_at && <span className="small muted">Saved {ago(saved.updated_at)}</span>}
      </div>
    </Sheet>
  );
}

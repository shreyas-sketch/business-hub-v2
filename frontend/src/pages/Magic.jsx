import React, { useState } from "react";
import { Link } from "react-router-dom";
import { api, day, rs } from "../api.js";
import { Busy, Field, FormError, Sheet, Stat, useHub, useLoad } from "../ui.jsx";
import { Loading, Num, Pill } from "../v2.jsx";
import "./member.css";

const fmt = (x) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 }).format(x || 0);

/** Done so far against the month's target, with a white line where an even pace would be today. */
function Pace({ label, got, of, pct, expected, money }) {
  const show = (v) => (money ? <span className="money">{rs(v)}</span> : fmt(v));
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row between">
        <span className="label">{label}</span>
        <Pill kind={pct >= expected ? "on" : ""}>{pct >= expected ? "On pace" : "Behind pace"}</Pill>
      </div>
      <div className="row" style={{ alignItems: "baseline", gap: 8 }}>
        <span className="num" style={{ fontSize: 28 }}>{show(got)}</span>
        <span className="small muted">of {show(of)} · {pct}%</span>
      </div>
      <div className="m-pace" role="img" aria-label={`${label}: ${pct}% of the month's target; an even pace would be ${expected}% by today`}>
        <i style={{ width: `${Math.min(pct, 100)}%` }} /><b style={{ left: `${Math.min(expected, 100)}%` }} />
      </div>
    </div>
  );
}

function Body({ initial }) {
  const { toast } = useHub();
  const [data, setData] = useState(initial);
  const i0 = initial.inputs || {};
  const [f, setF] = useState({ monthly_target: i0.monthly_target ?? "", avg_sale: i0.avg_sale ?? "", close_rate: i0.close_rate ?? "", meeting_rate: i0.meeting_rate || "" });
  const [err, setErr] = useState("");
  const set = (k) => (v) => setF({ ...f, [k]: v });
  const ok = (v, max) => Number(v) > 0 && Number(v) <= max;
  const ready = ok(f.monthly_target, 1e11) && ok(f.avg_sale, 1e10) && ok(f.close_rate, 100) && (f.meeting_rate === "" || (Number(f.meeting_rate) >= 0 && Number(f.meeting_rate) <= 100));
  const save = async () => {
    const body = { monthly_target: Number(f.monthly_target), avg_sale: Number(f.avg_sale), close_rate: Number(f.close_rate), meeting_rate: Number(f.meeting_rate) || 0 };
    setData(await api("/magic", { method: "PUT", body }));
    toast("Your numbers are worked out");
  };
  const r = data.result && Object.keys(data.result).length ? data.result : null;
  const inp = data.inputs;
  const p = data.progress;
  const salesPct = inp && p ? Math.round((p.sales / inp.monthly_target) * 100) : 0;

  return (
    <>
      <div className="panel">
        <span className="label">Your numbers</span>
        <div className="grid2">
          <Field label="Monthly sales target (₹)" hint={Number(f.monthly_target) > 0 ? <>The money you want each month: <span className="money">{rs(f.monthly_target)}</span></> : "The money you want coming in each month"}>
            <Num min="0" placeholder="e.g. 1000000" value={f.monthly_target} onChange={set("monthly_target")} />
          </Field>
          <Field label="Average sale (₹)" hint={Number(f.avg_sale) > 0 ? <>One customer spends about <span className="money">{rs(f.avg_sale)}</span></> : "What one customer spends with you, on average"}>
            <Num min="0" placeholder="e.g. 100000" value={f.avg_sale} onChange={set("avg_sale")} />
          </Field>
          <Field label="Close rate (%)" hint="Out of 10 inquiries, how many buy? 2 of 10 is 20%.">
            <Num min="0" max="100" placeholder="e.g. 20" value={f.close_rate} onChange={set("close_rate")} />
          </Field>
          <Field label="Meeting rate (%) — optional" hint="Out of 10 inquiries, how many become a meeting or site visit?">
            <Num min="0" max="100" placeholder="e.g. 50" value={f.meeting_rate} onChange={set("meeting_rate")} />
          </Field>
        </div>
        <FormError msg={err} />
        <div className="row">
          <Busy className="btn primary" disabled={!ready} run={save} onError={setErr}>{r ? "Work it out again" : "Work out my numbers"}</Busy>
          {data.updated_at && <span className="small muted">Last worked out {day(data.updated_at)}</span>}
        </div>
      </div>

      {r && inp && (
        <>
          <div className="stack">
            <h2>What it takes, worked back</h2>
            <div className="m-tiles">
              <div><span className="m-step">01 · Target</span><span className="num"><span className="money">{rs(inp.monthly_target)}</span></span><span className="small muted">in sales a month</span></div>
              <div><span className="m-step">02 · Customers</span><span className="num">{fmt(r.customers_month)}</span><span className="small muted">a month, at <span className="money">{rs(inp.avg_sale)}</span> each</span></div>
              <div><span className="m-step">03 · Inquiries</span><span className="num">{fmt(r.inquiries_month)}</span><span className="small muted">a month, if {fmt(inp.close_rate)}% buy</span></div>
              <div><span className="m-step">04 · Each week</span><span className="num aqua">{fmt(r.inquiries_week)}</span><span className="small muted">inquiries a week</span></div>
              <div><span className="m-step">05 · Each day</span><span className="num aqua">{fmt(r.inquiries_day)}</span><span className="small muted">inquiries a day, over 26 working days</span></div>
            </div>
          </div>
          <div className="statgrid">
            {r.meetings_month != null && <Stat label="Meetings a month" value={fmt(r.meetings_month)} note={`${fmt(inp.meeting_rate)}% of inquiries`} />}
            <Stat label="Follow-ups a day" value={fmt(r.followups_day)} note="3 for every new inquiry" />
            <Stat label="Posts a week" value={fmt(r.posts_week)} note="to keep inquiries coming" />
          </div>
        </>
      )}

      {r && p && (
        <div className="panel">
          <div className="row between">
            <span className="label">This month so far</span>
            <span className="small muted">{p.days_left} {p.days_left === 1 ? "day" : "days"} left · {p.expected_pct}% of the month gone</span>
          </div>
          <div className="grid3">
            <Pace label="Inquiries" got={p.inquiries} of={r.inquiries_month} pct={p.inquiries_pct} expected={p.expected_pct} />
            <Pace label="Customers" got={p.customers} of={r.customers_month} pct={p.customers_pct} expected={p.expected_pct} />
            <Pace label="Sales" got={p.sales} of={inp.monthly_target} pct={salesPct} expected={p.expected_pct} money />
          </div>
          <span className="small muted m-key"><i /> Where you'd be today at an even pace.</span>
          <span className="small muted">
            Counted for you from <Link to="/leads">Leads</Link>: new inquiries this month, and leads marked Won this month with their value.
          </span>
        </div>
      )}
    </>
  );
}

export default function Magic() {
  const [d, , err] = useLoad("/magic");
  return (
    <Sheet kicker="Structure · Magic Number" id="MB-06" title={<>Your <em>Magic</em> Number.</>}
      sub="Work back from the money you want to the inquiries you need each day.">
      {!d ? (err ? <FormError msg={err.message} /> : <Loading />) : <Body initial={d} />}
    </Sheet>
  );
}

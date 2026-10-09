import React, { useEffect, useState } from "react";
import { ago, api, rs } from "../api.js";
import { Busy, Field, FormError, Sheet, useHub, useLoad } from "../ui.jsx";
import { Empty, Loading, Num } from "../v2.jsx";
import "./program.css";

const n = (x) => Number(x) || 0;
const BLANK = { name: "", kind: "B2C", ticket: "", margin: "", repeat: "maybe", collect_days: 30, effort: 5, conversion: 20, letter: "" };
const FIELDS = Object.keys(BLANK);
const KINDS = [["B2C", "B2C"], ["B2B", "B2B"], ["B2Ch", "B2Ch"]];
const REPEAT = [["yes", "Yes"], ["maybe", "Maybe"], ["no", "No"]];
const QUADS = [["A", "High return · low effort"], ["B", "High return · high effort"], ["C", "Low return · low effort"], ["D", "Low return · high effort"]];
const count = (x, one, many) => (x == null ? "—" : `${new Intl.NumberFormat("en-IN").format(x)} ${x === 1 ? one : many}`);

/** A saved segment back into form fields. A letter the hub chose is left blank, so the hub keeps choosing it. */
const toForm = (s) => ({ ...Object.fromEntries(FIELDS.map((k) => [k, s[k] ?? BLANK[k]])), letter: s.auto === false ? s.letter : "" });
const toBody = (s) => ({
  name: s.name.trim(), kind: s.kind, ticket: n(s.ticket), margin: n(s.margin), repeat: s.repeat,
  collect_days: Math.round(n(s.collect_days)), effort: Math.min(10, Math.max(1, Math.round(n(s.effort) || 1))), conversion: n(s.conversion), letter: s.letter,
});

function SegmentForm({ s, i, onChange, onRemove }) {
  const set = (k) => (v) => onChange({ ...s, [k]: v });
  const ev = (k) => (e) => onChange({ ...s, [k]: e.target.value });
  return (
    <div className="pg-sec">
      <div className="pg-sec-head"><span className="small muted">Segment {i + 1}</span><button className="btn sm ghost" onClick={onRemove}>Remove</button></div>
      <div className="pg-fields">
        <div className="wide"><Field label="Who they are"><input className="input" maxLength={80} placeholder="New 2BHK families" value={s.name} onChange={ev("name")} /></Field></div>
        <Field label="Type"><select className="select" value={s.kind} onChange={ev("kind")}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Repeat buyers?"><select className="select" value={s.repeat} onChange={ev("repeat")}>{REPEAT.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="₹ a year each"><Num min="0" value={s.ticket} onChange={set("ticket")} /></Field>
        <Field label="Margin %"><Num min="0" max="100" value={s.margin} onChange={set("margin")} /></Field>
        <Field label="Paid in (days)"><Num min="0" max="720" step="1" value={s.collect_days} onChange={set("collect_days")} /></Field>
        <Field label="Inquiries that buy %"><Num min="1" max="100" value={s.conversion} onChange={set("conversion")} /></Field>
        <div className="wide">
          <Field label={`Effort to win and serve: ${s.effort || 1} of 10`}>
            <input className="pg-range" type="range" min="1" max="10" step="1" value={s.effort || 1} onChange={(e) => onChange({ ...s, effort: Number(e.target.value) })} />
          </Field>
        </div>
        <div className="wide">
          <Field label="Letter">
            <select className="select" value={s.letter} onChange={ev("letter")}>
              <option value="">Let the hub decide</option>
              {["A", "B", "C", "D"].map((l) => <option key={l} value={l}>{l} — my choice</option>)}
            </select>
          </Field>
        </div>
      </div>
    </div>
  );
}

function Grid({ segs, letters }) {
  return (
    <div className="pg-quad-wrap" role="img" aria-label="Your segments placed by return and effort">
      <span className="pg-quad-y">Return per customer →</span>
      <div className="pg-quad">
        {QUADS.map(([l, where]) => (
          <div key={l} className={l === "A" ? "qa" : l === "D" ? "qd" : ""}>
            <div className="ql"><b>{l}</b><span className="label">{letters[l]}</span></div>
            <span className="small muted">{where}</span>
            {segs.filter((s) => s.letter === l).map((s, i) => (
              <span key={i} className="pg-chip">{s.name}<span className="money small">{rs(s.return_per_customer)}</span></span>
            ))}
          </div>
        ))}
      </div>
      <span />
      <div className="pg-quad-x"><span>Low effort</span><span>High effort →</span></div>
    </div>
  );
}

export default function Portfolio() {
  const { toast } = useHub();
  const [loaded] = useLoad("/portfolio");
  const [goal, setGoal] = useState("");
  const [share, setShare] = useState(75);
  const [segs, setSegs] = useState([]);
  const [saved, setSaved] = useState(null);
  const [err, setErr] = useState("");
  const load = (p) => {
    setSaved(p);
    if (!p) { setSegs([{ ...BLANK }]); return; }
    setGoal(p.goal || "");
    setShare(p.amazing_share || 75);
    setSegs((p.segments || []).map(toForm));
  };
  useEffect(() => { if (loaded) load(loaded.portfolio); }, [loaded]);

  const head = { kicker: "Structure · Customer portfolio", id: "PR-04", pillar: "Structure" };
  const sub = "Sort the kinds of customers you serve by return and effort. Aim most of your effort at the Amazing ones, and stay away from the Dangerous ones.";
  if (!loaded) return <Sheet {...head} title={<>Aim at your <em>Amazing</em> customers.</>} sub={sub}><Loading /></Sheet>;

  const filled = segs.filter((s) => s.name.trim());
  const body = { goal: n(goal), amazing_share: share, segments: filled.map(toBody) };
  const savedBody = saved ? { goal: saved.goal || 0, amazing_share: saved.amazing_share, segments: (saved.segments || []).map((s) => toBody(toForm(s))) } : null;
  const dirty = JSON.stringify(body) !== JSON.stringify(savedBody);
  const ready = filled.length > 0 && filled.every((s) => s.name.trim().length >= 2);
  const result = saved?.segments || [];
  const save = async () => {
    const d = await api("/portfolio", { method: "PUT", body });
    load(d.portfolio);
    toast("Portfolio sorted");
  };

  return (
    <Sheet {...head} sub={sub} title={<>Aim at your <em>Amazing</em> customers.</>}>
      <div className="panel">
        <div className="grid2">
          <Field label="Your goal for the year (₹)" hint={n(goal) ? <span className="money">{rs(n(goal))}</span> : "Leave empty to sort only."}>
            <Num min="0" value={goal} onChange={setGoal} />
          </Field>
          <Field label={`Share of the goal from A customers: ${share}%`} hint={`The other ${100 - share}% comes from B customers.`}>
            <input className="pg-range" type="range" min="50" max="90" step="5" value={share} onChange={(e) => setShare(Number(e.target.value))} />
          </Field>
        </div>
      </div>

      <div className="panel">
        <div className="stack" style={{ gap: 4 }}>
          <span className="label">Your customer segments</span>
          <p className="small muted">A segment is a group of customers who buy for the same reason — like "new 2BHK families", "builders" or "small repairs". Type: B2C sells to people, B2B to businesses, B2Ch through dealers and channels.</p>
        </div>
        {segs.map((s, i) => (
          <SegmentForm key={i} s={s} i={i} onChange={(x) => setSegs(segs.map((y, j) => (j === i ? x : y)))} onRemove={() => setSegs(segs.filter((_, j) => j !== i))} />
        ))}
        {segs.length < 20 && <div><button className="btn sm ghost" onClick={() => setSegs([...segs, { ...BLANK }])}>Add a segment</button></div>}
        <FormError msg={err} />
        <div className="row">
          <Busy className="btn primary" disabled={!ready || !dirty} onError={setErr} run={save}>Sort my customers</Busy>
          {saved?.updated_at && !dirty && <span className="small muted">Saved {ago(saved.updated_at)}</span>}
          {dirty && result.length > 0 && <span className="pg-stale">Changes not saved — the grid below shows your last save.</span>}
        </div>
      </div>

      {result.length === 0 ? (
        <Empty>Add your segments above and tap Sort my customers. Each one gets a letter, A to D, and — with a goal — the customers and leads it needs.</Empty>
      ) : (
        <>
          <Grid segs={result} letters={loaded.letters} />
          <div className="stack" style={{ gap: 10 }}>
            {["A", "B", "C", "D"].map((l) => (
              <div key={l} className="pg-letter-key">
                <span className={`pg-letter ${l === "D" ? "d" : ""}`}>{l}</span>
                <span className="small"><b>{loaded.letters[l]}.</b> <span className="muted">{loaded.rules[l]}</span></span>
              </div>
            ))}
          </div>
          <table className="t cards">
            <thead><tr><th>Segment</th><th>Letter</th><th>Return per customer</th><th>Target a year</th><th>Customers needed</th><th>Leads needed</th></tr></thead>
            <tbody>{result.map((s, i) => (
              <tr key={i}>
                <td><b>{s.name}</b><div className="small muted">{s.kind}{s.auto ? "" : " · letter set by you"}</div></td>
                <td data-l="Letter"><span className="row" style={{ gap: 8, flexWrap: "nowrap" }}><span className={`pg-letter ${s.letter === "D" ? "d" : ""}`}>{s.letter}</span><span className="small">{s.type}</span></span></td>
                <td data-l="Return per customer"><span className="money">{rs(s.return_per_customer)}</span></td>
                <td data-l="Target a year">{s.target ? <span className="money">{rs(s.target)}</span> : <span className="muted">—</span>}</td>
                <td data-l="Customers needed">{count(s.customers_needed, "customer", "customers")}</td>
                <td data-l="Leads needed">{count(s.leads_needed, "lead", "leads")}</td>
              </tr>
            ))}</tbody>
          </table>
          {!saved.goal && <p className="small muted">Add your goal for the year to see the target, customers and leads for each A and B segment.</p>}
        </>
      )}
    </Sheet>
  );
}

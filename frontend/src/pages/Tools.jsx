import React, { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ago, api } from "../api.js";
import { Busy, Field, FormError, Locked, Sheet, canAct, useHub, useLoad } from "../ui.jsx";
import { Empty, Loading, Pill, Tabs, ToolOutput } from "../v2.jsx";
import "./member.css";

const saves = (m) => (m >= 60 ? `${+(m / 60).toFixed(1)} ${m === 60 ? "hour" : "hours"}` : `${m} minutes`);
const blankFor = (t) => Object.fromEntries(t.inputs.map((i) => [i.key, i.type === "select" ? i.options?.[0] || "" : ""]));

function Input({ i, value, onChange }) {
  const p = { value, placeholder: i.placeholder || undefined, onChange: (e) => onChange(e.target.value) };
  if (i.type === "textarea") return <textarea className="textarea" maxLength={6000} {...p} />;
  if (i.type === "select") return <select className="select" {...p}>{i.options.map((o) => <option key={o} value={o}>{o}</option>)}</select>;
  return <input className="input" maxLength={600} {...p} />;
}

function History({ t, items }) {
  const [open, setOpen] = useState(null);
  if (!items) return <Loading />;
  if (!items.length) return <p className="small muted">Your drafts from this tool will show here.</p>;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {items.slice(0, 10).map((o) => (
        <div key={o.id} className="panel flat" style={{ padding: "12px 14px" }}>
          <button className="linkbtn" style={{ textAlign: "left" }} aria-expanded={open === o.id} onClick={() => setOpen(open === o.id ? null : o.id)}>
            {o.title || t.name}
          </button>
          <span className="small muted">{ago(o.created_at)}</span>
          {open === o.id && <ToolOutput out={o.content} />}
        </div>
      ))}
    </div>
  );
}

function ToolForm({ t }) {
  const { me, refresh } = useHub();
  const [vals, setVals] = useState(() => blankFor(t));
  const [out, setOut] = useState(null);
  const [err, setErr] = useState("");
  const [hist, reloadHist] = useLoad(`/tools/${encodeURIComponent(t.key)}/history`);
  const missing = t.inputs.filter((i) => i.required && (vals[i.key] || "").trim().length < 2).map((i) => i.label);
  const hasExample = Object.keys(t.example || {}).length > 0;
  const run = async () => {
    setOut(null);
    const r = await api(`/tools/${encodeURIComponent(t.key)}/run`, { method: "POST", body: { inputs: vals } });
    setOut(r.output);
    reloadHist();
    refresh();
  };
  if (!canAct(me, t.role)) return <p className="muted">Ask your manager or the business owner to use this tool.</p>;
  return (
    <>
      {t.inputs.map((i) => (
        <Field key={i.key} label={i.label} hint={i.hint || null}>
          <Input i={i} value={vals[i.key] ?? ""} onChange={(v) => setVals({ ...vals, [i.key]: v })} />
        </Field>
      ))}
      <FormError msg={err} />
      <div className="row">
        <Busy className="btn primary" disabled={missing.length > 0} run={run} onError={setErr}>Write it for me</Busy>
        {hasExample && <button className="btn ghost" onClick={() => setVals({ ...blankFor(t), ...t.example })}>Fill an example</button>}
      </div>
      <span className="small muted">
        {missing.length > 0 ? `Fill in: ${missing.join(", ")}. ` : ""}Uses one AI run · {me.runs?.left ?? 0} left this month.
      </span>
      {out && (
        <div className="stack">
          <hr className="rule" />
          <ToolOutput out={out} />
          {me.features?.outputs && <span className="small muted">Saved in <Link to="/outputs">My outputs</Link>.</span>}
        </div>
      )}
      <hr className="rule" />
      <span className="label">Earlier drafts</span>
      <History t={t} items={hist} />
    </>
  );
}

function ToolPanel({ t }) {
  return (
    <div className="panel active">
      <div className="row between">
        <span className="label">{t.desk}</span>
        <span className="small muted">Saves you about {saves(t.minutes)}</span>
      </div>
      <h2>{t.name}</h2>
      <p className="sub">{t.what}</p>
      {t.locked ? <Locked feature={t.feature} what={t.name} /> : <ToolForm key={t.key} t={t} />}
    </div>
  );
}

export default function Tools() {
  const [d, , err] = useLoad("/tools");
  const [params, setParams] = useSearchParams();
  const [desk, setDesk] = useState("all");
  const panelRef = useRef(null);
  const head = { kicker: "Scale · AI tools", id: "MB-05", title: <>Tools that know your <em>business</em>.</>,
    sub: "Pick a tool, answer a question or two, and get a ready draft in your voice — no setting up. Every draft is saved in My outputs." };
  if (!d) return <Sheet {...head}>{err ? <FormError msg={err.message} /> : <Loading />}</Sheet>;

  const tools = d.tools || [];
  const desks = d.desks.filter((x) => tools.some((t) => t.desk === x));
  const shown = desk === "all" ? tools : tools.filter((t) => t.desk === desk);
  const chosen = tools.find((t) => t.key === params.get("tool"));
  const sel = chosen && shown.includes(chosen) ? chosen : shown.find((t) => !t.locked) || shown[0];
  const pick = (k) => {
    setParams({ tool: k }, { replace: true });
    if (window.innerWidth <= 900) setTimeout(() => panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  };
  const pickDesk = (k) => { setDesk(k); setParams({}, { replace: true }); };

  return (
    <Sheet {...head}>
      {tools.length === 0 ? <Empty>No AI tools are switched on right now.</Empty> : (
        <>
          <Tabs tabs={[["all", "All"], ...desks.map((x) => [x, x])]} value={desk} onChange={pickDesk} />
          <div className="split">
            <div className="listbox">
              {shown.map((t) => (
                <button key={t.key} className={sel?.key === t.key ? "on" : ""} aria-current={sel?.key === t.key} onClick={() => pick(t.key)}>
                  <span className="row between" style={{ gap: 8 }}>
                    <b style={{ fontWeight: 500 }}>{t.name}</b>
                    {t.locked ? <Pill>{t.tier_name}</Pill> : <span className="small muted">~{saves(t.minutes)}</span>}
                  </span>
                  <span className="small muted">{t.what}</span>
                </button>
              ))}
            </div>
            <div ref={panelRef} style={{ scrollMarginTop: 80, minWidth: 0 }}>
              {sel ? <ToolPanel key={sel.key} t={sel} /> : <Empty>Pick a tool to start.</Empty>}
            </div>
          </div>
        </>
      )}

      {d.roles?.length > 0 && (
        <div className="panel">
          <div className="row between">
            <span className="label">Your AI staff · {d.roles.length}</span>
            <Link className="btn sm" to="/workforce">Open Workforce</Link>
          </div>
          <div className="m-calls">
            {d.roles.map((r) => (
              <div key={r.key} className="m-call-row">
                <div className="stack" style={{ gap: 2 }}><b style={{ fontWeight: 500 }}>{r.name}</b><span className="small muted">{r.what}</span></div>
                <span className="small muted">{r.desk}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Sheet>
  );
}

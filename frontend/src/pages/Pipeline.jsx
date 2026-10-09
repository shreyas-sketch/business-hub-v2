import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ago, api, localPhone, rs, waLink } from "../api.js";
import { Busy, Sheet, Stat, useHub, useLoad } from "../ui.jsx";
import { Loading } from "../v2.jsx";
import "./program.css";

// The Football Field: the 5 stages every sale goes through, left to right.
const STAGES = [
  ["identification", "Identification", "Who are they, and what do they need?"],
  ["logic", "Logic / reason", "The reason they'd buy."],
  ["pain", "Pain / consequence", "What it costs them to wait."],
  ["vision", "Solution / vision", "Their life with your solution."],
  ["close", "Ask / close", "Ask for the order."],
];
const OPEN = ["new", "contacted"];
const stageOf = (l) => (STAGES.some(([k]) => k === l.stage) ? l.stage : "identification");
const sum = (list) => list.reduce((t, l) => t + (Number(l.value) || 0), 0);

function Card({ l, onMove, onPatch }) {
  const [value, setValue] = useState(l.value ?? "");
  const [dragging, setDragging] = useState(false);
  const [grab, setGrab] = useState(true); // not while typing in the value box or using the menu
  useEffect(() => setValue(l.value ?? ""), [l.value]);
  const saveValue = () => {
    if (value === "" || Number(value) === Number(l.value ?? NaN)) return;
    const v = Number(value);
    if (Number.isNaN(v) || v < 0) { setValue(l.value ?? ""); return; }
    onPatch(l, { value: v }, `Deal value saved: ${rs(v)}`);
  };
  return (
    <div className={`kcard ${dragging ? "dragging" : ""}`} draggable={grab}
      onMouseDown={(e) => setGrab(!e.target.closest("input, select, button, a"))}
      onDragStart={(e) => { e.dataTransfer.setData("text/plain", l.id); e.dataTransfer.effectAllowed = "move"; setDragging(true); }}
      onDragEnd={() => setDragging(false)}>
      <div className="row between" style={{ alignItems: "baseline" }}>
        <b style={{ overflowWrap: "anywhere" }}>{l.name || "Customer"}</b>
        <span className="small muted">{ago(l.created_at)}</span>
      </div>
      {l.phone && <a className="mono small" href={waLink("", l.phone)} target="_blank" rel="noopener" aria-label={`WhatsApp ${l.name || "customer"}`}>{localPhone(l.phone)}</a>}
      {l.message && <span className="msg-line" title={l.message}>{l.message}</span>}
      <label className="val">
        <span className="small muted">Deal ₹</span>
        <input className="input money" type="number" min="0" step="any" inputMode="decimal" aria-label={`Deal value for ${l.name || "this lead"}`}
          value={value} placeholder="Value" onChange={(e) => setValue(e.target.value)} onBlur={saveValue}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
      </label>
      <select className="select" aria-label={`Move ${l.name || "this lead"} to another stage`} value="" onChange={(e) => e.target.value && onMove(l, e.target.value)}>
        <option value="">Move to…</option>
        {STAGES.filter(([k]) => k !== stageOf(l)).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
      </select>
      <div className="row">
        <Busy className="btn sm primary" run={() => onPatch(l, { status: "won" }, `${l.name || "Lead"} marked won${l.value ? ` — ${rs(l.value)}` : ""}`)}>Won</Busy>
        <Busy className="btn sm ghost" run={() => onPatch(l, { status: "lost" }, `${l.name || "Lead"} marked lost. You can change it on the Leads page.`)}>Lost</Busy>
      </div>
    </div>
  );
}

export default function Pipeline() {
  const { toast } = useHub();
  const [loaded, reload] = useLoad("/leads");
  const [leads, setLeads] = useState(null);
  const [over, setOver] = useState(null);
  useEffect(() => { if (loaded) setLeads(loaded); }, [loaded]);

  const head = { kicker: "Systems · Sales pipeline", id: "PR-05", pillar: "Systems" };
  const sub = "Every open lead on the Football Field — the 5 stages of a sale. Drag a lead to the next stage as the talk moves forward; mark it Won or Lost when it's decided.";
  if (!leads) return <Sheet {...head} title={<>Move every deal down the <em>field</em>.</>} sub={sub}><Loading /></Sheet>;

  const patch = async (l, body, msg) => {
    setLeads((list) => list.map((x) => (x.id === l.id ? { ...x, ...body, updated_at: new Date().toISOString() } : x)));
    try {
      await api(`/leads/${l.id}`, { method: "PATCH", body });
      if (msg) toast(msg);
    } catch (e) {
      if (!e.handled) toast(e.message, "err");
      reload();
    }
  };
  const move = (l, stage) => { if (l && stage !== stageOf(l)) patch(l, { stage }, `Moved to ${STAGES.find(([k]) => k === stage)[1]}`); };

  const open = leads.filter((l) => OPEN.includes(l.status));
  const since = Date.now() - 30 * 86400000;
  const won = leads.filter((l) => l.status === "won" && new Date(l.updated_at || l.created_at).getTime() >= since);
  const title = open.length ? <>{open.length} open {open.length === 1 ? "deal" : "deals"} on the <em>field</em>.</> : <>Move every deal down the <em>field</em>.</>;

  return (
    <Sheet {...head} title={title} sub={sub}>
      <div className="statgrid">
        <Stat label="Open deals" value={open.length} />
        <Stat label="Value on the field" value={rs(sum(open))} money note={open.some((l) => !l.value) ? "Add a value to every deal" : undefined} />
        <Stat label="Won · last 30 days" value={rs(sum(won))} money note={`${won.length} ${won.length === 1 ? "deal" : "deals"}`} />
      </div>

      {!open.length && (
        <div className="empty">
          <h2>No open leads right now.</h2>
          <p className="muted">New inquiries from your website and your guide start here, in Identification. Share your website link to bring the next one in.</p>
          <Link className="btn" to="/leads">See all leads</Link>
        </div>
      )}

      {open.length > 0 && (
        <div className="pg-board">
          <div className="kanban">
            {STAGES.map(([key, label, hint]) => {
              const col = open.filter((l) => stageOf(l) === key);
              return (
                <div key={key} className={`kcol ${over === key ? "over" : ""}`} aria-label={label}
                  onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (over !== key) setOver(key); }}
                  onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOver(null); }}
                  onDrop={(e) => { e.preventDefault(); setOver(null); move(open.find((l) => l.id === e.dataTransfer.getData("text/plain")), key); }}>
                  <div className="kcol-head">
                    <span className="label" style={{ color: "var(--paper)" }}>{label}</span>
                    <span className="small muted">{hint}</span>
                    <span className="n">{col.length} {col.length === 1 ? "lead" : "leads"} · <span className="money">{rs(sum(col))}</span></span>
                  </div>
                  {col.map((l) => <Card key={l.id} l={l} onMove={move} onPatch={patch} />)}
                  {!col.length && <span className="small muted">Drop a lead here.</span>}
                </div>
              );
            })}
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>On a phone, swipe sideways to see every stage, and use "Move to…" on a card.</p>
        </div>
      )}
    </Sheet>
  );
}

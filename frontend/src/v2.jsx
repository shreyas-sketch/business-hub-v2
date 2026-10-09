import React from "react";
import { waLink } from "./api.js";
import { Copy, useHub } from "./ui.jsx";

/* Shared pieces for the v2 pages. */

/** The generic AI output shape {title, summary, sections[{heading, text, points}], messages[{label, text}]} — used by
    AI tools, the 82 roles, and anything else written in that shape. `phone` pre-fills the WhatsApp link. */
export function ToolOutput({ out, phone = "", title = true }) {
  if (!out) return null;
  const asText = [out.title, out.summary, ...(out.sections || []).map((s) => [s.heading, s.text, ...(s.points || []).map((p) => `• ${p}`)].filter(Boolean).join("\n"))]
    .filter(Boolean).join("\n\n");
  return (
    <div className="stack out">
      {title && (
        <div className="row between">
          <h3>{out.title}</h3>
          <Copy text={asText} label="Copy all" />
        </div>
      )}
      {out.summary && <p className="sub">{out.summary}</p>}
      {(out.sections || []).map((s, i) => (
        <div key={i} className="panel flat out-sec">
          {s.heading && <span className="label">{s.heading}</span>}
          {s.text && <p style={{ whiteSpace: "pre-wrap" }}>{s.text}</p>}
          {s.points?.length > 0 && <ul className="read-list">{s.points.map((p, j) => <li key={j}>{p}</li>)}</ul>}
        </div>
      ))}
      {(out.messages || []).map((m, i) => (
        <div key={i} className="panel active">
          <div className="row between"><span className="label">{m.label || "Message"}</span>
            <div className="row"><Copy text={m.text} /><a className="btn sm" href={waLink(m.text, phone)} target="_blank" rel="noreferrer">Send on WhatsApp</a></div>
          </div>
          <div className="prompt">{m.text}</div>
        </div>
      ))}
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>{l}</button>)}
    </div>
  );
}

export const Empty = ({ children }) => <div className="panel flat empty"><p className="muted">{children}</p></div>;

export const Pill = ({ children, kind = "" }) => <span className={`pill ${kind}`}>{children}</span>;

/** One line under a page title saying what the feature does, from the admin's description (so the admin's words show). */
export function What({ feature }) {
  const { me } = useHub();
  const w = me?.feature_info?.[feature]?.what;
  return w ? <p className="sub">{w}</p> : null;
}

/** A number input that keeps empty as "" while typing. */
export function Num({ value, onChange, ...p }) {
  return <input className="input" type="number" inputMode="decimal" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} {...p} />;
}

export const Loading = () => <p className="muted">Loading…</p>;

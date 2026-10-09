import React, { useMemo, useState } from "react";
import { ago, api } from "../api.js";
import { Copy, Sheet, canAct, useHub, useLoad } from "../ui.jsx";

const LABEL = {
  posts: "Posts", reply: "Reply", answer: "Answer", brand: "Brand message", site: "Website", goal_coach: "Goal actions",
  wheel_comment: "Wheel review", "kit:sop": "SOP", "kit:jd": "Hiring kit", "kit:decision": "Decision log", "kit:role": "Role clarity",
  "kit:culture": "Culture charter", "kit:competence": "Competence plan", "kit:review": "Monthly review", report: "Report",
  standup: "Standup", meeting_actions: "Meeting actions", followup: "Follow-up",
};
const GROUPS = [
  ["", "All", () => true],
  ["posts", "Posts", (k) => k === "posts"],
  ["replies", "Replies & answers", (k) => k === "reply" || k === "answer" || k === "followup"],
  ["docs", "Documents", (k) => k.startsWith("kit:") && k !== "kit:review"],
  ["reports", "Reviews & reports", (k) => ["kit:review", "report", "standup", "wheel_comment", "goal_coach", "meeting_actions"].includes(k)],
  ["brand", "Brand & website", (k) => k === "brand" || k === "site"],
];
const SKIP = new Set(["id", "kind", "version", "language"]);
const human = (k) => { const s = String(k).replace(/_/g, " "); return s.charAt(0).toUpperCase() + s.slice(1); };

/** Any saved AI output as plain, readable text — the same text the Copy button copies. */
function toText(v, depth = 0) {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v !== "object") return String(v);
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x !== "object" || x === null)) return v.filter((x) => x !== "" && x != null).map((x) => `• ${x}`).join("\n");
    return v.map((x) => toText(x, depth + 1)).filter(Boolean).join("\n\n");
  }
  return Object.entries(v).filter(([k, x]) => !SKIP.has(k) && x !== "" && x != null && !(Array.isArray(x) && !x.length))
    .map(([k, x]) => (typeof x === "object" ? `${human(k)}\n${toText(x, depth + 1)}` : `${human(k)}: ${x}`)).join(depth ? "\n" : "\n\n");
}

function asText(o) {
  const c = o.content || {};
  if (o.kind === "posts") return (c.posts || []).map((p) => `${p.day}: ${p.hook}\n${p.caption}`).join("\n\n");
  if (o.kind === "brand") return (c.options || []).map((x, i) => `${i + 1}. ${x.message}\n${x.pitch}`).join("\n\n");
  if (o.kind === "site") return [c.headline, c.subheadline, c.about].filter(Boolean).join("\n\n");
  if (o.kind === "reply" || o.kind === "answer" || o.kind === "followup") return c.reply || c.answer || c.message || toText(c);
  return toText(c);
}

export default function Outputs() {
  const { toast, me } = useHub();
  const [group, setGroup] = useState("");
  const [items, reload] = useLoad("/outputs");
  const [open, setOpen] = useState(null);
  const filter = GROUPS.find(([k]) => k === group)[2];
  const shown = useMemo(() => (items || []).filter((o) => filter(o.kind)), [items, filter]);
  const groups = GROUPS.filter(([k, , f]) => !k || (items || []).some((o) => f(o.kind)));
  return (
    <Sheet kicker="Scale · My outputs" id="O-01" pillar="Scale" title={<>Everything the AI wrote, <em>kept</em>.</>}>
      <div className="tabs">{groups.map(([k, l]) => <button key={k} className={group === k ? "on" : ""} onClick={() => setGroup(k)}>{l}</button>)}</div>
      {items && !shown.length && <div className="empty"><p className="muted">Nothing here yet.</p></div>}
      <div className="stack">{shown.map((o) => (
        <div key={o.id} className="panel">
          <div className="out-head">
            <span style={{ minWidth: 0 }}><b style={{ overflowWrap: "anywhere" }}>{o.title}</b> <span className="small muted">· {LABEL[o.kind] || human(o.kind.replace("kit:", ""))} · {ago(o.created_at)}</span></span>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn sm" onClick={() => setOpen(open === o.id ? null : o.id)}>{open === o.id ? "Hide" : "Show"}</button>
              <Copy text={asText(o)} />
              {canAct(me, "manager") && <button className="btn sm ghost" onClick={async () => {
                if (!window.confirm(`Delete “${o.title}”? It can't be brought back.`)) return;
                try { await api(`/outputs/${o.id}`, { method: "DELETE" }); toast("Deleted"); reload(); } catch (e) { toast(e.message, "err"); }
              }}>Delete</button>}
            </div>
          </div>
          {open === o.id && <div className="prompt" style={{ overflowWrap: "anywhere" }}>{asText(o) || "This output has no text to show."}</div>}
        </div>))}
      </div>
    </Sheet>
  );
}

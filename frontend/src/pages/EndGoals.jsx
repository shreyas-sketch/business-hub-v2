import React, { useEffect, useState } from "react";
import { ago, api } from "../api.js";
import { Busy, FormError, Sheet, useHub, useLoad } from "../ui.jsx";
import { Loading } from "../v2.jsx";
import "./program.css";

const KEYS = ["identity", "income", "freedom", "legacy"];
const blank = () => Object.fromEntries(KEYS.map((k) => [k, { text: "", by: "" }]));

export default function EndGoals() {
  const { toast } = useHub();
  const [loaded] = useLoad("/end-goals");
  const [g, setG] = useState(blank);
  const [savedAt, setSavedAt] = useState(null);
  const [savedJson, setSavedJson] = useState(JSON.stringify(blank()));
  const [err, setErr] = useState("");
  const take = (d) => {
    const v = Object.fromEntries(KEYS.map((k) => [k, { text: d.goals?.[k]?.text || "", by: d.goals?.[k]?.by || "" }]));
    setG(v);
    setSavedJson(JSON.stringify(v));
    setSavedAt(d.goals?.updated_at || null);
  };
  useEffect(() => { if (loaded) take(loaded); }, [loaded]);

  const head = { kicker: "Structure · 4 end goals", id: "PR-07", pillar: "Structure" };
  const sub = "Four answers that sit behind every target in the hub. Take your time — there are no wrong answers, and you can change them any day.";
  if (!loaded) return <Sheet {...head} title={<>Where is all of this <em>going</em>?</>} sub={sub}><Loading /></Sheet>;

  const set = (k, patch) => setG({ ...g, [k]: { ...g[k], ...patch } });
  const dirty = JSON.stringify(g) !== savedJson;
  const written = KEYS.filter((k) => g[k].text.trim()).length;

  return (
    <Sheet {...head} sub={sub}
      title={written === 4 && !dirty ? <>You know where this is <em>going</em>.</> : <>Where is all of this <em>going</em>?</>}>
      <div className="pg-endgoals">
        {loaded.prompts.map((p, i) => (
          <section key={p.key} className="pg-endgoal" aria-labelledby={`eg-${p.key}`}>
            <span className="no" aria-hidden="true">0{i + 1}</span>
            <div className="stack" style={{ gap: 12 }}>
              <span className="label" id={`eg-${p.key}`}>{p.label}</span>
              <p className="q">{p.q}</p>
              <textarea className="textarea" maxLength={800} aria-label={p.q} placeholder="Write it the way you'd say it to someone you trust."
                value={g[p.key]?.text || ""} onChange={(e) => set(p.key, { text: e.target.value })} />
              <label className="by">
                <span className="small muted">By when</span>
                <input className="input" maxLength={20} placeholder="e.g. March 2030" value={g[p.key]?.by || ""} onChange={(e) => set(p.key, { by: e.target.value })} />
              </label>
            </div>
          </section>
        ))}
      </div>
      <FormError msg={err} />
      <div className="row">
        <Busy className="btn primary" disabled={!dirty} onError={setErr} run={async () => {
          const body = Object.fromEntries(KEYS.map((k) => [k, { text: g[k].text.trim(), by: g[k].by.trim() }]));
          take(await api("/end-goals", { method: "PUT", body }));
          toast("Your end goals are saved");
        }}>Save my end goals</Busy>
        <span className="small muted">{dirty ? "Changes not saved yet" : savedAt ? `Saved ${ago(savedAt)} · ${written} of 4 written` : `${written} of 4 written`}</span>
      </div>
    </Sheet>
  );
}

import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ago, api, waLink } from "../api.js";
import { Busy, Copy, Field, FormError, Sheet, Stat, Switch, useHub, useLoad } from "../ui.jsx";
import { Loading, Pill } from "../v2.jsx";
import "./program.css";

const FORMATS = [["checklist", "Checklist"], ["guide", "Step-by-step guide"], ["price guide", "Price guide"], ["mistakes list", "Mistakes to avoid"]];
const MAX_SECTIONS = 10;

/** The two questions the AI needs before it writes the guide. */
function WriteForm({ first, onDone, onCancel }) {
  const { refresh } = useHub();
  const [problem, setProblem] = useState("");
  const [format, setFormat] = useState("checklist");
  const [err, setErr] = useState("");
  return (
    <div className="panel active">
      <span className="label">{first ? "Write your guide" : "Write a new guide"}</span>
      <Field label="What problem does it solve for your customer?" hint="One line, in your customer's words. For example: choosing a modular kitchen without overpaying.">
        <textarea className="textarea" style={{ minHeight: 72 }} maxLength={300} value={problem} onChange={(e) => setProblem(e.target.value)} />
      </Field>
      <div className="stack" style={{ gap: 8 }}>
        <span className="label">Format</span>
        <div className="row" role="radiogroup" aria-label="Format">
          {FORMATS.map(([k, l]) => (
            <button key={k} type="button" role="radio" aria-checked={format === k} className={`btn sm ${format === k ? "primary" : "ghost"}`} onClick={() => setFormat(k)}>{l}</button>
          ))}
        </div>
      </div>
      <FormError msg={err} />
      <div className="row">
        <Busy className="btn primary" onError={setErr} disabled={problem.trim().length < 5} run={async () => {
          if (!first && !window.confirm("Write a new guide? It replaces the one you have now.")) return;
          const d = await api("/lead-magnet/generate", { method: "POST", body: { problem: problem.trim(), format } });
          refresh();
          onDone(d);
        }}>Write my guide</Busy>
        {onCancel && <button className="btn ghost" onClick={onCancel}>Cancel</button>}
      </div>
      <span className="small muted">Uses 1 AI run. Written from your Business Brain — you can change every word after.</span>
    </div>
  );
}

/** Every word of the guide, editable. Points are one per line. */
function GuideEditor({ content, onSaved }) {
  const { toast } = useHub();
  const [c, setC] = useState(content);
  const [err, setErr] = useState("");
  const saved = JSON.stringify(content);
  useEffect(() => setC(content), [saved]); // a fresh copy from the server only when the saved words changed
  const set = (k) => (e) => setC({ ...c, [k]: e.target.value });
  const setSec = (i, patch) => setC({ ...c, sections: c.sections.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const clean = () => ({ ...c, sections: c.sections.map((s) => ({ ...s, points: (s.points || []).map((p) => p.trim()).filter(Boolean) })) });
  const dirty = JSON.stringify(clean()) !== saved;
  const ready = c.title.trim().length > 0 && c.sections.filter((s) => s.heading.trim()).length >= 2;
  return (
    <div className="panel">
      <div className="row between"><span className="label">Your guide</span>{dirty && <span className="small muted">Changes not saved yet</span>}</div>
      <Field label="Title"><input className="input" maxLength={140} value={c.title} onChange={set("title")} /></Field>
      <Field label="Line under the title"><input className="input" maxLength={200} value={c.subtitle} onChange={set("subtitle")} /></Field>
      <Field label="The promise" hint="What the reader gets from it, in one line."><input className="input" maxLength={200} value={c.promise} onChange={set("promise")} /></Field>
      <Field label="Opening"><textarea className="textarea" maxLength={800} value={c.intro} onChange={set("intro")} /></Field>
      <div className="stack">
        <span className="label">Sections</span>
        {c.sections.map((s, i) => (
          <div key={i} className="pg-sec">
            <div className="pg-sec-head">
              <span className="small muted">Section {i + 1}</span>
              {c.sections.length > 2 && <button className="btn sm ghost" onClick={() => setC({ ...c, sections: c.sections.filter((_, j) => j !== i) })}>Remove</button>}
            </div>
            <Field label="Heading"><input className="input" maxLength={140} value={s.heading} onChange={(e) => setSec(i, { heading: e.target.value })} /></Field>
            <Field label="Text"><textarea className="textarea" style={{ minHeight: 72 }} maxLength={800} value={s.text} onChange={(e) => setSec(i, { text: e.target.value })} /></Field>
            <Field label="Points" hint="One per line, up to 8.">
              <textarea className="textarea" style={{ minHeight: 0 }} rows={Math.max(3, (s.points || []).length + 1)} value={(s.points || []).join("\n")}
                onChange={(e) => setSec(i, { points: e.target.value.split("\n").slice(0, 8) })} />
            </Field>
          </div>
        ))}
        {c.sections.length < MAX_SECTIONS && (
          <button className="btn sm ghost" style={{ justifySelf: "start" }} onClick={() => setC({ ...c, sections: [...c.sections, { heading: "", text: "", points: [] }] })}>Add a section</button>
        )}
      </div>
      <Field label="Closing call to action" hint="What you want them to do next — message you, book a visit."><textarea className="textarea" style={{ minHeight: 64 }} maxLength={400} value={c.cta} onChange={set("cta")} /></Field>
      <FormError msg={err} />
      <div className="row">
        <Busy className="btn primary" disabled={!ready || !dirty} onError={setErr} run={async () => {
          const d = await api("/lead-magnet", { method: "PUT", body: { content: clean() } });
          toast("Guide saved");
          onSaved(d);
        }}>Save guide</Busy>
        {dirty && <button className="btn ghost" onClick={() => setC(content)}>Undo changes</button>}
      </div>
      {!ready && <span className="hint">The guide needs a title and at least two sections with headings.</span>}
    </div>
  );
}

export default function LeadMagnet() {
  const { toast, refresh } = useHub();
  const [loaded] = useLoad("/lead-magnet");
  const [data, setData] = useState(null);
  const [rewrite, setRewrite] = useState(false);
  const [pubErr, setPubErr] = useState("");
  const [publishing, setPublishing] = useState(false);
  useEffect(() => { if (loaded) setData(loaded); }, [loaded]);

  const head = { kicker: "Scale · Lead magnet", id: "PR-01", pillar: "Scale" };
  const sub = "A free guide on your website that turns visitors into inquiries. Visitors leave their name and number to read it, and each one lands in your leads.";
  if (!data) return <Sheet {...head} title={<>A free guide that brings <em>inquiries</em>.</>} sub={sub}><Loading /></Sheet>;

  const g = data.guide;
  if (!g) {
    return (
      <Sheet {...head} title={<>A free guide that brings <em>inquiries</em>.</>} sub={sub}>
        <WriteForm first onDone={setData} />
      </Sheet>
    );
  }

  const live = !!g.published;
  const content = g.content;
  const togglePublish = async (published) => {
    setPublishing(true);
    setPubErr("");
    try {
      const d = await api("/lead-magnet/publish", { method: "POST", body: { published } });
      setData(d);
      refresh();
      toast(published ? "Your guide is live on your website" : "Guide taken off your website");
    } catch (e) { if (!e.handled) setPubErr(e.message); }
    finally { setPublishing(false); }
  };
  const shareText = `Here's a free guide for you: ${content.title}. Read it here: ${data.url}`;
  const rate = data.stats.views ? Math.round((data.stats.leads / data.stats.views) * 1000) / 10 : 0;

  return (
    <Sheet {...head} sub={sub}
      title={!live ? <>Check your guide, then <em>publish</em> it.</> : data.stats.leads ? <>Your guide is bringing in <em>leads</em>.</> : <>Your guide is live. Now <em>share</em> it.</>}>
      <div className={`panel ${live ? "active" : ""}`}>
        <div className="row between">
          <span className="label">On your website</span>
          {live ? <Pill kind="on">Live{g.published_at ? ` · ${ago(g.published_at)}` : ""}</Pill> : <Pill>Not published</Pill>}
        </div>
        <Switch checked={live} disabled={publishing} label={live ? "Published on my website" : "Publish on my website"} onChange={togglePublish} />
        <FormError msg={pubErr} />
        {!data.site_live && !live && (
          <p className="small muted">The guide lives on your website, so the website has to be live first. <Link to="/website">Go to my website</Link></p>
        )}
        {data.url && live && (
          <>
            <a className="pg-link" href={data.url} target="_blank" rel="noopener">{data.url}</a>
            <div className="pg-actions">
              <Copy text={data.url} label="Copy link" />
              <a className="btn sm" href={data.url} target="_blank" rel="noopener">Open</a>
              <a className="btn sm" href={waLink(shareText)} target="_blank" rel="noopener">Share on WhatsApp</a>
            </div>
            <p className="small muted">Put this link in your WhatsApp Status, your groups and your Google profile. A link to it also shows on your website.</p>
          </>
        )}
        {data.url && !live && data.site_live && <span className="small muted">Once published, it will be at <span className="pg-link">{data.url}</span></span>}
      </div>

      <div className="statgrid">
        <Stat label="People who opened it" value={data.stats.views} />
        <Stat label="Left their number" value={data.stats.leads} note={data.stats.views ? `${rate}% of readers` : "Counted from the day you publish"} />
      </div>

      <GuideEditor content={content} onSaved={setData} />

      {rewrite
        ? <WriteForm onDone={(d) => { setData(d); setRewrite(false); }} onCancel={() => setRewrite(false)} />
        : <div><button className="btn ghost sm" onClick={() => setRewrite(true)}>Write a new guide with AI</button></div>}
    </Sheet>
  );
}

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, day, localPhone } from "../api.js";
import { Busy, Field, FormError, Sheet, Switch, useHub, useLoad } from "../ui.jsx";
import { Player } from "./Recordings.jsx";

const WHO = [
  ["free", "Everyone (Free and up)"],
  ["lite", "Membership and up"],
  ["program", "Action Program ₹10k and up"],
  ["running", "Running the Business ₹25k and up"],
  ["growth", "Growth Mentorship ₹1.5L and up"],
  ["office", "LegacyWorkforce ₹6L only"],
  ["none", "Only owners I add"],
];
const blankRec = () => ({ title: "", link: "", recorded_on: "", duration_min: "", notes: "", resources: [], published: true });

/** Checks a pasted link as the admin types, and says how it will play. */
function LinkCheck({ link }) {
  const [v, setV] = useState(null);
  const [err, setErr] = useState("");
  const [show, setShow] = useState(false);
  useEffect(() => {
    setV(null); setErr(""); setShow(false);
    if (link.trim().length < 6) return undefined;
    const t = setTimeout(() => api("/admin/video-check", { method: "POST", body: { link } }).then(setV).catch((e) => setErr(e.message)), 450);
    return () => clearTimeout(t);
  }, [link]);
  if (err) return <span className="hint" style={{ color: "var(--amber)" }}>{err}</span>;
  if (!v) return <span className="hint">Paste a Vimeo, YouTube, Loom, Wistia, Bunny Stream, Google Drive or GoHighLevel/.mp4 link.</span>;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <span className="hint">{v.provider_name} · {v.kind === "link" ? "opens in a new tab (this kind of link can't play inside the hub)" : "plays inside the hub"}
        {" · "}<button type="button" className="linkbtn" onClick={() => setShow(!show)}>{show ? "Hide preview" : "Preview"}</button></span>
      {show && <Player video={v} title="Preview" />}
    </div>
  );
}

function RecordingForm({ initial, sections, onSave, onCancel }) {
  const [f, setF] = useState(() => ({ ...blankRec(), ...initial, recorded_on: initial?.recorded_on || "", duration_min: initial?.duration_min || "",
    resources: initial?.resources || [] }));
  const [err, setErr] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const setRes = (i, k, val) => setF({ ...f, resources: f.resources.map((r, j) => (j === i ? { ...r, [k]: val } : r)) });
  return (
    <div className="objrow">
      <div className="grid2">
        <Field label="Title"><input className="input" maxLength={160} value={f.title} onChange={set("title")} placeholder="Week 3 · Live Q&A call" /></Field>
        {sections && (
          <Field label="Section"><select className="select" value={f.section_id} onChange={set("section_id")}>
            {sections.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></Field>
        )}
      </div>
      <Field label="Video link"><input className="input mono" maxLength={1000} value={f.link} onChange={set("link")} placeholder="https://vimeo.com/123456789/abcdef" /></Field>
      <LinkCheck link={f.link} />
      <div className="grid2">
        <Field label="Recorded on (optional)"><input className="input" type="date" value={f.recorded_on} onChange={set("recorded_on")} /></Field>
        <Field label="Length in minutes (optional)"><input className="input" type="number" min="1" max="600" inputMode="numeric" value={f.duration_min} onChange={set("duration_min")} placeholder="90" /></Field>
      </div>
      <Field label="Notes (optional)" hint="Shown under the video. Line breaks are kept and web addresses become links.">
        <textarea className="textarea" rows={5} maxLength={20000} value={f.notes} onChange={set("notes")} placeholder={"Key points from the call\nHomework for next week\nSlides: https://…"} />
      </Field>
      <div className="stack" style={{ gap: 8 }}>
        <span className="label">Resources (optional)</span>
        {f.resources.map((r, i) => (
          <div key={i} className="res-row">
            <input className="input" aria-label="Resource name" maxLength={80} value={r.label} onChange={(e) => setRes(i, "label", e.target.value)} placeholder="Slides" />
            <input className="input mono" aria-label="Resource link" maxLength={1000} value={r.url} onChange={(e) => setRes(i, "url", e.target.value)} placeholder="https://…" />
            <button type="button" className="btn sm ghost" onClick={() => setF({ ...f, resources: f.resources.filter((_, j) => j !== i) })}>Remove</button>
          </div>
        ))}
        {f.resources.length < 8 && <div><button type="button" className="btn sm ghost" onClick={() => setF({ ...f, resources: [...f.resources, { label: "", url: "" }] })}>Add a resource link</button></div>}
      </div>
      <FormError msg={err} />
      <div className="row between">
        <Switch checked={f.published} onChange={(published) => setF({ ...f, published })} label={f.published ? "Published" : "Draft — hidden from owners"} />
        <div className="row">
          <button type="button" className="btn sm ghost" onClick={onCancel}>Cancel</button>
          <Busy className="btn sm primary" onError={setErr} run={() => {
            if (f.title.trim().length < 2) throw new Error("Add a title of at least 2 characters.");
            if (!f.link.trim()) throw new Error("Paste the video link.");
            return onSave({
            ...f, duration_min: f.duration_min ? Number(f.duration_min) : null, recorded_on: f.recorded_on || null,
            resources: f.resources.filter((r) => r.url.trim()),
            });
          }}>Save recording</Busy>
        </div>
      </div>
    </div>
  );
}

function BulkForm({ sectionId, onDone, onCancel }) {
  const [lines, setLines] = useState("");
  const [err, setErr] = useState("");
  const { toast } = useHub();
  return (
    <div className="objrow">
      <Field label="Add many at once" hint="One recording per line: Title | link | date (date optional, like 2026-10-18). You can add notes to each one afterwards.">
        <textarea className="textarea mono" rows={6} value={lines} onChange={(e) => setLines(e.target.value)}
          placeholder={"Call 1 · Kickstart | https://vimeo.com/123456789 | 2026-10-11\nCall 2 · Brand message | https://vimeo.com/123456790 | 2026-10-18"} />
      </Field>
      <FormError msg={err ? err.split(" · ").join("\n") : ""} />
      <div className="row">
        <button className="btn sm ghost" onClick={onCancel}>Cancel</button>
        <Busy className="btn sm primary" onError={setErr} disabled={!lines.trim()} run={async () => {
          const r = await api("/admin/recordings/bulk", { method: "POST", body: { section_id: sectionId, lines } });
          toast(`Added ${r.added} recording${r.added === 1 ? "" : "s"}`); onDone();
        }}>Add them</Busy>
      </div>
    </div>
  );
}

function RecordingRow({ r, first, last, sections, reload }) {
  const { toast } = useHub();
  const [editing, setEditing] = useState(false);
  if (editing) {
    return <RecordingForm initial={r} sections={sections} onCancel={() => setEditing(false)}
      onSave={async (body) => { await api(`/admin/recordings/${r.id}`, { method: "PATCH", body }); toast("Saved"); setEditing(false); reload(); }} />;
  }
  return (
    <div className="rec-row">
      <div className="stack" style={{ gap: 2, minWidth: 0 }}>
        <span style={{ overflowWrap: "anywhere" }}>{r.title}</span>
        <span className="small muted">{[r.video?.provider_name, r.recorded_on && day(r.recorded_on), r.duration_min && `${r.duration_min} min`, r.notes && "notes", r.resources?.length && `${r.resources.length} link${r.resources.length === 1 ? "" : "s"}`].filter(Boolean).join(" · ")}</span>
      </div>
      <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
        {!r.published && <span className="token grey">Draft</span>}
        <button className="btn sm ghost" aria-label={`Move ${r.title} up`} disabled={first} onClick={async () => { await api(`/admin/recordings/${r.id}/move`, { method: "POST", body: { dir: "up" } }); reload(); }}>↑</button>
        <button className="btn sm ghost" aria-label={`Move ${r.title} down`} disabled={last} onClick={async () => { await api(`/admin/recordings/${r.id}/move`, { method: "POST", body: { dir: "down" } }); reload(); }}>↓</button>
        <button className="btn sm" onClick={() => setEditing(true)}>Edit</button>
        <Busy className="btn sm ghost" run={async () => {
          if (!window.confirm(`Delete “${r.title}”? Owners won't see it any more.`)) return;
          await api(`/admin/recordings/${r.id}`, { method: "DELETE" }); toast("Deleted"); reload();
        }}>Delete</Busy>
      </div>
    </div>
  );
}

function SectionBlock({ s, first, last, sections, reload }) {
  const { toast } = useHub();
  const [title, setTitle] = useState(s.title);
  const [mode, setMode] = useState(null); // add | bulk
  useEffect(() => setTitle(s.title), [s.title]);
  return (
    <div className="panel">
      <div className="row between" style={{ alignItems: "flex-end" }}>
        <Field label="Section">
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input className="input" maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Section name" />
            {title.trim() && title !== s.title && <Busy className="btn sm" run={async () => { await api(`/admin/sections/${s.id}`, { method: "PATCH", body: { title } }); toast("Renamed"); reload(); }}>Save</Busy>}
          </div>
        </Field>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm ghost" aria-label="Move section up" disabled={first} onClick={async () => { await api(`/admin/sections/${s.id}/move`, { method: "POST", body: { dir: "up" } }); reload(); }}>↑</button>
          <button className="btn sm ghost" aria-label="Move section down" disabled={last} onClick={async () => { await api(`/admin/sections/${s.id}/move`, { method: "POST", body: { dir: "down" } }); reload(); }}>↓</button>
          <Busy className="btn sm ghost" run={async () => {
            const n = s.recordings.length;
            if (!window.confirm(n ? `Delete “${s.title}” and its ${n} recording${n === 1 ? "" : "s"}?` : `Delete “${s.title}”?`)) return;
            await api(`/admin/sections/${s.id}`, { method: "DELETE" }); toast("Section deleted"); reload();
          }}>Delete section</Busy>
        </div>
      </div>
      {s.recordings.length ? (
        <div className="stack" style={{ gap: 0 }}>
          {s.recordings.map((r, i) => <RecordingRow key={r.id} r={r} first={i === 0} last={i === s.recordings.length - 1} sections={sections} reload={reload} />)}
        </div>
      ) : <span className="small muted">No recordings in this section yet. Owners don't see empty sections.</span>}
      {mode === "add" && <RecordingForm initial={{ section_id: s.id }} onCancel={() => setMode(null)}
        onSave={async (body) => { await api("/admin/recordings", { method: "POST", body: { ...body, section_id: s.id } }); toast("Recording added"); setMode(null); reload(); }} />}
      {mode === "bulk" && <BulkForm sectionId={s.id} onCancel={() => setMode(null)} onDone={() => { setMode(null); reload(); }} />}
      {!mode && (
        <div className="row">
          <button className="btn sm primary" onClick={() => setMode("add")}>Add a recording</button>
          <button className="btn sm ghost" onClick={() => setMode("bulk")}>Add many</button>
        </div>
      )}
    </div>
  );
}

function ProgramEditor({ id, onChanged, onDeleted, onDirty }) {
  const { toast } = useHub();
  const [p, reloadP] = useLoad(`/admin/programs/${id}`);
  const [f, setF] = useState(null);
  const [section, setSection] = useState("");
  const [phone, setPhone] = useState("");
  const [errs, setErrs] = useState({});
  const errFor = (k) => (m) => setErrs((e) => ({ ...e, [k]: m }));
  useEffect(() => { if (p) setF({ title: p.title, description: p.description || "", tier: p.tier, team: !!p.team, published: !!p.published }); }, [p]);
  const dirty = !!(p && f) && (f.title !== p.title || f.description !== (p.description || "") || f.tier !== p.tier || f.team !== !!p.team || f.published !== !!p.published);
  useEffect(() => { onDirty(dirty); }, [dirty, onDirty]);
  if (!p || !f) return null;
  const reload = () => { reloadP(); onChanged(); };
  const sectionsLite = p.sections_list.map((s) => ({ id: s.id, title: s.title }));
  return (
    <div className="stack" style={{ gap: 16, minWidth: 0 }}>
      <div className="panel active">
        <div className="row between">
          <span className="label">Program</span>
          <span className={`token ${p.published ? "" : "grey"}`}>{p.published ? "Published" : "Draft — hidden from owners"}</span>
        </div>
        <Field label="Name"><input className="input" maxLength={140} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="Who can watch" hint={f.tier === "none" ? "Add each owner below." : "Owners on this plan or a higher one. You can also add owners by hand below."}>
          <select className="select" value={f.tier} onChange={(e) => setF({ ...f, tier: e.target.value })}>{WHO.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        </Field>
        <div className="row" style={{ gap: 18 }}>
          <Switch checked={f.published} onChange={(published) => setF({ ...f, published })} label="Published" />
          <Switch checked={f.team} onChange={(team) => setF({ ...f, team })} label="Owners' team members can watch too" />
        </div>
        <Field label="Description (optional)"><textarea className="textarea" rows={2} maxLength={1000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="Weekly live calls of the Action Program, with notes and homework" /></Field>
        <FormError msg={errs.program} />
        <div className="row between">
          <Busy className="btn primary" disabled={!dirty} onError={errFor("program")} run={async () => { await api(`/admin/programs/${id}`, { method: "PATCH", body: f }); toast("Program saved"); reload(); }}>Save program</Busy>
          <Busy className="btn sm ghost" run={async () => {
            if (!window.confirm(`Delete “${p.title}” with its ${p.sections} section${p.sections === 1 ? "" : "s"} and ${p.recordings} recording${p.recordings === 1 ? "" : "s"}? This can't be undone.`)) return;
            await api(`/admin/programs/${id}`, { method: "DELETE" }); toast("Program deleted"); onDeleted();
          }}>Delete program</Busy>
        </div>
      </div>

      <div className="panel">
        <span className="label">Owners you added {p.allowed.length ? `· ${p.allowed.length}` : ""}</span>
        <p className="small muted">Give this program to specific owners — for example someone who paid offline. They must have logged in to the hub once.</p>
        <div className="inline-add">
          <input className="input" inputMode="tel" maxLength={24} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Owner's mobile number" aria-label="Owner's mobile number" />
          <Busy className="btn" disabled={!phone.trim()} onError={errFor("phone")} run={async () => { await api(`/admin/programs/${id}/allowed`, { method: "POST", body: { phone } }); setPhone(""); toast("Added"); reload(); }}>Add</Busy>
        </div>
        <FormError msg={errs.phone} />
        {p.allowed.length > 0 && (
          <div className="stack" style={{ gap: 0 }}>
            {p.allowed.map((u) => (
              <div key={u.id} className="rec-row">
                <span>{u.business || u.name || "Owner"} <span className="small muted mono">{localPhone(u.phone)}</span></span>
                <Busy className="btn sm ghost" run={async () => { await api(`/admin/programs/${id}/allowed/${u.id}`, { method: "DELETE" }); toast("Removed"); reload(); }}>Remove</Busy>
              </div>
            ))}
          </div>
        )}
      </div>

      {p.sections_list.map((s, i) => <SectionBlock key={s.id} s={s} first={i === 0} last={i === p.sections_list.length - 1} sections={sectionsLite} reload={reload} />)}

      <div className="panel flat">
        <span className="label">Add a section</span>
        <div className="inline-add">
          <input className="input" maxLength={100} value={section} onChange={(e) => setSection(e.target.value)} placeholder={p.sections_list.length ? "Week 2 · Systems" : "Week 1 · Kickstart"} aria-label="New section name" />
          <Busy className="btn" disabled={!section.trim()} onError={errFor("section")} run={async () => { await api(`/admin/programs/${id}/sections`, { method: "POST", body: { title: section } }); setSection(""); reload(); }}>Add section</Busy>
        </div>
        <FormError msg={errs.section} />
        <span className="small muted">Sections group recordings — by week, by module or by call type.</span>
      </div>
    </div>
  );
}

export default function AdminRecordings() {
  const { toast } = useHub();
  const [list, reload] = useLoad("/admin/programs");
  const [params, setParams] = useSearchParams();
  const [title, setTitle] = useState("");
  const [tier, setTier] = useState("program");
  const [newErr, setNewErr] = useState("");
  const dirty = useRef(false);
  const editorRef = useRef(null);
  const onDirty = useCallback((d) => { dirty.current = d; }, []);
  const selected = params.get("p") || list?.[0]?.id;
  const pick = (pid) => {
    if (pid === selected) return;
    if (dirty.current && !window.confirm("This program has changes you haven't saved. Leave without saving?")) return;
    dirty.current = false;
    setParams({ p: pid });
    if (window.innerWidth < 900) setTimeout(() => editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
  };
  return (
    <Sheet kicker="Admin · Recordings" id="A-02" pillar="Admin" title={<>Programs, sections and <em>recordings</em>.</>}
      sub="Upload each call to Vimeo, YouTube, GoHighLevel or a similar service, then paste its link here. Owners watch it in the hub; the video streams from that service.">
      <div className="split">
        <div className="stack">
          <span className="label">Programs</span>
          {list && !list.length && <span className="small muted">No programs yet. Create the first one below.</span>}
          <div className="listbox">
            {list?.map((p, i) => (
              <div key={p.id} className="prog-item">
                <button className={p.id === selected ? "on" : ""} onClick={() => pick(p.id)}>
                  <span>{p.title}</span>
                  <span className="small muted">{p.tier_name} · {p.recordings} recording{p.recordings === 1 ? "" : "s"}{p.published ? "" : " · draft"}</span>
                </button>
                <div className="prog-move">
                  <button className="btn sm ghost" aria-label={`Move ${p.title} up`} disabled={i === 0} onClick={async () => { await api(`/admin/programs/${p.id}/move`, { method: "POST", body: { dir: "up" } }); reload(); }}>↑</button>
                  <button className="btn sm ghost" aria-label={`Move ${p.title} down`} disabled={i === list.length - 1} onClick={async () => { await api(`/admin/programs/${p.id}/move`, { method: "POST", body: { dir: "down" } }); reload(); }}>↓</button>
                </div>
              </div>
            ))}
          </div>
          <div className="panel flat" style={{ padding: 16 }}>
            <span className="label">New program</span>
            <input className="input" maxLength={140} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Action Program · Oct 2026 batch" aria-label="New program name" />
            <select className="select" value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Who can watch">{WHO.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <FormError msg={newErr} />
            <Busy className="btn primary" disabled={!title.trim()} onError={setNewErr} run={async () => {
              const p = await api("/admin/programs", { method: "POST", body: { title, tier, published: false } });
              setTitle(""); await reload(); pick(p.id); toast("Program created as a draft — add sections and recordings, then publish it");
            }}>Create program</Busy>
          </div>
          <p className="small muted">Tip: in Vimeo, set each video's privacy to “Hide from Vimeo” and allow embedding only on your hub's domain, so it plays in the hub and nowhere else.</p>
        </div>
        <div ref={editorRef} style={{ minWidth: 0, scrollMarginTop: 72 }}>
          {selected ? <ProgramEditor key={selected} id={selected} onChanged={reload} onDirty={onDirty} onDeleted={async () => { dirty.current = false; setParams({}); await reload(); }} />
            : <div className="empty"><p className="muted">Create a program to start adding recordings.</p></div>}
        </div>
      </div>
    </Sheet>
  );
}

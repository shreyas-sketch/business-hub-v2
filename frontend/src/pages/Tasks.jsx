import React, { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, day } from "../api.js";
import { Busy, Field, Gate, Modal, Sheet, canAct, useHub, useLoad } from "../ui.jsx";
import "./team.css";

const today = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local time

function TaskEdit({ task, people, onClose, onSaved }) {
  const [v, setV] = useState({ title: task.title, note: task.note || "", due: task.due || "", assignee_id: task.assignee_id || "" });
  const save = async () => {
    await api(`/tasks/${task.id}`, { method: "PATCH", body: { ...v, due: v.due || null, assignee_id: v.assignee_id || null } });
    onSaved();
  };
  return (
    <Modal onClose={onClose}>
      <span className="kicker">Edit task</span>
      <Field label="Task"><input className="input" value={v.title} maxLength={200} onChange={(e) => setV({ ...v, title: e.target.value })} /></Field>
      <Field label="Note (optional)"><textarea className="textarea" value={v.note} maxLength={1000} onChange={(e) => setV({ ...v, note: e.target.value })} /></Field>
      <div className="grid2">
        <Field label="Who"><select className="select" value={v.assignee_id} onChange={(e) => setV({ ...v, assignee_id: e.target.value })}>
          <option value="">No one yet</option>
          {people.map((p) => <option key={p.id} value={p.id}>{p.name}{p.role === "owner" ? " (owner)" : ""}</option>)}
        </select></Field>
        <Field label="Due"><input className="input" type="date" value={v.due} onChange={(e) => setV({ ...v, due: e.target.value })} /></Field>
      </div>
      <div className="row">
        <Busy className="btn primary" disabled={!v.title.trim()} run={save}>Save</Busy>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function TaskRow({ t, me, manager, onChange, onEdit }) {
  const { toast } = useHub();
  const mine = t.assignee_id === me.user.id;
  const late = t.status === "open" && t.due && t.due < today();
  const toggle = async () => {
    try {
      await api(`/tasks/${t.id}`, { method: "PATCH", body: { status: t.status === "done" ? "open" : "done" } });
      toast(t.status === "done" ? "Task reopened" : "Done. Nice work.");
      onChange();
    } catch (e) { if (!e.handled) toast(e.message, "err"); }
  };
  return (
    <div className={`task-row ${t.status === "done" ? "done" : ""}`}>
      <button className={`tick ${t.status === "done" ? "on" : ""}`} disabled={!manager && !mine} onClick={toggle}
        aria-label={t.status === "done" ? `Reopen: ${t.title}` : `Mark done: ${t.title}`} title={t.status === "done" ? "Reopen" : "Mark done"} />
      <div className="task-body">
        <span className="task-title">{t.title}</span>
        {t.note && <span className="task-note">{t.note}</span>}
        <div className="task-meta">
          <span>{t.assignee_name ? (mine ? "You" : t.assignee_name) : "No one yet"}</span>
          {t.due && <span className={late ? "late" : ""}>{late ? "Overdue · " : "Due "}{day(t.due)}</span>}
          {t.status === "done" && t.done_at && <span>Done {day(t.done_at)}</span>}
          {t.source?.kind === "meeting" && t.source.id && <Link to={`/meetings?id=${t.source.id}`}>From a meeting</Link>}
          {t.source?.kind === "office" && <span>From the AI office</span>}
          {t.created_by_name && t.created_by !== t.assignee_id && t.source?.kind === "manual" && <span>Added by {t.created_by === me.user.id ? "you" : t.created_by_name}</span>}
        </div>
      </div>
      {manager && (
        <div className="row task-actions">
          <button className="btn sm ghost" onClick={() => onEdit(t)}>Edit</button>
          <Busy className="btn sm ghost" run={async () => { if (!window.confirm("Delete this task?")) return; await api(`/tasks/${t.id}`, { method: "DELETE" }); toast("Task deleted"); onChange(); }}>Delete</Busy>
        </div>
      )}
    </div>
  );
}

function TasksInner() {
  const { me, refresh, toast } = useHub();
  const manager = canAct(me, "manager");
  const [params] = useSearchParams();
  const [scope, setScope] = useState(manager && params.get("scope") === "all" ? "all" : "mine");
  const [status, setStatus] = useState("open");
  const [tasks, reload] = useLoad(`/tasks?scope=${scope}&status=${status}`);
  const [people] = useLoad("/team/people");
  const blank = { title: "", due: "", assignee_id: me.user.id };
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState(null);
  const changed = () => { reload(); refresh(); };

  const add = async () => {
    const body = { title: form.title, due: form.due || null, ...(manager ? { assignee_id: form.assignee_id || null } : {}) };
    const t = await api("/tasks", { method: "POST", body });
    setForm({ ...blank, assignee_id: form.assignee_id });
    toast(t.assignee_id && t.assignee_id !== me.user.id ? `Task sent to ${t.assignee_name}` : "Task added");
    changed();
  };

  const n = tasks?.length || 0;
  const title = status === "done" ? <>What's been <em>done</em>.</>
    : !tasks ? <>Your <em>tasks</em>.</>
    : scope === "all" ? (n ? <>{n} open {n === 1 ? "task" : "tasks"} across the <em>team</em>.</> : <>Nothing open across the <em>team</em>.</>)
    : n ? <>{n} {n === 1 ? "task" : "tasks"} on your <em>list</em>.</> : <>Your list is <em>clear</em>.</>;

  return (
    <Sheet kicker="Start · Tasks" id="ST-02" title={title}
      sub={manager ? "Give a task to anyone on the team, with a due date. They see it on their list and get a note on their Home. Tasks from meetings land here too."
        : "Everything that's yours to do, in order of when it's due. Tick it off when it's done."}>
      <div className="panel active">
        <span className="label">New task</span>
        <div className="task-add">
          <Field label="What needs doing"><input className="input" value={form.title} maxLength={200} placeholder="Send the quotation to Mr. Joshi"
            onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label="Due (optional)"><input className="input" type="date" value={form.due} min={today()} onChange={(e) => setForm({ ...form, due: e.target.value })} /></Field>
          {manager ? (
            <Field label="Who"><select className="select" value={form.assignee_id} onChange={(e) => setForm({ ...form, assignee_id: e.target.value })}>
              <option value="">No one yet</option>
              {(people || []).map((p) => <option key={p.id} value={p.id}>{p.id === me.user.id ? `Me (${p.name})` : p.name}</option>)}
            </select></Field>
          ) : <span />}
          <Busy className="btn primary" disabled={!form.title.trim()} run={add}>Add</Busy>
        </div>
      </div>

      <div className="row between">
        <div className="tabs" role="tablist">
          {[["open", "Open"], ["done", "Done"]].map(([k, l]) => (
            <button key={k} role="tab" aria-selected={status === k} className={status === k ? "on" : ""} onClick={() => setStatus(k)}>{l}</button>
          ))}
        </div>
        {manager && (
          <div className="tabs" role="tablist" aria-label="Whose tasks">
            {[["mine", "Mine"], ["all", "Everyone"]].map(([k, l]) => (
              <button key={k} role="tab" aria-selected={scope === k} className={scope === k ? "on" : ""} onClick={() => setScope(k)}>{l}</button>
            ))}
          </div>
        )}
      </div>

      {!tasks ? <div className="panel muted">Loading…</div> : !tasks.length ? (
        <div className="empty">
          <p className="muted">{status === "done" ? "Finished tasks will show here." : scope === "all" ? "No open tasks. Add one above, or pull them out of your next meeting."
            : "Nothing on your list right now."}</p>
          {status === "open" && me.features.meetings && <Link className="btn sm ghost" to="/meetings">Go to meetings</Link>}
        </div>
      ) : (
        <div className="task-list">
          {tasks.map((t) => <TaskRow key={t.id} t={t} me={me} manager={manager} onChange={changed} onEdit={setEditing} />)}
        </div>
      )}

      {editing && <TaskEdit task={editing} people={people || []} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); toast("Saved"); changed(); }} />}
    </Sheet>
  );
}

export default function Tasks() {
  return (
    <Gate feature="tasks" role="staff" kicker="Start · Tasks" id="ST-02" what="Give tasks to your team with due dates, and see what's done.">
      <TasksInner />
    </Gate>
  );
}

import React, { useState } from "react";
import { ago, api, localPhone } from "../api.js";
import { Busy, Copy, Field, Gate, Modal, Sheet, useHub, useLoad } from "../ui.jsx";
import "./team.css";

const ROLES = {
  manager: { label: "Manager", can: "Leads, tasks, meetings, money owed, approvals and insights." },
  staff: { label: "Staff", can: "Leads, their own tasks, SOPs, meetings (to read) and GPT bots." },
};


function Share({ invite, primary }) {
  return (
    <div className="row">
      <a className={`btn sm ${primary ? "primary" : ""}`} href={invite.share_link} target="_blank" rel="noopener">Send on WhatsApp</a>
      <Copy text={invite.message} label="Copy message" className="btn sm ghost" />
    </div>
  );
}

function TeamInner() {
  const { toast } = useHub();
  const [team, reload] = useLoad("/team");
  const blank = { name: "", phone: "", role: "staff" };
  const [form, setForm] = useState(blank);
  const [fresh, setFresh] = useState(null);
  const [removing, setRemoving] = useState(null);

  const count = team?.members.length || 0;
  const title = !team ? <>Your <em>team</em>.</>
    : count ? <>{count} {count === 1 ? "person" : "people"} on your <em>team</em>.</>
    : <>Bring your team onto the <em>hub</em>.</>;
  const full = team && team.used >= team.limit;

  const invite = async () => {
    const inv = await api("/team/invites", { method: "POST", body: form });
    setFresh(inv);
    setForm(blank);
    reload();
  };
  const setRole = async (m, role) => {
    await api(`/team/members/${m.id}`, { method: "PATCH", body: { role } });
    toast(`${m.name || "They"} can now use the hub as ${role === "manager" ? "a manager" : "staff"}.`);
    reload();
  };

  return (
    <Sheet kicker="Systems · Team" id="SY-07" pillar="Systems" title={title}
      sub="Each person logs in with their own mobile number and sees only what their role needs. You can change a role or remove someone at any time.">
      <div className="grid2">
        {Object.entries(ROLES).map(([k, r]) => (
          <div key={k} className="role-card"><span className="label">{r.label}</span><span className="small">{r.can}</span></div>
        ))}
      </div>
      <p className="small muted">Only you see the Business Brain, website settings, the team, and plans and billing.</p>

      {!team ? <div className="panel muted">Loading…</div> : (
        <>
          <div className="panel active">
            <div className="row between">
              <span className="label">Add someone</span>
              <span className="small muted">{team.used} of {team.limit} team logins used</span>
            </div>
            {full ? (
              <p className="small muted">Your team is full. Remove someone or cancel an invite to add another person.</p>
            ) : (
              <>
                <div className="grid2">
                  <Field label="Name"><input className="input" value={form.name} maxLength={80} placeholder="Ravi Kumar" onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
                  <Field label="Their mobile number" hint="The number they'll log in with.">
                    <input className="input mono" type="tel" inputMode="tel" value={form.phone} maxLength={24} placeholder="98200 00000" onChange={(e) => setForm({ ...form, phone: e.target.value })} />
                  </Field>
                </div>
                <Field label="Role">
                  <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                    {Object.entries(ROLES).map(([k, r]) => <option key={k} value={k}>{r.label} — {r.can}</option>)}
                  </select>
                </Field>
                <div><Busy className="btn primary" disabled={form.name.trim().length < 1 || form.phone.replace(/\D/g, "").length < 10} run={invite}>Add to team</Busy></div>
              </>
            )}
            {fresh && (
              <div className="notice">
                <span className="small"><b>{fresh.name}</b> can log in now. Send them the link so they know.</span>
                <Share invite={fresh} primary />
              </div>
            )}
          </div>

          {team.invites.length > 0 && (
            <div className="stack">
              <span className="label">Waiting to log in</span>
              {team.invites.map((i) => (
                <div key={i.id} className="panel flat" style={{ padding: "14px 16px" }}>
                  <div className="row between">
                    <span><b>{i.name}</b> <span className="mono muted">{localPhone(i.phone)}</span> <span className="token grey">{ROLES[i.role]?.label}</span>
                      <span className="small muted"> · added {ago(i.created_at)}</span></span>
                    <div className="row">
                      <Share invite={i} />
                      <Busy className="btn sm ghost" run={async () => { await api(`/team/invites/${i.id}`, { method: "DELETE" }); if (fresh?.id === i.id) setFresh(null); toast("Invite cancelled"); reload(); }}>Cancel</Busy>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="stack">
            <span className="label">On your team</span>
            {!team.members.length ? (
              <div className="empty"><p className="muted">No one has logged in yet. Once they log in with their number, they'll show here.</p></div>
            ) : (
              <table className="t cards">
                <thead><tr><th>Name</th><th>Number</th><th>Role</th><th>Last seen</th><th /></tr></thead>
                <tbody>{team.members.map((m) => (
                  <tr key={m.id}>
                    <td><b>{m.name || "No name yet"}</b></td>
                    <td className="mono" data-l="Number">{localPhone(m.phone)}</td>
                    <td data-l="Role">
                      <select className="select" style={{ minWidth: 130 }} aria-label={`Role for ${m.name}`} value={m.role} onChange={(e) => setRole(m, e.target.value).catch((err) => toast(err.message, "err"))}>
                        {Object.entries(ROLES).map(([k, r]) => <option key={k} value={k}>{r.label}</option>)}
                      </select>
                    </td>
                    <td className="small muted" data-l="Last seen">{m.last_seen_at ? ago(m.last_seen_at) : "Not yet"}</td>
                    <td><button className="btn sm ghost" onClick={() => setRemoving(m)}>Remove</button></td>
                  </tr>))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {removing && (
        <Modal onClose={() => setRemoving(null)}>
          <span className="kicker">Team</span>
          <h2>Remove <em>{removing.name || "this person"}</em>?</h2>
          <p className="sub">They'll be logged out straight away and can't see your hub any more. Their open tasks go back to unassigned.</p>
          <div className="row">
            <Busy className="btn" run={async () => { await api(`/team/members/${removing.id}`, { method: "DELETE" }); toast(`${removing.name || "They"} removed from the team`); setRemoving(null); reload(); }}>Remove</Busy>
            <button className="btn ghost" onClick={() => setRemoving(null)}>Keep</button>
          </div>
        </Modal>
      )}
    </Sheet>
  );
}

export default function Team() {
  return (
    <Gate feature="team_logins" role="owner" kicker="Systems · Team" id="SY-07"
      what="Give your managers and staff their own logins, each seeing only what their role needs.">
      <TeamInner />
    </Gate>
  );
}

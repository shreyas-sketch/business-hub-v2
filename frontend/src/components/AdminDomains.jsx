import React, { useState } from "react";
import { api, ago, localPhone } from "../api.js";
import { Busy, Copy, Field, useHub, useLoad } from "../ui.jsx";
import { DOMAIN_STATUS } from "./DomainPanel.jsx";

/** Admin: owners' own domains. A verified domain is added in Railway (custom domains), and once its certificate is issued it is marked live here. */
export default function AdminDomains() {
  const { toast } = useHub();
  const [rows, reload] = useLoad("/admin/domains");
  if (!rows) return null;
  const waiting = rows.filter((r) => r.status === "verified").length;
  const toSetUp = rows.filter((r) => r.status === "setup").length;
  const setLive = async (r, live) => {
    await api(`/admin/domains/${r.site_id}/live`, { method: "POST", body: { live } });
    toast(live ? `${r.name} is live — the owner has been told` : `${r.name} moved back to connected`);
    reload();
  };
  return (
    <div className="panel">
      <div className="row between">
        <span className="label">Own domains</span>
        <span className="small muted">{[toSetUp && `${toSetUp} to set up`, waiting && `${waiting} waiting for https`].filter(Boolean).join(" · ") || "Nothing waiting"}</span>
      </div>
      <p className="small muted">New domain: add it in Railway (service → Settings → Networking → Custom domain) and paste the CNAME and TXT records Railway shows below — the owner then sees exactly those. Once the owner's check passes and Railway shows the certificate, mark it live.</p>
      {!rows.length ? <span className="small muted">No owner has added a domain yet.</span> : (
        <table className="t cards">
          <thead><tr><th>Domain</th><th>Business</th><th>Status</th><th>Checked</th><th /></tr></thead>
          <tbody>{rows.map((r) => {
            const [label, cls] = DOMAIN_STATUS[r.status] || DOMAIN_STATUS.pending;
            return (
              <tr key={`${r.site_id}-${r.name}`}>
                <td><div className="row" style={{ gap: 8 }}><b className="mono">{r.name}</b><Copy text={r.name} className="btn sm ghost" /></div></td>
                <td data-l="Business"><span>{r.business || r.slug}<div className="small muted mono">{localPhone(r.phone)}</div>
                  {r.slug && <a className="small" href={r.hub_url} target="_blank" rel="noopener">/s/{r.slug}</a>}{r.slug && r.site_status !== "live" && <span className="small muted"> · offline</span>}</span></td>
                <td data-l="Status"><span className={cls}>{label}</span></td>
                <td data-l="Checked" className="small muted">{r.status === "released" ? `removed ${ago(r.released_at)}` : r.checked_at ? ago(r.checked_at) : "never"}</td>
                <td>
                  {r.status === "verified" && <Busy className="btn sm primary" run={() => setLive(r, true)}>Mark live</Busy>}
                  {r.status === "live" && <Busy className="btn sm ghost" run={() => setLive(r, false)}>Undo live</Busy>}
                  {r.status === "pending" && <span className="small muted">Owner hasn't pointed it yet</span>}
                  {r.mode === "hosted" && (r.status === "setup" || r.status === "pending") && <Records r={r} onSaved={reload} />}
                  {r.status === "released" && <Busy className="btn sm ghost" run={async () => { await api(`/admin/domains/released/${encodeURIComponent(r.name)}`, { method: "DELETE" }); reload(); }}>Removed from Railway</Busy>}
                </td>
              </tr>
            );
          })}</tbody>
        </table>
      )}
    </div>
  );
}


/** Hosted mode: the records Railway shows for this domain, pasted by the admin and shown to the owner. */
function Records({ r, onSaved }) {
  const { toast } = useHub();
  const cname = (r.records || []).find((x) => x.type === "CNAME");
  const txt = (r.records || []).find((x) => x.type === "TXT");
  const [open, setOpen] = useState(r.status === "setup");
  const [f, setF] = useState({ cname: cname?.value || "", txt_name: txt?.name || "", txt_value: txt?.value || "" });
  if (!open) return <button className="btn sm ghost" onClick={() => setOpen(true)}>Edit records</button>;
  return (
    <div className="stack" style={{ gap: 6, minWidth: 240 }}>
      <Field label="CNAME value"><input className="input mono" placeholder="abc123.up.railway.app" value={f.cname} onChange={(e) => setF({ ...f, cname: e.target.value })} /></Field>
      <Field label="TXT name"><input className="input mono" placeholder="_railway-verify.www" value={f.txt_name} onChange={(e) => setF({ ...f, txt_name: e.target.value })} /></Field>
      <Field label="TXT value"><input className="input mono" placeholder="railway-verify=…" value={f.txt_value} onChange={(e) => setF({ ...f, txt_value: e.target.value })} /></Field>
      <Busy className="btn sm primary" disabled={f.cname.trim().length < 4} run={async () => {
        await api(`/admin/domains/${r.site_id}/records`, { method: "PUT", body: f });
        toast(r.status === "setup" ? "Saved — the owner has been told" : "Records updated");
        setOpen(false); onSaved();
      }}>{r.status === "setup" ? "Save and tell the owner" : "Save"}</Busy>
    </div>
  );
}

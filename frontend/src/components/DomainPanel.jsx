import React, { useState } from "react";
import { api, ago } from "../api.js";
import { Busy, Copy, Locked, useHub, useLoad } from "../ui.jsx";
import "../pages/membership.css";

export const DOMAIN_STATUS = {
  setup: ["Being prepared", "token grey"],
  pending: ["Waiting for your DNS records", "token grey"],
  verified: ["Connected · https on the way", "token"],
  live: ["Live", "token"],
  released: ["Removed by owner", "token grey"],
};

/** Website page: show the website on the owner's own domain (Membership). */
export default function DomainPanel() {
  const { me } = useHub();
  if (!me || me.workspace?.role !== "owner") return null;
  if (!me.features?.custom_domain) return <Locked feature="custom_domain" what="Your own domain, like www.yourbusiness.in" />;
  return <DomainInner />;
}

function DomainInner() {
  const { toast } = useHub();
  const [data, reload] = useLoad("/site/domain");
  const [name, setName] = useState("");
  if (!data) return null;
  const d = data.domain;

  if (!d) {
    return (
      <div className="panel">
        <span className="label">Your own domain</span>
        <p className="small">Already own a domain? Show this website on it — for example <span className="mono">www.yourbusiness.in</span>. Your hub address keeps working too.</p>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input className="input mono" aria-label="Your domain" placeholder="www.yourbusiness.in" value={name} onChange={(e) => setName(e.target.value)} />
          <Busy className="btn" disabled={name.trim().length < 4} run={async () => { await api("/site/domain", { method: "POST", body: { domain: name } }); setName(""); await reload(); }}>Connect</Busy>
        </div>
        <p className="small muted">No domain yet? You can buy one from any domain provider (GoDaddy, Hostinger, BigRock and others), then come back here.</p>
      </div>
    );
  }

  const [label, cls] = DOMAIN_STATUS[d.status] || DOMAIN_STATUS.pending;
  const records = d.records || [];
  const cname = records.find((x) => x.type === "CNAME");
  return (
    <div className={`panel ${d.status === "live" ? "active" : ""}`}>
      <div className="row between"><span className="label">Your own domain</span><span className={cls}>{label}</span></div>
      {d.status === "live"
        ? <a className="mono" href={d.url} target="_blank" rel="noopener" style={{ fontSize: 16 }}>{d.url}</a>
        : <span className="mono" style={{ fontSize: 16 }}>{d.name}</span>}
      {d.status === "setup" && (
        <p className="small">We're getting your domain ready on our side. Within a working day the records to add will appear here, and you'll get a notice in the hub.</p>
      )}
      {d.status === "pending" && records.length > 0 && (
        <>
          <p className="small">Add {records.length === 1 ? "this record" : `these ${records.length} records`} in your domain's DNS settings:</p>
          {records.map((x) => (
            <div key={`${x.type}-${x.name}`} className="dns-rec">
              <span className="label">Type</span><span className="mono">{x.type}</span><span />
              <span className="label">Name / Host</span><span className="mono">{x.name}</span><Copy text={x.name} className="btn sm ghost" />
              <span className="label">{x.type === "CNAME" ? "Points to" : "Value"}</span><span className="mono">{x.value}</span><Copy text={x.value} className="btn sm ghost" />
            </div>
          ))}
          <ol className="steps-list">
            <li>Log in where you bought the domain and open its DNS settings.</li>
            {cname && <li>Delete any old record with the name <span className="mono">{cname.name}</span>, then add the CNAME record above. Leave TTL as it is.</li>}
            {records.some((x) => x.type === "TXT") && <li>Add the TXT record exactly as shown — it proves the domain is yours.</li>}
            <li>Come back and press Check now. It can take a few hours to start working.</li>
          </ol>
          {d.apex && <p className="small muted">Some providers don't allow a CNAME on the main domain (@). If yours doesn't, connect <span className="mono">www.{d.name}</span> instead.</p>}
        </>
      )}
      {d.note && <p className="small">{d.note}</p>}
      {!data.site.live && <p className="small muted">Your website is offline right now. Publish it to show it on this domain.</p>}
      <div className="row">
        {d.status !== "live" && d.status !== "setup" && <Busy className="btn sm" run={async () => { const x = await api("/site/domain/check", { method: "POST" }); await reload(); toast(DOMAIN_STATUS[x.domain.status][0]); }}>Check now</Busy>}
        <Busy className="btn sm ghost" run={async () => { if (!window.confirm(`Remove ${d.name}? Your website stays on your hub address.`)) return; await api("/site/domain", { method: "DELETE" }); await reload(); }}>Remove</Busy>
        {d.checked_at && <span className="small muted">Checked {ago(d.checked_at)}</span>}
      </div>
    </div>
  );
}

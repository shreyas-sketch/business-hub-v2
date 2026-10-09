import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, waLink } from "../api.js";
import { Busy, Copy, Field, InviteLine, Locked, Sheet, useHub, useLoad } from "../ui.jsx";
import DomainPanel from "../components/DomainPanel.jsx";

function ListEditor({ label, items, setItems, fields, max, blank }) {
  return (
    <div className="stack">
      <span className="label">{label}</span>
      {items.map((it, i) => (
        <div key={i} className="stack" style={{ borderLeft: "1px solid var(--ink-line)", paddingLeft: 12 }}>
          {fields.map(([k, ph, long]) => long
            ? <textarea key={k} className="textarea" style={{ minHeight: 64 }} placeholder={ph} value={it[k] || ""} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} />
            : <input key={k} className="input" placeholder={ph} value={it[k] || ""} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} />)}
          <button className="btn sm ghost" style={{ justifySelf: "start" }} onClick={() => setItems(items.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      {items.length < max && <button className="btn sm ghost" style={{ justifySelf: "start" }} onClick={() => setItems([...items, blank])}>Add</button>}
    </div>
  );
}

export default function Website() {
  const { me, refresh, toast } = useHub();
  const [site, reload] = useLoad("/site");
  const [c, setC] = useState(null);
  const [accent, setAccent] = useState(null);
  const [slug, setSlug] = useState("");
  const [showcase, setShowcase] = useState(false);
  const [frame, setFrame] = useState(0);
  const [building, setBuilding] = useState(false);
  const [guideUrl, setGuideUrl] = useState(null);

  useEffect(() => {
    if (site?.content) { setC(site.content); setAccent(site.accent); setSlug(site.slug); setShowcase(!!site.showcase); }
  }, [site]);
  // The free guide's link, once the lead magnet is published (Action Program).
  useEffect(() => {
    if (!me.features?.lead_magnet || site?.status !== "live") { setGuideUrl(null); return; }
    api("/lead-magnet").then((d) => setGuideUrl(d.guide?.published ? d.url : null)).catch(() => setGuideUrl(null));
  }, [me.features?.lead_magnet, site?.status, site?.slug]);

  const build = async () => {
    setBuilding(true);
    try { await api("/site/generate", { method: "POST" }); await reload(); await refresh(); setFrame((f) => f + 1); }
    catch (e) { if (!e.handled) toast(e.message, "err"); } finally { setBuilding(false); }
  };
  const save = async () => {
    const r = await api("/site", { method: "PUT", body: { content: c, accent, slug, showcase } });
    await reload(); setFrame((f) => f + 1); await refresh(); return r;
  };

  if (site === null) return null;
  if (!site.content) {
    return (
      <Sheet kicker="Systems · Website" id="SY-01" pillar="Systems" step={2} title={<>Your website, written from your <em>Brain</em>.</>}
        sub="The AI uses your brand message, your products and why customers choose you. Nothing invented — you can edit every word before it goes live.">
        <div className="empty">
          <h2>{building ? "Writing your website…" : "Ready when you are."}</h2>
          <p className="muted">Uses 1 AI run. Takes about a minute.</p>
          <button className="btn primary" disabled={building} onClick={build}>{building ? "Building…" : "Build my website"}</button>
        </div>
      </Sheet>
    );
  }
  if (!c) return null;
  const live = site.status === "live";
  const shareText = encodeURIComponent(`Here's our website — you can send an inquiry directly: ${site.url}`);
  return (
    <Sheet kicker="Systems · Website" id="SY-01" pillar="Systems" step={2}
      title={live ? <>Your website is <em>live</em>.</> : <>Check it, then go <em>live</em>.</>}
      sub={live ? "Every inquiry from the form lands in Leads and alerts you on WhatsApp." : "Edit anything on the left. The preview on the right is exactly what customers will see."}
      actions={<>
        <Busy className="btn ghost sm" run={async () => { await save(); toast("Saved"); }}>Save</Busy>
        {live
          ? <Busy className="btn ghost sm" run={async () => { await api("/site/unpublish", { method: "POST" }); await reload(); await refresh(); }}>Take offline</Busy>
          : <Busy className="btn primary" run={async () => { await save(); await api("/site/publish", { method: "POST" }); await reload(); await refresh(); toast("Your website is live"); }}>Publish</Busy>}
      </>}>
      {live && (
        <div className="panel active">
          <span className="label">Your web address</span>
          <div className="row"><a className="mono" href={site.url} target="_blank" rel="noopener" style={{ wordBreak: "break-all" }}>{site.url}</a></div>
          <div className="row">
            <Copy text={site.url} label="Copy link" />
            <a className="btn sm" href={`https://wa.me/?text=${shareText}`} target="_blank" rel="noopener">Send to customers on WhatsApp</a>
          </div>
          <p className="small muted">Put this link on your WhatsApp Business profile, Google Business listing and visiting card.</p>
          {site.card_url && (
            <>
              <hr className="rule" />
              <span className="label">Your digital visiting card</span>
              <a className="mono small" href={site.card_url} target="_blank" rel="noopener" style={{ wordBreak: "break-all" }}>{site.card_url}</a>
              <div className="row">
                <Copy text={site.card_url} label="Copy link" />
                <a className="btn sm" href={waLink(`Here's my visiting card — save my number in one tap: ${site.card_url}`)} target="_blank" rel="noopener">Share on WhatsApp</a>
              </div>
            </>
          )}
          {guideUrl && (
            <>
              <hr className="rule" />
              <span className="label">Your free guide</span>
              <a className="mono small" href={guideUrl} target="_blank" rel="noopener" style={{ wordBreak: "break-all" }}>{guideUrl}</a>
              <div className="row">
                <Copy text={guideUrl} label="Copy link" />
                <a className="btn sm" href={waLink(`Here's a free guide for you: ${guideUrl}`)} target="_blank" rel="noopener">Share on WhatsApp</a>
                <Link className="btn sm ghost" to="/lead-magnet">Edit the guide</Link>
              </div>
            </>
          )}
        </div>
      )}
      <DomainPanel />
      <div className="grid2" style={{ alignItems: "start" }}>
        <div className="stack">
          <div className="panel">
            <Field label="Headline"><input className="input" value={c.headline} maxLength={120} onChange={(e) => setC({ ...c, headline: e.target.value })} /></Field>
            <Field label="Line under the headline"><textarea className="textarea" style={{ minHeight: 64 }} value={c.subheadline} maxLength={300} onChange={(e) => setC({ ...c, subheadline: e.target.value })} /></Field>
            <Field label="Button text"><input className="input" value={c.cta} maxLength={40} onChange={(e) => setC({ ...c, cta: e.target.value })} /></Field>
            <Field label="About us"><textarea className="textarea" value={c.about} maxLength={1200} onChange={(e) => setC({ ...c, about: e.target.value })} /></Field>
          </div>
          <div className="panel">
            <ListEditor label="What you offer" items={c.offers} setItems={(offers) => setC({ ...c, offers })} max={12} blank={{ name: "", description: "", price: "" }}
              fields={[["name", "Product or service"], ["description", "One line about it", true], ["price", "Price (leave empty to quote)"]]} />
          </div>
          <div className="panel">
            <ListEditor label="Why customers choose you" items={c.why} setItems={(why) => setC({ ...c, why })} max={6} blank={{ title: "", text: "" }} fields={[["title", "Reason"], ["text", "One line (optional)"]]} />
          </div>
          <div className="panel">
            <ListEditor label="How it works" items={c.steps} setItems={(steps) => setC({ ...c, steps })} max={6} blank={{ title: "", text: "" }} fields={[["title", "Step"], ["text", "What happens"]]} />
          </div>
          <div className="panel">
            <ListEditor label="Questions customers ask" items={c.faq} setItems={(faq) => setC({ ...c, faq })} max={10} blank={{ q: "", a: "" }} fields={[["q", "Question"], ["a", "Answer", true]]} />
          </div>
          <div className="panel">
            <span className="label">Look</span>
            <div className="row">{site.accents.map((a) => <button key={a} className={`swatch ${a === accent ? "on" : ""}`} style={{ background: a }} aria-label={`Colour ${a}`} onClick={() => setAccent(a)} />)}</div>
            <Field label="Web address" hint="Lowercase letters, numbers and dashes. Changing it changes your link everywhere.">
              <div className="row" style={{ flexWrap: "nowrap", gap: 6 }}>
                {!site.sites_domain && <span className="small muted hide-sm">{site.url.replace(/[^/]+$/, "")}</span>}
                <input className="input mono" style={{ minWidth: 0 }} aria-label="Web address" value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} />
                {site.sites_domain && <span className="small muted mono" style={{ flex: "none" }}>.{site.sites_domain}</span>}
              </div>
            </Field>
            <label className="row small" style={{ cursor: "pointer" }}><input type="checkbox" checked={showcase} onChange={(e) => setShowcase(e.target.checked)} /> Show my website in the public showcase</label>
          </div>
          <div className="panel">
            <span className="label">Badge</span>
            <p className="small">{site.badge ? "Free websites show a small “Built free with Business AI Action Hub” badge. When an owner signs up from your badge, you get rewards." : "Badge off — your website shows only your business."}</p>
            {site.badge && <Locked feature="badge_off" what="Remove the badge" />}
          </div>
          <div className="row">
            <Busy className="btn ghost sm" run={async () => { if (window.confirm("Rewrite the website with AI? This replaces your edits and uses 1 AI run.")) await build(); }}>Rewrite with AI</Busy>
          </div>
          <InviteLine />
        </div>
        <div style={{ position: "sticky", top: 20 }}>
          <span className="label">Preview{live ? " · live" : " · only you can see this"}</span>
          <iframe key={frame} title="Website preview" className="preview-frame" style={{ marginTop: 10 }} src={`/s/${site.slug}?preview=1`} />
        </div>
      </div>
    </Sheet>
  );
}

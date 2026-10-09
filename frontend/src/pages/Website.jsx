import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, upload, waLink } from "../api.js";
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

/** Phone photos are 5–10 MB: shrink them in the browser (longest side 1800 px, JPEG) before uploading. */
async function shrink(file) {
  const img = await new Promise((ok, bad) => {
    const i = new Image();
    i.onload = () => ok(i); i.onerror = () => bad(new Error("That file isn't a photo we can read. Try a JPG or PNG."));
    i.src = URL.createObjectURL(file);
  });
  const scale = Math.min(1, 1800 / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.naturalWidth * scale); canvas.height = Math.round(img.naturalHeight * scale);
  canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
  URL.revokeObjectURL(img.src);
  return new Promise((ok) => canvas.toBlob(ok, "image/jpeg", 0.85));
}

function PhotoThumb({ p, onRemove, tall }) {
  return (
    <div style={{ position: "relative", border: "1px solid var(--ink-line)", aspectRatio: tall ? "4 / 3" : "1", overflow: "hidden", background: "var(--ink)" }}>
      <img src={p.thumb || p.src} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
      <span className="small" style={{ position: "absolute", left: 6, bottom: 6, background: "rgba(10,24,38,.8)", padding: "2px 6px", fontSize: 11 }}>
        {p.kind === "upload" ? "Your photo" : `Stock · ${p.credit}`}
      </span>
      <button className="btn sm ghost" style={{ position: "absolute", right: 6, top: 6, minHeight: 28, padding: "0 10px", background: "rgba(10,24,38,.85)" }}
        onClick={onRemove} aria-label="Remove photo">Remove</button>
    </div>
  );
}

function PhotosPanel({ site, onChange }) {
  const { toast } = useHub();
  const [busy, setBusy] = useState("");
  const ph = site.photos || { hero: null, gallery: [] };
  const run = async (label, fn) => {
    setBusy(label);
    try { await fn(); await onChange(); } catch (e) { if (!e.handled) toast(e.message, "err"); } finally { setBusy(""); }
  };
  const send = (slot, files) => run(slot, async () => {
    for (const f of files) {
      const form = new FormData();
      form.append("slot", slot);
      form.append("file", await shrink(f), "photo.jpg");
      await upload("/site/photos", form);
    }
  });
  const remove = (slot, index = 0) => run("remove", () => api("/site/photos/remove", { method: "POST", body: { slot, index } }));
  const room = 6 - ph.gallery.filter((p) => p.kind === "upload").length;
  return (
    <div className="panel">
      <span className="label">Photos</span>
      <p className="small muted">Real photos of your work, shop or team make the biggest difference. {site.stock_photos ? "Until you add your own, the website uses professional stock photos that match your business." : "Without photos, the website uses designed artwork in your colour."}</p>
      <span className="label" style={{ marginTop: 6 }}>Main photo</span>
      {ph.hero ? <PhotoThumb p={ph.hero} tall onRemove={() => remove("hero")} /> : <p className="small muted">No main photo — your website shows designed artwork instead.</p>}
      <label className="btn sm" style={{ justifySelf: "start", cursor: "pointer" }}>
        {busy === "hero" ? "Uploading…" : ph.hero?.kind === "upload" ? "Replace main photo" : "Upload main photo"}
        <input type="file" accept="image/*" hidden disabled={!!busy} onChange={(e) => { const f = [...e.target.files]; e.target.value = ""; if (f.length) send("hero", f.slice(0, 1)); }} />
      </label>
      <span className="label" style={{ marginTop: 10 }}>Gallery and about-us photos · up to 6</span>
      {ph.gallery.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
          {ph.gallery.map((p, i) => <PhotoThumb key={(p.id || "") + i} p={p} onRemove={() => remove("gallery", i)} />)}
        </div>
      )}
      <div className="row">
        {room > 0 && (
          <label className="btn sm" style={{ cursor: "pointer" }}>
            {busy === "gallery" ? "Uploading…" : "Add photos"}
            <input type="file" accept="image/*" multiple hidden disabled={!!busy} onChange={(e) => { const f = [...e.target.files].slice(0, room); e.target.value = ""; if (f.length) send("gallery", f); }} />
          </label>
        )}
        {site.stock_photos && (
          <button className="btn sm ghost" disabled={!!busy} onClick={() => run("stock", async () => { await api("/site/photos/stock", { method: "POST" }); toast("New stock photos found. Your own photos stay."); })}>
            {busy === "stock" ? "Finding…" : "Find stock photos"}
          </button>
        )}
      </div>
      <p className="small muted">JPG or PNG. Photos are resized automatically, so phone photos are fine.</p>
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
          <PhotosPanel site={site} onChange={async () => { await reload(); setFrame((f) => f + 1); }} />
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

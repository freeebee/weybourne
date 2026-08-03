/* Contact creator — a business card in (file, drag-drop, paste, or phone
   camera), a Notion contact out: vision extraction, dedupe check, editable
   preview, best-effort LinkedIn match whose photo becomes the page icon. */
import React from "react";
import { get, post, postFile } from "../api.js";
import {
  Button, Card, Chip, ErrorNote, Field, FilePick, Mascot, PageHeader,
  SearchSelect, SectionHead, inputStyle,
} from "../ui.jsx";

export default function ContactCard() {
  const [file, setFile] = React.useState(null);
  const [preview, setPreview] = React.useState("");     // object URL of the card
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState(null);
  const [result, setResult] = React.useState(null);     // /api/contact-card reply
  const [fields, setFields] = React.useState({});
  const [editing, setEditing] = React.useState({});
  const [linked, setLinked] = React.useState(null);     // linkedin lookup reply
  const [usePhoto, setUsePhoto] = React.useState(true);
  const [created, setCreated] = React.useState(null);
  const [typeOpts, setTypeOpts] = React.useState([]);
  const [companyNames, setCompanyNames] = React.useState([]);
  const cameraRef = React.useRef(null);

  React.useEffect(() => {
    get("/api/notion/options?kind=contact")
      .then((d) => setTypeOpts(d.options?.Type || [])).catch(() => {});
    get("/api/notion/names?kind=company")
      .then((d) => setCompanyNames(d.names || [])).catch(() => {});
  }, []);

  // Clipboard paste anywhere on the page.
  React.useEffect(() => {
    const onPaste = (e) => {
      const item = [...(e.clipboardData?.items || [])]
        .find((i) => i.type.startsWith("image/"));
      if (item) {
        const f = item.getAsFile();
        if (f) ingest(f);
      }
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, []);

  async function ingest(f) {
    setFile(f); setResult(null); setCreated(null); setLinked(null);
    setError(null); setFields({}); setEditing({});
    setPreview(URL.createObjectURL(f));
    setBusy("extract");
    try {
      const r = await postFile("/api/contact-card", f, f.name || "card.jpg");
      setResult(r);
      setFields(r.editable || {});
      // Kick off the LinkedIn lookup with the extracted identity.
      const name = r.editable?.Name, company = r.editable?.["Employed By"];
      if (name) {
        setBusy("linkedin");
        try { setLinked(await post("/api/contact-card/linkedin", { name, company })); }
        catch { setLinked(null); }
      }
    } catch (e) { setError(e.message); }
    setBusy("");
  }

  async function create() {
    setBusy("create"); setError(null);
    try {
      const highMatch = linked?.confidence === "high";
      const res = await post("/api/contact-card/create", {
        fields: {
          ...fields,
          LinkedIn: fields.LinkedIn || (highMatch ? linked.profile_url : ""),
        },
        icon_url: (usePhoto && highMatch && linked.image_url) || "",
        linkedin_prop: result?.props?.linkedin || "",
        phone_prop: result?.props?.phone || "",
      });
      setCreated(res);
    } catch (e) { setError(e.message); }
    setBusy("");
  }

  const fieldRows = Object.entries(fields);
  const editStyle = { fontSize: "12.5px", padding: "5px 8px",
                      background: "var(--paper-000)",
                      border: "1px solid var(--paper-200)", borderRadius: 4,
                      color: "var(--ink-700)", fontFamily: "inherit",
                      lineHeight: 1.5, flex: 1 };

  return (
    <div className="fade-in">
      <PageHeader eyebrow="UPKEEP · CONTACTS" title="Contact creator">
        Drop in a business card — photo, screenshot or paste — and it becomes a
        properly filed Notion contact: details extracted, duplicates checked,
        company linked, LinkedIn matched where the evidence is strong.
      </PageHeader>

      <ErrorNote error={error} />

      {/* Input card */}
      <Card style={{ marginBottom: 18 }}>
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault();
            const f = e.dataTransfer.files?.[0]; if (f) ingest(f); }}
          style={{ display: "flex", gap: 18, alignItems: "center",
                   flexWrap: "wrap", border: "1px dashed var(--paper-300)",
                   borderRadius: "var(--radius)", padding: "16px 18px" }}>
          <Mascot state="reading" width={54} />
          <div style={{ flex: "1 1 260px" }}>
            <span className="microlabel">BUSINESS CARD</span>
            <div style={{ fontSize: "13.5px", color: "var(--stone-600)", marginTop: 3 }}>
              Choose a file, drag it here, paste a screenshot
              (Ctrl+V), or take a photo on your phone.
            </div>
            <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
              <FilePick file={file} accept="image/*"
                label="Choose image" onChange={(f) => f && ingest(f)} />
              <input ref={cameraRef} type="file" accept="image/*"
                capture="environment" hidden
                onChange={(e) => { const f = e.target.files?.[0]; if (f) ingest(f); }} />
              <Button variant="ghost" onClick={() => cameraRef.current?.click()}>
                Take photo
              </Button>
            </div>
          </div>
          {preview && (
            <img src={preview} alt="card"
              style={{ maxWidth: 190, maxHeight: 120, borderRadius: 4,
                       border: "1px solid var(--paper-200)" }} />
          )}
        </div>
      </Card>

      {busy === "extract" && (
        <Mascot state="crunching" width={60} text="Reading the card…" />
      )}

      {result && !created && (
        <Card accent="teal" style={{ marginBottom: 18 }}>
          <SectionHead label="CONTACT TO BE CREATED"
            right={result.live ? "LIVE" : "DEMO MODE"} />

          {/* Duplicate warning */}
          {result.existing && (
            <div style={{ padding: "10px 14px", marginBottom: 12,
                          background: "var(--caution-100)",
                          borderRadius: "var(--radius)", fontSize: "13px" }}>
              <b>Possible duplicate:</b> “{result.existing.name}”
              {result.existing.email ? ` (${result.existing.email})` : ""} already
              exists{result.existing.action === "link_existing"
                ? " with the same identifier" : ` — ${Math.round(result.existing.score * 100)}% name match`}.
              Creating anyway will make a second record.
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "130px 1fr",
                        gap: "6px 12px" }}>
            {fieldRows.map(([k, v]) => {
              const isEditing = !!editing[k];
              const picker = k === "Type"
                ? { options: typeOpts, multi: false }
                : k === "Employed By"
                  ? { options: companyNames, multi: false } : null;
              return (
                <React.Fragment key={k}>
                  <span className="microlabel" style={{ paddingTop: 3 }}>{k}</span>
                  <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                    {isEditing ? (
                      picker
                        ? <SearchSelect value={v} options={picker.options}
                            onChange={(nv) => setFields({ ...fields, [k]: nv })} />
                        : <input value={v} style={editStyle}
                            onChange={(e) => setFields({ ...fields, [k]: e.target.value })} />
                    ) : (
                      <span style={{ fontSize: "12.5px", flex: 1,
                                     overflowWrap: "anywhere" }}>
                        {v || <span className="muted">(empty)</span>}
                      </span>
                    )}
                    <button onClick={() => setEditing({ ...editing, [k]: !isEditing })}
                      style={{ background: "none", border: "none", cursor: "pointer",
                               color: "var(--teal-700)", fontFamily: "var(--mono)",
                               fontSize: 10, letterSpacing: ".1em", paddingTop: 3 }}>
                      {isEditing ? "DONE" : "EDIT"}
                    </button>
                  </div>
                </React.Fragment>
              );
            })}
          </div>

          {/* LinkedIn */}
          <div style={{ marginTop: 14, borderTop: "1px solid var(--paper-200)",
                        paddingTop: 12 }}>
            <span className="microlabel">LINKEDIN</span>
            {busy === "linkedin" ? (
              <div style={{ marginTop: 6 }}>
                <Mascot state="thinking" width={44}
                  text="Searching for a matching profile…" />
              </div>
            ) : linked && linked.confidence !== "none" && linked.profile_url ? (
              <div style={{ display: "flex", gap: 12, alignItems: "center",
                            marginTop: 8, flexWrap: "wrap" }}>
                {linked.image_url && (
                  <img src={linked.image_url} alt=""
                    style={{ width: 44, height: 44, borderRadius: "50%",
                             objectFit: "cover",
                             border: "1px solid var(--paper-200)" }}
                    onError={(e) => { e.currentTarget.style.display = "none"; }} />
                )}
                <a href={linked.profile_url} target="_blank" rel="noreferrer"
                   style={{ fontSize: "13px", color: "var(--teal-700)" }}>
                  {linked.profile_url}
                </a>
                <Chip tone={linked.confidence === "high" ? "positive" : "caution"}>
                  {linked.confidence.toUpperCase()} CONFIDENCE
                </Chip>
                {linked.confidence === "high" && linked.image_url && (
                  <label className="mono" style={{ fontSize: 10.5,
                        letterSpacing: ".08em", display: "flex", gap: 6,
                        alignItems: "center", color: "var(--stone-500)" }}>
                    <input type="checkbox" checked={usePhoto}
                      onChange={(e) => setUsePhoto(e.target.checked)} />
                    USE PHOTO AS PAGE ICON
                  </label>
                )}
              </div>
            ) : (
              <p className="muted" style={{ fontSize: "12.5px", margin: "6px 0 0" }}>
                No confident profile match — the contact saves without one.
              </p>
            )}
          </div>

          <div className="row" style={{ marginTop: 14 }}>
            <Button variant="dark" busy={busy === "create"} onClick={create}>
              Create the contact
            </Button>
            {result.existing?.action === "link_existing" && (
              <span className="muted" style={{ fontSize: "12.5px" }}>
                …or leave it — the existing record already covers this person.
              </span>
            )}
          </div>
        </Card>
      )}

      {created && (
        <Card accent="brass">
          <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <Mascot state="celebrating" width={56} />
            <div>
              <b style={{ fontSize: "15px" }}>Contact created.</b>
              <div style={{ fontSize: "13px", marginTop: 3 }}>
                {created.url
                  ? <a href={created.url} target="_blank" rel="noreferrer"
                       style={{ color: "var(--teal-700)" }}>Open it in Notion</a>
                  : "Demo mode — nothing was actually written."}
              </div>
            </div>
            <Button variant="ghost" onClick={() => {
              setFile(null); setPreview(""); setResult(null); setCreated(null);
              setLinked(null); setFields({});
            }}>Another card</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

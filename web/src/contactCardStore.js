/* Contact card creator — state lives at module scope, not component state,
   so extraction / photo lookup / creation keep running (and their result
   lands) even if you navigate away mid-flow and come back later. Same
   subscribe/notify pattern as felixStore.js and liveStore.js. */
import { get, post, postFile } from "./api.js";

export const S = {
  file: null,
  preview: "",        // object URL of the card
  busy: "",
  error: null,
  result: null,        // /api/contact-card reply
  fields: {},          // editable "create a new contact" form
  editing: {},
  updateFields: {},    // editable "update the existing record" form
  updateEditing: {},
  photo: null,          // photo-search reply
  usePhoto: true,
  created: null,        // { ...response, kind: "created" | "updated" }
  typeOpts: [],
  companyNames: [],
  version: 0,
};

let listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }
function emit() { S.version++; listeners.forEach((f) => f()); }

let optionsLoaded = false;
export function loadOptions() {
  if (optionsLoaded) return;
  optionsLoaded = true;
  get("/api/notion/options?kind=contact")
    .then((d) => { S.typeOpts = d.options?.Type || []; emit(); }).catch(() => {});
  get("/api/notion/names?kind=company")
    .then((d) => { S.companyNames = d.names || []; emit(); }).catch(() => {});
}

export function setFields(fields) { S.fields = fields; emit(); }
export function setEditing(editing) { S.editing = editing; emit(); }
export function setUpdateFields(fields) { S.updateFields = fields; emit(); }
export function setUpdateEditing(editing) { S.updateEditing = editing; emit(); }
export function setUsePhoto(v) { S.usePhoto = v; emit(); }

/* The existing record's own values win (never blank a filled-in field);
   the freshly-scanned card only fills in what the existing record lacks. */
function mergeExistingFields(existingFields, cardFields) {
  const merged = { ...cardFields };
  for (const k of Object.keys(existingFields)) {
    merged[k] = (existingFields[k] || "").trim() || cardFields[k] || "";
  }
  return merged;
}

export async function ingest(f) {
  S.file = f; S.result = null; S.created = null; S.photo = null;
  S.error = null; S.fields = {}; S.editing = {};
  S.updateFields = {}; S.updateEditing = {};
  S.preview = URL.createObjectURL(f);
  S.busy = "extract";
  emit();
  try {
    const r = await postFile("/api/contact-card", f, f.name || "card.jpg");
    S.result = r;
    S.fields = r.editable || {};
    if (r.existing?.fields) {
      S.updateFields = mergeExistingFields(r.existing.fields, r.editable || {});
    }
    emit();
    // Kick off the photo lookup with the extracted identity.
    const name = r.editable?.Name, company = r.editable?.["Employed By"];
    if (name) {
      S.busy = "photo"; emit();
      try { S.photo = await post("/api/contact-card/photo", { name, company }); }
      catch { S.photo = null; }
      if (S.photo?.confidence === "high" && S.photo.evidence) {
        const note = `Photo sourced via web search: ${S.photo.evidence}`
          + (S.photo.source_url ? ` (${S.photo.source_url})` : "");
        S.fields = { ...S.fields,
          Description: [S.fields.Description, note].filter(Boolean).join(" · ") };
        S.updateFields = { ...S.updateFields,
          Description: [S.updateFields.Description, note].filter(Boolean).join(" · ") };
      }
      emit();
    }
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

function iconUrl() {
  return (S.usePhoto && S.photo?.confidence === "high" && S.photo.image_url) || "";
}

export async function create() {
  S.busy = "create"; S.error = null; emit();
  try {
    const res = await post("/api/contact-card/create", {
      fields: S.fields,
      icon_url: iconUrl(),
      linkedin_prop: S.result?.props?.linkedin || "",
      phone_prop: S.result?.props?.phone || "",
    });
    S.created = { ...res, kind: "created" };
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

export async function update() {
  S.busy = "update"; S.error = null; emit();
  try {
    const res = await post("/api/contact-card/update", {
      page_id: S.result?.existing?.id || "",
      fields: S.updateFields,
      icon_url: iconUrl(),
      linkedin_prop: S.result?.props?.linkedin || "",
      phone_prop: S.result?.props?.phone || "",
    });
    S.created = { ...res, kind: "updated" };
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

export function reset() {
  S.file = null; S.preview = ""; S.result = null; S.created = null;
  S.photo = null; S.fields = {}; S.editing = {};
  S.updateFields = {}; S.updateEditing = {};
  emit();
}

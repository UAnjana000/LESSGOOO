export interface ItemMetadata {
  title: string;
  subjects: string[];
  people: string[];
  places: string[];
  date_text: string | null;
  date_start: string | null;
  date_end: string | null;
  date_certainty: string;
  languages: string[];
  edition: string | null;
  volume: string | null;
  publisher: string | null;
  creator: string | null;
}

export const CERTAINTIES = ["exact", "approximate", "unknown"] as const;
const LISTS = ["subjects", "people", "places", "languages"] as const;
const TEXTS = ["title", "date_text", "date_start", "date_end", "edition", "volume", "publisher", "creator"] as const;

export type MetadataForm = Record<(typeof LISTS)[number] | (typeof TEXTS)[number] | "date_certainty" | "reason", string>;

export function parseList(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

export function metadataForm(m: Partial<ItemMetadata> | undefined): MetadataForm {
  const f = { date_certainty: m?.date_certainty || "unknown", reason: "" } as MetadataForm;
  for (const k of LISTS) f[k] = (m?.[k] ?? []).join(", ");
  for (const k of TEXTS) f[k] = m?.[k] ?? "";
  return f;
}

/** Body for PUT /api/staff/items/{id}/metadata: lists as arrays, blank text as null. */
export function metadataBody(f: MetadataForm): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const k of LISTS) body[k] = parseList(f[k]);
  for (const k of TEXTS) body[k] = f[k].trim() || null;
  if (!body.title) delete body.title; // the title cannot be blanked; leaving it out keeps the stored one
  body.date_certainty = f.date_certainty;
  body.reason = f.reason.trim();
  return body;
}

type Detail = { loc?: unknown[]; msg?: string; message?: string; problems?: string[]; files?: FileNote[] };
export interface FileNote { name?: string; status?: string; detail?: string | null }

/** Per-file intake outcome, e.g. "a.pdf: duplicate (already stored as file 12)". */
export function fileNotes(files: FileNote[] | undefined): string {
  return (files ?? []).map((f) => `${f.name ?? "?"}: ${f.status ?? "?"}${f.detail ? ` (${f.detail})` : ""}`).join("; ");
}

/** Readable text for an API error detail: validation errors as "<field>: <msg>", structured details with their problems or file notes. */
export function detailText(detail: unknown): string {
  if (Array.isArray(detail)) {
    return detail.map((p: string | Detail) => {
      if (typeof p === "string") return p;
      const field = Array.isArray(p.loc) && p.loc.length ? p.loc[p.loc.length - 1] : null;
      const msg = p.msg ?? JSON.stringify(p);
      return field == null ? msg : `${String(field)}: ${msg}`;
    }).join("; ");
  }
  if (detail && typeof detail === "object") {
    const d = detail as Detail;
    const parts = [d.message ?? "", (d.problems ?? []).join("; "), fileNotes(d.files)];
    return parts.filter(Boolean).join(" ") || JSON.stringify(detail);
  }
  return String(detail);
}

const RIGHTS_OPTIONAL = ["source_url", "edition", "volume", "pages", "training_basis", "notes"] as const;

/** Body for POST /api/staff/rights: blank optional text as null, so saving an entry does not turn null into "". */
export function rightsBody<F extends Record<string, unknown>>(f: F): Record<string, unknown> {
  const body: Record<string, unknown> = { ...f };
  for (const k of RIGHTS_OPTIONAL) body[k] = typeof f[k] === "string" ? (f[k] as string).trim() || null : f[k] ?? null;
  return body;
}

/** Permissions a rights edit moves away from "allowed": the server then withdraws published items (display) or flags datasets (training). */
export function rightsDowngrades(before: Record<string, unknown> | undefined, after: Record<string, unknown>): ("display_permission" | "training_permission")[] {
  if (!before) return [];
  return (["display_permission", "training_permission"] as const).filter((k) => before[k] === "allowed" && after[k] !== "allowed");
}

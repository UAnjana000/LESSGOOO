export interface ItemMetadata {
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
const TEXTS = ["date_text", "date_start", "date_end", "edition", "volume", "publisher", "creator"] as const;

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
  body.date_certainty = f.date_certainty;
  body.reason = f.reason.trim();
  return body;
}

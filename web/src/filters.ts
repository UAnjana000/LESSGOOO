export const ITEM_TYPES = ["text", "printed_scan", "manuscript", "photograph", "audio", "video"] as const;
export type Facet = "subject" | "person" | "place";

const SEARCH_KEYS = ["collection", "item_type", "lang", "date_from", "date_to", "subject", "person", "place"] as const;
/** URL key -> items endpoint key. The items endpoint takes no dates. */
const BROWSE_KEYS: Record<string, string> = { collection: "collection", item_type: "item_type", lang: "language", subject: "subject", person: "person", place: "place" };

export function searchPath(params: URLSearchParams): string | null {
  const q = params.get("q")?.trim();
  if (!q) return null;
  const qs = new URLSearchParams({ q });
  for (const k of SEARCH_KEYS) {
    const v = params.get(k);
    if (v) qs.set(k, v);
  }
  return `/api/visitor/search?${qs}`;
}

export function browsePath(params: URLSearchParams): string {
  const qs = new URLSearchParams();
  for (const [from, to] of Object.entries(BROWSE_KEYS)) {
    const v = params.get(from);
    if (v) qs.set(to, v);
  }
  const s = qs.toString();
  return s ? `/api/visitor/items?${s}` : "/api/visitor/items";
}

export function facetLink(key: Facet, value: string): string {
  return `/search?${new URLSearchParams({ [key]: value })}`;
}

export function hasFilters(params: URLSearchParams): boolean {
  return SEARCH_KEYS.some((k) => Boolean(params.get(k)));
}

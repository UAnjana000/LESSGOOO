// Shared by the page and the service worker. Mirrors archive/exhibit.py:
// canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
// signature = ECDSA P-256 / SHA-256 in IEEE P1363 (r||s) form, base64.

export interface ExhibitPayload {
  manifest_version: number;
  issued_at: string;
  lease_expires_at: string;
  lease_hours: number;
  budget_bytes: number;
  total_bytes: number;
  items: { item_id: number; version: number; bytes: number; urls: string[]; sha256: string[] }[];
  skipped_over_budget: number[];
  withdrawn_item_ids: number[];
  shared_urls: string[];
  device_id: string | null;
}

export interface SignedManifest {
  payload: ExhibitPayload;
  signature: string;
  alg: string;
}

export function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const obj = value as Record<string, unknown>;
  return `{${Object.keys(obj)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canonical(obj[k])}`)
    .join(",")}}`;
}

const b64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

export async function importPublicKey(spkiB64: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("spki", b64(spkiB64), { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
}

export async function verifyManifest(m: SignedManifest, key: CryptoKey): Promise<boolean> {
  if (m.alg !== "ECDSA-P256-SHA256") return false;
  const data = new TextEncoder().encode(canonical(m.payload));
  return crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, b64(m.signature), data);
}

export function leaseValid(p: ExhibitPayload, now = Date.now()): boolean {
  return Date.parse(p.lease_expires_at) > now;
}

/** The withdrawal list always wins over cached content. */
export function itemIdFromUrl(url: string): number | null {
  const m = url.match(/\/api\/visitor\/items\/(\d+)/);
  return m ? Number(m[1]) : null;
}

export function servable(p: ExhibitPayload, url: string, fileItem: Map<string, number>, now = Date.now()): boolean {
  if (!leaseValid(p, now)) return false;
  const path = new URL(url, "http://x").pathname;
  const itemId = itemIdFromUrl(path) ?? fileItem.get(path) ?? null;
  if (itemId !== null) {
    if (p.withdrawn_item_ids.includes(itemId)) return false;
    return p.items.some((i) => i.item_id === itemId);
  }
  return p.shared_urls.includes(path);
}

export function fileItemIndex(p: ExhibitPayload): Map<string, number> {
  const m = new Map<string, number>();
  for (const it of p.items) for (const u of it.urls) m.set(u, it.item_id);
  return m;
}

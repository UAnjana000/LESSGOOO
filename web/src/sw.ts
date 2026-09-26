/// <reference lib="webworker" />
// Kiosk service worker.
// - Precaches the app shell (build output) so the kiosk UI opens without the edge server.
// - Keeps a signed, leased exhibit cache of published, fully public items only.
// - Network first for visitor data; cached exhibit items only when offline, only within the lease,
//   and never for withdrawn items. Ask and staff routes are never cached.
import { precacheAndRoute } from "workbox-precaching";
import {
  fileItemIndex,
  importPublicKey,
  servable,
  verifyManifest,
  type ExhibitPayload,
  type SignedManifest,
} from "./exhibitVerify";

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);

const META = "exhibit-meta";
const MANIFEST_KEY = "/__exhibit/manifest";
const PUBKEY_KEY = "/__exhibit/public-key";

async function readJson<T>(key: string): Promise<T | null> {
  const res = await (await caches.open(META)).match(key);
  return res ? ((await res.json()) as T) : null;
}

async function writeJson(key: string, value: unknown): Promise<void> {
  await (await caches.open(META)).put(key, new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } }));
}

async function currentManifest(): Promise<ExhibitPayload | null> {
  return (await readJson<SignedManifest>(MANIFEST_KEY))?.payload ?? null;
}

async function sync(deviceId: string): Promise<{ ok: boolean; reason?: string; version?: number }> {
  // The public key is pinned on first successful sync (trust on first use by the installer).
  let spki = await readJson<{ spki_b64: string }>(PUBKEY_KEY);
  if (!spki) {
    spki = await (await fetch("/api/visitor/exhibit/public-key")).json();
    await writeJson(PUBKEY_KEY, spki);
  }
  const signed: SignedManifest = await (await fetch(`/api/visitor/exhibit/manifest?device_id=${encodeURIComponent(deviceId)}`)).json();
  const key = await importPublicKey(spki!.spki_b64);
  if (!(await verifyManifest(signed, key))) return { ok: false, reason: "signature" };
  const p = signed.payload;
  const cacheName = `exhibit-v${p.manifest_version}`;
  const cache = await caches.open(cacheName);
  const urls = [...p.shared_urls, ...p.items.flatMap((i) => i.urls)];
  for (const u of urls) {
    try {
      const res = await fetch(u);
      if (res.ok) await cache.put(u, res);
    } catch {
      /* keep going; missing entries simply are not available offline */
    }
  }
  // Apply withdrawals and drop older exhibit caches only after the new set is in place.
  for (const name of await caches.keys()) {
    if (name.startsWith("exhibit-v") && name !== cacheName) await caches.delete(name);
  }
  for (const id of p.withdrawn_item_ids) {
    for (const req of await cache.keys()) {
      if (req.url.includes(`/api/visitor/items/${id}`)) await cache.delete(req);
    }
  }
  await writeJson(MANIFEST_KEY, signed);
  return { ok: true, version: p.manifest_version };
}

self.addEventListener("message", (event) => {
  const data = event.data as { type?: string; deviceId?: string };
  if (data?.type === "exhibit-sync") {
    event.waitUntil(
      sync(data.deviceId ?? "unregistered")
        .catch((e) => ({ ok: false, reason: String(e) }))
        .then((r) => event.source?.postMessage({ type: "exhibit-sync-result", ...r })),
    );
  }
  if (data?.type === "exhibit-status") {
    event.waitUntil(currentManifest().then((p) => event.source?.postMessage({ type: "exhibit-status", payload: p })));
  }
});

const offlineJson = (body: unknown, status = 503) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "x-archive-offline": "1" } });

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/staff")) return;
  if (url.pathname === "/api/visitor/ask") {
    event.respondWith(fetch(event.request).catch(() => offlineJson({ outcome: "offline", citations: [], sentences: [] })));
    return;
  }
  if (event.request.method !== "GET" || !url.pathname.startsWith("/api/visitor/")) return;
  event.respondWith(
    (async () => {
      try {
        return await fetch(event.request);
      } catch {
        const p = await currentManifest();
        if (!p) return offlineJson({ detail: "offline" });
        if (!servable(p, url.pathname, fileItemIndex(p))) {
          return offlineJson({ detail: "Not saved on this screen, or the saved copy has expired." }, 404);
        }
        const hit = await caches.match(url.pathname + url.search, { ignoreSearch: false }) ?? (await caches.match(url.pathname));
        if (!hit) return offlineJson({ detail: "offline" });
        const headers = new Headers(hit.headers);
        headers.set("x-archive-offline", "1");
        return new Response(hit.body, { status: hit.status, headers });
      }
    })(),
  );
});

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

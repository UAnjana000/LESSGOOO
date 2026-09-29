/// <reference lib="webworker" />
export type {};
declare const self: ServiceWorkerGlobalScope;

// Keep reference for Workbox injectManifest
const _manifest = (self as unknown as { __WB_MANIFEST: unknown }).__WB_MANIFEST || [];
void _manifest;

self.addEventListener("install", () => {
  void self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
      await self.clients.claim();
      try {
        await self.registration.unregister();
      } catch {
        /* ignore */
      }
    })()
  );
});

self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});


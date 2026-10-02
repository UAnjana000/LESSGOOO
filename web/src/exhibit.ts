import { useEffect, useState } from "react";
import { leaseValid, type ExhibitPayload } from "./exhibitVerify";
import { isKiosk } from "./kiosk";

const SYNC_EVERY_MS = 15 * 60_000;
const DEVICE_KEY = "archive-kiosk-device";

export interface ExhibitStatus {
  version: number | null;
  leaseExpiresAt: string | null;
  leaseValid: boolean | null;
  items: number;
  lastResult: string | null;
}

let status: ExhibitStatus = { version: null, leaseExpiresAt: null, leaseValid: null, items: 0, lastResult: null };
const listeners = new Set<(s: ExhibitStatus) => void>();
const emit = (patch: Partial<ExhibitStatus>) => {
  status = { ...status, ...patch };
  listeners.forEach((l) => l(status));
};

function deviceId(): string {
  let id: string | null = null;
  try {
    id = localStorage.getItem(DEVICE_KEY);
  } catch {
    /* storage blocked */
  }
  if (!id) {
    id = `kiosk-${crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Date.now().toString(36)}`;
    try {
      localStorage.setItem(DEVICE_KEY, id);
    } catch {
      /* the id then lasts for this page load only */
    }
  }
  return id;
}

function applyPayload(p: ExhibitPayload | null) {
  if (!p) return;
  emit({ version: p.manifest_version, leaseExpiresAt: p.lease_expires_at, leaseValid: leaseValid(p), items: p.items.length });
}

/** Kiosks only (main.tsx gates the call): register the service worker for the offline shell and sync the exhibit cache. */
export async function startExhibit(): Promise<void> {
  if (!("serviceWorker" in navigator) || import.meta.env.DEV) return;
  const reg = await navigator.serviceWorker.register("/sw.js", { type: "module", scope: "/" }).catch(() => null);
  if (!reg) return;
  await navigator.serviceWorker.ready;
  navigator.serviceWorker.addEventListener("message", (e: MessageEvent) => {
    const d = e.data as { type: string; ok?: boolean; reason?: string; payload?: ExhibitPayload | null };
    if (d.type === "exhibit-status") applyPayload(d.payload ?? null);
    if (d.type === "exhibit-sync-result") {
      emit({ lastResult: d.ok ? "ok" : `failed: ${d.reason ?? "unknown"}` });
      navigator.serviceWorker.controller?.postMessage({ type: "exhibit-status" });
    }
  });
  const post = (msg: object) => (navigator.serviceWorker.controller ?? reg.active)?.postMessage(msg);
  // Lease status only matters on kiosks; phones never sync, so an old manifest must not raise lease banners.
  if (!isKiosk()) return;
  post({ type: "exhibit-status" });
  const sync = () => navigator.onLine && post({ type: "exhibit-sync", deviceId: deviceId() });
  sync();
  window.setInterval(sync, SYNC_EVERY_MS);
  window.addEventListener("online", sync);
  window.setInterval(() => post({ type: "exhibit-status" }), 60_000);
}

export function useExhibitStatus(): ExhibitStatus {
  const [s, setS] = useState(status);
  useEffect(() => {
    listeners.add(setS);
    return () => {
      listeners.delete(setS);
    };
  }, []);
  return s;
}

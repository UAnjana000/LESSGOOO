import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { startExhibit } from "./exhibit";
import { isKiosk } from "./kiosk";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

/** Remove any service worker and cache left behind, so the public website always serves the current build. */
export function cleanupServiceWorkers(): void {
  if ("serviceWorker" in navigator) {
    void navigator.serviceWorker.getRegistrations().then((registrations) => {
      for (const reg of registrations) void reg.unregister();
    });
  }
  if ("caches" in window) {
    void caches.keys().then((names) => {
      for (const name of names) void caches.delete(name);
    });
  }
}

// Only gallery kiosks run the service worker (offline shell and exhibit cache); the public site stays SW-free.
if (isKiosk()) void startExhibit();
else cleanupServiceWorkers();

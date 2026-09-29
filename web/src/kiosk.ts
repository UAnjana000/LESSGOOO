const KIOSK_KEY = "archive-kiosk-mode";

/** Kiosk behaviour (idle reset, attract screen, exhibit sync) applies to installed gallery screens, not visitors' phones. */
export function isKiosk(): boolean {
  const flag = new URLSearchParams(window.location.search).get("kiosk");
  if (flag === "1") localStorage.setItem(KIOSK_KEY, "1");
  if (flag === "0") localStorage.removeItem(KIOSK_KEY);
  return localStorage.getItem(KIOSK_KEY) === "1" || window.matchMedia?.("(display-mode: fullscreen)").matches === true;
}

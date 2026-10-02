const KIOSK_KEY = "archive-kiosk-mode";

/** Kiosk behaviour (idle reset, attract screen, exhibit sync) applies to installed gallery screens, not visitors' phones. */
export function isKiosk(): boolean {
  let stored = false;
  try {
    const flag = new URLSearchParams(window.location.search).get("kiosk");
    if (flag === "1") localStorage.setItem(KIOSK_KEY, "1");
    if (flag === "0") localStorage.removeItem(KIOSK_KEY);
    stored = localStorage.getItem(KIOSK_KEY) === "1";
  } catch {
    /* storage blocked: fall back to the display mode alone */
  }
  return stored || window.matchMedia?.("(display-mode: fullscreen)").matches === true;
}

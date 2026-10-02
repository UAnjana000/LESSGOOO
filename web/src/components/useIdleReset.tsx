import { useEffect, useRef, useState, type RefObject } from "react";
import { useSession } from "../state";

export const IDLE_MS_DEFAULT = 120_000;
/** WCAG 2.2.1: visitors get at least 20 s warning, and one simple action, before the visit is cleared. */
export const IDLE_WARNING_MS = 30_000;
// "click" covers screen-reader activation, which fires a click with no key or pointer event.
const ACTIVITY = ["pointerdown", "keydown", "click", "wheel", "touchstart", "input", "focusin", "scroll"] as const;

export function openModal(d: HTMLDialogElement | null) {
  if (!d || d.open) return;
  if (typeof d.showModal === "function") d.showModal();
  else d.setAttribute("open", "");
}

export function closeModal(d: HTMLDialogElement | null) {
  if (!d?.open) return;
  if (typeof d.close === "function") d.close();
  else d.removeAttribute("open");
}

/**
 * Idle timer shared by the kiosk shell and the /kiosk dock: warns IDLE_WARNING_MS before the configured
 * session_idle_seconds, then calls `onExpire`. Pass `enabled: false` while the attract screen is up, because
 * its own focus would otherwise count as activity and re-arm the warning.
 */
export function useIdleReset(enabled: boolean, onExpire: () => void) {
  const { config } = useSession();
  const warnRef = useRef<HTMLDialogElement>(null);
  const [remaining, setRemaining] = useState(IDLE_WARNING_MS / 1000);
  const idleMs = (config?.session_idle_seconds ?? 0) * 1000 || IDLE_MS_DEFAULT;
  const warnAfter = Math.max(idleMs - IDLE_WARNING_MS, 10_000);
  const expireRef = useRef(onExpire);
  expireRef.current = onExpire;

  useEffect(() => {
    if (!enabled) return;
    let warnTimer = 0;
    let resetTimer = 0;
    let tick = 0;
    const clear = () => {
      window.clearTimeout(warnTimer);
      window.clearTimeout(resetTimer);
      window.clearInterval(tick);
    };
    const arm = () => {
      clear();
      closeModal(warnRef.current);
      warnTimer = window.setTimeout(() => {
        const started = Date.now();
        setRemaining(IDLE_WARNING_MS / 1000);
        openModal(warnRef.current);
        tick = window.setInterval(() => setRemaining(Math.max(0, Math.ceil((IDLE_WARNING_MS - (Date.now() - started)) / 1000))), 1000);
        resetTimer = window.setTimeout(() => {
          clear();
          closeModal(warnRef.current);
          expireRef.current();
        }, IDLE_WARNING_MS);
      }, warnAfter);
    };
    // Screen-reader and switch users often move focus or scroll without key or pointer events on the page.
    const onActivity = (e: Event) => {
      const insideWarning = e.target instanceof Node && warnRef.current?.contains(e.target);
      if (insideWarning && (e.type === "focusin" || e.type === "scroll")) return;
      arm();
    };
    ACTIVITY.forEach((e) => window.addEventListener(e, onActivity, { passive: true, capture: true }));
    arm();
    return () => {
      clear();
      closeModal(warnRef.current);
      ACTIVITY.forEach((e) => window.removeEventListener(e, onActivity, { capture: true }));
    };
  }, [warnAfter, enabled]);

  return { warnRef, remaining };
}

export function IdleWarning({ warnRef, remaining }: { warnRef: RefObject<HTMLDialogElement | null>; remaining: number }) {
  const { t } = useSession();
  return (
    <dialog ref={warnRef} className="idle-warning" aria-labelledby="idle-title" aria-describedby="idle-body">
      <h2 id="idle-title">{t("idleTitle")}</h2>
      <p id="idle-body">{t("idleBody", { n: IDLE_WARNING_MS / 1000 })}</p>
      <p className="countdown" aria-hidden="true">{t("seconds", { n: remaining })}</p>
      <div className="actions">
        <button type="button" className="btn" onClick={() => closeModal(warnRef.current)}>
          {t("idleStay")}
        </button>
      </div>
    </dialog>
  );
}

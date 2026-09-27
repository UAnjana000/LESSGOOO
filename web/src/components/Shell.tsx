import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../state";
import { useExhibitStatus } from "../exhibit";
import { LanguageSwitch } from "./Bits";
import { IconAsk, IconConstitution, IconHome, IconList, IconMap, IconSearch, IconStories, IconTimeline } from "./Icons";

const IDLE_MS_DEFAULT = 120_000;
/** WCAG 2.2.1: visitors get at least 20 s warning, and one simple action, before the visit is cleared. */
export const IDLE_WARNING_MS = 30_000;
const KIOSK_KEY = "archive-kiosk-mode";
// "click" covers screen-reader activation, which fires a click with no key or pointer event.
const ACTIVITY = ["pointerdown", "keydown", "click", "wheel", "touchstart", "input", "focusin", "scroll"] as const;

/** Kiosk behaviour (idle reset, attract screen) applies to installed gallery screens, not visitors' phones. */
export function isKiosk(): boolean {
  const flag = new URLSearchParams(window.location.search).get("kiosk");
  if (flag === "1") localStorage.setItem(KIOSK_KEY, "1");
  if (flag === "0") localStorage.removeItem(KIOSK_KEY);
  return localStorage.getItem(KIOSK_KEY) === "1" || window.matchMedia?.("(display-mode: fullscreen)").matches === true;
}

function openModal(d: HTMLDialogElement | null) {
  if (!d || d.open) return;
  if (typeof d.showModal === "function") d.showModal();
  else d.setAttribute("open", "");
}

function closeModal(d: HTMLDialogElement | null) {
  if (!d?.open) return;
  if (typeof d.close === "function") d.close();
  else d.removeAttribute("open");
}

export function Shell() {
  const s = useSession();
  const { t } = s;
  const nav = useNavigate();
  const { pathname } = useLocation();
  const finishRef = useRef<HTMLDialogElement>(null);
  const warnRef = useRef<HTMLDialogElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const [attract, setAttract] = useState(false);
  const [remaining, setRemaining] = useState(IDLE_WARNING_MS / 1000);
  const exhibit = useExhibitStatus();
  const idleMs = (s.config?.session_idle_seconds ?? 0) * 1000 || IDLE_MS_DEFAULT;
  const warnAfter = Math.max(idleMs - IDLE_WARNING_MS, 10_000);

  const endVisit = useCallback(() => {
    closeModal(finishRef.current);
    s.finish();
    nav("/");
  }, [s, nav]);
  const endRef = useRef(endVisit);
  endRef.current = endVisit;

  useEffect(() => {
    if (!isKiosk()) return;
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
          endRef.current();
          setAttract(true);
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
      ACTIVITY.forEach((e) => window.removeEventListener(e, onActivity, { capture: true }));
    };
  }, [warnAfter]);

  const firstPath = useRef(true);
  useEffect(() => {
    if (firstPath.current) {
      firstPath.current = false;
      return;
    }
    const main = mainRef.current;
    if (!main) return;
    main.scrollTop = 0;
    main.focus({ preventScroll: true });
    // On narrow screens the document scrolls instead of <main>.
    if ((document.scrollingElement?.scrollTop ?? 0) > main.offsetTop) main.scrollIntoView?.({ block: "start" });
  }, [pathname]);

  const links = [
    { to: "/", label: t("navHome"), icon: <IconHome />, end: true },
    { to: "/search", label: t("navSearch"), icon: <IconSearch /> },
    { to: "/ask", label: t("navAsk"), icon: <IconAsk /> },
    { to: "/timeline", label: t("navTimeline"), icon: <IconTimeline /> },
    { to: "/stories", label: t("navStories"), icon: <IconStories /> },
    { to: "/map", label: t("navMap"), icon: <IconMap /> },
    { to: "/constitution", label: t("navConstitution"), icon: <IconConstitution /> },
  ];

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        {t("skip")}
      </a>
      <header className="rail" inert={attract || undefined}>
        <NavLink to="/" className="mark">
          {t("archiveShort")}
        </NavLink>
        <nav aria-label={t("navMain")}>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} className="navlink">
              {l.icon}
              <span>{l.label}</span>
            </NavLink>
          ))}
          <NavLink to="/list" className="navlink">
            <IconList />
            <span>{t("navBasket")}</span>
            {s.basket.length > 0 && (
              <>
                <span className="badge" aria-hidden="true">{s.basket.length}</span>
                <span className="visually-hidden">, {t("itemsCount", { n: s.basket.length })}</span>
              </>
            )}
          </NavLink>
        </nav>
        <div className="controls" role="group" aria-label={t("displaySettings")}>
          <LanguageSwitch />
          <button type="button" className="toggle" onClick={s.cycleTextScale} aria-label={`${t("textSize")}: ${Math.round(s.textScale * 100)}%`}>
            A<span aria-hidden="true" style={{ fontSize: "1.3em" }}>A</span> {Math.round(s.textScale * 100)}%
          </button>
          <button type="button" className="toggle" aria-pressed={s.contrast} onClick={s.toggleContrast}>
            {t("contrast")}
          </button>
          <button type="button" className="finish" onClick={() => openModal(finishRef.current)}>
            {t("finish")}
          </button>
        </div>
      </header>
      <main id="main" ref={mainRef} className="main" tabIndex={-1} inert={attract || undefined}>
        {!s.online && <div className="banner offline" role="status">{exhibit.leaseValid === false ? t("leaseExpired") : t("offlineBanner")}</div>}
        {s.online && exhibit.leaseValid === false && <div className="banner warn" role="status">{t("leaseExpired")}</div>}
        {(s.config?.fixture_items_visible ?? 0) > 0 && <div className="banner">{t("fixtureBanner")}</div>}
        <Outlet />
      </main>
      <dialog ref={finishRef} aria-labelledby="finish-title" aria-describedby="finish-body">
        <h2 id="finish-title">{t("finishTitle")}</h2>
        <p id="finish-body">{t("finishBody")}</p>
        <div className="actions">
          <button type="button" className="btn secondary" onClick={() => closeModal(finishRef.current)}>
            {t("cancel")}
          </button>
          <button type="button" className="btn" onClick={endVisit}>
            {t("finishConfirm")}
          </button>
        </div>
      </dialog>
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
      {attract && (
        <button type="button" className="attract" onClick={() => setAttract(false)} autoFocus>
          <span className="attract-title">{t("archiveName")}</span>
          <span className="attract-lead">{t("attractTitle")}</span>
        </button>
      )}
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LANGS } from "../i18n";
import { useSession } from "../state";
import { useExhibitStatus } from "../exhibit";
import { IconAsk, IconHome, IconList, IconMap, IconSearch, IconStories, IconTimeline } from "./Icons";

const IDLE_MS_DEFAULT = 120_000;
const KIOSK_KEY = "archive-kiosk-mode";

/** Kiosk behaviour (idle reset, attract screen) applies to installed gallery screens, not visitors' phones. */
export function isKiosk(): boolean {
  const flag = new URLSearchParams(window.location.search).get("kiosk");
  if (flag === "1") localStorage.setItem(KIOSK_KEY, "1");
  if (flag === "0") localStorage.removeItem(KIOSK_KEY);
  return localStorage.getItem(KIOSK_KEY) === "1" || window.matchMedia("(display-mode: fullscreen)").matches;
}

export function Shell() {
  const s = useSession();
  const { t } = s;
  const nav = useNavigate();
  const finishRef = useRef<HTMLDialogElement>(null);
  const [attract, setAttract] = useState(false);
  const exhibit = useExhibitStatus();
  const idleMs = (s.config?.session_idle_seconds ?? 0) * 1000 || IDLE_MS_DEFAULT;

  const endVisit = useCallback(() => {
    finishRef.current?.close();
    s.finish();
    nav("/");
  }, [s, nav]);

  useEffect(() => {
    if (!isKiosk()) return;
    let timer = window.setTimeout(() => {}, 0);
    const arm = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        endVisit();
        setAttract(true);
      }, idleMs);
    };
    const events = ["pointerdown", "keydown", "wheel", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, arm, { passive: true }));
    arm();
    return () => {
      window.clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, arm));
    };
  }, [endVisit, idleMs]);

  const links = [
    { to: "/", label: t("navHome"), icon: <IconHome />, end: true },
    { to: "/search", label: t("navSearch"), icon: <IconSearch /> },
    { to: "/ask", label: t("navAsk"), icon: <IconAsk /> },
    { to: "/timeline", label: t("navTimeline"), icon: <IconTimeline /> },
    { to: "/stories", label: t("navStories"), icon: <IconStories /> },
    { to: "/map", label: t("navMap"), icon: <IconMap /> },
  ];

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        {t("skip")}
      </a>
      <aside className="rail" aria-label={t("archiveShort")}>
        <NavLink to="/" className="mark">
          {t("archiveShort")}
        </NavLink>
        <nav>
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
              <span className="badge" aria-label={t("itemsCount", { n: s.basket.length })}>
                {s.basket.length}
              </span>
            )}
          </NavLink>
        </nav>
        <div className="controls">
          <div className="langs" role="group" aria-label={t("language")}>
            {LANGS.map((l) => (
              <button key={l.code} type="button" lang={l.code} aria-pressed={s.lang === l.code} aria-label={l.name} onClick={() => s.setLang(l.code)}>
                {l.label}
              </button>
            ))}
          </div>
          <button type="button" className="toggle" onClick={s.cycleTextScale} aria-label={`${t("textSize")}: ${Math.round(s.textScale * 100)}%`}>
            A<span aria-hidden="true" style={{ fontSize: "1.3em" }}>A</span> {Math.round(s.textScale * 100)}%
          </button>
          <button type="button" className="toggle" aria-pressed={s.contrast} onClick={s.toggleContrast}>
            {t("contrast")}
          </button>
          <button type="button" className="finish" onClick={() => finishRef.current?.showModal()}>
            {t("finish")}
          </button>
        </div>
      </aside>
      <main id="main" className="main" tabIndex={-1}>
        {!s.online && <div className="banner offline" role="status">{exhibit.leaseValid === false ? t("leaseExpired") : t("offlineBanner")}</div>}
        {s.online && exhibit.leaseValid === false && <div className="banner warn" role="status">{t("leaseExpired")}</div>}
        {(s.config?.fixture_items_visible ?? 0) > 0 && <div className="banner">{t("fixtureBanner")}</div>}
        <Outlet />
      </main>
      <dialog ref={finishRef} aria-labelledby="finish-title">
        <h2 id="finish-title">{t("finishTitle")}</h2>
        <p>{t("finishBody")}</p>
        <div className="actions">
          <button type="button" className="btn secondary" onClick={() => finishRef.current?.close()}>
            {t("cancel")}
          </button>
          <button type="button" className="btn" onClick={endVisit}>
            {t("finishConfirm")}
          </button>
        </div>
      </dialog>
      {attract && (
        <button type="button" className="attract" onClick={() => setAttract(false)} autoFocus>
          <h1>{t("archiveName")}</h1>
          <p>{t("attractTitle")}</p>
        </button>
      )}
    </div>
  );
}

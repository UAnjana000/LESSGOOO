import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../state";
import { useExhibitStatus } from "../exhibit";
import { isKiosk } from "../kiosk";
import { LanguageSwitch } from "./Bits";
import { closeModal, IDLE_WARNING_MS, IdleWarning, openModal, useIdleReset } from "./useIdleReset";
import { IconAsk, IconConstitution, IconHome, IconList, IconMap, IconSearch, IconSettings, IconStories, IconTimeline } from "./Icons";

export { IDLE_WARNING_MS };

export function Shell() {
  const s = useSession();
  const { t } = s;
  const nav = useNavigate();
  const { pathname } = useLocation();
  const finishRef = useRef<HTMLDialogElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const settingsRef = useRef<HTMLDivElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [attract, setAttract] = useState(false);
  const exhibit = useExhibitStatus();

  // Close settings drop-up on click outside or Escape
  useEffect(() => {
    if (!settingsOpen) return;
    const handlePointerDown = (e: PointerEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSettingsOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [settingsOpen]);

  const endVisit = useCallback(() => {
    closeModal(finishRef.current);
    s.finish();
    nav("/");
  }, [s, nav]);
  const kiosk = isKiosk();
  const { warnRef, remaining } = useIdleReset(kiosk && !attract, () => {
    endVisit();
    setAttract(true);
  });

  // Gallery lockdown: no context menu, no text selection (CSS), fullscreen on first touch, and links stay in the app.
  useEffect(() => {
    if (!kiosk) return;
    document.documentElement.dataset.kiosk = "1";
    const noMenu = (e: Event) => e.preventDefault();
    const fullscreen = () => {
      if (document.fullscreenElement) return;
      try {
        void Promise.resolve(document.documentElement.requestFullscreen?.()).catch(() => {});
      } catch {
        /* not allowed here */
      }
    };
    const onClick = (e: MouseEvent) => {
      const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
      if (!(a instanceof HTMLAnchorElement)) return;
      let url: URL;
      try {
        url = new URL(a.href, window.location.href);
      } catch {
        return;
      }
      if (url.origin !== window.location.origin) {
        e.preventDefault();
        return;
      }
      if (a.target === "_blank") {
        e.preventDefault();
        nav(url.pathname + url.search + url.hash);
      }
    };
    document.addEventListener("contextmenu", noMenu);
    document.addEventListener("pointerdown", fullscreen, { once: true });
    document.addEventListener("click", onClick, true);
    return () => {
      delete document.documentElement.dataset.kiosk;
      document.removeEventListener("contextmenu", noMenu);
      document.removeEventListener("pointerdown", fullscreen);
      document.removeEventListener("click", onClick, true);
    };
  }, [kiosk, nav]);

  const dismissAttract = () => {
    setAttract(false);
    // <main> is still inert in this render; focus it once the attract screen has gone.
    window.setTimeout(() => mainRef.current?.focus({ preventScroll: true }));
  };

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
        <div className="controls" role="group" aria-label={t("displaySettings")} ref={settingsRef}>
          <div className="settings-dropup-wrap">
            <button
              type="button"
              className={`toggle settings-toggle-btn ${settingsOpen ? "active" : ""}`}
              onClick={() => setSettingsOpen((prev) => !prev)}
              aria-expanded={settingsOpen}
              aria-haspopup="dialog"
              aria-label={t("displaySettings")}
              title={t("displaySettings")}
            >
              <IconSettings />
              <span className="settings-toggle-label">{t("displaySettings")}</span>
            </button>

            {settingsOpen && (
              <div className="settings-dropup-menu" role="dialog" aria-label={t("displaySettings")}>
                <div className="settings-dropup-header">
                  <span className="settings-dropup-title">{t("displaySettings")}</span>
                  <button
                    type="button"
                    className="settings-close-btn"
                    onClick={() => setSettingsOpen(false)}
                    aria-label={t("clearSelection")}
                  >
                    ✕
                  </button>
                </div>

                <div className="settings-section">
                  <span className="settings-section-title">{t("language")}</span>
                  <LanguageSwitch className="langs settings-langs" />
                </div>

                <div className="settings-section">
                  <span className="settings-section-title">{t("textSize")}</span>
                  <button
                    type="button"
                    className="toggle settings-option-btn"
                    onClick={s.cycleTextScale}
                    aria-label={`${t("textSize")}: ${Math.round(s.textScale * 100)}%`}
                  >
                    A<span aria-hidden="true" style={{ fontSize: "1.3em" }}>A</span> {Math.round(s.textScale * 100)}%
                  </button>
                </div>

                <div className="settings-section">
                  <span className="settings-section-title">{t("contrast")}</span>
                  <button
                    type="button"
                    className="toggle settings-option-btn"
                    aria-pressed={s.contrast}
                    onClick={s.toggleContrast}
                  >
                    {t("contrast")}
                  </button>
                </div>
              </div>
            )}
          </div>

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
      <IdleWarning warnRef={warnRef} remaining={remaining} />
      {attract && (
        <button type="button" className="attract" onClick={dismissAttract} autoFocus>
          <span className="attract-title">{t("archiveName")}</span>
          <span className="attract-lead">{t("attractTitle")}</span>
        </button>
      )}
    </div>
  );
}

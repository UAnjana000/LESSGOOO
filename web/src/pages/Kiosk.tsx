import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { startExhibit } from "../exhibit";
import { markKiosk } from "../kiosk";
import { useNavigate } from "react-router-dom";
import { useSession } from "../state";
import { Loading } from "../components/Bits";
import { VirtualKeyboard } from "../components/VirtualKeyboard";
import { Search } from "./Search";
import { Ask } from "./Ask";
import { Stories } from "./Stories";
import { Timeline, Basket, KnowledgeMap } from "./Explore";
import { IdleWarning, useIdleReset } from "../components/useIdleReset";

const Constitution = lazy(async () => {
  const m = await import("./Constitution");
  return { default: m.Constitution };
});

export function KioskMode() {
  const { t, lang, setLang, basket, finish } = useSession();
  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState<"search" | "ask" | "stories" | "timeline" | "constitution" | "map" | "list">("search");
  const [activeInput, setActiveInput] = useState<HTMLInputElement | HTMLTextAreaElement | null>(null);
  const [isIdle, setIsIdle] = useState(false);
  const [currentTime, setCurrentTime] = useState("");

  // Clock
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(now.toLocaleTimeString(`${lang}-IN`, { hour: "2-digit", minute: "2-digit" }));
    };
    updateTime();
    const interval = window.setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, [lang]);

  // Search keeps its query in the URL (?q=) and Ask asks whatever ?q= holds when it opens, so a tab switch starts
  // with a clean URL: otherwise searching "caste" then opening Ask sends "caste" to the answer model unasked.
  const openTab = (tab: typeof activeTab) => {
    navigate({ search: "" }, { replace: true });
    setActiveInput(null);
    setActiveTab(tab);
  };

  // This screen is a gallery kiosk: remember it (offline shell and exhibit cache from the next load), start the
  // exhibit sync now, and keep the browser's context menu away from visitors.
  useEffect(() => {
    markKiosk();
    void startExhibit();
    const block = (e: Event) => e.preventDefault();
    document.addEventListener("contextmenu", block);
    return () => document.removeEventListener("contextmenu", block);
  }, []);

  // Staff Exit needs a 2-second press, so a visitor's tap cannot open the staff tools.
  const holdTimer = useRef<number | null>(null);
  const [exitHint, setExitHint] = useState(false);
  const startHold = () => {
    holdTimer.current = window.setTimeout(() => navigate("/staff"), 2000);
  };
  const cancelHold = () => {
    if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
    holdTimer.current = null;
  };

  // Same idle policy as the main kiosk shell: warn, then end the visit (session_idle_seconds) and show the attract screen.
  const { warnRef, remaining } = useIdleReset(!isIdle, () => {
    finish();
    setActiveTab("search");
    setActiveInput(null);
    setIsIdle(true);
  });

  // Global Input Focus Listener for Virtual Keyboard
  useEffect(() => {
    const handleFocusIn = (e: FocusEvent) => {
      const target = e.target;
      if (
        target instanceof HTMLInputElement &&
        (target.type === "text" || target.type === "search" || !target.type)
      ) {
        setActiveInput(target);
      } else if (target instanceof HTMLTextAreaElement) {
        setActiveInput(target);
      }
    };

    document.addEventListener("focusin", handleFocusIn);
    return () => {
      document.removeEventListener("focusin", handleFocusIn);
    };
  }, []);

  return (
    <div className="kiosk-shell">
      {/* Kiosk Sticky Navigation Header */}
      <header className="kiosk-header" role="banner">
        <div className="kiosk-header-left">
          <span className="kiosk-emblem" aria-hidden="true">🏛️</span>
          <div className="kiosk-title-col">
            <span className="kiosk-app-title">{t("archiveName")}</span>
            <span className="kiosk-terminal-tag">{t("kioskTitle")}</span>
          </div>
        </div>

        {/* Primary Kiosk Navigation Dock */}
        <nav className="kiosk-dock" role="navigation" aria-label={t("kioskTitle")}>
          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "search" ? "active" : ""}`}
            onClick={() => openTab("search")}
            aria-pressed={activeTab === "search"}
          >
            <span className="dock-icon" aria-hidden="true">🔍</span>
            <span className="kiosk-nav-label">{t("searchButton")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "ask" ? "active" : ""}`}
            onClick={() => openTab("ask")}
            aria-pressed={activeTab === "ask"}
          >
            <span className="dock-icon" aria-hidden="true">💬</span>
            <span className="kiosk-nav-label">{t("askTitle")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "stories" ? "active" : ""}`}
            onClick={() => openTab("stories")}
            aria-pressed={activeTab === "stories"}
          >
            <span className="dock-icon" aria-hidden="true">📖</span>
            <span className="kiosk-nav-label">{t("storiesTitle")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "timeline" ? "active" : ""}`}
            onClick={() => openTab("timeline")}
            aria-pressed={activeTab === "timeline"}
          >
            <span className="dock-icon" aria-hidden="true">⏳</span>
            <span className="kiosk-nav-label">{t("timelineTitle")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "constitution" ? "active" : ""}`}
            onClick={() => openTab("constitution")}
            aria-pressed={activeTab === "constitution"}
          >
            <span className="dock-icon" aria-hidden="true">📜</span>
            <span className="kiosk-nav-label">{t("navConstitution")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "map" ? "active" : ""}`}
            onClick={() => openTab("map")}
            aria-pressed={activeTab === "map"}
          >
            <span className="dock-icon" aria-hidden="true">🌐</span>
            <span className="kiosk-nav-label">{t("mapTitle")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "list" ? "active" : ""}`}
            onClick={() => openTab("list")}
            aria-pressed={activeTab === "list"}
          >
            <span className="dock-icon" aria-hidden="true">🔖</span>
            <span className="kiosk-nav-label">{t("basketTitle")}</span>
            {basket.length > 0 && <span className="kiosk-badge">{basket.length}</span>}
          </button>
        </nav>

        {/* Right Controls: Language & Staff Exit */}
        <div className="kiosk-header-right">
          <span className="kiosk-clock" aria-hidden="true">{currentTime}</span>

          <div className="kiosk-lang-group" role="group" aria-label={t("language")}>
            <button
              type="button"
              className={`btn small ${lang === "en" ? "primary" : "secondary"}`}
              onClick={() => setLang("en")}
              aria-pressed={lang === "en"}
            >
              EN
            </button>
            <button
              type="button"
              className={`btn small ${lang === "hi" ? "primary" : "secondary"}`}
              onClick={() => setLang("hi")}
              aria-pressed={lang === "hi"}
            >
              हिं
            </button>
            <button
              type="button"
              className={`btn small ${lang === "mr" ? "primary" : "secondary"}`}
              onClick={() => setLang("mr")}
              aria-pressed={lang === "mr"}
            >
              मरा
            </button>
          </div>

          <button
            type="button"
            className="btn quiet small kiosk-exit-btn"
            onPointerDown={startHold}
            onPointerUp={cancelHold}
            onPointerLeave={cancelHold}
            onPointerCancel={cancelHold}
            onClick={() => setExitHint(true)}
            aria-label={`${t("kioskExit")}: ${t("kioskExitHold")}`}
            title={t("kioskExitHold")}
          >
            {t("kioskExit")}
          </button>
          {exitHint && <span className="kiosk-exit-hint" role="status">{t("kioskExitHold")}</span>}
        </div>
      </header>

      {/* Main Kiosk Content Area */}
      <main className="kiosk-main-stage">
        {activeTab === "search" && <Search />}
        {activeTab === "ask" && <Ask autoAsk={false} />}
        {activeTab === "stories" && <Stories />}
        {activeTab === "timeline" && <Timeline />}
        {activeTab === "constitution" && (
          <Suspense fallback={<Loading />}>
            <Constitution />
          </Suspense>
        )}
        {activeTab === "map" && <KnowledgeMap />}
        {activeTab === "list" && <Basket />}
      </main>

      {/* Docked Virtual Keyboard */}
      <VirtualKeyboard
        activeInput={activeInput}
        onClose={() => setActiveInput(null)}
      />

      {/* Attract Mode Overlay */}
      {isIdle && (
        <div
          className="kiosk-attract-overlay"
          // Swallow the waking tap so it cannot activate whatever sits underneath.
          onPointerDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setIsIdle(false);
          }}
          role="region"
          aria-label={t("attractTitle")}
        >
          <div className="attract-content">
            <span className="attract-emblem" aria-hidden="true">🏛️</span>
            <h1 className="attract-title">{t("attractTitle")}</h1>
            <p className="attract-lead">{t("storiesLead")}</p>
            <button type="button" className="btn primary large attract-wake-btn">
              {t("attractTitle")}
            </button>
          </div>
        </div>
      )}

      <IdleWarning warnRef={warnRef} remaining={remaining} />
    </div>
  );
}

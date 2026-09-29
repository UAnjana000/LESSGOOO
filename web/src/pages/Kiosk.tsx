import { lazy, Suspense, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../state";
import { Loading } from "../components/Bits";
import { VirtualKeyboard } from "../components/VirtualKeyboard";
import { Search } from "./Search";
import { Ask } from "./Ask";
import { Stories } from "./Stories";
import { Timeline, Basket } from "./Explore";

const Constitution = lazy(async () => {
  const m = await import("./Constitution");
  return { default: m.Constitution };
});

export function KioskMode() {
  const { t, lang, setLang, basket } = useSession();
  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState<"search" | "ask" | "stories" | "timeline" | "constitution" | "list">("search");
  const [activeInput, setActiveInput] = useState<HTMLInputElement | HTMLTextAreaElement | null>(null);
  const [showExitModal, setShowExitModal] = useState(false);
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState(false);
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

  // Inactivity Attract Mode (60 seconds)
  useEffect(() => {
    let idleTimer: number | null = null;
    const resetTimer = () => {
      setIsIdle(false);
      if (idleTimer) window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => {
        setIsIdle(true);
        setActiveInput(null);
      }, 60000);
    };

    resetTimer();
    window.addEventListener("pointerdown", resetTimer, { passive: true });
    window.addEventListener("keydown", resetTimer, { passive: true });
    window.addEventListener("touchstart", resetTimer, { passive: true });

    return () => {
      if (idleTimer) window.clearTimeout(idleTimer);
      window.removeEventListener("pointerdown", resetTimer);
      window.removeEventListener("keydown", resetTimer);
      window.removeEventListener("touchstart", resetTimer);
    };
  }, []);

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

  const handlePinSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (pin === "1956" || pin === "admin") {
      setShowExitModal(false);
      navigate("/staff");
    } else {
      setPinError(true);
    }
  };

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
            onClick={() => setActiveTab("search")}
            aria-pressed={activeTab === "search"}
          >
            <span className="dock-icon" aria-hidden="true">🔍</span>
            <span>{t("searchButton")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "ask" ? "active" : ""}`}
            onClick={() => setActiveTab("ask")}
            aria-pressed={activeTab === "ask"}
          >
            <span className="dock-icon" aria-hidden="true">💬</span>
            <span>{t("askTitle")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "stories" ? "active" : ""}`}
            onClick={() => setActiveTab("stories")}
            aria-pressed={activeTab === "stories"}
          >
            <span className="dock-icon" aria-hidden="true">📖</span>
            <span>{t("storiesTitle")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "timeline" ? "active" : ""}`}
            onClick={() => setActiveTab("timeline")}
            aria-pressed={activeTab === "timeline"}
          >
            <span className="dock-icon" aria-hidden="true">⏳</span>
            <span>{t("timelineTitle")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "constitution" ? "active" : ""}`}
            onClick={() => setActiveTab("constitution")}
            aria-pressed={activeTab === "constitution"}
          >
            <span className="dock-icon" aria-hidden="true">📜</span>
            <span>{t("constitutionTitle")}</span>
          </button>

          <button
            type="button"
            className={`kiosk-nav-btn ${activeTab === "list" ? "active" : ""}`}
            onClick={() => setActiveTab("list")}
            aria-pressed={activeTab === "list"}
          >
            <span className="dock-icon" aria-hidden="true">🔖</span>
            <span>{t("basketTitle")}</span>
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
            onClick={() => setShowExitModal(true)}
            aria-label={t("kioskExit")}
          >
            🔒 {t("kioskExit")}
          </button>
        </div>
      </header>

      {/* Main Kiosk Content Area */}
      <main className="kiosk-main-stage">
        {activeTab === "search" && <Search />}
        {activeTab === "ask" && <Ask />}
        {activeTab === "stories" && <Stories />}
        {activeTab === "timeline" && <Timeline />}
        {activeTab === "constitution" && (
          <Suspense fallback={<Loading />}>
            <Constitution />
          </Suspense>
        )}
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
          onClick={() => setIsIdle(false)}
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

      {/* Staff PIN Lock Modal */}
      {showExitModal && (
        <div className="kiosk-modal-backdrop" role="dialog" aria-modal="true" aria-label={t("kioskExit")}>
          <div className="kiosk-modal-card">
            <h2 className="kiosk-modal-title">{t("kioskExit")}</h2>
            <p className="kiosk-modal-prompt">{t("kioskPinPrompt")}</p>

            <form onSubmit={handlePinSubmit} className="kiosk-pin-form">
              <input
                type="password"
                className="input kiosk-pin-input"
                autoFocus
                maxLength={8}
                value={pin}
                onChange={(e) => {
                  setPin(e.target.value);
                  setPinError(false);
                }}
                aria-label={t("kioskPinPrompt")}
              />

              {pinError && <p className="notice bad" role="alert">{t("kioskPinError")}</p>}

              <div className="kiosk-modal-actions">
                <button type="button" className="btn secondary" onClick={() => setShowExitModal(false)}>
                  {t("cancel")}
                </button>
                <button type="submit" className="btn primary">
                  {t("kioskExit")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

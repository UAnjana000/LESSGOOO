import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fileUrl } from "../api";
import { useApi } from "../hooks";
import { ErrorState, LangText, Loading, Page, useDocumentTitle, pickText } from "../components/Bits";
import { useSession } from "../state";
import type { ItemCard, Hit } from "../api";

export interface StorySummary {
  slug: string;
  titles: Record<string, string>;
  blocks: number;
  cover_image_file_id?: number | null;
  duration?: string | null;
  theme?: Record<string, string> | string | null;
}

export interface StoryBlock {
  item: ItemCard;
  chapter_title?: Record<string, string>;
  year?: string;
  captions?: Record<string, string>;
  quote_text?: Record<string, string>;
  image_file_id?: number | null;
  image_url?: string | null;
  passage?: Hit | null;
  citation?: string;
  deep_link: string;
}

export interface StoryDetailData {
  slug: string;
  titles: Record<string, string>;
  blocks: StoryBlock[];
  duration?: string | null;
  theme?: Record<string, string> | string | null;
  narration_file_ids: Record<string, number>;
  narration_label: string;
}

export function Stories() {
  const { t, lang } = useSession();
  const st = useApi<StorySummary[]>("/api/visitor/stories");

  return (
    <Page title={t("storiesTitle")}>
      <div className="stories-gallery-hero">
        <span className="stories-eyebrow">{t("storiesTitle")}</span>
        <h1 className="stories-lead-title">{t("storiesLead")}</h1>
      </div>

      {st.loading && <Loading center />}
      {st.error && <ErrorState error={st.error} retry={st.reload} />}
      {st.data?.length === 0 && <p className="empty-state">{t("storiesEmpty")}</p>}

      {!!st.data?.length && (
        <div className="stories-card-grid">
          {st.data.map((s, idx) => {
            const themeText = typeof s.theme === "object" && s.theme !== null ? pickText(s.theme, lang) : typeof s.theme === "string" ? s.theme : "";
            return (
              <article key={s.slug} className="story-card story-journey-card">
                <div className="story-card-cover">
                  {s.cover_image_file_id ? (
                    <img src={fileUrl(s.cover_image_file_id)} alt="" loading="lazy" className="story-cover-img" />
                  ) : (
                    <div className="story-cover-placeholder">
                      <span className="story-cover-badge">{t("chapterLabel", { n: idx + 1 })}</span>
                    </div>
                  )}
                  <div className="story-cover-overlay">
                    <div className="story-pill-row">
                      <span className="story-pill duration-pill">
                        {s.duration ?? t("durationPill", { read: 8, audio: s.blocks })}
                      </span>
                      <span className="story-pill chapter-pill">
                        {t("chaptersCount", { n: s.blocks })}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="story-card-body">
                  <h2 className="story-card-title">
                    <LangText map={s.titles} />
                  </h2>
                  {themeText ? <p className="story-card-theme">{themeText}</p> : null}
                  <div className="story-card-actions">
                    <Link to={`/stories/${s.slug}`} className="btn primary enter-journey-btn">
                      {t("enterJourney")}
                    </Link>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </Page>
  );
}

export function Story() {
  const { slug } = useParams();
  const { t, lang } = useSession();
  const st = useApi<StoryDetailData>(`/api/visitor/stories/${slug}`);
  const d = st.data;

  const [mode, setMode] = useState<"walkthrough" | "reading">("walkthrough");
  const [activeIdx, setActiveIdx] = useState(0);
  const [autoplay, setAutoplay] = useState(false);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [audioProgress, setAudioProgress] = useState(0);

  const synthRef = useRef<SpeechSynthesisUtterance | null>(null);
  const audioElemRef = useRef<HTMLAudioElement | null>(null);
  const lastActiveRef = useRef<number>(Date.now());
  const advanceTimeoutRef = useRef<number | null>(null);

  useDocumentTitle(d ? pickText(d.titles, lang) : t("storiesTitle"));

  const blocks = useMemo(() => d?.blocks ?? [], [d]);
  const currentBlock = blocks[activeIdx] ?? null;
  const total = blocks.length;

  // Track visitor inactivity - auto start Guided Tour at 15s inactivity
  useEffect(() => {
    const handleActivity = () => {
      lastActiveRef.current = Date.now();
    };

    window.addEventListener("pointerdown", handleActivity, { passive: true });
    window.addEventListener("keydown", handleActivity, { passive: true });
    window.addEventListener("touchstart", handleActivity, { passive: true });

    const interval = window.setInterval(() => {
      const idleTime = Date.now() - lastActiveRef.current;
      if (idleTime >= 15000 && !autoplay && mode === "walkthrough" && total > 0) {
        setAutoplay(true);
      }
    }, 1000);

    return () => {
      window.removeEventListener("pointerdown", handleActivity);
      window.removeEventListener("keydown", handleActivity);
      window.removeEventListener("touchstart", handleActivity);
      clearInterval(interval);
    };
  }, [autoplay, mode, total]);

  // Stop audio on unmount or slide change
  const stopNarration = () => {
    if (advanceTimeoutRef.current) {
      clearTimeout(advanceTimeoutRef.current);
      advanceTimeoutRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    if (audioElemRef.current) {
      audioElemRef.current.pause();
      audioElemRef.current.currentTime = 0;
    }
    setIsPlayingAudio(false);
    setAudioProgress(0);
  };

  useEffect(() => {
    stopNarration();
  }, [activeIdx, mode]);

  const startNarration = () => {
    const narrationFileId = d?.narration_file_ids?.[lang] ?? d?.narration_file_ids?.en;
    if (narrationFileId && audioElemRef.current) {
      audioElemRef.current.play().catch(() => {});
      setIsPlayingAudio(true);
      return;
    }

    if (typeof window !== "undefined" && "speechSynthesis" in window && currentBlock) {
      const chapterTitle = currentBlock.chapter_title ? pickText(currentBlock.chapter_title, lang) : "";
      const caption = currentBlock.captions ? pickText(currentBlock.captions, lang) : "";
      const quote = currentBlock.quote_text ? pickText(currentBlock.quote_text, lang) : "";
      const textToSpeak = `${chapterTitle}. ${caption}. ${quote}`;

      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(textToSpeak);
      u.lang = lang === "hi" ? "hi-IN" : lang === "mr" ? "mr-IN" : "en-IN";
      u.rate = 0.95;

      u.onstart = () => {
        setIsPlayingAudio(true);
        setAudioProgress(25);
      };
      u.onboundary = () => {
        setAudioProgress((prev) => Math.min(prev + 15, 95));
      };
      u.onend = () => {
        setIsPlayingAudio(false);
        setAudioProgress(100);
        if (autoplay && total > 0) {
          if (advanceTimeoutRef.current) clearTimeout(advanceTimeoutRef.current);
          advanceTimeoutRef.current = window.setTimeout(() => {
            setActiveIdx((prev) => (prev + 1) % total);
          }, 3000);
        }
      };
      u.onerror = () => {
        setIsPlayingAudio(false);
        setAudioProgress(0);
        if (autoplay && total > 0) {
          if (advanceTimeoutRef.current) clearTimeout(advanceTimeoutRef.current);
          advanceTimeoutRef.current = window.setTimeout(() => {
            setActiveIdx((prev) => (prev + 1) % total);
          }, 8000);
        }
      };

      synthRef.current = u;
      window.speechSynthesis.speak(u);
    } else if (autoplay && total > 0) {
      if (advanceTimeoutRef.current) clearTimeout(advanceTimeoutRef.current);
      advanceTimeoutRef.current = window.setTimeout(() => {
        setActiveIdx((prev) => (prev + 1) % total);
      }, 10000);
    }
  };

  // Synchronized autoplay: trigger narration for chapter in autoplay mode
  useEffect(() => {
    if (!autoplay || mode !== "walkthrough" || total === 0) return;
    const tId = window.setTimeout(() => {
      startNarration();
    }, 450);
    return () => clearTimeout(tId);
  }, [autoplay, activeIdx, mode]);

  const toggleNarration = () => {
    lastActiveRef.current = Date.now();
    if (isPlayingAudio) {
      stopNarration();
      return;
    }
    startNarration();
  };

  const narrationFile = d?.narration_file_ids?.[lang] ?? d?.narration_file_ids?.en;

  return (
    <div className="page story-experience-page">
      <div className="story-experience-topbar">
        <Link to="/stories" className="btn quiet back-to-stories-btn">
          <span aria-hidden="true">← </span>
          {t("backToStories")}
        </Link>

        <div className="story-mode-toggle" role="group" aria-label={t("storiesTitle")}>
          {autoplay && (
            <span className="guided-tour-badge" role="status">
              <span className="pulsing-dot" aria-hidden="true" />
              {t("guidedTourActive")}
            </span>
          )}
          <button
            type="button"
            className={`btn ${mode === "walkthrough" ? "primary" : "secondary"}`}
            aria-pressed={mode === "walkthrough"}
            onClick={() => setMode("walkthrough")}
          >
            {t("exhibitionMode")}
          </button>
          <button
            type="button"
            className={`btn ${mode === "reading" ? "primary" : "secondary"}`}
            aria-pressed={mode === "reading"}
            onClick={() => setMode("reading")}
          >
            {t("readingMode")}
          </button>
        </div>
      </div>

      {st.loading && <Loading center />}
      {st.error && <ErrorState error={st.error} retry={st.reload} />}

      {d && (
        <>
          <header className="story-header">
            <h1 className="story-main-title">
              <LangText map={d.titles} />
            </h1>
            {d.theme ? (
              <p className="story-theme-lead">
                {typeof d.theme === "object" ? pickText(d.theme, lang) : d.theme}
              </p>
            ) : null}
          </header>

          {/* Hidden audio element if an archive audio file is provided */}
          {narrationFile ? (
            <audio
              ref={audioElemRef}
              src={fileUrl(narrationFile)}
              preload="none"
              onEnded={() => {
                setIsPlayingAudio(false);
                setAudioProgress(100);
                if (autoplay && total > 0) {
                  if (advanceTimeoutRef.current) clearTimeout(advanceTimeoutRef.current);
                  advanceTimeoutRef.current = window.setTimeout(() => {
                    setActiveIdx((prev) => (prev + 1) % total);
                  }, 3000);
                }
              }}
              onTimeUpdate={(e) => {
                const el = e.currentTarget;
                if (el.duration) setAudioProgress((el.currentTime / el.duration) * 100);
              }}
            />
          ) : null}

          {/* VIEW 1: Exhibition Walkthrough Mode */}
          {mode === "walkthrough" && currentBlock && (
            <div className="story-block exhibition-stage">
              <div className="exhibition-split-layout">
                {/* Left Pane: Media Canvas */}
                <div className="exhibition-media-pane">
                  <div className="exhibition-canvas-frame">
                    {currentBlock.image_file_id ? (
                      <img
                        src={fileUrl(currentBlock.image_file_id)}
                        alt={currentBlock.item.title}
                        className="exhibition-scan-image"
                        loading="eager"
                      />
                    ) : (
                      <div className="exhibition-document-preview">
                        <div className="doc-preview-inner">
                          <span className="doc-preview-year">{currentBlock.year ?? "1927"}</span>
                          <h3 className="doc-preview-title">{currentBlock.item.title}</h3>
                          <span className="doc-preview-col">{currentBlock.item.collection}</span>
                        </div>
                      </div>
                    )}
                    <div className="museum-watermark" aria-hidden="true">
                      <span>{t("memorialWatermark")}</span>
                    </div>
                  </div>
                </div>

                {/* Right Pane: Curator Narrative & Spotlight Quote */}
                <div className="exhibition-content-pane">
                  <div className="exhibition-meta-row">
                    <span className="milestone-badge">
                      {t("milestoneYear", { year: currentBlock.year ?? "1927" })}
                    </span>
                    <span className="chapter-step-badge">
                      {t("chapterIndicator", { current: activeIdx + 1, total })}
                    </span>
                  </div>

                  <h2 className="exhibition-chapter-title">
                    {currentBlock.chapter_title ? (
                      <LangText map={currentBlock.chapter_title} />
                    ) : (
                      t("chapterLabel", { n: activeIdx + 1 })
                    )}
                  </h2>

                  {/* Audio Narration Bar */}
                  <div className="narration-player-widget">
                    <button
                      type="button"
                      className={`btn narration-toggle-btn ${isPlayingAudio ? "playing" : ""}`}
                      onClick={toggleNarration}
                      aria-pressed={isPlayingAudio}
                    >
                      <span aria-hidden="true">{isPlayingAudio ? "⏸ " : "▶ "}</span>
                      {t("listenNarration")}
                    </button>
                    <div className="narration-waveform" aria-hidden="true">
                      <div
                        className="waveform-fill"
                        style={{ width: isPlayingAudio ? `${Math.max(audioProgress, 12)}%` : "0%" }}
                      />
                      <span className={`wave-bar ${isPlayingAudio ? "animating" : ""}`} />
                      <span className={`wave-bar ${isPlayingAudio ? "animating" : ""}`} />
                      <span className={`wave-bar ${isPlayingAudio ? "animating" : ""}`} />
                      <span className={`wave-bar ${isPlayingAudio ? "animating" : ""}`} />
                    </div>
                  </div>

                  {currentBlock.captions ? (
                    <p className="exhibition-narrative-text">
                      <LangText map={currentBlock.captions} />
                    </p>
                  ) : null}

                  {/* Verifiable Historical Passage Block */}
                  <div className="exhibition-spotlight-quote">
                    <div className="quote-badge-row">
                      <span className="chip verified-chip">
                        <span aria-hidden="true">✓ </span>
                        {t("verifiedEvidence")}
                      </span>
                    </div>

                    <blockquote className="spotlight-passage">
                      {currentBlock.quote_text ? (
                        <LangText map={currentBlock.quote_text} />
                      ) : (
                        currentBlock.passage?.text ?? ""
                      )}
                    </blockquote>

                    {currentBlock.citation ? (
                      <span className="cite museum-cite">
                        {t("citation")}: {currentBlock.citation}
                      </span>
                    ) : null}
                  </div>

                  <div className="exhibition-actions-row">
                    <Link to={currentBlock.deep_link} className="btn secondary inspect-reader-btn">
                      {t("inspectInReader")}
                    </Link>
                  </div>
                </div>
              </div>

              {/* Bottom Walkthrough Controls Bar */}
              <nav className="exhibition-nav-bar" aria-label={t("chapterIndicator", { current: activeIdx + 1, total })}>
                <button
                  type="button"
                  className="btn secondary nav-step-btn"
                  disabled={activeIdx === 0}
                  onClick={() => setActiveIdx((p) => Math.max(0, p - 1))}
                  aria-label={t("previousChapter")}
                >
                  <span aria-hidden="true">← </span>
                  {t("previousChapter")}
                </button>

                <div className="chapter-dots-row">
                  {blocks.map((_, i) => (
                    <button
                      key={i}
                      type="button"
                      className={`chapter-dot ${i === activeIdx ? "active" : ""}`}
                      onClick={() => setActiveIdx(i)}
                      aria-current={i === activeIdx ? "step" : undefined}
                      aria-label={t("chapterLabel", { n: i + 1 })}
                    >
                      <span className="chapter-dot-inner" aria-hidden="true" />
                    </button>
                  ))}
                </div>

                <div className="nav-right-controls">
                  <button
                    type="button"
                    className={`btn ${autoplay ? "primary" : "secondary"}`}
                    onClick={() => setAutoplay((a) => !a)}
                    aria-pressed={autoplay}
                  >
                    <span aria-hidden="true">{autoplay ? "⏹ " : "⏳ "}</span>
                    {t("autoplay")}
                  </button>

                  <button
                    type="button"
                    className="btn primary nav-step-btn"
                    disabled={activeIdx === total - 1}
                    onClick={() => setActiveIdx((p) => Math.min(total - 1, p + 1))}
                    aria-label={t("nextChapter")}
                  >
                    {t("nextChapter")}
                    <span aria-hidden="true"> →</span>
                  </button>
                </div>
              </nav>
            </div>
          )}

          {/* VIEW 2: Long-Form Reading Mode (Scrollytelling) */}
          {mode === "reading" && (
            <div className="longform-reading-layout">
              <aside className="story-toc-rail" aria-label={t("tableOfContents")}>
                <div className="story-toc-sticky">
                  <h3 className="toc-heading">{t("tableOfContents")}</h3>
                  <ol className="toc-list">
                    {blocks.map((b, idx) => (
                      <li key={idx}>
                        <a href={`#chapter-${idx + 1}`} className="toc-link">
                          <span className="toc-number">{idx + 1}. </span>
                          <span>
                            {b.chapter_title ? pickText(b.chapter_title, lang) : t("chapterLabel", { n: idx + 1 })}
                          </span>
                        </a>
                      </li>
                    ))}
                  </ol>
                </div>
              </aside>

              <main className="story-chapters-stream">
                {blocks.map((b, idx) => (
                  <section key={idx} id={`chapter-${idx + 1}`} className="story-block longform-chapter-section">
                    <div className="chapter-header-row">
                      <span className="milestone-badge">
                        {t("milestoneYear", { year: b.year ?? "1927" })}
                      </span>
                      <span className="chapter-step-badge">
                        {t("chapterIndicator", { current: idx + 1, total })}
                      </span>
                    </div>

                    <h2 className="longform-chapter-title">
                      {b.chapter_title ? <LangText map={b.chapter_title} /> : t("chapterLabel", { n: idx + 1 })}
                    </h2>

                    {b.image_file_id ? (
                      <div className="longform-image-wrap">
                        <img
                          src={fileUrl(b.image_file_id)}
                          alt={b.item.title}
                          loading="lazy"
                          className="longform-chapter-img"
                        />
                        <div className="museum-watermark" aria-hidden="true">
                          <span>{t("memorialWatermark")}</span>
                        </div>
                      </div>
                    ) : null}

                    {b.captions ? (
                      <p className="longform-narrative">
                        <LangText map={b.captions} />
                      </p>
                    ) : null}

                    <div className="longform-quote-card">
                      <div className="quote-badge-row">
                        <span className="chip verified-chip">
                          <span aria-hidden="true">✓ </span>
                          {t("verifiedEvidence")}
                        </span>
                      </div>
                      <blockquote className="spotlight-passage">
                        {b.quote_text ? <LangText map={b.quote_text} /> : b.passage?.text ?? ""}
                      </blockquote>
                      {b.citation ? (
                        <span className="cite museum-cite">
                          {t("citation")}: {b.citation}
                        </span>
                      ) : null}
                    </div>

                    <div className="chapter-footer-actions">
                      <Link to={b.deep_link} className="btn secondary">
                        {t("inspectInReader")}
                      </Link>
                    </div>
                  </section>
                ))}
              </main>
            </div>
          )}
        </>
      )}
    </div>
  );
}

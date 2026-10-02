import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, fileUrl, resolveApiUrl, type ItemDetail, type PassageView } from "../api";
import { derivativeLabel, type Key } from "../i18n";
import { itemCitation } from "../basket";
import { formatMs, useApi } from "../hooks";
import { useSession } from "../state";
import { AddToList, ArticleLinks, ContentText, ErrorState, FacetLinks, FixtureChip, KindChip, Loading, useDocumentTitle, VerifiedChip } from "../components/Bits";
import { ScanViewer } from "../components/ScanViewer";
import { IconChevronLeft, IconChevronRight, IconPlay } from "../components/Icons";

type Tab = "original" | "reviewed";

/** Above this many pages the pager is a drop-down instead of one button per page. */
const PAGER_CHIPS_MAX = 12;

function MachineTranslation({ passage, enabled }: { passage: PassageView; enabled: boolean }) {
  const { t, lang, config } = useSession();
  const [state, setState] = useState<{ text?: string; error?: string; loading?: boolean }>({});
  useEffect(() => setState({}), [lang, passage.id]);
  if (lang === passage.language || passage.translations[lang]) return null;
  if (!enabled) return <p className="muted">{t("mtOff")}</p>;
  if (!config?.machine_translation.available) return null;
  const run = async () => {
    setState({ loading: true });
    try {
      const r = await api.get<{ text: string }>(`/api/visitor/translate/${passage.id}?lang=${lang}`);
      setState({ text: r.text });
    } catch (e) {
      const err = e as ApiError;
      setState({ error: err.status === 403 ? t("mtOff") : t("mtUnavailable") });
    }
  };
  return (
    <div className="stack" style={{ gap: 8 }}>
      {!state.text && (
        <button type="button" className="btn quiet small" onClick={run} disabled={state.loading}>
          {state.loading ? <Loading inline size="sm" /> : t("translateOnDemand")}
        </button>
      )}
      {state.error && <p className="notice bad" role="alert">{state.error}</p>}
      {state.text && (
        <div>
          <span className="chip mt">{t("mtLabel")}</span>
          <p className="passage" lang={lang} style={{ marginTop: 8 }}>
            {state.text}
          </p>
        </div>
      )}
    </div>
  );
}

function Narration({ item, passage }: { item: ItemDetail; passage: PassageView }) {
  const { t, lang } = useSession();
  const n = item.narrations.find((x) => x.language === lang && x.source_ids.includes(passage.id))
    ?? item.narrations.find((x) => x.source_ids.includes(passage.id) && x.language === passage.language);
  if (!n) return null;
  return (
    <div className="stack" style={{ gap: 4 }}>
      <span className="muted" style={{ fontSize: "var(--step--1)" }}>
        {t("listen")}: {t("synthNarration")}
      </span>
      <audio controls preload="none" src={fileUrl(n.file_id)} aria-label={`${t("listen")}: ${t("synthNarration")}`} />
    </div>
  );
}

function PassageBlock({ item, passage, citation, page, tab, target }: { item: ItemDetail; passage: PassageView; citation: string; page?: number; tab: Tab; target: boolean }) {
  const { t, lang } = useSession();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (target) ref.current?.scrollIntoView({ block: "center" });
  }, [target]);
  const reviewed = passage.translations[lang];
  const showReviewed = tab === "reviewed" && reviewed;
  return (
    <div ref={ref} className="stack" style={{ gap: 10 }}>
      <div className="chips">
        {showReviewed ? <span className="chip">{t("reviewedTranslation")}</span> : <KindChip label={passage.kind_label} />}
        <VerifiedChip verified={passage.quote_verified && !showReviewed} />
      </div>
      <div className={`passage${target ? " target" : ""}`} lang={showReviewed ? lang : passage.language}>
        {showReviewed ? reviewed.text : passage.text}
      </div>
      <div className="row">
        <AddToList entry={{ item_id: item.id, title: item.title, passage_id: showReviewed ? reviewed.passage_id : passage.id, page, citation }} />
      </div>
      {tab === "original" && <MachineTranslation passage={passage} enabled={item.machine_translation_enabled} />}
      <Narration item={item} passage={passage} />
    </div>
  );
}

function Media({ item, startMs, targetPassage }: { item: ItemDetail; startMs: number | null; targetPassage: number | null }) {
  const { t } = useSession();
  const media = item.media!;
  const player = useRef<HTMLAudioElement & HTMLVideoElement>(null);
  const pendingStart = useRef<number | null>(startMs);
  const [now, setNow] = useState(0);
  const isVideo = media.format.startsWith("video/");

  // Browsers may ignore currentTime set before metadata has loaded, so a ?t= start waits for loadedmetadata.
  useEffect(() => {
    pendingStart.current = startMs;
    const el = player.current;
    if (startMs !== null && el && el.readyState >= HTMLMediaElement.HAVE_METADATA) {
      el.currentTime = startMs / 1000;
      pendingStart.current = null;
    }
  }, [startMs]);
  const applyStart = () => {
    const el = player.current;
    if (!el || pendingStart.current === null) return;
    el.currentTime = pendingStart.current / 1000;
    pendingStart.current = null;
  };

  const seek = (ms: number) => {
    if (!player.current) return;
    player.current.currentTime = ms / 1000;
    void player.current.play().catch(() => {});
  };
  const Player = isVideo ? "video" : "audio";
  return (
    <section className="sheet stack" aria-labelledby="media-h">
      <h2 id="media-h">{t("transcript")}</h2>
      <Player ref={player} controls preload="metadata" playsInline={isVideo || undefined} src={fileUrl(media.file_id)}
        onLoadedMetadata={applyStart} onTimeUpdate={(e) => setNow(e.currentTarget.currentTime * 1000)}>
        <track kind="captions" src={resolveApiUrl(media.captions)}srcLang={item.languages[0] ?? "en"} label={isVideo ? t("captions") : t("transcript")} default />
      </Player>
      <div className="chips">
        <span className="chip">{t("transcript")}</span>
      </div>
      <ol className="segments">
        {media.segments.map((s) => {
          const active = now >= s.start_ms && now < s.end_ms;
          const passage = s.passages[0];
          const target = targetPassage !== null && s.passages.some((p) => p.id === targetPassage);
          const citation = `${item.title}, ${t("atTime", { time: formatMs(s.start_ms) })}`;
          return (
            <li key={s.id} className={`segment${active || target ? " active" : ""}`} aria-current={active ? "true" : undefined}>
              <button type="button" className="time" onClick={() => seek(s.start_ms)} aria-label={`${t("playFrom")} ${formatMs(s.start_ms)}`}>
                <IconPlay /> {formatMs(s.start_ms)}
              </button>
              <div className="stack" style={{ gap: 6 }}>
                {s.speaker && <strong>{s.speaker}</strong>}
                <p className="passage" style={{ margin: 0 }} lang={passage?.language}>
                  {s.text}
                </p>
                <div className="row">
                  <VerifiedChip verified={s.quote_verified} />
                  <AddToList entry={{ item_id: item.id, title: item.title, passage_id: passage?.id, start_ms: s.start_ms, citation }} />
                </div>
                <ArticleLinks articles={s.articles} />
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function Item() {
  const { id = "" } = useParams();
  const { t, lang } = useSession();
  const [params, setParams] = useSearchParams();
  // The API rejects a non-numeric id (422), and retrying cannot fix the address.
  const validId = /^\d+$/.test(id);
  const item = useApi<ItemDetail>(validId ? `/api/visitor/items/${id}?lang=${lang}` : null);
  const pageParam = params.get("page");
  const targetPassage = params.get("passage") ? Number(params.get("passage")) : null;
  const startMs = params.get("t") ? Number(params.get("t")) : null;
  const d = item.data;
  // ?page= is the page sequence; the printed page label the reader shows ("Page 1210") is accepted too.
  const requested = useMemo(
    () => (pageParam === null ? undefined : d?.pages.find((p) => p.sequence === Number(pageParam)) ?? d?.pages.find((p) => p.label === pageParam)),
    [d, pageParam],
  );
  const page = requested ?? d?.pages[0];
  const missingPage = pageParam !== null && Boolean(d?.pages.length) && !requested;
  const hasReviewed = Boolean(page?.passages.some((p) => p.translations[lang]));
  const targetIsTranslation = Boolean(page?.passages.some((p) => Object.values(p.translations).some((x) => x.passage_id === targetPassage)));
  const [tab, setTab] = useState<Tab>("original");
  useEffect(() => setTab(hasReviewed && targetIsTranslation ? "reviewed" : "original"), [hasReviewed, targetIsTranslation]);
  useDocumentTitle(!validId || item.error ? t("notAvailable") : d?.title);

  const pageIndex = d && page ? d.pages.indexOf(page) : -1;
  const prevPage = pageIndex > 0 ? d!.pages[pageIndex - 1] : undefined;
  const nextPage = d && pageIndex >= 0 ? d.pages[pageIndex + 1] : undefined;
  const prevBtn = useRef<HTMLButtonElement>(null);
  const nextBtn = useRef<HTMLButtonElement>(null);
  const pendingFocus = useRef<HTMLButtonElement | null>(null);
  // A history entry per page, so Back returns to the page the visitor was reading.
  const goToPage = (seq: number) => setParams({ page: String(seq) });
  // A focused button that becomes disabled drops focus to <body>, so hand it to the other arrow.
  const step = (dir: -1 | 1) => {
    const to = dir < 0 ? prevPage : nextPage;
    if (!to) return false;
    goToPage(to.sequence);
    const atEnd = dir < 0 ? d!.pages[0] === to : d!.pages[d!.pages.length - 1] === to;
    if (atEnd && document.activeElement === (dir < 0 ? prevBtn.current : nextBtn.current)) pendingFocus.current = (dir < 0 ? nextBtn : prevBtn).current;
    return true;
  };
  useEffect(() => {
    pendingFocus.current?.focus();
    pendingFocus.current = null;
  }, [page]);
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      const el = e.target instanceof Element ? e.target : null;
      // Fields, tabs, media and the zoomable scan use the arrow keys themselves.
      if (el?.closest("input, textarea, select, [contenteditable]:not([contenteditable=false]), [role=tablist], audio, video, .osd, dialog")) return;
      if (stepRef.current(e.key === "ArrowLeft" ? -1 : 1)) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!validId || item.error) {
    return (
      <div className="page">
        <h1>{t("notAvailable")}</h1>
        <ErrorState error={item.error ?? new ApiError(404, "Invalid item id")} retry={item.reload} notFound={t("pageNotFoundBody")} />
        <Link className="link-target" to="/search">{t("back")}</Link>
      </div>
    );
  }
  if (item.loading && !d) return <div className="page"><Loading center /></div>;
  if (!d) return null;

  const targetBoxes = page?.passages.find((p) => p.id === targetPassage)?.bboxes;
  const summary = d.summaries.find((s) => s.language === lang) ?? d.summaries.find((s) => s.language === "en");
  const pageLabel = page ? derivativeLabel(lang, page.derivative_label) : null;

  return (
    <div className="page">
      {item.offline && <div className="banner offline">{t("offlineBanner")}</div>}
      <header className="reader-head">
        <div>
          <h1><ContentText text={d.title} /></h1>
          <div className="meta">
            {d.date_text && <span><ContentText text={d.date_text} />{d.date_certainty !== "exact" ? ` (${t("dateApprox")})` : ""}</span>}
            {d.creator && <ContentText text={d.creator} />}
            <span>{t(`col_${d.collection}` as Key)}</span>
            {d.edition && <ContentText text={d.edition} />}
          </div>
          <div className="chips" style={{ marginTop: 8 }}>
            <FixtureChip show={d.is_fixture} />
            {d.online_only && <span className="chip">{t("onlineOnly")}</span>}
          </div>
        </div>
        <AddToList entry={{ item_id: d.id, title: d.title, citation: itemCitation(d) }} />
      </header>

      {summary && (
        <section className="sheet" aria-labelledby="sum-h" style={{ marginBottom: 20 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <h2 id="sum-h" style={{ margin: 0, fontSize: "var(--step-1)" }}>{t("summary")}</h2>
            <KindChip label={summary.label} />
          </div>
          <p style={{ margin: 0 }} lang={summary.language}>{summary.text}</p>
          {summary.label.startsWith("AI summary") && <p className="muted" style={{ margin: "8px 0 0", fontSize: "var(--step--1)" }}>{t("summaryAiNote")}</p>}
        </section>
      )}

      {page && (
        <>
          {missingPage && <p className="notice" role="status">{t("pageNotInItem", { n: pageParam })}</p>}
          {d.pages.length > 1 && (
            <nav className="pager-step" aria-label={t("pages")} style={{ marginBottom: 14 }}>
              <button ref={prevBtn} type="button" className="btn secondary step-btn prev" disabled={!prevPage} onClick={() => step(-1)}>
                <IconChevronLeft /><span>{t("prevPage")}</span>
              </button>
              <div className="pager">
                {d.pages.length > PAGER_CHIPS_MAX ? (
                  <>
                    <label htmlFor="page-select" className="visually-hidden">{t("pages")}</label>
                    <select id="page-select" value={page.sequence} onChange={(e) => goToPage(Number(e.target.value))}>
                      {d.pages.map((p) => <option key={p.id} value={p.sequence}>{t("page", { n: p.label })}</option>)}
                    </select>
                  </>
                ) : d.pages.map((p) => (
                  <button key={p.id} type="button" className="btn secondary small" aria-current={p.sequence === page.sequence ? "true" : undefined}
                    onClick={() => goToPage(p.sequence)}>
                    {t("page", { n: p.label })}
                  </button>
                ))}
              </div>
              <button ref={nextBtn} type="button" className="btn secondary step-btn next" disabled={!nextPage} onClick={() => step(1)}>
                <span>{t("nextPage")}</span><IconChevronRight />
              </button>
            </nav>
          )}
          <div className="reader">
            {page.image_file_id ? (
              <figure className="scan-pane" style={{ margin: 0 }}>
                <ScanViewer iiif={page.iiif} fileId={page.image_file_id} label={`${t("scan")}: ${d.title}, ${t("page", { n: page.label })}`} highlight={targetBoxes} />
                <figcaption className="caption">{t("scan")}, {t("page", { n: page.label })}</figcaption>
              </figure>
            ) : <div />}
            <section className="text-pane" aria-label={t("text")}>
              <div className="sheet">
                {hasReviewed && (
                  <div className="tabs" role="tablist" aria-label={t("text")}
                    onKeyDown={(e) => {
                      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
                      const next: Tab = tab === "original" ? "reviewed" : "original";
                      setTab(next);
                      document.getElementById(`tab-${next}`)?.focus();
                    }}>
                    <button type="button" role="tab" id="tab-original" aria-controls="text-panel" aria-selected={tab === "original"} tabIndex={tab === "original" ? 0 : -1}
                      onClick={() => setTab("original")} lang={pageLabel?.lang}>{pageLabel?.text}</button>
                    <button type="button" role="tab" id="tab-reviewed" aria-controls="text-panel" aria-selected={tab === "reviewed"} tabIndex={tab === "reviewed" ? 0 : -1}
                      onClick={() => setTab("reviewed")}>{t("reviewedTranslation")}</button>
                  </div>
                )}
                {!hasReviewed && <h2 style={{ fontSize: "var(--step-1)" }} lang={pageLabel?.lang}>{pageLabel?.text}</h2>}
                {d.photo && (
                  <dl className="facts" style={{ marginBottom: 14 }}>
                    <dt>{t("caption")}</dt><dd>{d.photo.caption}</dd>
                    {d.photo.photographer && (<><dt>{t("photographer")}</dt><dd>{d.photo.photographer}</dd></>)}
                    {d.photo.source_reference && (<><dt>{t("sourceReference")}</dt><dd>{d.photo.source_reference}</dd></>)}
                    {d.photo.credit && !d.photo.photographer && !d.photo.source_reference && (<><dt>{t("credit")}</dt><dd>{d.photo.credit}</dd></>)}
                    {d.photo.place && (<><dt>{t("place")}</dt><dd>{d.photo.place}</dd></>)}
                    {d.photo.event && (<><dt>{t("event")}</dt><dd>{d.photo.event}</dd></>)}
                    {(d.photo.date_text ?? d.date_text) && (<><dt>{t("date")}</dt><dd>{d.photo.date_text ?? d.date_text}</dd></>)}
                    {d.photo.people?.length > 0 && (<><dt>{t("people")}</dt><dd><FacetLinks facet="person" values={d.photo.people} /></dd></>)}
                    <dt>{t("rights")}</dt><dd>{d.rights_line}</dd>
                  </dl>
                )}
                <div className="stack" style={{ gap: 26 }} {...(hasReviewed ? { id: "text-panel", role: "tabpanel", "aria-labelledby": `tab-${tab}` } : {})}>
                  {page.passages.map((p) => (
                    <PassageBlock key={p.id} item={d} passage={p} citation={page.citation} page={page.sequence} tab={tab} target={p.id === targetPassage || Object.values(p.translations).some((x) => x.passage_id === targetPassage)} />
                  ))}
                </div>
                {page.articles?.length > 0 && <div style={{ marginTop: 20 }}><ArticleLinks articles={page.articles} /></div>}
              </div>
              <span className="cite">{t("citation")}: <ContentText text={page.citation} /></span>
            </section>
          </div>
        </>
      )}

      {d.media && <div style={{ marginTop: 20 }}><Media item={d} startMs={startMs} targetPassage={targetPassage} /></div>}

      <section className="sheet" aria-labelledby="prov-h" style={{ marginTop: 20 }}>
        <h2 id="prov-h" style={{ fontSize: "var(--step-1)" }}>{t("provenance")}</h2>
        <dl className="facts">
          <dt>{t("source")}</dt><dd>{d.source_institution}</dd>
          {d.publisher && (<><dt>{t("publisher")}</dt><dd>{d.publisher}</dd></>)}
          {d.volume && (<><dt>{t("volume")}</dt><dd>{d.volume}</dd></>)}
          {d.subjects?.length > 0 && (<><dt>{t("subjects")}</dt><dd><FacetLinks facet="subject" values={d.subjects} /></dd></>)}
          {d.people?.length > 0 && (<><dt>{t("people")}</dt><dd><FacetLinks facet="person" values={d.people} /></dd></>)}
          {d.places?.length > 0 && (<><dt>{t("places")}</dt><dd><FacetLinks facet="place" values={d.places} /></dd></>)}
          <dt>{t("rights")}</dt><dd>{d.rights_line}</dd>
          <dt>{t("version")}</dt><dd>{d.version}</dd>
        </dl>
      </section>

      {d.related.length > 0 && (
        <section aria-labelledby="rel-h" style={{ marginTop: 24 }}>
          <h2 id="rel-h" style={{ fontSize: "var(--step-1)" }}>{t("related")}</h2>
          <ul className="results">
            {d.related.map((r) => (
              <li key={r.id} className="result">
                <h3><Link to={`/item/${r.id}`}><ContentText text={r.title} /></Link></h3>
                <div className="meta">{r.date_text && <span>{r.date_text}</span>}<span>{t(`col_${r.collection}` as Key)}</span></div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

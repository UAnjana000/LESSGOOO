import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Hit, type ItemCard, type TimelineEvent } from "../api";
import type { Key } from "../i18n";
import { basketLink } from "../basket";
import { formatMs, useApi } from "../hooks";
import { useSession } from "../state";
import { ContentText, ErrorState, FixtureChip, LangText, LanguageSwitch, Loading, Page, pickText, useDocumentTitle } from "../components/Bits";
import { GraphView, getNodeColor } from "../components/GraphView";

const MAJOR_MILESTONE_YEARS = new Set([
  "1891", "1916", "1924", "1927", "1930", "1932", "1935",
  "1936", "1942", "1947", "1948", "1949", "1950", "1956", "1990"
]);

function isMilestoneEvent(e: TimelineEvent): boolean {
  const year = e.sort_date ? e.sort_date.substring(0, 4) : "";
  return MAJOR_MILESTONE_YEARS.has(year) || e.date_text.includes("1891") || e.date_text.includes("1950") || e.date_text.includes("1956");
}

export function Timeline() {
  const { t } = useSession();
  const tl = useApi<TimelineEvent[]>("/api/visitor/timeline");
  const [isDetailed, setIsDetailed] = useState(true);

  const displayedEvents = useMemo(() => {
    if (!tl.data) return [];
    if (isDetailed) return tl.data;

    // Filter to key landmark milestones when overview zoom is selected
    const milestones = tl.data.filter(isMilestoneEvent);
    return milestones.length >= 8 ? milestones : tl.data.filter((_, idx) => idx % 3 === 0);
  }, [tl.data, isDetailed]);

  return (
    <Page title={t("timelineTitle")}>
      {tl.loading && <Loading center />}
      {tl.error && <ErrorState error={tl.error} retry={tl.reload} />}
      {tl.data?.length === 0 && <p className="empty-state">{t("timelineEmpty")}</p>}
      {!!tl.data?.length && (
        <div className="timeline-wrap">
          <div className="timeline-toolbar">
            <span className="timeline-stats muted">
              {t("itemsCount", { n: displayedEvents.length })} {isDetailed ? `(${t("timelineZoomIn")})` : `(${t("timelineZoomOut")})`}
            </span>
            <div className="timeline-zoom-controls" role="group" aria-label={t("timelineTitle")}>
              <button
                type="button"
                className={`btn secondary small timeline-zoom-btn ${!isDetailed ? "active" : ""}`}
                onClick={() => setIsDetailed(false)}
                title={t("timelineZoomOut")}
                aria-pressed={!isDetailed}
                aria-label={t("timelineZoomOut")}
              >
                <span>−</span> {t("timelineZoomOut")}
              </button>
              <button
                type="button"
                className={`btn secondary small timeline-zoom-btn ${isDetailed ? "active" : ""}`}
                onClick={() => setIsDetailed(true)}
                title={t("timelineZoomIn")}
                aria-pressed={isDetailed}
                aria-label={t("timelineZoomIn")}
              >
                <span>+</span> {t("timelineZoomIn")}
              </button>
            </div>
          </div>

          <ol className="timeline">
            {displayedEvents.map((e) => {
              const isMilestone = isMilestoneEvent(e);
              const itemClasses = [
                e.date_certainty !== "exact" ? "approx" : "",
                !isMilestone ? "detailed-sub-event" : "milestone-event"
              ].filter(Boolean).join(" ");

              return (
                <li key={e.id} className={itemClasses || undefined}>
                  <div className="date">
                    {e.date_text}
                    {e.date_certainty !== "exact" && (
                      <span className="muted" style={{ font: "400 var(--step--1) var(--ui)", marginLeft: 10 }}>
                        {t("dateApprox")}
                      </span>
                    )}
                    {!isMilestone && (
                      <span className="sub-event-badge" style={{ font: "500 var(--step--2) var(--ui)", marginLeft: 8, padding: "1px 6px", borderRadius: 4, background: "#e8effc", color: "#365d9d", verticalAlign: "middle" }}>
                        {t("timelineDetailTag")}
                      </span>
                    )}
                  </div>
                  <h2 style={{ fontSize: isMilestone ? "var(--step-1)" : "var(--step-0)", margin: "4px 0" }}>
                    <LangText map={e.titles} />
                  </h2>
                  <p className="muted">
                    <LangText map={e.descriptions} />
                  </p>
                  <div className="row">
                    {e.items.map((it) => (
                      <Link key={it.id} className="btn secondary small" to={`/item/${it.id}`}>
                        <ContentText text={it.title} />
                      </Link>
                    ))}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </Page>
  );
}

export { Stories, Story } from "./Stories";

interface MapData {
  nodes: { id: number; type: string; labels: Record<string, string>; description: string | null; item_ids: number[] }[];
  edges: { id: number; from: number; to: number; relation: string }[];
}

const TYPE_ORDER = ["person", "organisation", "place", "event", "concept", "document"];

export function KnowledgeMap() {
  const { t, lang } = useSession();
  const m = useApi<MapData>("/api/visitor/map");
  const items = useApi<ItemCard[]>("/api/visitor/items");
  const titles = useMemo(() => new Map((items.data ?? []).map((i) => [i.id, i.title])), [items.data]);
  const [sel, setSel] = useState<number | null>(null);
  const [nameFilter, setNameFilter] = useState("");

  const selected = m.data?.nodes.find((n) => n.id === sel) ?? null;

  const byType = useMemo(() => {
    const out = new Map<string, MapData["nodes"]>();
    for (const n of m.data?.nodes ?? []) {
      const q = nameFilter.trim().toLowerCase();
      if (q) {
        const text = pickText(n.labels, lang).toLowerCase();
        if (!text.includes(q)) continue;
      }
      out.set(n.type, [...(out.get(n.type) ?? []), n]);
    }
    return [...out.entries()].sort(([a], [b]) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b));
  }, [m.data, nameFilter, lang]);

  const suggestedNodes = useMemo(() => {
    if (!m.data?.nodes.length) return [];
    return [...m.data.nodes]
      .sort((a, b) => (b.item_ids.length + (b.id === 25 ? 10 : 0)) - (a.item_ids.length + (a.id === 25 ? 10 : 0)))
      .slice(0, 4);
  }, [m.data?.nodes]);

  return (
    <Page title={t("mapTitle")} lead={t("mapLead")}>
      {(m.loading || (!m.data && items.loading)) && <Loading center />}
      {m.error && <ErrorState error={m.error} retry={m.reload} />}
      {items.error && <ErrorState error={items.error} retry={items.reload} />}
      {m.data?.nodes.length === 0 && <p className="empty-state">{t("mapEmpty")}</p>}
      {!!m.data?.nodes.length && (
        <div className="knowledge-map-layout">
          {/* Top Full-Width Interactive Obsidian/Logseq Graph Canvas */}
          <div className="map-wrap">
            <GraphView data={m.data} selectedId={sel} onSelectNode={setSel} />
          </div>

          {/* Bottom 2-Panel Layout: Inspector (Left) & Directory (Right) */}
          <div className="map-panels-grid">
            {/* Panel 1: Connection Inspector & Evidence */}
            <section className="map-panel map-inspector-panel" aria-live="polite">
              <div className="panel-header">
                <h2>{selected ? pickText(selected.labels, lang) : t("connectedTo")}</h2>
                <p className="panel-subtitle">{t("mapPick")}</p>
              </div>

              {!selected && (
                <div className="inspector-empty-state">
                  <div className="empty-icon" aria-hidden="true">🕸️</div>
                  <h3>{t("mapPick")}</h3>
                  <p className="muted">{t("mapPickLead")}</p>
                  {suggestedNodes.length > 0 && (
                    <div className="suggested-entities">
                      <span className="suggested-title">{t("mapSuggested")}</span>
                      <div className="chips">
                        {suggestedNodes.map((sn) => (
                          <button
                            key={sn.id}
                            type="button"
                            className="chip-link"
                            onClick={() => setSel(sn.id)}
                          >
                            <LangText map={sn.labels} />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {selected && (
                <div className="inspector-card">
                  <div className="inspector-title-row">
                    <div>
                      <h3 className="inspector-entity-title"><LangText map={selected.labels} /></h3>
                      <span
                        className="entity-type-badge"
                        style={{
                          backgroundColor: getNodeColor(selected.type).bg,
                          color: "#ffffff",
                        }}
                      >
                        {t(`node_${selected.type}` as Key)}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="btn quiet small close-selection-btn"
                      onClick={() => setSel(null)}
                      title={t("clearSelection")}
                      aria-label={t("clearSelection")}
                    >
                      ✕
                    </button>
                  </div>

                  {selected.description && <p className="inspector-desc"><ContentText text={selected.description} /></p>}

                  <div className="inspector-section">
                    <h4>{t("connectedTo")} ({m.data.edges.filter((e) => e.from === selected.id || e.to === selected.id).length})</h4>
                    <ul className="connected-list">
                      {m.data.edges
                        .filter((e) => e.from === selected.id || e.to === selected.id)
                        .map((e) => {
                          const other = m.data!.nodes.find((n) => n.id === (e.from === selected.id ? e.to : e.from));
                          if (!other) return null;
                          const otherColor = getNodeColor(other.type);
                          return (
                            <li key={e.id} className="connected-item">
                              <button
                                type="button"
                                className="btn quiet small connected-name-btn"
                                onClick={() => setSel(other.id)}
                              >
                                <span className="connected-dot" style={{ backgroundColor: otherColor.bg }} />
                                <LangText map={other.labels} />
                              </button>
                              <span className="relation-tag">
                                <ContentText text={e.relation.replace(/_/g, " ")} />
                              </span>
                            </li>
                          );
                        })}
                    </ul>
                  </div>

                  <div className="inspector-section">
                    <h4>{t("evidence")} ({selected.item_ids.length})</h4>
                    <div className="evidence-items-grid">
                      {selected.item_ids.map((id) => (
                        <Link key={id} className="evidence-card-link" to={`/item/${id}`}>
                          <span className="evidence-icon" aria-hidden="true">📄</span>
                          <span className="evidence-text">
                            {titles.has(id) ? <ContentText text={titles.get(id)} /> : t("openItem")}
                          </span>
                          <span className="evidence-arrow" aria-hidden="true">→</span>
                        </Link>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </section>

            {/* Panel 2: All Names on the Map (Directory) */}
            <section className="map-panel map-directory-panel" aria-labelledby="map-names-h">
              <div className="panel-header">
                <div className="panel-title-with-search">
                  <h2 id="map-names-h">{t("mapAllNames")}</h2>
                  <div className="directory-search">
                    <input
                      type="text"
                      placeholder={t("mapFilterPlaceholder")}
                      value={nameFilter}
                      onChange={(e) => setNameFilter(e.target.value)}
                      className="directory-search-input"
                      aria-label={t("mapFilterLabel")}
                    />
                    {nameFilter && (
                      <button
                        type="button"
                        className="directory-search-clear"
                        onClick={() => setNameFilter("")}
                        aria-label={t("clearFilters")}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="directory-groups">
                {byType.map(([type, nodes]) => {
                  const color = getNodeColor(type);
                  return (
                    <div key={type} role="group" aria-label={t(`node_${type}` as Key)} className="directory-category-card">
                      <div className="category-header">
                        <span className="category-indicator" style={{ backgroundColor: color.bg }} />
                        <span className="category-title">{t(`node_${type}` as Key)}</span>
                        <span className="category-count">{nodes.length}</span>
                      </div>
                      <div className="chips directory-chips">
                        {nodes.map((n) => (
                          <button
                            key={n.id}
                            type="button"
                            className="chip-link directory-chip"
                            aria-pressed={n.id === sel}
                            onClick={() => setSel(n.id === sel ? null : n.id)}
                          >
                            <span className="chip-dot" style={{ backgroundColor: color.bg }} />
                            <LangText map={n.labels} />
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          </div>
        </div>
      )}
    </Page>
  );
}

interface CollectionResult {
  token: string;
  url: string;
  expires_at: string;
  qr_svg: string;
  count: number;
}

export function Basket() {
  const s = useSession();
  const { t } = s;
  const [qr, setQr] = useState<CollectionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [making, setMaking] = useState(false);
  const [copied, setCopied] = useState(false);
  const hours = qr ? Math.round((Date.parse(qr.expires_at) - Date.now()) / 3_600_000) : 0;
  const make = async () => {
    setError(null);
    setMaking(true);
    try {
      const data = await api.post<CollectionResult>("/api/visitor/collections", {
        entries: s.basket.map((b) => ({ item_id: b.item_id, passage_id: b.passage_id, page: b.page, start_ms: b.start_ms })),
        language: s.lang,
        base_url: typeof window !== "undefined" ? window.location.origin : undefined,
      });
      setQr(data);
    } catch {
      setError(s.online ? t("errorGeneric") : t("qrOffline"));
    } finally {
      setMaking(false);
    }
  };

  const copyLink = async () => {
    if (!qr) return;
    const link = qr.url || `${window.location.origin}/c/${qr.token}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {}
  };

  return (
    <Page title={t("basketTitle")}>
      {s.basket.length === 0 && <p className="empty-state">{t("basketEmpty")}</p>}
      {s.basket.length > 0 && (
        <>
          <ul className="results screen-only">
            {s.basket.map((b) => (
              <li key={`${b.item_id}-${b.passage_id}-${b.page}-${b.start_ms}`} className="result">
                <div>
                  <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}><Link to={basketLink(b)}><ContentText text={b.title} /></Link></h2>
                  <span className="cite" style={{ marginTop: 6 }}>{b.citation}</span>
                </div>
                <button type="button" className="btn secondary small" onClick={() => s.removeFromBasket(b)}>
                  {t("remove")}<span className="visually-hidden">: {b.title}</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="row screen-only basket-actions-bar" style={{ marginTop: 20, gap: 12, flexWrap: "wrap" }}>
            <button type="button" className="btn primary" onClick={() => window.print()}>
              <span aria-hidden="true">📄 </span>
              {t("downloadBooklet")}
            </button>
            <button type="button" className="btn secondary" onClick={make} disabled={making}>
              {making ? <Loading inline size="sm" label={t("qrMaking")} /> : t("basketMakeQr")}
            </button>
          </div>
          <div role="status" className="screen-only">
            {qr && (
              <div className="qr-panel">
                <div className="qr" dangerouslySetInnerHTML={{ __html: qr.qr_svg }} role="img" aria-label={t("qrAlt")} />
                <div>
                  <p style={{ fontSize: "var(--step-1)" }}>{t("basketQrLead", { h: hours })}</p>
                  <p className="muted">{t("expires")}: {new Date(qr.expires_at).toLocaleString(`${s.lang}-IN`)}</p>
                  <div style={{ marginTop: 12, display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <a
                      href={qr.url || `/c/${qr.token}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn secondary small"
                    >
                      {t("openCollectionLink")}
                    </a>
                    <button type="button" className="btn quiet small" onClick={copyLink}>
                      {copied ? t("linkCopied") : t("copyLink")}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
          {error && <p className="notice bad screen-only" role="alert">{error}</p>}

          {/* Printable Memorial Booklet Guide */}
          <section className="memorial-booklet-sheet print-only" aria-label={t("memorialBookletSubtitle")}>
            <header className="booklet-header">
              <h1 className="booklet-institution">{t("memorialBookletHeader")}</h1>
              <p className="booklet-subtitle">{t("memorialBookletSubtitle")}</p>
              <div className="booklet-meta-grid">
                <div><span>{t("visitDate")}: </span><strong>{new Date().toLocaleDateString(`${s.lang}-IN`, { dateStyle: "long" })}</strong></div>
                <div><span>{t("sessionRef")}: </span><strong>#{s.sessionId.slice(0, 8)}</strong></div>
                <div><span>{t("itemsCount", { n: s.basket.length })}</span></div>
              </div>
            </header>

            <hr className="booklet-rule" />

            <div className="booklet-entries-list">
              {s.basket.map((b, idx) => (
                <article key={idx} className="booklet-entry">
                  <div className="booklet-entry-num">{(idx + 1).toString().padStart(2, "0")}</div>
                  <div className="booklet-entry-content">
                    <h2 className="booklet-entry-title">{b.title}</h2>
                    <span className="booklet-entry-cite">{b.citation}</span>
                  </div>
                </article>
              ))}
            </div>

            {qr && (
              <footer className="booklet-footer">
                <div className="booklet-qr" dangerouslySetInnerHTML={{ __html: qr.qr_svg }} />
                <p className="booklet-qr-note">{t("scanToView")}</p>
              </footer>
            )}
          </section>
        </>
      )}
    </Page>
  );
}

interface SharedCollection {
  expires_at: string;
  entries: { item: ItemCard; rights_line: string; passage: Hit | null; citation: string; deep_link: string; start_ms: number | null }[];
  removed_count: number;
}

export function SharedList() {
  const { token } = useParams();
  const { t, lang } = useSession();
  const c = useApi<SharedCollection>(`/api/visitor/collections/${token}`);
  useDocumentTitle(t("collectionTitle"));
  return (
    <main className="phone" id="main">
      <div className="phone-head">
        <LanguageSwitch className="langs phone-langs" />
      </div>
      <h1>{t("collectionTitle")}</h1>
      <p className="muted">{t("archiveName")}</p>
      {c.loading && <Loading center />}
      {c.error && (c.error.status === 410 ? <p className="notice bad" role="alert">{t("collectionExpired")}</p> : <ErrorState error={c.error} />)}
      {c.data && (
        <>
          {c.data.removed_count > 0 && <p className="notice">{t("collectionRemoved", { n: c.data.removed_count })}</p>}
          <ul className="results">
            {c.data.entries.map((e, i) => (
              <li key={i} className="result" style={{ gridTemplateColumns: "1fr" }}>
                <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}><Link to={e.deep_link}><ContentText text={e.item.title} /></Link></h2>
                {e.start_ms != null && <span className="meta">{t("atTime", { time: formatMs(e.start_ms) })}</span>}
                {e.passage && <blockquote lang={e.passage.language}>{e.passage.text}</blockquote>}
                <span className="cite">{t("citation")}: {e.citation}</span>
                <span className="muted" style={{ fontSize: "var(--step--1)" }}>{t("rights")}: {e.rights_line}</span>
                <FixtureChip show={e.item.is_fixture} />
              </li>
            ))}
          </ul>
          <p className="muted" style={{ marginTop: 16 }}>{t("expires")}: {new Date(c.data.expires_at).toLocaleString(`${lang}-IN`)}</p>
        </>
      )}
    </main>
  );
}
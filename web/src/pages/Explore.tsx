import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fileUrl, type Hit, type ItemCard, type TimelineEvent } from "../api";
import type { Key } from "../i18n";
import { basketLink } from "../basket";
import { formatMs, useApi } from "../hooks";
import { useSession } from "../state";
import { ContentText, ErrorState, FixtureChip, KindChip, LangText, LanguageSwitch, Loading, Page, pickText, useDocumentTitle, VerifiedChip } from "../components/Bits";

export function Timeline() {
  const { t } = useSession();
  const tl = useApi<TimelineEvent[]>("/api/visitor/timeline");
  return (
    <Page title={t("timelineTitle")}>
      {tl.loading && <Loading />}
      {tl.error && <ErrorState error={tl.error} retry={tl.reload} />}
      {tl.data && (
        <ol className="timeline">
          {tl.data.map((e) => (
            <li key={e.id} className={e.date_certainty !== "exact" ? "approx" : undefined}>
              <div className="date">
                {e.date_text}
                {e.date_certainty !== "exact" && <span className="muted" style={{ font: "400 var(--step--1) var(--ui)", marginLeft: 10 }}>{t("dateApprox")}</span>}
              </div>
              <h2 style={{ fontSize: "var(--step-1)", margin: "4px 0" }}><LangText map={e.titles} /></h2>
              <p className="muted"><LangText map={e.descriptions} /></p>
              <div className="row">
                {e.items.map((it) => (
                  <Link key={it.id} className="btn secondary small" to={`/item/${it.id}`}><ContentText text={it.title} /></Link>
                ))}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Page>
  );
}

export function Stories() {
  const { t } = useSession();
  const st = useApi<{ slug: string; titles: Record<string, string>; blocks: number }[]>("/api/visitor/stories");
  return (
    <Page title={t("storiesTitle")}>
      {st.loading && <Loading />}
      {st.error && <ErrorState error={st.error} retry={st.reload} />}
      {st.data && (
        <div className="story-strip">
          {st.data.map((s) => (
            <Link key={s.slug} to={`/stories/${s.slug}`} className="story-card">
              <LangText map={s.titles} />
              <span>{t("itemsCount", { n: s.blocks })}</span>
            </Link>
          ))}
        </div>
      )}
    </Page>
  );
}

interface StoryData {
  slug: string;
  titles: Record<string, string>;
  blocks: { item: ItemCard; captions: Record<string, string>; image_file_id: number | null; passage: Hit | null; citation: string; deep_link: string }[];
  narration_file_ids: Record<string, number>;
  narration_label: string;
}

export function Story() {
  const { slug } = useParams();
  const { t, lang } = useSession();
  const st = useApi<StoryData>(`/api/visitor/stories/${slug}`);
  const d = st.data;
  const narration = d?.narration_file_ids[lang] ?? d?.narration_file_ids.en;
  useDocumentTitle(d ? pickText(d.titles, lang) : t("storiesTitle"));
  return (
    <div className="page">
      {st.loading && <Loading />}
      {st.error && <ErrorState error={st.error} retry={st.reload} />}
      {d && (
        <>
          <h1><LangText map={d.titles} /></h1>
          {narration && (
            <div className="stack" style={{ gap: 4, maxWidth: 560 }}>
              <span className="muted">{t("listen")}: {t("synthNarration")}</span>
              <audio controls preload="none" src={fileUrl(narration)} aria-label={`${t("listen")}: ${t("synthNarration")}`} />
            </div>
          )}
          {d.blocks.map((b, i) => (
            <section key={i} className="story-block">
              <div>
                {b.image_file_id ? <img src={fileUrl(b.image_file_id)} alt={t("imageOf", { title: b.item.title })} loading="lazy" /> : null}
              </div>
              <div className="stack">
                <p style={{ fontSize: "var(--step-1)", fontFamily: "var(--read)" }}><LangText map={b.captions} /></p>
                {b.passage && (
                  <>
                    <div className="chips"><KindChip label={b.passage.kind_label} /><VerifiedChip verified={b.passage.quote_verified} /></div>
                    <blockquote className="passage" lang={b.passage.language} style={{ margin: 0 }}>{b.passage.text}</blockquote>
                  </>
                )}
                <span className="cite">{t("citation")}: {b.citation}</span>
                <div className="row">
                  <Link className="btn small" to={b.deep_link}>{t("openItem")}</Link>
                  <FixtureChip show={b.item.is_fixture} />
                </div>
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  );
}

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
  const layout = useMemo(() => {
    if (!m.data) return null;
    const W = 1100, H = 640, cx = W / 2, cy = H / 2;
    const groups = new Map<string, number[]>();
    for (const n of m.data.nodes) groups.set(n.type, [...(groups.get(n.type) ?? []), n.id]);
    const types = [...groups.keys()].sort((a, b) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b));
    const pos = new Map<number, { x: number; y: number }>();
    types.forEach((type, gi) => {
      const ids = groups.get(type)!;
      const base = (gi / types.length) * Math.PI * 2 - Math.PI / 2;
      const span = (Math.PI * 2) / types.length;
      ids.forEach((id, i) => {
        const a = base + span * ((i + 0.5) / ids.length) * 0.85;
        const r = 170 + (i % 2) * 95;
        pos.set(id, { x: cx + Math.cos(a) * r * 1.55, y: cy + Math.sin(a) * r });
      });
    });
    return { W, H, pos };
  }, [m.data]);
  const selected = m.data?.nodes.find((n) => n.id === sel) ?? null;
  const neighbours = new Set(m.data?.edges.flatMap((e) => (e.from === sel ? [e.to] : e.to === sel ? [e.from] : [])) ?? []);
  const byType = useMemo(() => {
    const out = new Map<string, MapData["nodes"]>();
    for (const n of m.data?.nodes ?? []) out.set(n.type, [...(out.get(n.type) ?? []), n]);
    return [...out.entries()].sort(([a], [b]) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b));
  }, [m.data]);

  return (
    <Page title={t("mapTitle")} lead={t("mapLead")}>
      {m.loading && <Loading />}
      {m.error && <ErrorState error={m.error} retry={m.reload} />}
      {m.data && layout && (
        <div className="reader">
          <div className="stack">
            {/* The drawing is a pointer shortcut; the name list below is the keyboard, screen-reader and 48 px equivalent. */}
            <div className="map-wrap" aria-hidden="true">
              <svg viewBox={`0 0 ${layout.W} ${layout.H}`} focusable="false">
                {m.data.edges.map((e) => {
                  const a = layout.pos.get(e.from)!, b = layout.pos.get(e.to)!;
                  return <line key={e.id} className={`map-edge${e.from === sel || e.to === sel ? " sel" : ""}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
                })}
                {m.data.nodes.map((n) => {
                  const p = layout.pos.get(n.id)!;
                  const dim = sel !== null && n.id !== sel && !neighbours.has(n.id);
                  return (
                    <g key={n.id} className={`map-node${n.id === sel ? " sel" : ""}${dim ? " dim" : ""}`} transform={`translate(${p.x},${p.y})`}
                      onClick={() => setSel(n.id === sel ? null : n.id)}>
                      <circle className="hit" r={24} />
                      <circle r={n.type === "person" ? 13 : 10} />
                      <text x={18} y={6}>{pickText(n.labels, lang)}</text>
                    </g>
                  );
                })}
              </svg>
            </div>
            <section aria-labelledby="map-names-h">
              <h2 id="map-names-h" style={{ fontSize: "var(--step-1)" }}>{t("mapAllNames")}</h2>
              {byType.map(([type, nodes]) => (
                <div key={type} role="group" aria-label={t(`node_${type}` as Key)} className="stack" style={{ gap: 6, marginBottom: 12 }}>
                  <span className="muted" style={{ fontSize: "var(--step--1)" }} aria-hidden="true">{t(`node_${type}` as Key)}</span>
                  <div className="chips">
                    {nodes.map((n) => (
                      <button key={n.id} type="button" className="chip-link" aria-pressed={n.id === sel} onClick={() => setSel(n.id === sel ? null : n.id)}>
                        <LangText map={n.labels} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </section>
          </div>
          <aside className="sheet" aria-live="polite">
            {!selected && <p className="muted">{t("mapPick")}</p>}
            {selected && (
              <div className="stack">
                <h2 style={{ fontSize: "var(--step-2)" }}><LangText map={selected.labels} /></h2>
                <span className="chip">{t(`node_${selected.type}` as Key)}</span>
                {selected.description && <p><ContentText text={selected.description} /></p>}
                <h3>{t("connectedTo")}</h3>
                <ul>
                  {m.data.edges.filter((e) => e.from === selected.id || e.to === selected.id).map((e) => {
                    const other = m.data!.nodes.find((n) => n.id === (e.from === selected.id ? e.to : e.from));
                    return (
                      <li key={e.id}>
                        <button type="button" className="btn quiet small" onClick={() => setSel(other!.id)}><LangText map={other!.labels} /></button>
                        <span className="muted"> (<ContentText text={e.relation.replace(/_/g, " ")} />)</span>
                      </li>
                    );
                  })}
                </ul>
                <h3>{t("evidence")}</h3>
                <div className="row">
                  {selected.item_ids.map((id) => <Link key={id} className="btn secondary small" to={`/item/${id}`}>{titles.has(id) ? <ContentText text={titles.get(id)} /> : t("openItem")}</Link>)}
                </div>
              </div>
            )}
          </aside>
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
  const hours = qr ? Math.round((Date.parse(qr.expires_at) - Date.now()) / 3_600_000) : 0;
  const make = async () => {
    setError(null);
    setMaking(true);
    try {
      const res = await fetch("/api/visitor/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: s.basket.map((b) => ({ item_id: b.item_id, passage_id: b.passage_id, page: b.page, start_ms: b.start_ms })), language: s.lang }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setQr(await res.json());
    } catch {
      setError(s.online ? t("errorGeneric") : t("qrOffline"));
    } finally {
      setMaking(false);
    }
  };
  return (
    <Page title={t("basketTitle")}>
      {s.basket.length === 0 && <p className="empty-state">{t("basketEmpty")}</p>}
      {s.basket.length > 0 && (
        <>
          <ul className="results">
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
          <div className="row" style={{ marginTop: 20 }}>
            <button type="button" className="btn" onClick={make} disabled={making}>{making ? t("qrMaking") : t("basketMakeQr")}</button>
          </div>
          <div role="status">
            {qr && (
              <div className="qr-panel">
                <div className="qr" dangerouslySetInnerHTML={{ __html: qr.qr_svg }} role="img" aria-label={t("qrAlt")} />
                <div>
                  <p style={{ fontSize: "var(--step-1)" }}>{t("basketQrLead", { h: hours })}</p>
                  <p className="muted">{t("expires")}: {new Date(qr.expires_at).toLocaleString(`${s.lang}-IN`)}</p>
                </div>
              </div>
            )}
          </div>
          {error && <p className="notice bad" role="alert">{error}</p>}
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
      {c.loading && <Loading />}
      {c.error && (c.error.status === 410 ? <p className="notice">{t("collectionExpired")}</p> : <ErrorState error={c.error} />)}
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
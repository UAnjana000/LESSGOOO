import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fileUrl, type Facets, type Hit, type ItemCard } from "../api";
import { LANGS, type Key } from "../i18n";
import { formatMs, useApi } from "../hooks";
import { useSession } from "../state";
import { browsePath, hasFilters, ITEM_TYPES, MAX_QUERY, searchPath } from "../filters";
import { AddToList, ArticleLinks, ContentText, ErrorState, FixtureChip, KindChip, Loading, useDocumentTitle, VerifiedChip } from "../components/Bits";

const langName = (code: string) => LANGS.find((l) => l.code === code)?.name ?? code.toUpperCase();

const COLLECTIONS = ["writings", "speeches", "debates", "manuscripts", "photographs", "audio_video"];

function FacetSelect({ label, all, options, value, onChange }: { label: string; all: string; options: string[]; value: string; onChange: (v: string) => void }) {
  if (!options.length && !value) return null;
  const opts = value && !options.includes(value) ? [value, ...options] : options;
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{all}</option>
        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

// Words worth marking in a result: the query's own words, minus the framing ones every passage contains.
const QUERY_FILLER = new Set(["what", "which", "when", "where", "who", "why", "how", "did", "does", "the", "and", "for", "about", "say", "said", "with", "from", "that", "this", "was", "were", "are"]);
function queryTerms(q: string): string[] {
  return [...new Set((q.toLowerCase().match(/[\p{L}\p{M}\p{N}]+/gu) ?? []).filter((w) => w.length > 2 && !QUERY_FILLER.has(w)))];
}

/** The passage with the visitor's search words marked, so they can see why it matched. */
function Highlighted({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>;
  const escaped = terms.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "giu"));
  return <>{parts.map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : p))}</>;
}

function HitCard({ h, terms = [] }: { h: Hit; terms?: string[] }) {
  const { t } = useSession();
  const isPhoto = h.extra?.item_type === "photograph";
  const subjects = h.extra?.subjects ?? [];
  return (
    <li className="result" style={{ position: "relative" }}>
      <div>
        <h2 style={{ fontSize: "var(--step-1)", margin: "0 0 4px" }}>
          <Link to={h.deep_link}>
            <ContentText text={h.title} />
          </Link>
        </h2>
        <div className="meta" style={{ rowGap: "4px" }}>
          {h.extra?.creator && <span style={{ fontWeight: 600, color: "var(--ink)" }}>{h.extra.creator}</span>}
          {h.extra?.date_text && <span>{h.extra.date_text}</span>}
          <span>{t(`col_${h.collection}` as Key)}</span>
          {h.extra?.volume && <span>{h.extra.volume}</span>}
          {h.page_sequence != null && <span>p. {h.extra?.page_label ?? h.page_sequence}</span>}
          <span lang={h.language}>{langName(h.language)}</span>
          {h.start_ms != null && <span>{t("atTime", { time: formatMs(h.start_ms) })}</span>}
        </div>
      </div>
      <div className="chips" style={{ justifyContent: "flex-end", alignSelf: "flex-start" }}>
        <KindChip label={h.kind_label} />
        <VerifiedChip verified={h.quote_verified} />
        <FixtureChip show={h.extra?.is_fixture} />
      </div>

      <blockquote lang={h.language} style={{ borderLeft: "3px solid var(--indigo)", paddingLeft: "14px", margin: "8px 0" }}>
        <Highlighted text={h.text} terms={terms} />
      </blockquote>

      {subjects.length > 0 && (
        <div className="chips" style={{ gridColumn: "1 / -1", gap: "4px" }}>
          {subjects.slice(0, 4).map((s) => (
            <span key={s} className="chip" style={{ fontSize: "0.75rem", padding: "1px 8px", minHeight: "22px" }}>
              #{s}
            </span>
          ))}
        </div>
      )}

      {isPhoto && (h.extra.credit || h.extra.rights_line) && (
        <dl className="facts" style={{ gridColumn: "1 / -1" }}>
          {h.extra.credit && (<><dt>{t("credit")}</dt><dd>{h.extra.credit}</dd></>)}
          {h.extra.rights_line && (<><dt>{t("rights")}</dt><dd>{h.extra.rights_line}</dd></>)}
        </dl>
      )}

      <span className="cite" style={{ gridColumn: "1 / -1" }}>
        {t("citation")}: <ContentText text={h.citation} />
      </span>

      {(h.extra?.articles?.length ?? 0) > 0 && (
        <div style={{ gridColumn: "1 / -1" }}>
          <ArticleLinks articles={h.extra.articles} />
        </div>
      )}

      <div className="row" style={{ gridColumn: "1 / -1", marginTop: "4px" }}>
        <Link className="btn small" to={h.deep_link}>
          {t("openItem")}
        </Link>
        <AddToList
          entry={{
            item_id: h.item_id,
            title: h.title,
            passage_id: h.passage_id,
            page: h.page_sequence ?? undefined,
            start_ms: h.start_ms ?? undefined,
            citation: h.citation,
            snippet: h.text,
          }}
        />
      </div>
    </li>
  );
}

function ItemCardView({ it }: { it: ItemCard }) {
  const { t } = useSession();
  const photo = it.photo;
  const subjects = it.subjects ?? [];
  return (
    <li className="result">
      <div className={photo ? "thumb-row" : undefined}>
        {photo?.image_file_id != null && (
          <img
            className="thumb"
            src={fileUrl(photo.image_file_id)}
            alt={photo.caption}
            loading="lazy"
            decoding="async"
            width={128}
            height={96}
          />
        )}
        <div style={{ minWidth: 0 }}>
          <h2 style={{ fontSize: "var(--step-1)", margin: "0 0 4px" }}>
            <Link to={`/item/${it.id}`}>
              <ContentText text={it.title} />
            </Link>
          </h2>
          <div className="meta" style={{ rowGap: "4px" }}>
            {it.creator && <span style={{ fontWeight: 600, color: "var(--ink)" }}><ContentText text={it.creator} /></span>}
            {it.date_text && <ContentText text={it.date_text} />}
            <span>{t(`col_${it.collection}` as Key)}</span>
            {it.volume && <span>{it.volume}</span>}
            {it.edition && <span>{it.edition}</span>}
          </div>
          {photo && <p className="card-caption">{photo.caption}</p>}
          {photo?.credit && (
            <p className="muted" style={{ margin: "4px 0 0", fontSize: "var(--step--1)" }}>
              {t("credit")}: {photo.credit}
            </p>
          )}
          {subjects.length > 0 && (
            <div className="chips" style={{ marginTop: "6px", gap: "4px" }}>
              {subjects.slice(0, 4).map((s) => (
                <span key={s} className="chip" style={{ fontSize: "0.75rem", padding: "1px 8px", minHeight: "22px" }}>
                  #{s}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="chips" style={{ justifyContent: "flex-end", alignSelf: "flex-start" }}>
        <FixtureChip show={it.is_fixture} />
        {it.online_only && <span className="chip">{t("onlineOnlyShort")}</span>}
      </div>
    </li>
  );
}

export function Search() {
  const { t } = useSession();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);

  const searchUrl = searchPath(params);
  const search = useApi<{ results: Hit[]; info?: { cross_language?: boolean } }>(searchUrl);
  const browse = useApi<ItemCard[]>(searchUrl ? null : browsePath(params));
  const facets = useApi<Facets>("/api/visitor/facets");

  // Each query and filter change is its own history entry, so Back returns to the previous results.
  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (next.toString() !== params.toString()) setParams(next);
  };
  const clearFilters = () => setParams(q ? { q } : {});
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setFilter("q", draft.trim());
  };

  const collection = params.get("collection");
  const title = !searchUrl && collection ? t(`col_${collection}` as Key) : t("navSearch");
  useDocumentTitle(q ? `${q} — ${title}` : title);

  return (
    <div className="page">
      <h1>{title}</h1>
      <form className="searchbar" role="search" onSubmit={submit}>
        <label htmlFor="q" className="visually-hidden">
          {t("searchPlaceholder")}
        </label>
        <input id="q" type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("searchPlaceholder")} autoComplete="off" enterKeyHint="search" maxLength={MAX_QUERY} />
        <button type="submit" className="btn">
          {t("searchButton")}
        </button>
      </form>
      <fieldset className="filters" style={{ border: 0, padding: 0 }}>
        <legend className="visually-hidden">{t("filters")}</legend>
        <label>
          {t("collections")}
          <select value={collection ?? ""} onChange={(e) => setFilter("collection", e.target.value)}>
            <option value="">{t("allCollections")}</option>
            {COLLECTIONS.map((c) => (
              <option key={c} value={c}>
                {t(`col_${c}` as Key)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("itemType")}
          <select value={params.get("item_type") ?? ""} onChange={(e) => setFilter("item_type", e.target.value)}>
            <option value="">{t("allTypes")}</option>
            {ITEM_TYPES.map((it) => (
              <option key={it} value={it}>{t(`type_${it}` as Key)}</option>
            ))}
          </select>
        </label>
        <label>
          {t("language")}
          <select value={params.get("lang") ?? ""} onChange={(e) => setFilter("lang", e.target.value)}>
            <option value="">{t("allLanguages")}</option>
            {LANGS.map((l) => <option key={l.code} value={l.code} lang={l.code}>{l.name}</option>)}
          </select>
        </label>
        <FacetSelect label={t("subject")} all={t("allSubjects")} options={facets.data?.subjects ?? []} value={params.get("subject") ?? ""} onChange={(v) => setFilter("subject", v)} />
        <FacetSelect label={t("person")} all={t("allPeople")} options={facets.data?.people ?? []} value={params.get("person") ?? ""} onChange={(v) => setFilter("person", v)} />
        <FacetSelect label={t("place")} all={t("allPlaces")} options={facets.data?.places ?? []} value={params.get("place") ?? ""} onChange={(v) => setFilter("place", v)} />
        {searchUrl && (
          <>
            <label>
              {t("dateFrom")}
              <input type="date" value={params.get("date_from") ?? ""} max={params.get("date_to") ?? undefined} onChange={(e) => setFilter("date_from", e.target.value)} />
            </label>
            <label>
              {t("dateTo")}
              <input type="date" value={params.get("date_to") ?? ""} min={params.get("date_from") ?? undefined} onChange={(e) => setFilter("date_to", e.target.value)} />
            </label>
          </>
        )}
        {hasFilters(params) && (
          <button type="button" className="btn secondary" style={{ alignSelf: "end" }} onClick={clearFilters}>
            {t("clearFilters")}
          </button>
        )}
      </fieldset>

      {searchUrl && search.loading && <Loading label={t("searching")} center />}
      {searchUrl && search.error && <ErrorState error={search.error} retry={search.reload} />}
      {searchUrl && search.data && (
        <>
          <p role="status" className="muted">
            {search.data.results.length ? t("results", { n: search.data.results.length }) : hasFilters(params) ? t("noResultsFiltered") : t("noResults", { q })}
          </p>
          {search.data.info?.cross_language && search.data.results.length > 0 && (
            <p className="notice">{t("crossLanguageResults")}</p>
          )}
          <ul className="results">
            {search.data.results.map((h) => <HitCard key={h.passage_id} h={h} terms={queryTerms(q)} />)}
          </ul>
        </>
      )}

      {!searchUrl && browse.loading && <Loading center />}
      {!searchUrl && browse.error && <ErrorState error={browse.error} retry={browse.reload} />}
      {!searchUrl && browse.data && (
        <ul className="results">
          {browse.data.length === 0 && <li className="empty-state">{t("collectionEmpty")}</li>}
          {browse.data.map((it) => <ItemCardView key={it.id} it={it} />)}
        </ul>
      )}
    </div>
  );
}

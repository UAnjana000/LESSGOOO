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

function HitCard({ h }: { h: Hit }) {
  const { t } = useSession();
  const isPhoto = h.extra?.item_type === "photograph";
  return (
    <li className="result">
      <div>
        <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}><Link to={h.deep_link}><ContentText text={h.title} /></Link></h2>
        <div className="meta">
          <span>{t(`col_${h.collection}` as Key)}</span>
          <span lang={h.language}>{langName(h.language)}</span>
          {h.start_ms != null && <span>{t("atTime", { time: formatMs(h.start_ms) })}</span>}
        </div>
      </div>
      <div className="chips" style={{ justifyContent: "flex-end" }}>
        <KindChip label={h.kind_label} />
        <VerifiedChip verified={h.quote_verified} />
        <FixtureChip show={h.extra?.is_fixture} />
      </div>
      <blockquote lang={h.language}>{h.text}</blockquote>
      {isPhoto && (h.extra.credit || h.extra.rights_line) && (
        <dl className="facts" style={{ gridColumn: "1 / -1" }}>
          {h.extra.credit && (<><dt>{t("credit")}</dt><dd>{h.extra.credit}</dd></>)}
          {h.extra.rights_line && (<><dt>{t("rights")}</dt><dd>{h.extra.rights_line}</dd></>)}
        </dl>
      )}
      <span className="cite" style={{ gridColumn: "1 / -1" }}>
        {t("citation")}: <ContentText text={h.citation} />
      </span>
      {(h.extra?.articles?.length ?? 0) > 0 && <div style={{ gridColumn: "1 / -1" }}><ArticleLinks articles={h.extra.articles} /></div>}
      <div className="row" style={{ gridColumn: "1 / -1" }}>
        <Link className="btn small" to={h.deep_link}>
          {t("openItem")}
        </Link>
        <AddToList
          entry={{ item_id: h.item_id, title: h.title, passage_id: h.passage_id, page: h.page_sequence ?? undefined, start_ms: h.start_ms ?? undefined, citation: h.citation }}
        />
      </div>
    </li>
  );
}

function ItemCardView({ it }: { it: ItemCard }) {
  const { t } = useSession();
  const photo = it.photo;
  return (
    <li className="result">
      <div className={photo ? "thumb-row" : undefined}>
        {photo?.image_file_id != null && (
          <img className="thumb" src={fileUrl(photo.image_file_id)} alt={photo.caption} loading="lazy" decoding="async" width={128} height={96} />
        )}
        <div style={{ minWidth: 0 }}>
          <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}><Link to={`/item/${it.id}`}><ContentText text={it.title} /></Link></h2>
          <div className="meta">
            {it.date_text && <ContentText text={it.date_text} />}
            {it.creator && <ContentText text={it.creator} />}
            <span>{t(`col_${it.collection}` as Key)}</span>
          </div>
          {photo && <p className="card-caption">{photo.caption}</p>}
          {photo?.credit && <p className="muted" style={{ margin: "4px 0 0", fontSize: "var(--step--1)" }}>{t("credit")}: {photo.credit}</p>}
        </div>
      </div>
      <div className="chips" style={{ justifyContent: "flex-end" }}>
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
  const search = useApi<{ results: Hit[] }>(searchUrl);
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

      {searchUrl && search.loading && <p role="status">{t("searching")}</p>}
      {searchUrl && search.error && <ErrorState error={search.error} retry={search.reload} />}
      {searchUrl && search.data && (
        <>
          <p role="status" className="muted">
            {search.data.results.length ? t("results", { n: search.data.results.length }) : hasFilters(params) ? t("noResultsFiltered") : t("noResults", { q })}
          </p>
          <ul className="results">
            {search.data.results.map((h) => <HitCard key={h.passage_id} h={h} />)}
          </ul>
        </>
      )}

      {!searchUrl && browse.loading && <Loading />}
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

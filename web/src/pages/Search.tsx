import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { Hit, ItemCard } from "../api";
import { LANGS, type Key } from "../i18n";
import { useApi } from "../hooks";
import { useSession } from "../state";
import { AddToList, ErrorState, FixtureChip, KindChip, Loading, VerifiedChip } from "../components/Bits";

const COLLECTIONS = ["writings", "speeches", "debates", "manuscripts", "photographs", "audio_video"];

export function Search() {
  const { t } = useSession();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);

  const filterKeys = ["collection", "lang", "date_from", "date_to"] as const;
  const qs = new URLSearchParams();
  if (q) qs.set("q", q);
  for (const k of filterKeys) if (params.get(k)) qs.set(k, params.get(k)!);

  const search = useApi<{ results: Hit[] }>(q ? `/api/visitor/search?${qs}` : null);
  const browse = useApi<ItemCard[]>(!q ? `/api/visitor/items${params.get("collection") ? `?collection=${params.get("collection")}` : ""}` : null);

  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setFilter("q", draft.trim());
  };

  const collection = params.get("collection");
  const title = !q && collection ? t(`col_${collection}` as Key) : t("navSearch");

  return (
    <div className="page">
      <h1>{title}</h1>
      <form className="searchbar" role="search" onSubmit={submit}>
        <label htmlFor="q" className="visually-hidden">
          {t("searchPlaceholder")}
        </label>
        <input id="q" type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("searchPlaceholder")} autoComplete="off" enterKeyHint="search" />
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
        {q && (
          <>
            <label>
              {t("language")}
              <select value={params.get("lang") ?? ""} onChange={(e) => setFilter("lang", e.target.value)}>
                <option value="">{t("allLanguages")}</option>
                <option value="en">English</option>
                <option value="hi">{LANGS[1].name}</option>
                <option value="mr">{LANGS[2].name}</option>
              </select>
            </label>
            <label>
              {t("dateFrom")}
              <input type="date" value={params.get("date_from") ?? ""} onChange={(e) => setFilter("date_from", e.target.value)} />
            </label>
            <label>
              {t("dateTo")}
              <input type="date" value={params.get("date_to") ?? ""} onChange={(e) => setFilter("date_to", e.target.value)} />
            </label>
          </>
        )}
      </fieldset>

      {q && search.loading && <p role="status">{t("searching")}</p>}
      {q && search.error && <ErrorState error={search.error} retry={search.reload} />}
      {q && search.data && (
        <>
          <p role="status" className="muted">
            {search.data.results.length ? t("results", { n: search.data.results.length }) : t("noResults", { q })}
          </p>
          <ul className="results">
            {search.data.results.map((h) => (
              <li key={h.passage_id} className="result">
                <div>
                  <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}><Link to={h.deep_link}>{h.title}</Link></h2>
                  <div className="meta">
                    <span>{t(`col_${h.collection}` as Key)}</span>
                    <span lang={h.language}>{h.language.toUpperCase()}</span>
                  </div>
                </div>
                <div className="chips" style={{ justifyContent: "flex-end" }}>
                  <KindChip label={h.kind_label} />
                  <VerifiedChip verified={h.quote_verified} />
                  <FixtureChip show={h.extra?.is_fixture} />
                </div>
                <blockquote lang={h.language}>{h.text}</blockquote>
                <span className="cite" style={{ gridColumn: "1 / -1" }}>
                  {t("citation")}: {h.citation}
                </span>
                <div className="row" style={{ gridColumn: "1 / -1" }}>
                  <Link className="btn small" to={h.deep_link}>
                    {t("openItem")}
                  </Link>
                  <AddToList
                    entry={{ item_id: h.item_id, title: h.title, passage_id: h.passage_id, page: h.page_sequence ?? undefined, start_ms: h.start_ms ?? undefined, citation: h.citation }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {!q && browse.loading && <Loading />}
      {!q && browse.error && <ErrorState error={browse.error} retry={browse.reload} />}
      {!q && browse.data && (
        <ul className="results">
          {browse.data.length === 0 && <li className="empty-state">{t("collectionEmpty")}</li>}
          {browse.data.map((it) => (
            <li key={it.id} className="result">
              <div>
                <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}><Link to={`/item/${it.id}`}>{it.title}</Link></h2>
                <div className="meta">
                  {it.date_text && <span>{it.date_text}</span>}
                  {it.creator && <span>{it.creator}</span>}
                  <span>{t(`col_${it.collection}` as Key)}</span>
                </div>
              </div>
              <div className="chips" style={{ justifyContent: "flex-end" }}>
                <FixtureChip show={it.is_fixture} />
                {it.online_only && <span className="chip">{t("onlineOnlyShort")}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

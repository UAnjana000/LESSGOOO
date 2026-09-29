import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Key } from "../i18n";
import { useApi } from "../hooks";
import { useSession } from "../state";
import { MAX_QUERY } from "../filters";
import { ErrorState, LangText, Loading, useDocumentTitle } from "../components/Bits";

interface HomeData {
  collections: { key: string; count: number }[];
  stories: { slug: string; titles: Record<string, string> }[];
}

const TAB_OFFSETS = ["-2px", "22%", "48%", "8%", "34%", "60%"];

export function Home() {
  const { t } = useSession();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const home = useApi<HomeData>("/api/visitor/home");
  useDocumentTitle(null);

  const go = (mode: "search" | "ask") => (e?: FormEvent) => {
    e?.preventDefault();
    const v = q.trim();
    if (!v) return;
    nav(mode === "search" ? `/search?q=${encodeURIComponent(v)}` : `/ask?q=${encodeURIComponent(v)}`);
  };

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>{t("archiveName")}</h1>
          <p className="lead">{t("homeLead")}</p>
        </div>
        <form className="bigsearch" role="search" onSubmit={go("search")}>
          <label htmlFor="home-q" className="visually-hidden">
            {t("searchPlaceholder")}
          </label>
          <input id="home-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("searchPlaceholder")} autoComplete="off" enterKeyHint="search" maxLength={MAX_QUERY} />
          <div className="row">
            <button type="submit" className="btn" style={{ flex: 1 }}>
              {t("searchButton")}
            </button>
            <button type="button" className="btn secondary" style={{ flex: 1 }} onClick={go("ask")}>
              {t("askButton")}
            </button>
          </div>
        </form>
      </section>

      <h2 className="visually-hidden">{t("collections")}</h2>
      {home.loading && <Loading />}
      {home.error && <ErrorState error={home.error} retry={home.reload} />}
      {home.data && (
        <ul className="drawers">
          {home.data.collections.map((c, i) => {
            const name = t(`col_${c.key}` as Key);
            return (
              <li key={c.key}>
                <Link
                  to={`/search?collection=${c.key}`}
                  className={`drawer${c.count === 0 ? " empty" : ""}`}
                  data-tab={String(i + 1).padStart(2, "0")}
                  style={{ ["--tab-offset" as string]: TAB_OFFSETS[i % TAB_OFFSETS.length] }}
                >
                  <h3>{name}</h3>
                  <span className="count">{t("itemsCount", { n: c.count })}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {home.data && home.data.stories.length > 0 && (
        <section aria-labelledby="stories-h">
          <h2 id="stories-h">{t("stories")}</h2>
          <div className="story-strip">
            {home.data.stories.map((st) => (
              <Link key={st.slug} to={`/stories/${st.slug}`} className="story-card">
                <LangText map={st.titles} />
                <span>{t("navStories")}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

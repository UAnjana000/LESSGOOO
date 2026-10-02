import { Link, useParams } from "react-router-dom";
import type { ConstitutionArticle, ConstitutionDetail } from "../api";
import { useApi } from "../hooks";
import { clipSnippet } from "../basket";
import { useSession } from "../state";
import { AddToList, ContentText, ErrorState, FixtureChip, KindChip, LangText, Loading, Page, useDocumentTitle, VerifiedChip } from "../components/Bits";

export function Constitution() {
  const { t } = useSession();
  const list = useApi<ConstitutionArticle[]>("/api/visitor/constitution");
  return (
    <Page title={t("constitutionTitle")} lead={t("constitutionLead")}>
      <p className="notice">{t("constitutionCurated")}</p>
      {list.loading && <Loading center />}
      {list.error && <ErrorState error={list.error} retry={list.reload} />}
      {list.data && (
        <ul className="results">
          {list.data.length === 0 && (
            <li className="empty-state constitution-empty">
              <p>{t("constitutionEmpty")}</p>
              <p className="muted">{t("constitutionNextSteps")}</p>
              <div className="row" style={{ justifyContent: "center", gap: 12, flexWrap: "wrap" }}>
                <Link className="btn" to="/search?q=constitution">{t("constitutionSearchLink")}</Link>
                <Link className="btn secondary" to="/search?collection=debates">{t("constitutionDebatesLink")}</Link>
              </div>
            </li>
          )}
          {list.data.map((a) => (
            <li key={a.number} className="result">
              <div>
                <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}>
                  <Link to={`/constitution/${encodeURIComponent(a.number)}`}>{t("article", { n: a.number })}</Link>
                </h2>
                <p style={{ margin: "4px 0 0", fontFamily: "var(--read)" }}><LangText map={a.titles} /></p>
                {a.part && <div className="meta"><ContentText text={a.part} /></div>}
              </div>
              <div className="chips" style={{ justifyContent: "flex-end" }}>
                <span className="chip">{t("debatesCount", { n: a.debates })}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}

export function ConstitutionArticlePage() {
  const { number = "" } = useParams();
  const { t } = useSession();
  const art = useApi<ConstitutionDetail>(`/api/visitor/constitution/${encodeURIComponent(number)}`);
  const d = art.data;
  useDocumentTitle(t("article", { n: number }));
  return (
    <div className="page">
      <p><Link className="link-target" to="/constitution">{t("allArticles")}</Link></p>
      {art.loading && !d && <Loading center />}
      {art.error && (
        <>
          <h1>{t("article", { n: number })}</h1>
          <ErrorState error={art.error} retry={art.reload} notFound={t("articleNotFound")} />
        </>
      )}
      {d && (
        <>
          <h1>
            {t("article", { n: d.number })}
            <span style={{ display: "block", fontSize: "var(--step-1)", fontWeight: 400, marginTop: 6 }}><LangText map={d.titles} /></span>
          </h1>
          {d.part && <div className="meta" style={{ marginBottom: 12 }}><ContentText text={d.part} /></div>}
          <p className="notice">{t("constitutionCurated")}</p>
          <ul className="results">
            {d.entries.map((e) => (
              <li key={e.link_id} className="result">
                <div>
                  <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}><Link to={e.deep_link}><ContentText text={e.item.title} /></Link></h2>
                  <div className="meta">
                    {e.item.date_text && <ContentText text={e.item.date_text} />}
                    {e.item.volume && <ContentText text={e.item.volume} />}
                  </div>
                </div>
                <div className="chips" style={{ justifyContent: "flex-end" }}>
                  {e.passage && <KindChip label={e.passage.kind_label} />}
                  {e.passage && <VerifiedChip verified={e.passage.quote_verified} />}
                  <FixtureChip show={e.item.is_fixture} />
                </div>
                {e.passage && <blockquote lang={e.passage.language}>{e.passage.text}</blockquote>}
                {e.note && (
                  <p style={{ gridColumn: "1 / -1", margin: 0 }}>
                    <span className="muted">{t("curatorNote")}: </span><ContentText text={e.note} />
                  </p>
                )}
                <span className="cite" style={{ gridColumn: "1 / -1" }}>{t("citation")}: <ContentText text={e.citation} /></span>
                <div className="row" style={{ gridColumn: "1 / -1" }}>
                  <Link className="btn" to={e.deep_link}>{t("openOriginal")}</Link>
                  <AddToList entry={{
                    item_id: e.item.id, title: e.item.title, passage_id: e.passage?.passage_id,
                    page: e.passage?.page_sequence ?? undefined, start_ms: e.passage?.start_ms ?? undefined, citation: e.citation,
                    snippet: e.passage?.text ? clipSnippet(e.passage.text) : undefined,
                  }} />
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ApiError, ArticleRef } from "../api";
import { facetLink, type Facet } from "../filters";
import { derivativeLabel, LANGS, pick, textLang, type Lang } from "../i18n";
import { useSession, type BasketEntry } from "../state";

/** Derivative label chip. API labels ("Reviewed transcription", …) are translated; others are shown as given. */
export function KindChip({ label }: { label: string }) {
  const { lang } = useSession();
  const d = derivativeLabel(lang, label);
  return <span className="chip" lang={d.lang}>{d.text}</span>;
}

/** Text from a {en,hi,mr} map, marked lang="en" when it falls back to English. */
export function LangText({ map }: { map: Record<string, string> | undefined }) {
  const { lang } = useSession();
  const p = pick(map, lang);
  if (!p.text) return null;
  return <span lang={p.fallback ? "en" : undefined}>{p.text}</span>;
}

/** Archive text whose language the API does not send (titles, curator notes). */
export function ContentText({ text }: { text: string | null | undefined }) {
  const { lang } = useSession();
  if (!text) return null;
  const l: Lang | undefined = textLang(text, lang);
  return <span lang={l && l !== lang ? l : undefined}>{text}</span>;
}

export function useDocumentTitle(title: string | null | undefined) {
  const { t } = useSession();
  const short = t("archiveShort");
  const full = t("archiveName");
  useEffect(() => {
    document.title = title ? `${title} — ${short}` : full;
  }, [title, short, full]);
}

export function LanguageSwitch({ className = "langs" }: { className?: string }) {
  const s = useSession();
  return (
    <div className={className} role="group" aria-label={s.t("language")}>
      {LANGS.map((l) => (
        <button key={l.code} type="button" lang={l.code} aria-pressed={s.lang === l.code} onClick={() => s.setLang(l.code)}>
          {l.name}
        </button>
      ))}
    </div>
  );
}

/** Numbered in-text citation. The visual number is small; the tap target is 48 × 48 px. */
export function CitationLink({ n, targetId }: { n: number; targetId: string }) {
  const { t } = useSession();
  return (
    <a className="cite-link" href={`#${targetId}`} aria-label={`${t("source")} ${n}`}>
      <span aria-hidden="true">{n}</span>
    </a>
  );
}

export function VerifiedChip({ verified }: { verified: boolean }) {
  const { t } = useSession();
  return verified ? (
    <span className="chip verified">{t("quoteVerified")}</span>
  ) : (
    <span className="chip">{t("notQuoteVerified")}</span>
  );
}

export function FixtureChip({ show }: { show?: boolean }) {
  const { t } = useSession();
  if (!show) return null;
  return <span className="chip fixture">{t("fixtureChip")}</span>;
}

export interface LoadingProps {
  label?: string;
  inline?: boolean;
  center?: boolean;
  card?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function Loading({ label, inline = false, center = false, card = false, size = "md", className = "" }: LoadingProps) {
  const { t } = useSession();
  const text = label ?? t("loading");
  const spinnerClass = `spinner ${size === "sm" ? "sm" : size === "lg" ? "lg" : ""}`.trim();
  const wrapClass = `loader-wrap ${inline ? "inline" : ""} ${center ? "center" : ""} ${card ? "card" : ""} ${className}`.trim();

  return (
    <div role="status" aria-live="polite" className={wrapClass}>
      <span className={spinnerClass} aria-hidden="true" />
      <span className="loader-text muted">{text}</span>
    </div>
  );
}

/** API error details are English-only, so visitors see a translated message instead. */
const WITHDRAWN_CATEGORIES = new Set(["withdrawn", "rights", "takedown"]);

export function ErrorState({ error, retry, notFound, message }: { error?: ApiError | null; retry?: () => void; notFound?: string; message?: string }) {
  const { t } = useSession();
  const withdrawn = error?.status === 410 && Boolean(error?.reasonCategory && WITHDRAWN_CATEGORIES.has(error.reasonCategory));
  const msg = message
    ? message
    : withdrawn
      ? t("withdrawnNotice")
      : error?.status === 404 || error?.status === 410
        ? notFound ?? t("notAvailable")
        : error?.offline
          ? t("offlineBanner")
          : t("errorGeneric");
  return (
    <div className="notice bad" role="alert">
      <div className="row" style={{ alignItems: "center", gap: 12 }}>
        <p style={{ margin: 0, flex: 1 }}>{msg}</p>
        {retry && error && error.status !== 404 && error.status !== 410 && (
          <button type="button" className="btn secondary small" onClick={retry}>
            {t("retry")}
          </button>
        )}
      </div>
    </div>
  );
}

export function AddToList({ entry }: { entry: BasketEntry }) {
  const s = useSession();
  const inList = s.inBasket(entry);
  return (
    <button
      type="button"
      className={`btn small ${inList ? "" : "secondary"}`}
      aria-pressed={inList}
      onClick={() => (inList ? s.removeFromBasket(entry) : s.addToBasket(entry))}
    >
      {inList ? s.t("inList") : s.t("addToList")}
    </button>
  );
}

export function ArticleLinks({ articles }: { articles?: ArticleRef[] }) {
  const { t } = useSession();
  if (!articles?.length) return null;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <span className="muted" style={{ fontSize: "var(--step--1)" }}>{t("linkedArticles")}</span>
      <div className="chips">
        {articles.map((a) => (
          <Link key={a.number} className="chip-link" to={`/constitution/${encodeURIComponent(a.number)}`}>
            {t("article", { n: a.number })}{a.title ? <>: <ContentText text={a.title} /></> : null}
          </Link>
        ))}
      </div>
    </div>
  );
}

export function FacetLinks({ facet, values }: { facet: Facet; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <span className="chips">
      {values.map((v) => (
        <Link key={v} className="chip-link" to={facetLink(facet, v)}>{v}</Link>
      ))}
    </span>
  );
}

export function Page({ title, lead, children }: { title: string; lead?: ReactNode; children: ReactNode }) {
  useDocumentTitle(title);
  return (
    <div className="page">
      <h1>{title}</h1>
      {lead && <p className="muted" style={{ maxWidth: "70ch" }}>{lead}</p>}
      {children}
    </div>
  );
}

export function pickText(map: Record<string, string> | undefined, lang: string): string {
  if (!map) return "";
  return map[lang] ?? map.en ?? Object.values(map)[0] ?? "";
}

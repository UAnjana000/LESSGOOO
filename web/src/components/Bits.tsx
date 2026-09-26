import type { ReactNode } from "react";
import type { ApiError } from "../api";
import { useSession, type BasketEntry } from "../state";

export function KindChip({ label }: { label: string }) {
  return <span className="chip">{label}</span>;
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

export function Loading() {
  const { t } = useSession();
  return (
    <p role="status" className="muted">
      {t("loading")}
    </p>
  );
}

export function ErrorState({ error, retry }: { error: ApiError; retry?: () => void }) {
  const { t } = useSession();
  const msg = error.status === 404 || error.status === 410 ? error.message || t("notAvailable") : error.offline ? t("offlineBanner") : t("errorGeneric");
  return (
    <div className="notice bad" role="alert">
      <p>{msg}</p>
      {retry && error.status !== 404 && (
        <button type="button" className="btn secondary small" onClick={retry}>
          {t("retry")}
        </button>
      )}
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

export function Page({ title, lead, children }: { title: string; lead?: ReactNode; children: ReactNode }) {
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

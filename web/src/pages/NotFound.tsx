import { Link } from "react-router-dom";
import { useSession } from "../state";
import { useDocumentTitle } from "../components/Bits";

/** Any address no route matches, shown inside the visitor shell so navigation stays available. */
export function NotFound() {
  const { t } = useSession();
  useDocumentTitle(t("pageNotFound"));
  return (
    <div className="page">
      <h1>{t("pageNotFound")}</h1>
      <p className="muted">{t("pageNotFoundBody")}</p>
      <div className="row">
        <Link className="btn" to="/">{t("navHome")}</Link>
        <Link className="btn secondary" to="/search">{t("navSearch")}</Link>
      </div>
    </div>
  );
}

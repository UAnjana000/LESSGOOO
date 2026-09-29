import { useEffect, useMemo, useState } from "react";
import { fileUrl, type Hit, type ItemCard, type TimelineEvent } from "../api";
import { pick, textLang, type Lang } from "../i18n";
import { useApi } from "../hooks";
import { useSession } from "../state";
import { Loading, useDocumentTitle } from "../components/Bits";

interface SignageData {
  timeline: TimelineEvent[];
  story: { titles: Record<string, string>; blocks: { item: ItemCard; captions: Record<string, string>; image_file_id: number | null; passage: Hit | null; citation: string }[] } | null;
  slide_seconds: number;
}

type Text = { text: string; lang?: Lang };

interface Slide {
  /** Timeline slides lead with a short date; story slides with the (often long) story title. */
  kind: "date" | "story";
  kicker: Text;
  title: Text;
  body: Text;
  image: number | null;
  citation: string;
}

/** Smart display: unattended, no input, rotates approved timeline and story content only. */
export function Signage() {
  const { t, lang } = useSession();
  const sig = useApi<SignageData>("/api/visitor/signage");
  const [i, setI] = useState(0);
  useDocumentTitle(null);
  const slides = useMemo<Slide[]>(() => {
    const d = sig.data;
    if (!d) return [];
    const loc = (map: Record<string, string> | undefined): Text => {
      const p = pick(map, lang);
      return { text: p.text, lang: p.fallback ? "en" : undefined };
    };
    const raw = (text: string): Text => ({ text, lang: textLang(text, lang) });
    const tl = d.timeline.map((e): Slide => ({ kind: "date", kicker: raw(e.date_text), title: loc(e.titles), body: loc(e.descriptions), image: null, citation: e.items.map((x) => x.title).join("; ") }));
    const st = (d.story?.blocks ?? []).map((b): Slide => ({ kind: "story", kicker: loc(d.story!.titles), title: raw(b.item.title), body: loc(b.captions), image: b.image_file_id, citation: b.citation }));
    return [...st, ...tl];
  }, [sig.data, lang]);

  useEffect(() => {
    if (!slides.length) return;
    const every = (sig.data?.slide_seconds ?? 12) * 1000;
    const id = window.setInterval(() => setI((x) => (x + 1) % slides.length), every);
    return () => window.clearInterval(id);
  }, [slides.length, sig.data]);

  useEffect(() => {
    const id = window.setInterval(sig.reload, 5 * 60_000);
    return () => window.clearInterval(id);
  }, [sig.reload]);

  // An unattended screen must recover by itself when the server comes back.
  useEffect(() => {
    if (!sig.error) return;
    const id = window.setTimeout(sig.reload, 30_000);
    return () => window.clearTimeout(id);
  }, [sig.error, sig.reload]);

  const s = slides[i % Math.max(1, slides.length)];
  return (
    <main className="signage">
      {s ? (
        <>
          <h1>{t("archiveName")}</h1>
          <div className="slide" key={i}>
            <div>
              <div className={s.kind === "date" ? "date" : "kicker"} lang={s.kicker.lang}>{s.kicker.text}</div>
              <h2 lang={s.title.lang}>{s.title.text}</h2>
              <p lang={s.body.lang}>{s.body.text}</p>
              <p className="source">{t("citation")}: {s.citation}</p>
            </div>
            {/* Offline, images of online-only items are not saved: hide them rather than show a broken image. */}
            <div className="art">{s.image && <img src={fileUrl(s.image)} alt={t("imageOf", { title: s.title.text })} onError={(e) => { e.currentTarget.hidden = true; }} />}</div>
          </div>
        </>
      ) : sig.loading ? (
        <div className="signage-loading">
          <Loading size="lg" label={t("loading")} />
        </div>
      ) : (
        // Nothing to rotate yet (no approved content, server unreachable): an attract screen, never a blank one.
        <div className="signage-idle">
          <h1 className="attract-title">{t("archiveName")}</h1>
          <span className="attract-lead">{t("attractTitle")}</span>
        </div>
      )}
      <footer>
        <span>{(sig.data?.timeline.some((e) => e.items.some((x) => x.is_fixture)) ?? false) ? t("fixtureBanner") : ""}</span>
        <span>{slides.length ? `${(i % slides.length) + 1} / ${slides.length}` : ""}</span>
      </footer>
    </main>
  );
}

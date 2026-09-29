import { useEffect, useMemo, useState } from "react";
import { fileUrl, type Hit, type ItemCard, type TimelineEvent } from "../api";
import { pick, textLang, type Lang } from "../i18n";
import { useApi } from "../hooks";
import { useSession } from "../state";
import { useDocumentTitle } from "../components/Bits";

interface SignageData {
  timeline: TimelineEvent[];
  story: { titles: Record<string, string>; blocks: { item: ItemCard; captions: Record<string, string>; image_file_id: number | null; passage: Hit | null; citation: string }[] } | null;
  slide_seconds: number;
}

type Text = { text: string; lang?: Lang };

interface Slide {
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
    const tl = d.timeline.map((e) => ({ kicker: raw(e.date_text), title: loc(e.titles), body: loc(e.descriptions), image: null, citation: e.items.map((x) => x.title).join("; ") }));
    const st = (d.story?.blocks ?? []).map((b) => ({ kicker: loc(d.story!.titles), title: raw(b.item.title), body: loc(b.captions), image: b.image_file_id, citation: b.citation }));
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

  const s = slides[i % Math.max(1, slides.length)];
  return (
    <main className="signage">
      <h1>{t("archiveName")}</h1>
      {s ? (
        <div className="slide" key={i}>
          <div>
            <div className="date" lang={s.kicker.lang}>{s.kicker.text}</div>
            <h2 style={{ fontSize: "2.6vw", marginTop: "2vh" }} lang={s.title.lang}>{s.title.text}</h2>
            <p lang={s.body.lang}>{s.body.text}</p>
            <p style={{ color: "var(--brass-ink)", fontSize: "1.2vw" }}>{t("citation")}: {s.citation}</p>
          </div>
          <div>{s.image && <img src={fileUrl(s.image)} alt={t("imageOf", { title: s.title.text })} />}</div>
        </div>
      ) : (
        <div />
      )}
      <footer>
        <span>{(sig.data?.timeline.some((e) => e.items.some((x) => x.is_fixture)) ?? false) ? t("fixtureBanner") : ""}</span>
        <span>{slides.length ? `${(i % slides.length) + 1} / ${slides.length}` : ""}</span>
      </footer>
    </main>
  );
}

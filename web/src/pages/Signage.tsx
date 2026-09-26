import { useEffect, useMemo, useState } from "react";
import { fileUrl, type Hit, type ItemCard, type TimelineEvent } from "../api";
import { useApi } from "../hooks";
import { useSession } from "../state";
import { pickText } from "../components/Bits";

interface SignageData {
  timeline: TimelineEvent[];
  story: { titles: Record<string, string>; blocks: { item: ItemCard; captions: Record<string, string>; image_file_id: number | null; passage: Hit | null; citation: string }[] } | null;
  slide_seconds: number;
}

interface Slide {
  kicker: string;
  title: string;
  body: string;
  image: number | null;
  citation: string;
}

/** Smart display: unattended, no input, rotates approved timeline and story content only. */
export function Signage() {
  const { t, lang } = useSession();
  const sig = useApi<SignageData>("/api/visitor/signage");
  const [i, setI] = useState(0);
  const slides = useMemo<Slide[]>(() => {
    const d = sig.data;
    if (!d) return [];
    const tl = d.timeline.map((e) => ({ kicker: e.date_text, title: pickText(e.titles, lang), body: pickText(e.descriptions, lang), image: null, citation: e.items.map((x) => x.title).join("; ") }));
    const st = (d.story?.blocks ?? []).map((b) => ({ kicker: pickText(d.story!.titles, lang), title: b.item.title, body: pickText(b.captions, lang), image: b.image_file_id, citation: b.citation }));
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
    <div className="signage">
      <h1>{t("archiveName")}</h1>
      {s ? (
        <div className="slide" key={i}>
          <div>
            <div className="date">{s.kicker}</div>
            <h2 style={{ color: "#fff", fontSize: "2.6vw", marginTop: "2vh" }}>{s.title}</h2>
            <p>{s.body}</p>
            <p style={{ color: "#c9a24a", fontSize: "1.2vw" }}>{t("citation")}: {s.citation}</p>
          </div>
          <div>{s.image && <img src={fileUrl(s.image)} alt="" />}</div>
        </div>
      ) : (
        <div />
      )}
      <footer>
        <span>{(sig.data?.timeline.some((e) => e.items.some((x) => x.is_fixture)) ?? false) ? t("fixtureBanner") : ""}</span>
        <span>{slides.length ? `${(i % slides.length) + 1} / ${slides.length}` : ""}</span>
      </footer>
    </div>
  );
}

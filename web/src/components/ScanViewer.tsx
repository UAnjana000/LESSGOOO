import { useEffect, useRef, useState } from "react";
import OpenSeadragon from "openseadragon";
import { fileUrl, resolveApiUrl } from "../api";
import { useSession } from "../state";

interface Props {
  iiif: string | null;
  fileId: number;
  label: string;
  highlight?: number[][];
}

/**
 * Deep-zoom scan. IIIF tiles when the edge server is reachable, otherwise the cached delivery image.
 * OpenSeadragon's own navigation buttons are small and English-only, so the zoom controls are ours.
 */
export function ScanViewer({ iiif, fileId, label, highlight }: Props) {
  const { t } = useSession();
  const host = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<OpenSeadragon.Viewer | null>(null);

  // Rebuild the viewer when the boxes change, not when a re-render hands over an equal array.
  const boxes = JSON.stringify(highlight ?? []);

  useEffect(() => {
    if (!host.current) return;
    const highlight = JSON.parse(boxes) as number[][];
    const simple = { type: "image", url: fileUrl(fileId) };
    const viewer = OpenSeadragon({
      element: host.current,
      showNavigationControl: false,
      prefixUrl: "/osd-images/",
      gestureSettingsTouch: { pinchRotate: false, flickEnabled: true },
      visibilityRatio: 0.9,
      minZoomImageRatio: 0.8,
      maxZoomPixelRatio: 3,
      crossOriginPolicy: false,
      animationTime: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 0.6,
    });
    viewerRef.current = viewer;
    let destroyed = false;
    let fellBack = false;
    const showSimple = () => {
      if (destroyed || fellBack) return;
      fellBack = true;
      viewer.open(simple as never);
    };
    viewer.addHandler("open-failed", showSimple);
    // Tiles can fail after info.json loaded (blocked host, timeout): the delivery image still shows the page.
    viewer.addHandler("tile-load-failed", showSimple);
    if (navigator.onLine && iiif) {
      // The server names its own host in info.json's "id", and behind a proxy (the website rewriting /iiif to
      // the API) that is a host the page may not load images from. Tiles are fetched where info.json was.
      const infoUrl = new URL(resolveApiUrl(iiif), window.location.href);
      fetch(infoUrl.href)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`info.json ${r.status}`))))
        .then((info: Record<string, unknown>) => {
          if (destroyed) return;
          const id = infoUrl.href.replace(/\/info\.json$/, "");
          viewer.open({ ...info, id, "@id": id } as never);
        })
        .catch(showSimple);
    } else {
      showSimple();
    }
    viewer.addHandler("open", () => {
      viewer.clearOverlays();
      const item = viewer.world.getItemAt(0);
      if (!item || !highlight?.length) return;
      for (const [x0, y0, x1, y1] of highlight) {
        const el = document.createElement("div");
        el.style.cssText = "border:3px solid #1a3fb8;background:rgba(26,63,184,.12);pointer-events:none";
        viewer.addOverlay({ element: el, location: item.imageToViewportRectangle(x0, y0, x1 - x0, y1 - y0) });
      }
    });
    return () => {
      destroyed = true;
      viewerRef.current = null;
      viewer.destroy();
    };
  }, [iiif, fileId, boxes]);

  const zoom = (factor: number) => {
    const v = viewerRef.current;
    if (!v) return;
    v.viewport.zoomBy(factor);
    v.viewport.applyConstraints();
  };

  // Full screen: the browser's Fullscreen API on the viewer (scan and its controls), or, where an element cannot
  // go full screen (iPhone Safari), the viewer covering the whole window until Esc or the button.
  const wrap = useRef<HTMLDivElement>(null);
  const [full, setFull] = useState<"native" | "window" | null>(null);
  useEffect(() => {
    const sync = () => setFull((cur) => (document.fullscreenElement === wrap.current ? "native" : cur === "native" ? null : cur));
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);
  useEffect(() => {
    if (full !== "window") return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFull(null); };
    document.addEventListener("keydown", onKey);
    document.body.classList.add("scan-fullwindow-open");
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("scan-fullwindow-open");
    };
  }, [full]);
  useEffect(() => {
    // The canvas changed size: show the whole page again once the layout has settled.
    const id = window.setTimeout(() => viewerRef.current?.viewport.goHome(true), 120);
    return () => window.clearTimeout(id);
  }, [full]);
  const toggleFull = () => {
    const el = wrap.current;
    if (!el) return;
    if (full === "native") {
      void document.exitFullscreen?.().catch(() => setFull(null));
    } else if (full === "window") {
      setFull(null);
    } else if (document.fullscreenEnabled && el.requestFullscreen) {
      el.requestFullscreen().catch(() => setFull("window"));
    } else {
      setFull("window");
    }
  };

  return (
    <div ref={wrap} className={`osd-wrap${full ? " is-full" : ""}${full === "window" ? " full-window" : ""}`} role="group" aria-label={label}>
      <div ref={host} className="osd" />
      <div className="osd-tools" role="group" aria-label={t("scanControls")}>
        <button type="button" onClick={() => zoom(1.4)}>
          <span aria-hidden="true">+</span>
          <span className="visually-hidden">{t("zoomIn")}</span>
        </button>
        <button type="button" onClick={() => zoom(1 / 1.4)}>
          <span aria-hidden="true">−</span>
          <span className="visually-hidden">{t("zoomOut")}</span>
        </button>
        <button type="button" onClick={() => viewerRef.current?.viewport.goHome()} title={t("zoomReset")}>
          <span aria-hidden="true">⟲</span>
          <span className="visually-hidden">{t("zoomReset")}</span>
        </button>
        <button type="button" className="osd-full" onClick={toggleFull} aria-pressed={full !== null} title={t(full ? "exitFullScreen" : "fullScreen")}>
          <span aria-hidden="true">{full ? "✕" : "⛶"}</span>
          <span className="visually-hidden">{t(full ? "exitFullScreen" : "fullScreen")}</span>
        </button>
      </div>
    </div>
  );
}

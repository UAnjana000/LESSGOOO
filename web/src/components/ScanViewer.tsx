import { useEffect, useRef } from "react";
import OpenSeadragon from "openseadragon";
import { fileUrl } from "../api";
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

  useEffect(() => {
    if (!host.current) return;
    const simple = { type: "image", url: fileUrl(fileId) };
    const viewer = OpenSeadragon({
      element: host.current,
      tileSources: navigator.onLine && iiif ? iiif : simple,
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
    viewer.addOnceHandler("open-failed", () => viewer.open(simple as never));
    viewer.addHandler("open", () => {
      viewer.clearOverlays();
      const item = viewer.world.getItemAt(0);
      if (!item || !highlight?.length) return;
      for (const [x0, y0, x1, y1] of highlight) {
        const el = document.createElement("div");
        el.style.cssText = "border:3px solid #c9a24a;background:rgba(201,162,74,.15);pointer-events:none";
        viewer.addOverlay({ element: el, location: item.imageToViewportRectangle(x0, y0, x1 - x0, y1 - y0) });
      }
    });
    return () => {
      viewerRef.current = null;
      viewer.destroy();
    };
  }, [iiif, fileId, highlight]);

  const zoom = (factor: number) => {
    const v = viewerRef.current;
    if (!v) return;
    v.viewport.zoomBy(factor);
    v.viewport.applyConstraints();
  };

  return (
    <div className="osd-wrap" role="group" aria-label={label}>
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
        <button type="button" onClick={() => viewerRef.current?.viewport.goHome()}>
          <span aria-hidden="true">⤢</span>
          <span className="visually-hidden">{t("zoomReset")}</span>
        </button>
      </div>
    </div>
  );
}

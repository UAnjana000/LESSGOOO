import { useEffect, useRef } from "react";
import OpenSeadragon from "openseadragon";
import { fileUrl } from "../api";

interface Props {
  iiif: string | null;
  fileId: number;
  label: string;
  highlight?: number[][];
}

/** Deep-zoom scan. IIIF tiles when the edge server is reachable, otherwise the cached delivery image. */
export function ScanViewer({ iiif, fileId, label, highlight }: Props) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!host.current) return;
    const simple = { type: "image", url: fileUrl(fileId) };
    const viewer = OpenSeadragon({
      element: host.current,
      tileSources: navigator.onLine && iiif ? iiif : simple,
      showNavigationControl: true,
      navigationControlAnchor: OpenSeadragon.ControlAnchor.TOP_RIGHT,
      prefixUrl: "/osd-images/",
      gestureSettingsTouch: { pinchRotate: false, flickEnabled: true },
      visibilityRatio: 0.9,
      minZoomImageRatio: 0.8,
      maxZoomPixelRatio: 3,
      crossOriginPolicy: false,
      animationTime: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 0.6,
    });
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
    return () => viewer.destroy();
  }, [iiif, fileId, highlight]);

  return <div ref={host} className="osd" role="img" aria-label={label} />;
}

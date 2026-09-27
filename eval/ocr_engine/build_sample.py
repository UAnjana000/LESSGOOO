"""Build the OCR engine-comparison sample (docs/OCR_ENGINE_EVAL.md).

    backend\\.venv\\Scripts\\python.exe eval/ocr_engine/build_sample.py --out data/ocr_eval

Pages are drawn with a fixed seed, stratified by source file, from the born-digital PDFs in data/incoming/.
Each page is rendered at 300 DPI (clean) and also degraded to look like an old rescan (lower DPI, blur, noise,
JPEG, slight skew; parameters drawn per page from the same seed). Ground truth is the PDF text layer:
Unicode for the English files, and for the Hindi files the Kruti Dev / Walkman Chanakya legacy-font runs
converted to Unicode by krutidev.py (runs in Latin fonts such as Times or Verdana are kept as they are).

Everything is written under --out, which must be inside the gitignored data/ tree: page images and page text
are source content and are never committed. Hindi pages listed in --exclude (after the by-eye spot check) are
dropped and the next page in the seeded order takes their place.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from krutidev import convert, leftover_latin  # noqa: E402

SEED = 20260927
DPI = 300
SOURCES = [
    # (file under data/incoming, language, pages to draw)
    ("baws/mea_Volume1.pdf", "en", 8),
    ("baws/mea_Volume13.pdf", "en", 8),
    ("cad/cad_04-11-1948_en_sansad.pdf", "en", 7),
    ("cad/cad_25-11-1949.pdf", "en", 7),
    ("baws/mea_VolumeH1.pdf", "hi", 10),
    ("cad/cad_04-11-1948_hindi.pdf", "hi", 10),
    ("cad/cad_25-11-1949_hindi.pdf", "hi", 10),
]
MIN_CHARS = 400


def _font_class(textpage, index: int, buf) -> str:
    flags = ctypes.c_int(0)
    n = pdfium_c.FPDFText_GetFontInfo(textpage, index, buf, len(buf), ctypes.byref(flags))
    name = bytes(buf[: max(0, n - 1)]).decode("latin-1").lower() if n else ""
    if "krutidev" in name:
        return "kruti"
    if "chanakya" in name:
        return "chanakya"
    return "latin" if name else ""


def _segments(tp, count: int) -> list[dict]:
    """Split the text layer into line segments at vertical jumps of more than one line height, keeping
    content-stream order inside each segment (legacy-font glyph order matters there). pdfium's own line
    breaks are treated as spaces: on bold legacy-font runs it breaks lines between a consonant and its
    matra."""
    buf = (ctypes.c_ubyte * 256)()
    segs: list[dict] = []
    cur: dict | None = None
    l, r, b, t = (ctypes.c_double() for _ in range(4))
    boxes = []
    for i in range(count):
        pdfium_c.FPDFText_GetCharBox(tp, i, *(ctypes.byref(v) for v in (l, r, b, t)))
        boxes.append((l.value, b.value, t.value))
    heights = sorted(bx[2] - bx[1] for bx in boxes if bx[2] > bx[1])
    line_h = heights[len(heights) // 2] if heights else 10.0
    for i in range(count):
        ch = chr(pdfium_c.FPDFText_GetUnicode(tp, i))
        if ch in "\r\n":
            ch = " "
        cls = _font_class(tp, i, buf) or (cur["chars"][-1][1] if cur and cur["chars"] else "latin")
        x0, y0, y1 = boxes[i]
        if not ch.isspace() and y1 > y0:
            cy = (y0 + y1) / 2
            # Matras above/below the line sit well within one line height of the base glyphs.
            if cur is None or (cur["cys"] and abs(cy - sorted(cur["cys"])[len(cur["cys"]) // 2]) > 1.2 * line_h):
                cur = {"chars": [], "cys": [], "h": line_h, "x0": x0}
                segs.append(cur)
            if not cur["cys"]:
                cur["x0"] = x0
            cur["cys"].append(cy)
        elif cur is None:
            cur = {"chars": [], "cys": [], "h": line_h, "x0": 0.0}
            segs.append(cur)
        cur["chars"].append((ch, cls))
    out = []
    for s in segs:
        if s["cys"]:
            s["cy"] = sorted(s["cys"])[len(s["cys"]) // 2]
            out.append(s)
    return out


def page_text(doc: pdfium.PdfDocument, index: int, language: str) -> dict:
    """Page ground truth in visual line order (top to bottom, then left to right)."""
    tp = doc[index].get_textpage()
    segs = _segments(tp.raw, pdfium_c.FPDFText_CountChars(tp.raw))
    segs.sort(key=lambda s: -s["cy"])
    lines: list[list[dict]] = []
    for s in segs:
        if lines and abs(lines[-1][0]["cy"] - s["cy"]) < 0.5 * max(lines[-1][0]["h"], s["h"]):
            lines[-1].append(s)
        else:
            lines.append([s])
    counts = {"kruti": 0, "chanakya": 0, "latin": 0}
    out_lines, left = [], 0
    for line in lines:
        parts = []
        for s in sorted(line, key=lambda s: s["x0"]):
            runs: list[list] = []
            for ch, cls in s["chars"]:
                if not ch.isspace():
                    counts[cls] += 1
                if runs and runs[-1][0] == cls:
                    runs[-1][1] += ch
                else:
                    runs.append([cls, ch])
            seg = []
            for cls, txt in runs:
                if language == "hi" and cls in ("kruti", "chanakya"):
                    c = convert(txt, chanakya=cls == "chanakya")
                    left += leftover_latin(c)
                    seg.append(c)
                else:
                    seg.append(txt)
            parts.append("".join(seg).strip())
        out_lines.append(" ".join(p for p in parts if p))
    legacy = counts["kruti"] + counts["chanakya"]
    total = max(1, sum(counts.values()))
    return {"text": "\n".join(out_lines), "legacy_share": round(legacy / total, 4), "leftover_latin": left,
            "font_classes": counts}


def render(doc: pdfium.PdfDocument, index: int) -> np.ndarray:
    pil = doc[index].render(scale=DPI / 72, grayscale=True).to_pil().convert("L")
    return np.array(pil)


def degrade(gray: np.ndarray, rng: random.Random) -> tuple[np.ndarray, dict]:
    """Rescan-like degradation: skew, optical blur, paper tone and noise, lower DPI, JPEG."""
    p = {"skew_deg": round(rng.uniform(-2.0, 2.0), 2), "blur_sigma": round(rng.uniform(0.6, 1.6), 2),
         "noise_sigma": round(rng.uniform(5, 15), 1), "dpi": rng.choice([150, 200, 200]),
         "jpeg_quality": rng.randint(25, 60), "paper": rng.randint(200, 235), "ink": rng.randint(20, 70)}
    img = gray.astype(np.float32) / 255.0
    img = p["ink"] + img * (p["paper"] - p["ink"])  # lower contrast, grey paper
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), p["skew_deg"], 1.0)
    img = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=float(p["paper"]))
    img = cv2.GaussianBlur(img, (0, 0), p["blur_sigma"])
    nrng = np.random.default_rng(rng.randint(0, 2**31))
    img = img + nrng.normal(0, p["noise_sigma"], img.shape)
    scale = p["dpi"] / DPI
    img = cv2.resize(np.clip(img, 0, 255).astype(np.uint8), (int(w * scale), int(h * scale)),
                     interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, p["jpeg_quality"]])
    assert ok
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE), p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--incoming", default="data/incoming")
    ap.add_argument("--out", default="data/ocr_eval")
    ap.add_argument("--exclude", nargs="*", default=[], help="page ids rejected at the Hindi spot check")
    ap.add_argument("--min-legacy-share", type=float, default=0.9)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "gt").mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    manifest = {"seed": SEED, "dpi": DPI, "min_chars": MIN_CHARS, "exclude": args.exclude, "pages": [],
                "skipped": []}
    for rel, lang, k in SOURCES:
        doc = pdfium.PdfDocument(str(Path(args.incoming) / rel))
        order = list(range(len(doc)))
        rng.shuffle(order)
        taken = 0
        for idx in order:
            if taken == k:
                break
            pid = f"{Path(rel).stem}_p{idx + 1:04d}"
            info = page_text(doc, idx, lang)
            n = len("".join(info["text"].split()))
            reason = None
            if n < MIN_CHARS:
                reason = f"only {n} non-space characters"
            elif lang == "hi" and info["legacy_share"] < args.min_legacy_share:
                reason = f"legacy-font share {info['legacy_share']}"
            elif pid in args.exclude:
                reason = "rejected at spot check"
            if reason:
                manifest["skipped"].append({"id": pid, "reason": reason})
                continue
            gray = render(doc, idx)
            Image.fromarray(gray).save(out / "pages" / f"{pid}.png", optimize=True)
            deg, params = degrade(gray, random.Random(f"{SEED}-{pid}"))
            Image.fromarray(deg).save(out / "pages" / f"{pid}_deg.png", optimize=True)
            (out / "gt" / f"{pid}.txt").write_text(info["text"], encoding="utf-8")
            manifest["pages"].append({
                "id": pid, "source": rel, "pdf_page": idx + 1, "language": lang, "gt_chars": n,
                "legacy_share": info["legacy_share"], "leftover_latin": info["leftover_latin"],
                "font_classes": info.get("font_classes"), "degrade": params,
                "size_clean": [int(gray.shape[1]), int(gray.shape[0])],
                "size_degraded": [int(deg.shape[1]), int(deg.shape[0])],
            })
            taken += 1
        print(f"{rel}: {taken} pages")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(manifest['pages'])} pages, {len(manifest['skipped'])} skipped -> {out / 'manifest.json'}")


if __name__ == "__main__":
    main()

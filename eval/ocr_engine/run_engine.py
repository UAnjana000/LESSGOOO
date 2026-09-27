"""Run one local OCR engine configuration over the sample built by build_sample.py (docs/OCR_ENGINE_EVAL.md).

    # Tesseract, inside the current API image (never the running containers):
    docker run --rm --cpus 4 --memory 1g -v %CD%:/work -w /work -e PYTHONPATH=/work/backend \
        ambedkar-archive/api:local python eval/ocr_engine/run_engine.py --engine tesseract-prod --name t-fast-prod

    # Python engines, from a separate eval venv:
    python eval/ocr_engine/run_engine.py --engine paddle --name paddle-v5-mobile

Every engine gets the page after the production preprocessing (archive.ingest.preprocess.preprocess: deskew,
median denoise, CLAHE, crop), exactly what ocr_local.run_ocr receives in the pipeline, unless --raw.
Per page it writes text, words ({t, c 0-100, bbox}), the layout text blocks used by the gate's coverage
signal, wall seconds and CPU seconds (own process plus child processes such as the tesseract binary).
run.json records the engine version, configuration, peak RSS and the host.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from archive.ingest import preprocess  # noqa: E402  (cv2/numpy/PIL only)

TESS_LANG = {"en": "eng", "hi": "hin", "mr": "mar"}


# ------------------------------------------------------------------ helpers

def cpu_now() -> float:
    t = os.times()
    return t.user + t.system + t.children_user + t.children_system


def peak_rss_mb() -> dict[str, float | None]:
    try:
        import resource
        self_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        child_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        cg = None
        for p in ("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
            if os.path.exists(p):
                cg = round(int(Path(p).read_text().strip()) / 2**20, 1)
                break
        return {"self_mb": round(self_kb / 1024, 1), "largest_child_mb": round(child_kb / 1024, 1),
                "container_peak_mb": cg}
    except ImportError:
        try:
            import psutil
            return {"self_mb": round(psutil.Process().memory_info().peak_wset / 2**20, 1),
                    "largest_child_mb": None, "container_peak_mb": None}
        except Exception:  # noqa: BLE001
            return {"self_mb": None, "largest_child_mb": None, "container_peak_mb": None}


def lines_to_text(items: list[tuple[str, list[float]]]) -> str:
    """Group line/segment boxes into visual lines (vertical overlap), left to right, top to bottom."""
    items = [(t, b) for t, b in items if t.strip()]
    items.sort(key=lambda it: (it[1][1] + it[1][3]) / 2)
    rows: list[list[tuple[str, list[float]]]] = []
    for t, b in items:
        cy, h = (b[1] + b[3]) / 2, max(1.0, b[3] - b[1])
        if rows:
            last = rows[-1]
            lcy = sum((x[1][1] + x[1][3]) / 2 for x in last) / len(last)
            lh = max(1.0, sum(x[1][3] - x[1][1] for x in last) / len(last))
            if abs(cy - lcy) < 0.5 * min(h, lh):
                last.append((t, b))
                continue
        rows.append([(t, b)])
    return "\n".join(" ".join(t for t, _ in sorted(r, key=lambda it: it[1][0])) for r in rows)


def words_from_segments(segs: list[tuple[str, list[float], float]]) -> list[dict[str, Any]]:
    """Engines without word boxes: split each segment into words sharing its box and confidence (0-100)."""
    out = []
    for text, box, conf in segs:
        for tok in text.split():
            out.append({"t": tok, "c": round(conf, 1), "bbox": [int(v) for v in box], "approx": True})
    return out


# ------------------------------------------------------------------ engines

def make_tesseract_prod() -> tuple[Callable, str]:
    from archive.ingest import ocr_local
    ver = ocr_local.engine_version()

    def run(gray: np.ndarray, lang: str) -> dict[str, Any]:
        out = ocr_local.run_ocr(gray, lang)
        return {"text": out.text, "words": out.words, "has_hocr": bool(out.hocr)}
    return run, ver


def make_tesseract_2pass() -> tuple[Callable, str]:
    """The pre-2026-09-27 ocr_local.run_ocr: image_to_data, then a second recognition for hOCR."""
    import pytesseract
    ver = f"tesseract {pytesseract.get_tesseract_version()}"

    def run(gray: np.ndarray, lang: str) -> dict[str, Any]:
        img, code, cfg = Image.fromarray(gray), {"hi": "hin", "mr": "mar"}.get(lang, "eng"), "--oem 1 --psm 3"
        data = pytesseract.image_to_data(img, lang=code, config=cfg, output_type=pytesseract.Output.DICT)
        hocr = pytesseract.image_to_pdf_or_hocr(img, lang=code, config=cfg, extension="hocr")
        words = [{"t": t, "c": float(c), "bbox": [x, y, x + w, y + h], "line": [b, p, ln]}
                 for t, c, x, y, w, h, b, p, ln in zip(data["text"], data["conf"], data["left"], data["top"],
                                                       data["width"], data["height"], data["block_num"],
                                                       data["par_num"], data["line_num"])
                 if float(c) >= 0 and t.strip()]
        return {"text": " ".join(w["t"] for w in words), "words": words, "has_hocr": bool(hocr)}
    return run, ver


def make_tesseract_cli(psm: int, lang_map: dict[str, str]) -> tuple[Callable, str]:
    """One tesseract run producing TSV (words) and hOCR together; text assembled like ocr_local."""
    import pytesseract
    from pytesseract.pytesseract import run_tesseract, save
    ver = f"tesseract {pytesseract.get_tesseract_version()}"

    def run(gray: np.ndarray, lang: str) -> dict[str, Any]:
        with save(Image.fromarray(gray)) as (base, path):
            run_tesseract(path, base, "tsv hocr", lang_map.get(lang, "eng"),
                          config=f"--oem 1 --psm {psm} -c tessedit_create_tsv=1")
            tsv = Path(f"{base}.tsv").read_text(encoding="utf-8")
            hocr = Path(f"{base}.hocr").read_bytes()
        words, lines = [], {}
        rows = tsv.splitlines()
        for row in rows[1:]:
            f = row.split("\t")
            if len(f) < 12 or not f[11].strip() or float(f[10]) < 0:
                continue
            x, y, w, h = map(int, f[6:10])
            key = (int(f[2]), int(f[3]), int(f[4]))
            words.append({"t": f[11], "c": round(float(f[10]), 1), "bbox": [x, y, x + w, y + h],
                          "line": list(key)})
            lines.setdefault(key, []).append(f[11])
        paras: dict[tuple[int, int], list[str]] = {}
        for (b, p, _l), toks in sorted(lines.items()):
            paras.setdefault((b, p), []).append(" ".join(toks))
        text = "\n\n".join("\n".join(ls) for _, ls in sorted(paras.items()))
        return {"text": text, "words": words, "has_hocr": bool(hocr)}
    return run, ver


def make_paddle(det: str, rec_en: str, rec_hi: str, det_limit: int) -> tuple[Callable, str]:
    import paddleocr
    from paddleocr import PaddleOCR
    threads = int(os.environ.get("OCR_THREADS", "4"))
    pipes: dict[str, Any] = {}
    limit = {"text_det_limit_side_len": det_limit, "text_det_limit_type": "max"} if det_limit else {}

    def pipe(lang: str):
        if lang not in pipes:
            pipes[lang] = PaddleOCR(**limit,
                text_detection_model_name=det,
                text_recognition_model_name=rec_hi if lang in ("hi", "mr") else rec_en,
                use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
                device="cpu", cpu_threads=threads, return_word_box=True,
                enable_mkldnn=os.environ.get("PADDLE_MKLDNN", "0") == "1")
        return pipes[lang]

    def run(gray: np.ndarray, lang: str) -> dict[str, Any]:
        rgb = np.stack([gray] * 3, axis=-1)
        res = pipe(lang).predict(rgb)[0]
        texts, scores, boxes = res["rec_texts"], res["rec_scores"], res["rec_boxes"]
        segs = [(t, [float(v) for v in b], float(s) * 100) for t, s, b in zip(texts, scores, boxes)]
        words = []
        tw, twr = res.get("text_word"), res.get("text_word_region")
        if tw and twr:
            for (t, b, conf), ws, regs in zip(segs, tw, twr):
                for w, r in zip(ws, regs):
                    if not str(w).strip():
                        continue
                    r = np.asarray(r).reshape(-1, 2)
                    words.append({"t": w, "c": round(conf, 1), "line_conf_only": True,
                                  "bbox": [int(r[:, 0].min()), int(r[:, 1].min()), int(r[:, 0].max()),
                                           int(r[:, 1].max())]})
        else:
            words = words_from_segments(segs)
        return {"text": lines_to_text([(t, b) for t, b, _ in segs]), "words": words, "has_hocr": False}
    return run, f"paddleocr {paddleocr.__version__} ({det} + {rec_en}/{rec_hi})"


def make_easyocr() -> tuple[Callable, str]:
    import easyocr
    import torch
    torch.set_num_threads(int(os.environ.get("OCR_THREADS", "4")))
    # Default 2560 needs > 3 GB for a 300 DPI page (CRAFT detector); the eval caps containers at 3 GB.
    canvas = int(os.environ.get("EASYOCR_CANVAS", "2560"))
    readers: dict[str, Any] = {}

    def run(gray: np.ndarray, lang: str) -> dict[str, Any]:
        langs = ["hi", "en"] if lang == "hi" else (["mr", "en"] if lang == "mr" else ["en"])
        key = "+".join(langs)
        if key not in readers:
            readers[key] = easyocr.Reader(langs, gpu=False, verbose=False)
        res = readers[key].readtext(gray, detail=1, paragraph=False, canvas_size=canvas)
        segs = []
        for poly, text, conf in res:
            p = np.asarray(poly, dtype=float)
            segs.append((text, [p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()], float(conf) * 100))
        return {"text": lines_to_text([(t, b) for t, b, _ in segs]), "words": words_from_segments(segs),
                "has_hocr": False}
    return run, f"easyocr {easyocr.__version__} canvas={canvas}"


def build(engine: str, args: argparse.Namespace) -> tuple[Callable, str]:
    if engine == "tesseract-prod":
        return make_tesseract_prod()
    if engine == "tesseract-2pass":
        return make_tesseract_2pass()
    if engine == "tesseract-cli":
        lm = dict(TESS_LANG)
        if args.hi_lang:
            lm["hi"] = args.hi_lang
        return make_tesseract_cli(args.psm, lm)
    if engine == "paddle":
        return make_paddle(args.paddle_det, args.paddle_rec_en, args.paddle_rec_hi, args.paddle_det_limit)
    if engine == "easyocr":
        return make_easyocr()
    raise SystemExit(f"unknown engine {engine}")


# ------------------------------------------------------------------ driver

_STATE: dict[str, Any] = {}


def _init(engine: str, args: argparse.Namespace) -> None:
    _STATE["run"], _STATE["version"] = build(engine, args)
    _STATE["raw"] = args.raw


def _one(job: tuple[str, str, str]) -> dict[str, Any]:
    image_path, lang, key = job
    gray = np.array(Image.open(image_path).convert("L"))
    img = gray if _STATE["raw"] else preprocess.preprocess(preprocess.to_png(gray), split_spreads=False)[0].image
    blocks = preprocess.detect_text_blocks(img)
    c0, t0 = cpu_now(), time.perf_counter()
    out = _STATE["run"](img, lang)
    out.update({"key": key, "language": lang, "engine_version": _STATE["version"],
                "seconds": round(time.perf_counter() - t0, 3),
                "cpu_seconds": round(cpu_now() - c0, 3), "text_blocks": blocks,
                "image_size": [int(img.shape[1]), int(img.shape[0])]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", required=True,
                    choices=["tesseract-prod", "tesseract-2pass", "tesseract-cli", "paddle", "easyocr"])
    ap.add_argument("--name", required=True, help="run name; output goes to <out>/<name>/")
    ap.add_argument("--sample", default="data/ocr_eval")
    ap.add_argument("--out", default="data/ocr_eval/runs")
    ap.add_argument("--sets", nargs="+", default=["clean", "degraded"], choices=["clean", "degraded"])
    ap.add_argument("--langs", nargs="+", default=["en", "hi"])
    ap.add_argument("--limit", type=int, default=0, help="first N pages per language (timing subsets)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--raw", action="store_true", help="skip the production preprocessing")
    ap.add_argument("--psm", type=int, default=3)
    ap.add_argument("--hi-lang", default="", help="tesseract language string for Hindi pages, e.g. hin+eng")
    ap.add_argument("--paddle-det", default="PP-OCRv5_mobile_det")
    ap.add_argument("--paddle-rec-en", default="en_PP-OCRv5_mobile_rec")
    ap.add_argument("--paddle-rec-hi", default="devanagari_PP-OCRv5_mobile_rec")
    ap.add_argument("--paddle-det-limit", type=int, default=0,
                    help="cap the longer image side for detection (0 = pipeline default)")
    ap.add_argument("--warmup", type=int, default=1, help="pages run first and not timed")
    args = ap.parse_args()

    sample = Path(args.sample)
    manifest = json.loads((sample / "manifest.json").read_text(encoding="utf-8"))
    pages = []
    for lang in args.langs:
        lp = [p for p in manifest["pages"] if p["language"] == lang]
        pages += lp[: args.limit] if args.limit else lp
    jobs = [(str(sample / "pages" / (p["id"] + ("" if s == "clean" else "_deg") + ".png")), p["language"],
             f"{p['id']}|{s}") for s in args.sets for p in pages]
    out_dir = Path(args.out) / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()
    results: list[dict[str, Any]] = []
    if args.workers > 1:
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.engine, args)) as ex:
            for i, r in enumerate(ex.map(_one, jobs)):
                results.append(r)
                print(f"[{i + 1}/{len(jobs)}] {r['key']} {r['seconds']}s", flush=True)
        version = results[0]["engine_version"] if results else "n/a"
    else:
        _init(args.engine, args)
        version = _STATE["version"]
        for j in jobs[: args.warmup]:
            _one(j)
        for i, j in enumerate(jobs):
            r = _one(j)
            results.append(r)
            print(f"[{i + 1}/{len(jobs)}] {r['key']} {r['seconds']}s cpu={r['cpu_seconds']}s", flush=True)
    for r in results:
        pid, s = r["key"].split("|")
        (out_dir / f"{pid}__{s}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    run = {"name": args.name, "engine": args.engine, "engine_version": version,
           "config": {k: v for k, v in vars(args).items() if k not in ("sample", "out")},
           "pages": len(results), "wall_seconds_total": round(time.perf_counter() - t_all, 1),
           "peak_memory": peak_rss_mb(), "host": {"platform": platform.platform(), "cpus": os.cpu_count(),
                                                  "tessdata_prefix": os.environ.get("TESSDATA_PREFIX")},
           "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (out_dir / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()

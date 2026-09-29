"""Per-page routing by document class (spec 4.2-4.4).

born_digital -> text layer (spot-check batch); unreliable text layer -> printed OCR path
printed      -> preprocess -> local OCR -> quality gate
                  pass -> sampled batch review
                  fail -> Sarvam fallback (only if the item allows external processing)
                          -> full review (Sarvam never auto-accepted)
                          Sarvam unavailable -> page stays pending review (sarvam_pending), never published
handwritten  -> human transcription (optional local OCR draft; not counted in fallback rate)
photograph   -> reviewed caption; delivery copy only
audio/video  -> delivery copy via FFmpeg; transcript segments go to full review
"""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from archive import audit, storage
from archive.config import get_settings
from archive.ingest import ocr_local, preprocess
from archive.ingest.quality import apply_gate, compute_signals, review_priority
from archive.ingest.sarvam_ocr import OcrFallback, SarvamRejected, SarvamUnavailable
from archive.ingest.textlayer import PdfPages, text_layer_reliable
from archive.models import (
    ArchivalItem,
    DocClass,
    FileVersion,
    OcrResult,
    OcrRoute,
    Page,
    PageStatus,
)
from archive.rights import external_processing_allowed

log = logging.getLogger(__name__)


@dataclass
class PageOutcome:
    page_id: int
    route: str
    status: str
    gate_passed: bool | None
    detail: dict[str, Any]


_open_pdfs: ContextVar[dict[int, PdfPages] | None] = ContextVar("open_pdfs", default=None)


@contextmanager
def pdf_documents() -> Iterator[None]:
    """While active, each PDF master is read and parsed once and shared by all its pages; all are closed on
    exit. Without it every page call opens its own document (still one page rendered, not all)."""
    cache: dict[int, PdfPages] = {}
    token = _open_pdfs.set(cache)
    try:
        yield
    finally:
        _open_pdfs.reset(token)
        for doc in cache.values():
            doc.close()


@contextmanager
def _pdf(master: FileVersion) -> Iterator[PdfPages]:
    cache = _open_pdfs.get()
    if cache is None:
        with PdfPages(storage.read_bytes(master.storage_uri)) as doc:
            yield doc
        return
    if master.id not in cache:
        cache[master.id] = PdfPages(storage.read_bytes(master.storage_uri))
    yield cache[master.id]


def _page_image(db: Session, page: Page) -> tuple[bytes, np.ndarray]:
    """Return (original-looking image bytes for delivery, grayscale array for OCR input)."""
    master = db.get(FileVersion, page.image_file_id)
    if master.format == "application/pdf":
        with _pdf(master) as doc:
            png = doc.render_png(page.preprocessing_params.get("pdf_page_index", 0))
        return png, preprocess.load_gray(png)
    data = storage.read_bytes(master.storage_uri)
    gray = preprocess.load_gray(data)
    half = page.preprocessing_params.get("spread_half")
    if half is not None:
        x = page.preprocessing_params["split_at_x"]
        gray = gray[:, :x] if half == 0 else gray[:, x:]
        return preprocess.to_png(gray), gray
    return data, gray


def _store_delivery(db: Session, page: Page, image_bytes: bytes, master_id: int) -> None:
    if page.delivery_file_id:
        return
    jpeg = preprocess.delivery_jpeg(image_bytes)
    stored = storage.put_bytes(jpeg, "delivery", ".jpg")
    fv = FileVersion(item_id=page.item_id, page_id=page.id, role="delivery", kind="page_image",
                     format="image/jpeg", byte_size=stored.byte_size, sha256=stored.sha256,
                     storage_uri=stored.uri, derived_from_id=master_id, generator="pillow jpeg q85 max2400")
    db.add(fv)
    db.flush()
    page.delivery_file_id = fv.id


def _store_hocr(db: Session, page: Page, hocr: bytes, engine_version: str) -> int:
    stored = storage.put_bytes(hocr, "derivative", ".hocr")
    fv = FileVersion(item_id=page.item_id, page_id=page.id, role="derivative", kind="hocr",
                     format="text/vnd.hocr+html", byte_size=stored.byte_size, sha256=stored.sha256,
                     storage_uri=stored.uri, derived_from_id=page.image_file_id, generator=engine_version)
    db.add(fv)
    db.flush()
    return fv.id


def _store_sarvam_raw(db: Session, page: Page, markdown: str, engine_version: str) -> int:
    stored = storage.put_bytes(markdown.encode("utf-8"), "derivative", ".md")
    fv = FileVersion(item_id=page.item_id, page_id=page.id, role="derivative", kind="sarvam_raw",
                     format="text/markdown", byte_size=stored.byte_size, sha256=stored.sha256,
                     storage_uri=stored.uri, derived_from_id=page.image_file_id, generator=engine_version)
    db.add(fv)
    db.flush()
    return fv.id


def _run_local(db: Session, page: Page, gray: np.ndarray) -> tuple[OcrResult, Any, Any]:
    prepared = preprocess.preprocess(preprocess.to_png(gray), split_spreads=False)[0]
    page.preprocessing_params = {**page.preprocessing_params, **prepared.params}
    out = ocr_local.run_ocr(prepared.image, page.language)
    blocks = preprocess.detect_text_blocks(prepared.image)
    signals = compute_signals(out.words, out.text, page.language, blocks)
    hocr_id = _store_hocr(db, page, out.hocr, out.engine_version)
    res = OcrResult(page_id=page.id, engine="tesseract", engine_version=out.engine_version, text=out.text,
                    words=out.words, mean_confidence=signals.mean_confidence, hocr_file_id=hocr_id,
                    raw_meta={"text_blocks": len(blocks)})
    db.add(res)
    db.flush()
    return res, signals, prepared


def process_page(db: Session, page: Page, fallback: OcrFallback | None, actor: str = "ingestion-graph") -> PageOutcome:
    item: ArchivalItem = page.item
    s = get_settings()
    image_bytes, gray = _page_image(db, page)
    _store_delivery(db, page, image_bytes, page.image_file_id)
    detail: dict[str, Any] = {}

    if page.doc_class == DocClass.photograph.value:
        page.ocr_route = OcrRoute.none.value
        page.status = PageStatus.needs_full_review.value
        page.review_mode = "full"
        return PageOutcome(page.id, "caption_review", page.status, None, detail)

    if page.doc_class == DocClass.born_digital.value:
        master = db.get(FileVersion, page.image_file_id)
        if master.format == "application/pdf":
            with _pdf(master) as doc:
                text = doc.text(page.preprocessing_params.get("pdf_page_index", 0))
            if text_layer_reliable(text, page.language):
                db.add(OcrResult(page_id=page.id, engine="text_layer", engine_version="pypdf", text=text,
                                 selected=True))
                page.ocr_route = OcrRoute.text_layer.value
                page.status = PageStatus.in_batch_review.value
                page.review_mode = "sampled"
                page.gate_passed = True
                return PageOutcome(page.id, "text_layer", page.status, True, detail)
        detail["text_layer"] = "unreliable or absent; routed to printed OCR"
        page.doc_class = DocClass.printed.value

    if page.doc_class == DocClass.handwritten.value:
        page.ocr_route = OcrRoute.manual.value
        page.status = PageStatus.manual_transcription.value
        page.review_mode = "full"
        try:
            res, signals, _ = _run_local(db, page, gray)
            res.raw_meta = {**res.raw_meta, "draft_only": True, "counted_in_fallback_rate": False}
            page.quality_signals = {**page.quality_signals, **signals.as_dict(), "draft_only": True}
        except ocr_local.LocalOcrUnavailable:
            pass
        return PageOutcome(page.id, "manual", page.status, None, detail)

    # printed
    local, signals, _ = _run_local(db, page, gray)
    decision = apply_gate(signals, DocClass.printed.value, page.language)
    page.quality_signals = {**page.quality_signals, **signals.as_dict(), "failed_checks": decision.failed_checks}
    page.gate_version = decision.version
    page.gate_passed = decision.passed
    page.ocr_route = OcrRoute.local.value
    local.selected = True
    detail.update({"signals": signals.as_dict(), "failed_checks": decision.failed_checks})
    audit.record(db, actor, "page.gate", "page", page.id,
                 detail={"passed": decision.passed, "gate_version": decision.version,
                         "failed_checks": decision.failed_checks})
    if decision.passed:
        page.status = PageStatus.in_batch_review.value
        page.review_mode = "sampled"
        page.review_priority = review_priority(signals, None)
        return PageOutcome(page.id, "local", page.status, True, detail)

    page.review_mode = "full"
    page.review_priority = review_priority(signals, None)
    if not (s.sarvam_ocr_enabled and external_processing_allowed(item)):
        page.status = PageStatus.needs_full_review.value
        detail["sarvam"] = "not permitted for this item (access level / external processing) or disabled"
        return PageOutcome(page.id, "local", page.status, False, detail)
    if fallback is None:
        page.status = PageStatus.sarvam_pending.value
        page.sarvam_last_error = "no Sarvam client configured"
        detail["sarvam"] = page.sarvam_last_error
        return PageOutcome(page.id, "local", page.status, False, detail)
    return run_sarvam(db, page, fallback, local_text=local.text, signals=signals, detail=detail, actor=actor)


def run_sarvam(db: Session, page: Page, fallback: OcrFallback, *, local_text: str | None = None, signals=None,
               detail: dict[str, Any] | None = None, actor: str = "ingestion-graph") -> PageOutcome:
    detail = detail or {}
    _img, gray = _page_image(db, page)
    page.sarvam_attempts += 1
    # Audit writes hold a transaction-scoped advisory lock on the hash chain; commit before the slow
    # external call so staff actions (login, review, publish) are not blocked behind Sarvam polling.
    db.commit()
    try:
        out = fallback.digitise_page(preprocess.to_png(gray), page.language)
    except SarvamUnavailable as exc:
        page.status = PageStatus.sarvam_pending.value
        page.sarvam_last_error = str(exc)
        db.add(OcrResult(page_id=page.id, engine="sarvam-doc-ai", engine_version="n/a", status="failed",
                         error=str(exc)))
        audit.record(db, actor, "page.sarvam_unavailable", "page", page.id, detail={"error": str(exc)[:300]})
        detail["sarvam"] = f"unavailable: {exc}"
        return PageOutcome(page.id, "local", page.status, False, detail)
    except SarvamRejected as exc:
        page.status = PageStatus.manual_transcription.value
        page.ocr_route = OcrRoute.manual.value
        page.sarvam_last_error = str(exc)
        db.add(OcrResult(page_id=page.id, engine="sarvam-doc-ai", engine_version="n/a", status="failed",
                         error=str(exc)))
        audit.record(db, actor, "page.sarvam_rejected", "page", page.id, detail={"error": str(exc)[:300]})
        detail["sarvam"] = f"rejected: {exc}; routed to manual transcription"
        return PageOutcome(page.id, "manual", page.status, False, detail)
    meta: dict[str, Any] = {"job_id": out.job_id, "status": out.raw_status, **out.stripped}
    if out.raw_markdown is not None:
        meta["raw_file_id"] = _store_sarvam_raw(db, page, out.raw_markdown, out.engine_version)
    if out.not_transcription:
        page.status = PageStatus.needs_full_review.value
        page.review_mode = "full"
        page.sarvam_last_error = out.not_transcription
        db.add(OcrResult(page_id=page.id, engine="sarvam-doc-ai", engine_version=out.engine_version,
                         status="failed", text="", error=out.not_transcription, raw_meta=meta))
        audit.record(db, actor, "page.sarvam_no_transcription", "page", page.id,
                     detail={"job_id": out.job_id, "error": out.not_transcription})
        detail["sarvam"] = f"no transcription: {out.not_transcription}; full review of the local draft"
        return PageOutcome(page.id, "local", page.status, False, detail)
    if local_text is None:
        prior = [r for r in page.ocr_results if r.engine == "tesseract"]
        local_text = prior[-1].text if prior else ""
    disagreement = 1 - fuzz.ratio(local_text or "", out.text) / 100
    meta["disagreement"] = round(disagreement, 4)
    # The Sarvam text is the reviewer's starting point (and the "before" of the review decision).
    for r in page.ocr_results:
        r.selected = False
    page.ocr_results.append(OcrResult(engine="sarvam-doc-ai", engine_version=out.engine_version, text=out.text,
                                      raw_meta=meta, selected=True))
    page.ocr_route = OcrRoute.sarvam.value
    page.status = PageStatus.needs_full_review.value
    page.sarvam_last_error = None
    if signals is not None:
        page.review_priority = review_priority(signals, disagreement)
    audit.record(db, actor, "page.sarvam_result", "page", page.id,
                 detail={"job_id": out.job_id, "disagreement": round(disagreement, 4)})
    detail["sarvam"] = {"job_id": out.job_id, "disagreement": round(disagreement, 4)}
    return PageOutcome(page.id, "sarvam", page.status, False, detail)


def make_media_delivery(db: Session, item: ArchivalItem) -> FileVersion | None:
    """FFmpeg delivery copy: AAC audio (m4a) or H.264/AAC MP4 video at one bitrate."""
    master = next((f for f in db.query(FileVersion).filter_by(item_id=item.id, role="preservation_master")), None)
    if master is None:
        return None
    existing = db.query(FileVersion).filter_by(item_id=item.id, role="delivery", kind="media").first()
    if existing:
        return existing
    is_video = master.format.startswith("video/")
    src = storage.resolve(master.storage_uri)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / ("delivery.mp4" if is_video else "delivery.m4a")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
        cmd += (["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-c:a", "aac", "-b:a", "96k",
                 "-movflags", "+faststart"] if is_video else ["-vn", "-c:a", "aac", "-b:a", "64k",
                                                              "-movflags", "+faststart"])
        subprocess.run([*cmd, str(out)], check=True, timeout=600)
        data = out.read_bytes()
    stored = storage.put_bytes(data, "delivery", out.suffix)
    fv = FileVersion(item_id=item.id, role="delivery", kind="media", format="video/mp4" if is_video else "audio/mp4",
                     byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri,
                     derived_from_id=master.id, generator="ffmpeg aac64k" if not is_video else "ffmpeg h264 crf26")
    db.add(fv)
    db.flush()
    return fv


def thumbnail(data: bytes, max_side: int = 480) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()

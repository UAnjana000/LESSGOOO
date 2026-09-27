"""Evaluation harness (spec 10). Every result records sample size, date, model/prompt/gate versions.
Nothing here invents numbers: unmeasured metrics are written as "UNMEASURED"."""

from __future__ import annotations

import datetime as dt
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Callable

from rapidfuzz.distance import Levenshtein
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive.config import get_settings
from archive.ingest.publish import current_index_version
from archive.models import AnswerLog, FileVersion, Page
from archive.search.hybrid import SearchFilters, keyword_ids, load_hits, semantic_ids
from archive.search.models import get_embedder, get_reranker

UNMEASURED = "UNMEASURED"


# ---------------------------------------------------------------- metrics

def cer(ref: str, hyp: str) -> float:
    return Levenshtein.distance(ref, hyp) / max(1, len(ref))


def wer(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    return Levenshtein.distance(r, h) / max(1, len(r))


def recall_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / max(1, len(relevant))


def mrr(ranked: list[int], relevant: set[int]) -> float:
    for i, pid in enumerate(ranked, 1):
        if pid in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, pid in enumerate(ranked[:k]) if pid in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


def bootstrap_ci(values: list[float], samples: int = 1000, seed: int = 7) -> tuple[float, float, float]:
    if not values:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples))
    return statistics.fmean(values), means[int(0.025 * samples)], means[int(0.975 * samples) - 1]


# ---------------------------------------------------------------- OCR

def evaluate_ocr(ground_truth: list[dict[str, Any]], engine: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """ground_truth rows: {id, image, language, doc_class, text, split: calibration|test, acceptable_wer}
    engine(row) -> {"local": text, "signals":{...}, "gate_passed": bool, "sarvam": text|None}"""
    rows = []
    for gt in ground_truth:
        out = engine(gt)
        local_wer = wer(gt["text"], out["local"])
        combined = out["sarvam"] if (not out["gate_passed"] and out.get("sarvam")) else out["local"]
        rows.append({"id": gt["id"], "split": gt.get("split", "test"), "language": gt["language"],
                     "doc_class": gt["doc_class"], "local_cer": cer(gt["text"], out["local"]),
                     "local_wer": local_wer, "combined_wer": wer(gt["text"], combined),
                     "sarvam_wer": wer(gt["text"], out["sarvam"]) if out.get("sarvam") else None,
                     "gate_passed": out["gate_passed"],
                     "bad_page": local_wer > gt.get("acceptable_wer", 0.1), "signals": out.get("signals", {})})
    test = [r for r in rows if r["split"] == "test"]
    bad = [r for r in test if r["bad_page"]]
    good = [r for r in test if not r["bad_page"]]
    return {
        "n_pages": len(rows), "n_test": len(test),
        "local_cer_mean": statistics.fmean(r["local_cer"] for r in test) if test else UNMEASURED,
        "local_wer_mean": statistics.fmean(r["local_wer"] for r in test) if test else UNMEASURED,
        "combined_wer_mean": statistics.fmean(r["combined_wer"] for r in test) if test else UNMEASURED,
        "sarvam_all_pages_wer": (statistics.fmean(r["sarvam_wer"] for r in test if r["sarvam_wer"] is not None)
                                 if any(r["sarvam_wer"] is not None for r in test) else UNMEASURED),
        "fallback_rate": sum(1 for r in test if not r["gate_passed"]) / len(test) if test else UNMEASURED,
        "bad_page_recall": sum(1 for r in bad if not r["gate_passed"]) / len(bad) if bad else UNMEASURED,
        "good_pages_sent_unnecessarily": sum(1 for r in good if not r["gate_passed"]) / len(good) if good else UNMEASURED,
        "rows": rows,
    }


def calibrate_gate(rows: list[dict[str, Any]], signal: str = "mean_confidence") -> dict[str, Any]:
    """Pick the lowest threshold on `signal` that catches every bad calibration page (max recall),
    then report how many good pages it would send to fallback."""
    cal = [r for r in rows if r["split"] == "calibration" and signal in r["signals"]]
    bad = [r["signals"][signal] for r in cal if r["bad_page"]]
    good = [r["signals"][signal] for r in cal if not r["bad_page"]]
    if not bad:
        return {"signal": signal, "threshold": None, "note": "no bad pages in calibration half", "n": len(cal)}
    threshold = max(bad) + 0.01
    return {"signal": signal, "threshold": round(threshold, 2), "n": len(cal), "bad": len(bad),
            "good_sent_to_fallback": sum(1 for g in good if g < threshold)}


# ---------------------------------------------------------------- retrieval

def base_rankings(db: Session, question: str, emb=None, rr=None, candidate_k: int | None = None) -> dict[str, Any]:
    """Rankings from the BASE models: keyword, semantic, hybrid (RRF) and hybrid + base reranker.
    Shared by the retrieval evaluation and hard-negative mining so both see the same candidates."""
    emb, rr = emb or get_embedder(), rr or get_reranker()
    cand_k = candidate_k or get_settings().retrieval_candidate_k
    kw = keyword_ids(db, question, SearchFilters(), cand_k)
    sem = semantic_ids(db, emb.embed_query(question), SearchFilters(), cand_k)
    scores: dict[int, float] = {}
    for lst in (kw, sem):
        for r, pid in enumerate(lst):
            scores[pid] = scores.get(pid, 0) + 1 / (61 + r)
    hyb = sorted(scores, key=scores.get, reverse=True)[:cand_k]
    hits = load_hits(db, hyb)
    texts = [hits[p].text for p in hyb if p in hits]
    ids = [p for p in hyb if p in hits]
    rscores = rr.score(question, texts) if texts else []
    ranked = sorted(zip(rscores, ids, strict=True), key=lambda t: -t[0])
    return {"keyword": kw, "semantic": sem, "hybrid": hyb, "hybrid_rerank": [p for _, p in ranked],
            "rerank_scores": {p: float(sc) for sc, p in ranked}, "rrf": scores, "candidate_k": cand_k}


def evaluate_retrieval(db: Session, questions: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    """questions: [{question, language, positive_passage_ids}]. Compares keyword, semantic, hybrid(RRF)
    and hybrid+rerank with the BASE models (no fine-tuning)."""
    s = get_settings()
    emb, rr = get_embedder(), get_reranker()
    modes: dict[str, dict[str, list[float]]] = {m: {"recall@k": [], "recall@cand": [], "mrr": [], "ndcg@k": []}
                                                for m in ("keyword", "semantic", "hybrid", "hybrid_rerank")}
    per_lang: dict[str, list[float]] = {}
    for q in questions:
        rel = set(q["positive_passage_ids"])
        rk = base_rankings(db, q["question"], emb, rr, s.retrieval_candidate_k)
        kw, sem, hyb, reranked = rk["keyword"], rk["semantic"], rk["hybrid"], rk["hybrid_rerank"]
        for mode, ranked in (("keyword", kw), ("semantic", sem), ("hybrid", hyb), ("hybrid_rerank", reranked)):
            modes[mode]["recall@k"].append(recall_at_k(ranked, rel, k))
            modes[mode]["recall@cand"].append(recall_at_k(ranked, rel, s.retrieval_candidate_k))
            modes[mode]["mrr"].append(mrr(ranked, rel))
            modes[mode]["ndcg@k"].append(ndcg_at_k(ranked, rel, k))
        per_lang.setdefault(q["language"], []).append(mrr(reranked, rel))
    summary = {}
    for mode, mets in modes.items():
        summary[mode] = {m: dict(zip(("mean", "ci_low", "ci_high"), (round(x, 4) for x in bootstrap_ci(v)), strict=True))
                         for m, v in mets.items()}
    return {"n_questions": len(questions), "k": k, "candidate_k": s.retrieval_candidate_k,
            "embedder": emb.name, "embedder_is_test_double": emb.is_test_double, "reranker": rr.name,
            "reranker_is_test_double": rr.is_test_double, "index_version": current_index_version(db),
            "modes": summary,
            "mrr_by_language_hybrid_rerank": {lang: {"n": len(v), "mean": round(statistics.fmean(v), 4)}
                                              for lang, v in per_lang.items()},
            "measured_at": dt.datetime.now(dt.UTC).isoformat()}


# ---------------------------------------------------------------- answers

def evaluate_answer_behaviour(results: list[dict[str, Any]]) -> dict[str, Any]:
    """results rows: {id, category, expected: answer|not_in_archive|refusal, outcome}. Claim support
    needs human graders and is left UNMEASURED here."""
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_cat.setdefault(r["expected"], []).append(r)

    def rate(rows, ok):
        return round(sum(1 for r in rows if ok(r)) / len(rows), 4) if rows else UNMEASURED

    abst = by_cat.get("not_in_archive", [])
    ans = by_cat.get("answer", [])
    predicted_abstain = [r for r in results if r["outcome"] == "insufficient"]
    return {
        "n": len(results),
        "correct_not_in_archive_rate": rate(abst, lambda r: r["outcome"] == "insufficient"),
        "correct_refusal_rate": rate(by_cat.get("refusal", []), lambda r: r["outcome"] == "refused"),
        "answerable_answered_rate": rate(ans, lambda r: r["outcome"] in ("answered", "extractive")),
        "abstention_precision": rate(predicted_abstain, lambda r: r["expected"] == "not_in_archive"),
        "abstention_recall": rate(abst, lambda r: r["outcome"] == "insufficient"),
        "claim_support": UNMEASURED + " (requires human grading; see eval/templates/claim_support_grading.csv)",
        "unsupported_claim_rate": UNMEASURED,
        "quote_match_rate": UNMEASURED if not any(r.get("quotes") for r in results) else
        rate([r for r in results if r.get("quotes")], lambda r: r.get("quotes_ok")),
    }


def answer_cost_latency(db: Session) -> dict[str, Any]:
    rows = db.execute(select(AnswerLog)).scalars().all()
    if not rows:
        return {"n": 0, "note": UNMEASURED}
    lat = sorted(r.latency_ms for r in rows if not r.cache_hit)
    prov = sorted(r.provider_latency_ms for r in rows if not r.cache_hit and r.provider_latency_ms)

    def pct(v, p):
        return v[min(len(v) - 1, int(p * len(v)))] if v else UNMEASURED

    return {"n": len(rows), "cache_hit_rate": round(sum(r.cache_hit for r in rows) / len(rows), 4),
            "p50_latency_ms": pct(lat, 0.5), "p95_latency_ms": pct(lat, 0.95),
            "provider_p50_ms": pct(prov, 0.5), "provider_p95_ms": pct(prov, 0.95),
            "tokens_in_mean": statistics.fmean(r.tokens_in for r in rows),
            "tokens_out_mean": statistics.fmean(r.tokens_out for r in rows),
            "cost_usd_total": round(sum(r.cost_usd for r in rows), 6),
            "llm_answers": sum(1 for r in rows if r.tokens_out > 0)}


def storage_report(db: Session) -> dict[str, Any]:
    by_role = dict(db.execute(select(FileVersion.role, func.sum(FileVersion.byte_size))
                              .where(FileVersion.deleted_at.is_(None)).group_by(FileVersion.role)).all())
    pages = db.execute(select(func.count()).select_from(Page)).scalar() or 0
    items = db.execute(select(func.count(func.distinct(FileVersion.item_id)))).scalar() or 0
    return {"bytes_by_role": {k: int(v) for k, v in by_role.items()}, "pages": pages, "items": items,
            "bytes_per_page_master": int(by_role.get("preservation_master", 0) / pages) if pages else UNMEASURED,
            "bytes_per_item_all": int(sum(by_role.values()) / items) if items else UNMEASURED}


def write_result(name: str, payload: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}-{dt.date.today().isoformat()}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path

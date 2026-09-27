"""Hard-negative mining and human review (spec 7.3 step 2; 10.1 "Training split").

mine   : for each reviewed, not-yet-frozen TrainingExample, rank passages with the BASE retriever (hybrid RRF +
         base reranker, the same ranking the retrieval evaluation uses). Keep the highest-scoring passages that are
         training-eligible (spec 4.10), not labelled relevant and not an exact duplicate of a positive. They are
         stored as candidates with the retriever version, rank and score.
review : a named person confirms a candidate (hard negative), marks it relevant (a false negative: it joins the
         example's positives) or rejects it (unusable). Only confirmed candidates reach a dataset version, and only
         when their work lands in the example's split (corpus.freeze_dataset).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive import audit
from archive.datasets.corpus import eligibility, resolve_anchor, work_key
from archive.evaluation import base_rankings
from archive.ingest.publish import current_index_version
from archive.models import (
    ArchivalItem,
    DatasetVersion,
    HardNegativeCandidate,
    Passage,
    TrainingExample,
    utcnow,
)
from archive.search.models import get_embedder, get_reranker

REVIEW_ACTIONS = {"confirm": "confirmed", "relevant": "false_negative", "reject": "rejected"}
NOT_A_PERSON = {"fixture-seed", "cli", "system", "worker", "hard-negative-miner", "label-import"}
_TOK = re.compile(r"\w+", re.UNICODE)


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _overlap(a: str, b: str) -> float:
    sa, sb = set(_TOK.findall(_norm(a))), set(_TOK.findall(_norm(b)))
    return round(len(sa & sb) / len(sa | sb), 3) if sa | sb else 0.0


def _person(name: str | None) -> str:
    name = (name or "").strip()
    if not name or name.lower() in NOT_A_PERSON:
        raise ValueError("a named person must review hard negatives")
    return name


def _passage_row(db: Session, pid: int) -> tuple[Passage, ArchivalItem] | None:
    row = db.execute(select(Passage, ArchivalItem).join(ArchivalItem, Passage.item_id == ArchivalItem.id)
                     .where(Passage.id == pid)).first()
    return (row[0], row[1]) if row else None


def _relation(item: ArchivalItem, pos_items: set[int], pos_works: set[str]) -> str:
    if item.id in pos_items:
        return "same_item"
    return "same_work" if work_key(item) in pos_works else "other_work"


def retriever_version(emb, rr, index_version: int | None, candidate_k: int) -> str:
    return (f"base-hybrid-rerank|embedder={emb.name}|reranker={rr.name}|index_v={index_version}"
            f"|candidate_k={candidate_k}")


def sync_example(db: Session, ex: TrainingExample) -> None:
    """Keep TrainingExample.hard_negative_passage_ids equal to its person-confirmed candidates."""
    cands = db.execute(select(HardNegativeCandidate).where(HardNegativeCandidate.training_example_id == ex.id)
                       .order_by(HardNegativeCandidate.rank.nulls_last(), HardNegativeCandidate.id)).scalars().all()
    ex.hard_negative_passage_ids = [c.passage_id for c in cands if c.status == "confirmed"]
    pending = sum(1 for c in cands if c.status == "candidate")
    ex.hard_negative_status = "unreviewed" if pending == len(cands) else "partial" if pending else "reviewed"


def mine(db: Session, *, per_question: int = 5, candidate_k: int | None = None, actor: str = "hard-negative-miner",
         example_ids: list[int] | None = None) -> dict[str, Any]:
    emb, rr = get_embedder(), get_reranker()
    index_version = current_index_version(db)
    stmt = select(TrainingExample).where(TrainingExample.reviewed_by.is_not(None),
                                         TrainingExample.dataset_version_id.is_(None))
    if example_ids:
        stmt = stmt.where(TrainingExample.id.in_(example_ids))
    examples = db.execute(stmt.order_by(TrainingExample.id)).scalars().all()
    excluded: Counter[str] = Counter({"labelled_positive": 0, "not_training_eligible": 0,
                                      "duplicate_of_positive": 0, "already_mined": 0})
    added, version = 0, None
    for ex in examples:
        positives = [r for r in (_passage_row(db, pid) for pid in ex.positive_passage_ids) if r]
        pos_ids = set(ex.positive_passage_ids)
        pos_hashes = {p.text_hash for p, _ in positives}
        pos_norms = {_norm(p.text) for p, _ in positives}
        pos_items = {i.id for _, i in positives}
        pos_works = {work_key(i) for _, i in positives}
        existing = set(db.execute(select(HardNegativeCandidate.passage_id)
                                  .where(HardNegativeCandidate.training_example_id == ex.id)).scalars())
        rk = base_rankings(db, ex.question, emb, rr, candidate_k)
        version = retriever_version(emb, rr, index_version, rk["candidate_k"])
        kept = 0
        for rank, pid in enumerate(rk["hybrid_rerank"], 1):
            if kept >= per_question:
                break
            if pid in pos_ids:
                excluded["labelled_positive"] += 1
                continue
            row = _passage_row(db, pid)
            if row is None or not eligibility(*row)[0]:
                excluded["not_training_eligible"] += 1
                continue
            p, item = row
            if p.text_hash in pos_hashes or _norm(p.text) in pos_norms:
                excluded["duplicate_of_positive"] += 1
                continue
            kept += 1
            if pid in existing:
                excluded["already_mined"] += 1
                continue
            db.add(HardNegativeCandidate(
                training_example_id=ex.id, passage_id=pid, text_sha256=p.text_hash,
                relation=_relation(item, pos_items, pos_works), retriever=version, rank=rank,
                score=rk["rerank_scores"][pid], mined_by=actor,
                provenance={"embedder": emb.name, "reranker": rr.name, "embedder_is_test_double": emb.is_test_double,
                            "reranker_is_test_double": rr.is_test_double, "index_version": index_version,
                            "candidate_k": rk["candidate_k"], "rrf": round(rk["rrf"].get(pid, 0.0), 6),
                            "keyword_rank": rk["keyword"].index(pid) + 1 if pid in rk["keyword"] else None,
                            "semantic_rank": rk["semantic"].index(pid) + 1 if pid in rk["semantic"] else None,
                            "item_id": item.id, "work_key": work_key(item), "language": p.language,
                            "max_token_overlap_with_positive": max((_overlap(p.text, q.text) for q, _ in positives),
                                                                   default=0.0)}))
            added += 1
        db.flush()
        sync_example(db, ex)
    report = {"examples": len(examples), "added": added, "excluded": dict(excluded), "retriever": version,
              "per_question": per_question}
    if examples:
        audit.record(db, actor, "hard_negative.mine", "training_example", "*", detail=report)
    db.flush()
    return report


def review(db: Session, candidate_id: int, decision: str, reviewer: str, note: str | None = None) -> dict[str, Any]:
    reviewer = _person(reviewer)
    if decision not in REVIEW_ACTIONS:
        raise ValueError(f"decision must be one of {sorted(REVIEW_ACTIONS)}")
    cand = db.get(HardNegativeCandidate, candidate_id)
    if cand is None:
        raise ValueError(f"no hard-negative candidate {candidate_id}")
    if cand.status != "candidate":
        raise ValueError(f"candidate {candidate_id} was already reviewed ({cand.status} by {cand.reviewed_by} "
                         f"on {cand.reviewed_at:%Y-%m-%d})")
    ex = db.get(TrainingExample, cand.training_example_id)
    if ex.dataset_version_id is not None:
        raise ValueError(f"example {ex.id} is frozen in dataset version {ex.dataset_version_id}")
    cand.status = REVIEW_ACTIONS[decision]
    cand.reviewed_by, cand.reviewed_at, cand.review_note = reviewer, utcnow(), note
    warning = None
    if decision == "relevant":
        if cand.passage_id not in ex.positive_passage_ids:
            ex.positive_passage_ids = [*ex.positive_passage_ids, cand.passage_id]
        row = _passage_row(db, cand.passage_id)
        if row and work_key(row[1]) != ex.group_key:
            warning = (f"passage {cand.passage_id} is in work '{work_key(row[1])}' but example {ex.id} belongs to "
                       f"'{ex.group_key}'. Give both items one capture_details.work_key (same text in another edition "
                       "is one work), otherwise the example's positives span splits and it is left out at freeze.")
    sync_example(db, ex)
    audit.record(db, reviewer, "hard_negative.review", "hard_negative_candidate", cand.id,
                 detail={"example_id": ex.id, "passage_id": cand.passage_id, "decision": cand.status, "note": note})
    db.flush()
    return {"candidate_id": cand.id, "example_id": ex.id, "passage_id": cand.passage_id, "status": cand.status,
            "reviewed_by": reviewer, "reviewed_at": cand.reviewed_at.isoformat(),
            "positive_passage_ids": list(ex.positive_passage_ids),
            "hard_negative_passage_ids": list(ex.hard_negative_passage_ids), "warning": warning}


def import_label_negatives(db: Session, ex: TrainingExample, lab: dict[str, Any], importer: str) -> list[str]:
    """Hard negatives listed in a labels file were already confirmed by a person (confirmed_by); they are stored
    as confirmed candidates with retriever 'label-import'. Returns problems for rows that were skipped."""
    problems = []
    pos_rows = [r for r in (_passage_row(db, pid) for pid in ex.positive_passage_ids) if r]
    pos_hashes = {p.text_hash for p, _ in pos_rows}
    pos_items, pos_works = {i.id for _, i in pos_rows}, {work_key(i) for _, i in pos_rows}
    for neg in lab.get("hard_negatives", []):
        tag = f"{lab.get('id')}: hard negative {neg.get('item_key')}/{neg.get('anchor', '')[:30]!r}"
        try:
            confirmed_by = _person(neg.get("confirmed_by"))
        except ValueError:
            problems.append(f"{tag} has no confirmed_by person; skipped")
            continue
        row = resolve_anchor(db, neg.get("item_key", ""), neg.get("anchor", ""))
        if row is None:
            problems.append(f"{tag} not found among published passages; skipped")
            continue
        p, item = row
        if not eligibility(p, item)[0]:
            problems.append(f"{tag} is not training-eligible ({eligibility(p, item)[1]}); skipped")
            continue
        if p.id in ex.positive_passage_ids or p.text_hash in pos_hashes:
            problems.append(f"{tag} is a positive or duplicates one; skipped")
            continue
        db.add(HardNegativeCandidate(
            training_example_id=ex.id, passage_id=p.id, text_sha256=p.text_hash,
            relation=_relation(item, pos_items, pos_works), retriever="label-import", status="confirmed",
            provenance={"source": "labels file", "label_id": lab.get("id"), "anchor": neg.get("anchor")},
            mined_by=importer, reviewed_by=confirmed_by, reviewed_at=utcnow(), review_note="confirmed in labels file"))
    db.flush()
    sync_example(db, ex)
    return problems


def list_candidates(db: Session, status: str | None = "candidate", limit: int = 200) -> list[dict[str, Any]]:
    """Reviewer worklist: question, positive and candidate text side by side."""
    stmt = select(HardNegativeCandidate, TrainingExample).join(
        TrainingExample, HardNegativeCandidate.training_example_id == TrainingExample.id)
    if status:
        stmt = stmt.where(HardNegativeCandidate.status == status)
    out = []
    for c, ex in db.execute(stmt.order_by(TrainingExample.id, HardNegativeCandidate.rank.nulls_last())
                            .limit(limit)).all():
        cand = _passage_row(db, c.passage_id)
        pos = _passage_row(db, ex.positive_passage_ids[0]) if ex.positive_passage_ids else None
        out.append({"candidate_id": c.id, "example_id": ex.id, "question": ex.question, "language": ex.language,
                    "status": c.status, "rank": c.rank, "score": c.score, "relation": c.relation,
                    "retriever": c.retriever, "passage_id": c.passage_id,
                    "candidate_item": cand[1].title if cand else None,
                    "candidate_text": cand[0].text[:600] if cand else None,
                    "positive_text": pos[0].text[:300] if pos else None,
                    "reviewed_by": c.reviewed_by, "reviewed_at": c.reviewed_at, "decision": None, "note": None})
    return out


def export_labels(db: Session, dv: DatasetVersion) -> dict[str, Any]:
    """Labels-file view of a frozen dataset version, for eval/check_training_leakage.py."""
    def ref(pid: int) -> dict[str, str] | None:
        row = _passage_row(db, pid)
        return {"item_key": str((row[1].capture_details or {}).get("item_key", "")), "anchor": row[0].text[:80]} \
            if row else None

    labels = []
    for e in dv.manifest.get("examples", []):
        labels.append({"id": f"ex-{e['example_id']}", "question": e["question"], "language": e["language"],
                       "origin": e["origin"], "reviewed_by": e["reviewed_by"], "split": e["split"],
                       "positives": [r for r in map(ref, e["positive_passage_ids"]) if r],
                       "hard_negatives": [{**r, "confirmed_by": h["reviewed_by"]} for h in e.get("hard_negatives", [])
                                          if (r := ref(h["passage_id"]))]})
    return {"_note": f"exported from dataset version {dv.name} ({dv.manifest_sha256})", "labels": labels}

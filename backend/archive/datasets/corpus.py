"""Training-eligible corpus, dataset versions, work-level splits and the minimum-data gate (spec 4.10, 7.3)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive import audit
from archive.models import (
    ArchivalItem,
    DatasetVersion,
    HardNegativeCandidate,
    MediaSegment,
    ModelVersion,
    Page,
    Passage,
    PublicationState,
    RightsRecord,
    TrainingExample,
)

ELIGIBLE_KINDS = {"source_text", "reviewed_transcription", "reviewed_transcript"}
ELIGIBLE_BASIS = {"full_review", "sampled_batch", "spot_check"}
GATE_PATH = Path(__file__).with_name("training_gate.json")
SPLIT_RATIOS = (("train", 0.7), ("dev", 0.15), ("test", 0.15))


def eligibility(passage: Passage, item: ArchivalItem) -> tuple[bool, str]:
    """Every rule must hold; returns (eligible, reason-if-not)."""
    if item.rights.training_permission != "allowed":
        return False, f"training permission is {item.rights.training_permission}"
    if item.publication_state != PublicationState.published.value or passage.item_version_id != item.published_version_id:
        return False, "not in the current published version"
    if not passage.indexed:
        return False, "not indexed"
    if passage.kind not in ELIGIBLE_KINDS:
        return False, f"kind {passage.kind} is not source text or a reviewed transcript"
    if passage.review_basis not in ELIGIBLE_BASIS:
        return False, f"review basis {passage.review_basis} not allowed"
    return True, ""


def work_key(item: ArchivalItem) -> str:
    """All editions of one work share a key so they land in the same split."""
    return str((item.capture_details or {}).get("work_key") or item.rights.source_key)


def eligible_passages(db: Session) -> list[tuple[Passage, ArchivalItem]]:
    rows = db.execute(select(Passage, ArchivalItem).join(ArchivalItem, Passage.item_id == ArchivalItem.id)
                      .join(RightsRecord, ArchivalItem.rights_record_id == RightsRecord.id)
                      .order_by(Passage.id)).all()
    return [(p, i) for p, i in rows if eligibility(p, i)[0]]


def assign_split(group: str, groups_sorted: list[str]) -> str:
    """Deterministic work-level split; guarantees test and dev get whole works when there are >= 3 works."""
    n = len(groups_sorted)
    if n >= 3:
        order = sorted(groups_sorted, key=lambda g: hashlib.sha256(g.encode()).hexdigest())
        idx = order.index(group)
        n_test = max(1, round(n * 0.15))
        n_dev = max(1, round(n * 0.15))
        if idx < n_test:
            return "test"
        if idx < n_test + n_dev:
            return "dev"
        return "train"
    h = int(hashlib.sha256(group.encode()).hexdigest(), 16) % 100
    acc = 0
    for name, ratio in SPLIT_RATIOS:
        acc += int(ratio * 100)
        if h < acc:
            return name
    return "train"


def load_gate() -> dict[str, Any]:
    return json.loads(GATE_PATH.read_text(encoding="utf-8"))


def gate_report(works_by_split: dict[str, set[str]], pairs_by_split: dict[str, int],
                test_pairs_by_lang: dict[str, int], gate: dict[str, Any] | None = None) -> dict[str, Any]:
    gate = gate or load_gate()
    total_works = len(set().union(*works_by_split.values())) if works_by_split else 0
    checks = {
        "independent_works_total": {"have": total_works, "need": gate["min_independent_works_total"]},
        "works_in_test": {"have": len(works_by_split.get("test", set())), "need": gate["min_works_in_test"]},
    }
    for split, need in gate["min_pairs"].items():
        checks[f"pairs_{split}"] = {"have": pairs_by_split.get(split, 0), "need": need}
    for v in checks.values():
        v["ok"] = v["have"] >= v["need"]
    claimable = [lang for lang, n in test_pairs_by_lang.items() if n >= gate["min_test_pairs_per_claimed_language"]]
    met = all(v["ok"] for v in checks.values())
    return {"gate_version": gate["version"], "met": met, "checks": checks, "claimable_languages": claimable,
            "note": "CI separation is checked at comparison time; trained-model results are shown only if met."}


def _build(db: Session) -> dict[str, Any]:
    """Everything a dataset version would contain, without writing anything."""
    pairs = eligible_passages(db)
    groups = sorted({work_key(i) for _, i in pairs})
    entries = []
    for p, item in pairs:
        page = db.get(Page, p.page_id) if p.page_id else None
        seg = db.get(MediaSegment, p.media_segment_id) if p.media_segment_id else None
        entries.append({
            "passage_id": p.id, "item_id": item.id, "text_version": p.text_version,
            "text_sha256": p.text_hash, "language": p.language, "edition": item.edition, "volume": item.volume,
            "anchor": {"page_sequence": page.sequence, "char_start": p.char_start, "char_end": p.char_end}
            if page else {"start_ms": seg.start_ms, "end_ms": seg.end_ms} if seg else None,
            "rights_status": item.rights.display_permission, "training_basis": item.rights.training_basis,
            "rights_source_key": item.rights.source_key, "reviewer": p.approved_by,
            "approved_at": p.approved_at.isoformat(), "review_basis": p.review_basis,
            "group_key": work_key(item), "split": assign_split(work_key(item), groups),
        })
    examples = db.execute(select(TrainingExample).where(TrainingExample.dataset_version_id.is_(None))
                          .order_by(TrainingExample.id)).scalars().all()
    pid_split = {e["passage_id"]: e["split"] for e in entries}
    works_by_split: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        works_by_split[e["split"]].add(e["group_key"])
    reviewed: dict[int, list[HardNegativeCandidate]] = defaultdict(list)
    if examples:
        for c in db.execute(select(HardNegativeCandidate).where(
                HardNegativeCandidate.training_example_id.in_([ex.id for ex in examples]))
                .order_by(HardNegativeCandidate.rank.nulls_last(), HardNegativeCandidate.id)).scalars():
            reviewed[c.training_example_id].append(c)
    hn: Counter[str] = Counter({"confirmed_included": 0, "cross_split_excluded": 0, "ineligible_excluded": 0,
                                "unreviewed_excluded": 0, "rejected_or_relevant": 0})
    pairs_by_split: Counter[str] = Counter()
    test_by_lang: Counter[str] = Counter()
    rows, excluded_examples = [], []
    for ex in examples:
        splits = {pid_split.get(pid) for pid in ex.positive_passage_ids}
        splits.discard(None)
        split = splits.pop() if len(splits) == 1 else None  # positives missing or span splits: excluded
        negs = []
        for c in reviewed.get(ex.id, []):
            if c.status == "candidate":
                hn["unreviewed_excluded"] += 1
            elif c.status != "confirmed":
                hn["rejected_or_relevant"] += 1
            elif split is None:
                continue
            elif c.passage_id not in pid_split:
                hn["ineligible_excluded"] += 1
            elif pid_split[c.passage_id] != split:
                hn["cross_split_excluded"] += 1  # its work sits in another split: would leak across splits
            else:
                hn["confirmed_included"] += 1
                negs.append({"passage_id": c.passage_id, "reviewed_by": c.reviewed_by,
                             "reviewed_at": c.reviewed_at.isoformat(), "retriever": c.retriever, "rank": c.rank,
                             "score": c.score, "relation": c.relation})
        if split is None:
            excluded_examples.append(ex.id)
            continue
        pairs_by_split[split] += len(ex.positive_passage_ids)
        if split == "test":
            test_by_lang[ex.language] += 1
        rows.append({"example_id": ex.id, "question": ex.question, "language": ex.language, "origin": ex.origin,
                     "reviewed_by": ex.reviewed_by, "split": split, "group_key": ex.group_key,
                     "positive_passage_ids": list(ex.positive_passage_ids),
                     "hard_negative_passage_ids": [n["passage_id"] for n in negs], "hard_negatives": negs})
    return {"entries": entries, "examples": rows, "excluded_examples": excluded_examples,
            "works_by_split": works_by_split, "hard_negatives": dict(hn),
            "gate": gate_report(works_by_split, dict(pairs_by_split), dict(test_by_lang)),
            "pairs_by_split": dict(pairs_by_split), "_example_rows": examples}


def manifest_leakage(manifest: dict[str, Any]) -> list[str]:
    """Work-level split check: a work in one split only, and every positive and hard negative of an example in the
    example's split."""
    problems = []
    work_splits: dict[str, set[str]] = defaultdict(set)
    for e in manifest.get("entries", []):
        work_splits[e["group_key"]].add(e["split"])
    problems += [f"work {w} is in splits {sorted(s)}" for w, s in work_splits.items() if len(s) > 1]
    pid_split = {e["passage_id"]: e["split"] for e in manifest.get("entries", [])}
    for ex in manifest.get("examples", []):
        for kind in ("positive_passage_ids", "hard_negative_passage_ids"):
            for pid in ex.get(kind, []):
                if pid_split.get(pid) != ex["split"]:
                    problems.append(f"example {ex['example_id']} ({ex['split']}) has {kind[:-4]} {pid} in "
                                    f"split {pid_split.get(pid)}")
    return problems


def preview_dataset(db: Session) -> dict[str, Any]:
    """Read-only: what the next dataset version and its gate report would be."""
    b = _build(db)
    return {"passages": len(b["entries"]), "items": len({e["item_id"] for e in b["entries"]}),
            "works_by_split": {k: len(v) for k, v in b["works_by_split"].items()},
            "examples_by_split": dict(Counter(r["split"] for r in b["examples"])),
            "pairs_by_split": b["pairs_by_split"], "excluded_examples": b["excluded_examples"],
            "hard_negatives": b["hard_negatives"], "gate": b["gate"], "entries": b["entries"],
            "leakage": manifest_leakage({"entries": b["entries"], "examples": b["examples"]})}


def freeze_dataset(db: Session, name: str, actor: str) -> DatasetVersion:
    b = _build(db)
    entries, report, works_by_split = b["entries"], b["gate"], b["works_by_split"]
    manifest = {"name": name, "rules": "spec 4.10: training permission allowed; approved text from fully reviewed "
                                        "page or passed sample batch; source text or reviewed transcript only",
                "hard_negative_policy": "spec 7.3 step 2: person-confirmed candidates only, training-eligible, "
                                        "and in the same work-level split as the example",
                "entries": entries, "examples": b["examples"], "hard_negatives": b["hard_negatives"]}
    problems = manifest_leakage(manifest)
    if problems:
        raise RuntimeError(f"split leakage, not freezing: {problems[:5]}")
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    dv = DatasetVersion(
        name=name, manifest=manifest, manifest_sha256=digest,
        languages=sorted({e["language"] for e in entries}), item_count=len({e["item_id"] for e in entries}),
        passage_count=len(entries),
        permission_summary=dict(Counter(e["training_basis"] or "unrecorded" for e in entries)),
        split_definition={"method": "work-level deterministic hash; editions of a work share group_key",
                          "works": {k: sorted(v) for k, v in works_by_split.items()}},
        gate_report=report, created_by=actor)
    db.add(dv)
    db.flush()
    rows = {r["example_id"]: r for r in b["examples"]}
    for ex in b["_example_rows"]:
        row = rows.get(ex.id)
        ex.split = row["split"] if row else None
        if row:
            ex.dataset_version_id = dv.id
            ex.hard_negative_passage_ids = row["hard_negative_passage_ids"]
    audit.record(db, actor, "dataset.freeze", "dataset_version", dv.id,
                 detail={"passages": len(entries), "examples": len(rows), "sha256": digest, "gate_met": report["met"],
                         "hard_negatives": b["hard_negatives"]})
    return dv


def flag_datasets_for_rights(db: Session, rights_record_id: int, actor: str) -> dict[str, list[int]]:
    """Training permission revoked: flag dataset versions that contain the source and models trained on them."""
    item_ids = set(db.execute(select(ArchivalItem.id).where(ArchivalItem.rights_record_id == rights_record_id)).scalars())
    flagged_ds, flagged_models = [], []
    for dv in db.execute(select(DatasetVersion)).scalars():
        if any(e["item_id"] in item_ids for e in dv.manifest.get("entries", [])):
            dv.status = "flagged"
            flagged_ds.append(dv.id)
            for mv in db.execute(select(ModelVersion).where(ModelVersion.dataset_version_id == dv.id)).scalars():
                mv.status = "flagged"
                flagged_models.append(mv.id)
    if flagged_ds:
        audit.record(db, actor, "dataset.flag", "rights_record", rights_record_id,
                     detail={"datasets": flagged_ds, "models": flagged_models})
    return {"datasets": flagged_ds, "models": flagged_models}


def resolve_anchor(db: Session, item_key: str, anchor: str) -> tuple[Passage, ArchivalItem] | None:
    """Locate a published passage by item_key + a verbatim anchor snippet (passage IDs change between databases)."""
    item = db.execute(select(ArchivalItem).where(ArchivalItem.capture_details["item_key"].astext == item_key)).scalar()
    if item is None or item.published_version_id is None or not anchor:
        return None
    hit = db.execute(select(Passage).where(Passage.item_version_id == item.published_version_id,
                                           Passage.text.contains(anchor)).order_by(Passage.id)).scalars().first()
    return (hit, item) if hit else None


def load_labels(db: Session, labels: list[dict[str, Any]], reviewer: str) -> tuple[int, list[str]]:
    """Import reviewed question-passage labels. Unreviewed or unresolved labels are rejected. Hard negatives in
    the file are imported only when a person is named in confirmed_by (spec 7.3 step 2)."""
    from archive.datasets.hard_negatives import import_label_negatives

    added, problems = 0, []
    for lab in labels:
        if not lab.get("reviewed_by"):
            problems.append(f"{lab.get('id')}: not reviewed; skipped")
            continue
        if lab.get("origin") not in ("human", "synthetic_reviewed"):
            problems.append(f"{lab.get('id')}: origin must be human or synthetic_reviewed")
            continue
        hits = [r for r in (resolve_anchor(db, pos["item_key"], pos["anchor"]) for pos in lab.get("positives", [])) if r]
        if not hits:
            problems.append(f"{lab.get('id')}: positives not found among published passages")
            continue
        ex = TrainingExample(question=lab["question"], language=lab["language"], origin=lab["origin"],
                             positive_passage_ids=[p.id for p, _ in hits], group_key=work_key(hits[0][1]),
                             reviewed_by=lab["reviewed_by"])
        db.add(ex)
        db.flush()
        problems += import_label_negatives(db, ex, lab, reviewer)
        added += 1
    db.flush()
    return added, problems

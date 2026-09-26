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


def freeze_dataset(db: Session, name: str, actor: str) -> DatasetVersion:
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
    manifest = {"name": name, "rules": "spec 4.10: training permission allowed; approved text from fully reviewed "
                                        "page or passed sample batch; source text or reviewed transcript only",
                "entries": entries}
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    examples = db.execute(select(TrainingExample).where(TrainingExample.dataset_version_id.is_(None))).scalars().all()
    pid_split = {e["passage_id"]: e["split"] for e in entries}
    works_by_split: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        works_by_split[e["split"]].add(e["group_key"])
    pairs_by_split: Counter[str] = Counter()
    test_by_lang: Counter[str] = Counter()
    for ex in examples:
        splits = {pid_split.get(pid) for pid in ex.positive_passage_ids}
        splits.discard(None)
        if len(splits) == 1:
            ex.split = splits.pop()
            pairs_by_split[ex.split] += len(ex.positive_passage_ids)
            if ex.split == "test":
                test_by_lang[ex.language] += 1
        else:
            ex.split = None  # positives missing or span splits: excluded from training/eval
    report = gate_report(works_by_split, dict(pairs_by_split), dict(test_by_lang))
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
    for ex in examples:
        if ex.split:
            ex.dataset_version_id = dv.id
    audit.record(db, actor, "dataset.freeze", "dataset_version", dv.id,
                 detail={"passages": len(entries), "sha256": digest, "gate_met": report["met"]})
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


def load_labels(db: Session, labels: list[dict[str, Any]], reviewer: str) -> tuple[int, list[str]]:
    """Import reviewed question-passage labels. Positives are located by item_key + a verbatim anchor
    snippet (passage IDs change between databases). Unreviewed or unresolved labels are rejected."""
    added, problems = 0, []
    for lab in labels:
        if not lab.get("reviewed_by"):
            problems.append(f"{lab.get('id')}: not reviewed; skipped")
            continue
        if lab.get("origin") not in ("human", "synthetic_reviewed"):
            problems.append(f"{lab.get('id')}: origin must be human or synthetic_reviewed")
            continue
        pids = []
        for pos in lab.get("positives", []):
            item = db.execute(select(ArchivalItem).where(
                ArchivalItem.capture_details["item_key"].astext == pos["item_key"])).scalar()
            if item is None or item.published_version_id is None:
                continue
            hit = db.execute(select(Passage.id).where(Passage.item_version_id == item.published_version_id,
                                                      Passage.text.contains(pos["anchor"]))).scalars().first()
            if hit:
                pids.append(hit)
        if not pids:
            problems.append(f"{lab.get('id')}: positives not found among published passages")
            continue
        item0 = db.execute(select(ArchivalItem).join(Passage, Passage.item_id == ArchivalItem.id)
                           .where(Passage.id == pids[0])).scalar()
        db.add(TrainingExample(question=lab["question"], language=lab["language"], origin=lab["origin"],
                               positive_passage_ids=pids, group_key=work_key(item0), reviewed_by=lab["reviewed_by"]))
        added += 1
    db.flush()
    return added, problems

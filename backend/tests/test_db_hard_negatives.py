"""Hard-negative mining and human review (spec 7.3 step 2, 10.1 "Training split"), against a real database.
Retrieval uses the deterministic test doubles from conftest; no trained model is involved."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from archive.datasets import hard_negatives as hn
from archive.datasets.corpus import freeze_dataset, load_labels, manifest_leakage, preview_dataset
from archive.ingest import publish, review
from archive.models import (
    AuditEvent,
    DatasetVersion,
    Derivative,
    HardNegativeCandidate,
    Passage,
    TrainingExample,
    Translation,
)

from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db

FEE = "The reading room charged no fee for reading within the rooms, because a fee keeps readers out."
NEAR = "The reading room committee debated whether a fee for reading would keep poor readers out of the rooms."
LAMP = "The committee bought a single lamp and three newspapers for the reading room in 1921."


def _pids(db, item) -> list[int]:
    return list(db.execute(select(Passage.id).where(Passage.item_version_id == item.published_version_id)
                           .order_by(Passage.id)).scalars())


def _example(db, item, question="Did the reading room charge a fee for reading?", language="en"):
    ex = TrainingExample(question=question, language=language, origin="human", positive_passage_ids=_pids(db, item)[:1],
                         group_key=item.capture_details["work_key"], reviewed_by="label-reviewer")
    db.add(ex)
    db.flush()
    return ex


@pytest.fixture
def corpus(db):
    ok = make_rights(db, key="hn-ok")
    blocked = make_rights(db, key="hn-no-training", training="not_allowed")
    pos = make_item(db, ok, [FEE, "A second page of the rules about opening hours in the reading room."],
                    title="Rules", item_key="hn-rules")
    near = make_item(db, ok, [NEAR], title="Committee debate", item_key="hn-debate")
    lamp = make_item(db, ok, [LAMP], title="Purchases", item_key="hn-purchases")
    no_train = make_item(db, blocked, [NEAR + " (blocked copy)"], title="Blocked", item_key="hn-blocked")
    dup = make_item(db, ok, [FEE], title="Reprint", item_key="hn-reprint")
    unpublished = make_item(db, ok, [NEAR + " Unpublished draft."], title="Draft", item_key="hn-draft")
    withdrawn = make_item(db, ok, [NEAR + " Withdrawn copy."], title="Withdrawn", item_key="hn-withdrawn")
    for it in (pos, near, lamp, no_train, dup, withdrawn):
        publish_item(db, it)
    publish.withdraw(db, withdrawn, "archivist", "test withdrawal")
    # A reviewed translation becomes a published passage; it is never training data (spec 4.10 rule 3).
    src = _pids(db, near)[0]
    tr = Translation(source_passage_id=src, target_language="hi", text="पढ़ने के शुल्क पर समिति की बहस", method="human")
    db.add(tr)
    db.flush()
    review.review_translation(db, tr, "approve", "rev", ["hi"])
    publish_item(db, near)
    # An unreviewed machine translation, a summary and an AI answer are not passages at all.
    db.add(Translation(source_passage_id=src, target_language="mr", text="शुल्क", method="machine"))
    db.add(Derivative(kind="summary", item_id=near.id, language="en", content=FEE, generator="test",
                      label_shown="Summary draft"))
    db.commit()
    return {"pos": pos, "near": near, "lamp": lamp, "no_train": no_train, "dup": dup,
            "unpublished": unpublished, "withdrawn": withdrawn}


class TestMining:
    def test_mining_excludes_positives_duplicates_and_ineligible_passages(self, db, corpus):
        ex = _example(db, corpus["pos"])
        report = hn.mine(db, per_question=20, actor="miner")
        got = {c.passage_id for c in db.execute(select(HardNegativeCandidate)).scalars()}
        allowed = set(_pids(db, corpus["near"])) | set(_pids(db, corpus["lamp"])) | set(_pids(db, corpus["pos"])[1:])
        translations = set(db.execute(select(Passage.id).where(Passage.kind == "reviewed_translation")).scalars())
        assert translations and got, report
        assert not (got & set(ex.positive_passage_ids))                     # labelled positives
        assert not (got & set(_pids(db, corpus["dup"])))                    # exact duplicate text in a reprint
        assert not (got & set(_pids(db, corpus["no_train"])))               # training permission not allowed
        assert not (got & translations)                                     # reviewed translations
        withdrawn_pids = set(db.execute(select(Passage.id).where(Passage.item_id == corpus["withdrawn"].id)).scalars())
        unpublished_pids = set(db.execute(select(Passage.id).where(Passage.item_id == corpus["unpublished"].id)).scalars())
        assert not (got & (withdrawn_pids | unpublished_pids))
        assert got <= allowed
        assert report["excluded"]["duplicate_of_positive"] >= 1
        assert report["excluded"]["not_training_eligible"] >= 1

    def test_candidates_carry_retriever_provenance_and_relation(self, db, corpus):
        _example(db, corpus["pos"])
        hn.mine(db, per_question=20, actor="miner")
        cands = db.execute(select(HardNegativeCandidate).order_by(HardNegativeCandidate.rank)).scalars().all()
        assert all(c.status == "candidate" and c.reviewed_by is None for c in cands)
        assert all(c.rank >= 1 and isinstance(c.score, float) and c.text_sha256 for c in cands)
        assert all("hash-embedder" in c.retriever and "lexical-overlap-reranker" in c.retriever for c in cands)
        assert all(c.provenance["index_version"] is not None and c.provenance["candidate_k"] for c in cands)
        relations = {c.passage_id: c.relation for c in cands}
        assert relations[_pids(db, corpus["pos"])[1]] == "same_item"       # same work, a different passage
        assert relations[_pids(db, corpus["lamp"])[0]] == "other_work"

    def test_mining_is_idempotent(self, db, corpus):
        _example(db, corpus["pos"])
        first = hn.mine(db, per_question=20, actor="miner")
        second = hn.mine(db, per_question=20, actor="miner")
        assert first["added"] > 0 and second["added"] == 0
        assert db.execute(select(HardNegativeCandidate)).scalars().all().__len__() == first["added"]

    def test_unreviewed_examples_are_not_mined(self, db, corpus):
        ex = _example(db, corpus["pos"])
        ex.reviewed_by = None
        db.flush()
        assert hn.mine(db, per_question=20, actor="miner")["examples"] == 0


class TestReview:
    def _one(self, db, corpus, passage_item="near"):
        ex = _example(db, corpus["pos"])
        hn.mine(db, per_question=20, actor="miner")
        pid = _pids(db, corpus[passage_item])[0]
        cand = db.execute(select(HardNegativeCandidate).where(HardNegativeCandidate.passage_id == pid)).scalar_one()
        return ex, cand

    def test_confirm_makes_a_hard_negative_with_reviewer_and_date(self, db, corpus):
        ex, cand = self._one(db, corpus)
        hn.review(db, cand.id, "confirm", "Named Reviewer", note="different topic")
        assert cand.status == "confirmed" and cand.reviewed_by == "Named Reviewer" and cand.reviewed_at
        assert ex.hard_negative_passage_ids == [cand.passage_id]
        assert cand.passage_id not in ex.positive_passage_ids
        assert db.execute(select(AuditEvent).where(AuditEvent.action == "hard_negative.review")).scalar()

    def test_relevant_flips_a_false_negative_into_the_labels(self, db, corpus):
        ex, cand = self._one(db, corpus)
        before = list(ex.positive_passage_ids)
        out = hn.review(db, cand.id, "relevant", "Named Reviewer", note="says the same thing")
        assert cand.status == "false_negative"
        assert ex.positive_passage_ids == before + [cand.passage_id]
        assert cand.passage_id not in ex.hard_negative_passage_ids
        assert out["warning"]  # the new positive is in another work: needs a shared work key to stay in one split

    def test_reject_excludes_without_changing_labels(self, db, corpus):
        ex, cand = self._one(db, corpus)
        hn.review(db, cand.id, "reject", "Named Reviewer", note="ambiguous")
        assert cand.status == "rejected" and ex.hard_negative_passage_ids == []

    def test_review_needs_a_named_person_and_happens_once(self, db, corpus):
        _, cand = self._one(db, corpus)
        with pytest.raises(ValueError):
            hn.review(db, cand.id, "confirm", "  ")
        with pytest.raises(ValueError):
            hn.review(db, cand.id, "confirm", "fixture-seed")
        with pytest.raises(ValueError):
            hn.review(db, cand.id, "maybe", "Named Reviewer")
        hn.review(db, cand.id, "confirm", "Named Reviewer")
        with pytest.raises(ValueError):
            hn.review(db, cand.id, "relevant", "Other Reviewer")

    def test_cli_worksheet_round_trip(self, db, corpus, tmp_path, capsys):
        from archive import cli

        _example(db, corpus["pos"])
        db.commit()
        cli.main(["mine-hard-negatives", "--per-question", "3"])
        sheet = tmp_path / "sheet.json"
        cli.main(["list-hard-negatives", "--out", str(sheet)])
        data = json.loads(sheet.read_text(encoding="utf-8"))
        assert len(data["candidates"]) == 3 and all(r["candidate_text"] for r in data["candidates"])
        data["candidates"][0]["decision"] = "confirm"
        data["candidates"][1]["decision"] = "relevant"
        sheet.write_text(json.dumps(data), encoding="utf-8")
        cli.main(["review-hard-negatives", "--file", str(sheet), "--reviewer", "Named Reviewer"])
        db.expire_all()
        assert sorted(c.status for c in db.execute(select(HardNegativeCandidate)).scalars()) == [
            "candidate", "confirmed", "false_negative"]
        capsys.readouterr()
        cli.main(["dataset-preview"])
        assert json.loads(capsys.readouterr().out)["gate"]["met"] is False

    def test_load_labels_imports_person_confirmed_hard_negatives(self, db, corpus):
        labels = [{"id": "l1", "question": "Did the reading room charge a fee?", "language": "en", "origin": "human",
                   "reviewed_by": "Named Reviewer",
                   "positives": [{"item_key": "hn-rules", "anchor": "charged no fee"}],
                   "hard_negatives": [{"item_key": "hn-purchases", "anchor": "single lamp", "confirmed_by": "Named Reviewer"},
                                      {"item_key": "hn-debate", "anchor": "committee debated"},
                                      {"item_key": "hn-blocked", "anchor": "blocked copy", "confirmed_by": "Named Reviewer"}]}]
        added, problems = load_labels(db, labels, "Named Reviewer")
        assert added == 1
        cands = db.execute(select(HardNegativeCandidate)).scalars().all()
        assert [(c.passage_id, c.status, c.retriever) for c in cands] == [
            (_pids(db, corpus["lamp"])[0], "confirmed", "label-import")]
        assert any("confirmed_by" in p for p in problems)
        assert any("not training-eligible" in p for p in problems)
        ex = db.execute(select(TrainingExample)).scalar_one()
        assert ex.hard_negative_passage_ids == [_pids(db, corpus["lamp"])[0]]


class TestManifest:
    def _works(self, db, n=7):
        ok = make_rights(db, key="hn-split")
        items = [make_item(db, ok, [f"work number {i} discusses lamps and reading rooms"], title=f"W{i}",
                           item_key=f"hw{i}") for i in range(n)]
        for it in items:
            publish_item(db, it)
        db.commit()
        return items

    def test_manifest_includes_only_confirmed_hard_negatives(self, db):
        items = self._works(db)
        preview = preview_dataset(db)
        split_of = {e["item_id"]: e["split"] for e in preview["entries"]}
        anchor = items[0]
        same = [it for it in items[1:] if split_of[it.id] == split_of[anchor.id]]
        if not same:
            pytest.skip("hash split put no second work beside the anchor work")
        ex = _example(db, anchor, question="What does work 0 discuss?")
        hn.mine(db, per_question=20, actor="miner")
        cands = {c.passage_id: c for c in db.execute(select(HardNegativeCandidate)).scalars()}
        keep = cands[_pids(db, same[0])[0]]
        hn.review(db, keep.id, "confirm", "Named Reviewer")
        others = [c for pid, c in cands.items() if c.id != keep.id]
        if len(others) >= 2:
            hn.review(db, others[0].id, "reject", "Named Reviewer")
        dv = freeze_dataset(db, "hn-v1", "tester")
        examples = {e["example_id"]: e for e in dv.manifest["examples"]}
        assert examples[ex.id]["hard_negative_passage_ids"] == [keep.passage_id]
        assert dv.manifest["hard_negatives"]["confirmed_included"] == 1
        assert dv.manifest["hard_negatives"]["unreviewed_excluded"] >= 1

    def test_cross_split_hard_negatives_are_dropped_so_no_work_leaks(self, db):
        items = self._works(db)
        split_of = {e["item_id"]: e["split"] for e in preview_dataset(db)["entries"]}
        anchor = items[0]
        other = next(it for it in items[1:] if split_of[it.id] != split_of[anchor.id])
        ex = _example(db, anchor, question="What does work 0 discuss?")
        hn.mine(db, per_question=20, actor="miner")
        cand = db.execute(select(HardNegativeCandidate).where(
            HardNegativeCandidate.passage_id == _pids(db, other)[0])).scalar_one()
        hn.review(db, cand.id, "confirm", "Named Reviewer")
        dv = freeze_dataset(db, "hn-v2", "tester")
        row = next(e for e in dv.manifest["examples"] if e["example_id"] == ex.id)
        assert cand.passage_id not in row["hard_negative_passage_ids"]
        assert dv.manifest["hard_negatives"]["cross_split_excluded"] == 1
        assert manifest_leakage(dv.manifest) == []
        assert db.get(TrainingExample, ex.id).hard_negative_passage_ids == []

    def test_leakage_check_catches_a_work_in_two_splits(self, db):
        self._works(db)
        dv = freeze_dataset(db, "hn-v3", "tester")
        bad = {**dv.manifest, "entries": [dict(e) for e in dv.manifest["entries"]]}
        bad["entries"].append({**bad["entries"][0], "passage_id": -1,
                               "split": "test" if bad["entries"][0]["split"] != "test" else "train"})
        assert manifest_leakage(bad)

    def test_exported_labels_pass_the_heldout_leakage_script(self, db):
        items = self._works(db)
        _example(db, items[0], question="What does work 0 discuss?")
        dv = freeze_dataset(db, "hn-v4", "tester")
        exported = hn.export_labels(db, dv)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))
        try:
            import check_training_leakage as leak
        finally:
            sys.path.pop(0)
        heldout = [{"id": "q1", "question": "Which lamp did the committee buy?", "language": "en", "positives": []}]
        assert leak.check(heldout, exported["labels"], 0.8)[0] == []
        leaked = [{"id": "q2", "question": "What does work 0 discuss?", "language": "en", "positives": []}]
        assert leak.check(leaked, exported["labels"], 0.8)[0]

    def test_preview_writes_nothing(self, db):
        self._works(db)
        report = preview_dataset(db)
        assert report["gate"]["met"] is False and report["passages"] == 7
        assert db.execute(select(DatasetVersion)).first() is None

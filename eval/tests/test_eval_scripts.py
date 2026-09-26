"""Tests for the standalone evaluation scripts. No backend, database or network needed:
python -m pytest eval/tests -q"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import calibrate_gate
import check_results
import check_training_leakage
import paired_bootstrap
import summarize_grading
import verify_restore_log
from evalkit import MEASURED, UNMEASURED, percentile
from results_schema import REQUIRED_AREAS, blank_results

EVAL_DIR = Path(__file__).resolve().parents[1]


def _measure(results, area, metric, **fields):
    m = results["areas"][area]["metrics"][metric]
    m.update({"status": MEASURED, "value": 0.5, "n": 40, "measured_at": "2026-10-01", "method": "x",
              "evidence": "eval/results/x.json", **fields})
    results["run"].update({"date": "2026-10-01"})
    results["run"]["dataset"]["is_synthetic_fixture"] = False
    return m


class TestResultsTemplate:
    def test_blank_template_is_valid_and_entirely_unmeasured(self):
        results = blank_results()

        errors, _ = check_results.check(results)

        assert errors == []
        assert set(results["areas"]) == set(REQUIRED_AREAS)
        assert all(c["MEASURED"] == 0 for c in check_results.counts(results).values())

    def test_committed_template_matches_schema(self):
        committed = json.loads((EVAL_DIR / "templates" / "results_template.json").read_text("utf-8"))
        assert committed == blank_results()

    @pytest.mark.parametrize("area", ["ocr_gate", "retrieval", "answers", "multilingual", "latency", "tokens_cost",
                                      "tablet", "storage", "offline", "server_capacity", "backup_restore"])
    def test_required_evaluation_areas_exist(self, area):
        assert area in REQUIRED_AREAS

    def test_unmeasured_metric_with_a_value_is_rejected(self):
        results = blank_results()
        results["areas"]["storage"]["metrics"]["bytes_per_page_master"]["value"] = 123

        errors, _ = check_results.check(results)

        assert any("must have value null" in e for e in errors)

    def test_measured_metric_needs_sample_size(self):
        results = blank_results()
        _measure(results, "retrieval", "mrr_hybrid_rerank", n=0)

        errors, _ = check_results.check(results)

        assert any("sample size" in e for e in errors)

    def test_trained_model_result_rejected_when_gate_not_met(self):
        results = blank_results()
        _measure(results, "trained_reranker", "mrr_delta", ci_low=0.01, ci_high=0.2)

        errors, _ = check_results.check(results)

        assert any("gate is not met" in e for e in errors)

    def test_difference_without_confidence_interval_rejected(self):
        results = blank_results()
        results["areas"]["trained_reranker"]["gate"]["met"] = True
        _measure(results, "trained_reranker", "mrr_delta")

        errors, _ = check_results.check(results)

        assert any("confidence interval" in e for e in errors)

    def test_human_graded_metric_needs_named_graders_and_no_seeded_rows(self):
        results = blank_results()
        _measure(results, "answers", "claim_support_rate")

        errors, _ = check_results.check(results)

        assert any("named graders" in e for e in errors)
        assert any("seeded" in e for e in errors)


def _row(split, bad, conf, lang="en"):
    return {"split": split, "bad_page": bad, "doc_class": "printed", "language": lang,
            "signals": {"mean_confidence": conf, "garbage_rate": 0.5 if bad else 0.02}}


class TestCalibrateGate:
    def test_threshold_catches_every_bad_calibration_page(self):
        rows = [_row("calibration", True, 55.0), _row("calibration", True, 62.0),
                *[_row("calibration", False, c) for c in (80.0, 85.0, 90.0)],
                _row("test", True, 60.0), _row("test", False, 88.0)]

        out = calibrate_gate.calibrate(rows, min_pages=5)["printed:en"]

        conf = out["signals"]["mean_confidence"]
        assert out["status"] == "PROPOSED"
        assert conf["threshold"] > 62.0 and conf["calibration_good_sent"] == 0
        assert conf["test_bad_recall"] == 1.0 and conf["test_good_sent_share"] == 0.0

    def test_small_calibration_sample_gets_no_proposal(self):
        rows = [_row("calibration", True, 50.0), _row("calibration", False, 90.0)]

        out = calibrate_gate.calibrate(rows, min_pages=10)["printed:en"]

        assert out["status"].startswith("INSUFFICIENT_SAMPLE") and out["proposal"] is None

    def test_refuses_synthetic_fixture_results(self, tmp_path):
        src = tmp_path / "ocr.json"
        src.write_text(json.dumps({"note": "Ground truth for SYNTHETIC fixture pages.", "rows": []}), "utf-8")

        proc = subprocess.run([sys.executable, str(EVAL_DIR / "calibrate_gate.py"), str(src), "--version", "g",
                               "--out", str(tmp_path / "p.json")], capture_output=True, text=True)

        assert proc.returncode != 0 and "SYNTHETIC" in proc.stderr
        assert not (tmp_path / "p.json").exists()


class TestSummarizeGrading:
    def test_seeded_rows_are_not_counted_as_human_evidence(self):
        rows = [
            {"question_id": "q1", "grader": "Asha", "support": "supported", "is_seeded_fixture": "false"},
            {"question_id": "q1", "grader": "Asha", "support": "partial", "is_seeded_fixture": "false"},
            {"question_id": "q2", "grader": "fixture-seed", "support": "supported", "is_seeded_fixture": ""},
        ]

        out = summarize_grading.claim_support(rows, "sheet.csv")

        assert out["claim_support_rate"]["n"] == 2
        assert out["claim_support_rate"]["value"] == 0.5
        assert out["unsupported_claim_rate"]["value"] == 0.5
        assert out["claim_support_rate"]["seeded_rows_dropped"] == 1

    def test_empty_sheets_stay_unmeasured(self):
        out = summarize_grading.claim_support([], None)
        assert out["claim_support_rate"]["status"] == UNMEASURED and out["claim_support_rate"]["n"] == 0

    def test_quote_checks_require_named_person_and_source_comparison(self):
        rows = [
            {"verifier": "R. Kamble", "compared_with": "scan", "result": "match"},
            {"verifier": "fixture-seed", "compared_with": "scan", "result": "match", "is_seeded_fixture": "true"},
            {"verifier": "R. Kamble", "compared_with": "ocr text", "result": "match"},
        ]

        out = summarize_grading.quote_checks(rows, "log.csv")["quotes_human_verified_against_source"]

        assert out["n"] == 1 and out["seeded_rows_dropped"] == 1


class TestPairedBootstrap:
    ROWS = [{"question_id": str(i), "language": "en", "base": "0.5", "trained": "0.7"} for i in range(40)]

    def test_comparison_refused_when_gate_not_met(self):
        with pytest.raises(PermissionError):
            paired_bootstrap.compare(self.ROWS, {"met": False}, samples=200)

    def test_baseline_never_claims_improvement(self):
        out = paired_bootstrap.baseline(self.ROWS, samples=200)
        assert out["improvement_claimed"] is False and out["n"] == 40 and out["base_mean"] == 0.5

    def test_language_without_its_own_test_examples_is_not_claimed(self):
        out = paired_bootstrap.compare(self.ROWS, {"met": True, "claimable_languages": []}, samples=200)
        assert out["by_language"]["en"]["status"] == UNMEASURED


class TestLeakageAndRestore:
    def test_held_out_question_in_training_labels_is_an_error(self):
        q = [{"id": "t1", "question": "What did the Assembly decide about fees?", "positives": []}]
        labels = [{"id": "l1", "question": "what did the assembly decide about fees", "positives": []}]

        errors, _ = check_training_leakage.check(q, labels, near=0.8)

        assert errors and "t1" in errors[0]

    @pytest.mark.parametrize("log,expected", [
        ({"success": True, "database_dump_checksum_ok": True, "manifest_mismatches": [], "files_restored": 10,
          "db_file_rows_checked": 10, "db_file_rows_failed": [], "seconds": 3.2, "finished": "t"}, "pass"),
        ({"success": False, "database_dump_checksum_ok": True, "manifest_mismatches": ["a"], "files_restored": 10,
          "db_file_rows_checked": 10, "db_file_rows_failed": [], "seconds": 3.2, "finished": "t"}, "fail"),
        ({"success": True, "database_dump_checksum_ok": True, "manifest_mismatches": [], "files_restored": 0,
          "db_file_rows_checked": 0, "db_file_rows_failed": [], "seconds": 1.0, "finished": "t"}, "fail"),
    ])
    def test_restore_passes_only_with_checksum_match_and_checked_rows(self, log, expected):
        out = verify_restore_log.summarise(log, "RESTORE_LOG.json", None, None)
        assert out["restore_success"]["value"] == expected
        assert out["target_was_clean_machine"]["status"] == UNMEASURED

    def test_percentile_of_empty_sample_is_none(self):
        assert percentile([], 95) is None

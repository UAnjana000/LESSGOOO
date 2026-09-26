"""Single definition of every spec 10.2 evaluation field.

    python eval/results_schema.py --write eval/templates/results_template.json

writes a blank results file in which every metric is UNMEASURED with value null and n 0. Fill a copy
(never the template), then run eval/check_results.py on it before quoting any number.
"""

from __future__ import annotations

import argparse
import copy
from typing import Any

from evalkit import UNMEASURED, write_json

TEMPLATE_VERSION = "results-template-v1"

# (metric key, unit, comparison / baseline, how measured, human_graded)
M = tuple[str, str, str, str, bool]

AREAS: dict[str, dict[str, Any]] = {
    "ocr": {
        "title": "OCR accuracy", "spec": "10.2 OCR; 4.3", "priority": "P1",
        "sample_unit": "pages from the TEST half of the hand-transcribed OCR set (10.1), per class and language",
        "metrics": [
            ("cer_local", "ratio", "local OCR only", "eval-ocr vs double-checked ground truth", False),
            ("wer_local", "ratio", "local OCR only", "eval-ocr vs double-checked ground truth", False),
            ("wer_local_plus_sarvam_fallback", "ratio", "local + Sarvam on failed pages", "eval-ocr", False),
            ("wer_sarvam_all_pages", "ratio", "Sarvam on every test page (comparison only)", "eval-ocr --sarvam-all", False),
        ],
    },
    "ocr_gate": {
        "title": "OCR quality gate and Sarvam fallback", "spec": "10.2 OCR gate; 4.3; 4.4", "priority": "P1",
        "sample_unit": "pages from the TEST half; thresholds set on the CALIBRATION half only",
        "metrics": [
            ("fallback_rate", "share of printed pages", "gate v(n) vs v(n+1)", "eval-ocr + calibrate_gate.py", False),
            ("bad_page_recall", "share of bad pages caught", "gate v(n) vs v(n+1)", "eval-ocr + calibrate_gate.py", False),
            ("good_pages_sent_unnecessarily", "share of good pages", "gate v(n) vs v(n+1)", "eval-ocr + calibrate_gate.py", False),
            ("calibration_pages", "count", "per class and language", "count of calibration-half pages used", False),
        ],
    },
    "review_load": {
        "title": "Archivist review load", "spec": "10.2 Review load; 4.5", "priority": "P1",
        "sample_unit": "timed page reviews",
        "metrics": [
            ("minutes_per_page_full_review", "minutes", "full review", "templates/review_time_log.csv", False),
            ("minutes_per_page_sampled_batch", "minutes", "sampled batch review", "templates/review_time_log.csv", False),
        ],
    },
    "retrieval": {
        "title": "Retrieval (base models only)", "spec": "10.2 Retrieval; 5.2", "priority": "P1",
        "sample_unit": "questions from the 10.1 question set with expected passages",
        "metrics": [
            ("recall_at_k_keyword", "ratio", "keyword only", "archive.cli eval-retrieval", False),
            ("recall_at_k_semantic", "ratio", "semantic only", "archive.cli eval-retrieval", False),
            ("recall_at_k_hybrid", "ratio", "hybrid (RRF)", "archive.cli eval-retrieval", False),
            ("recall_at_candidate_k_hybrid", "ratio", "pool passed to the reranker", "archive.cli eval-retrieval", False),
            ("mrr_hybrid_rerank", "ratio", "after reranking", "archive.cli eval-retrieval", False),
            ("ndcg_at_k_hybrid_rerank", "ratio", "after reranking", "archive.cli eval-retrieval", False),
            ("cross_lingual_choice", "text", "multilingual embeddings vs query translation", "same question set, both modes", False),
        ],
    },
    "answers": {
        "title": "Cited-answer support and answer behaviour", "spec": "10.2 Answers; 5.7", "priority": "P1",
        "sample_unit": "questions (and graded sentences) per prompt/model version",
        "metrics": [
            ("claim_support_rate", "share of sentences", "per prompt/model version", "human grading: templates/claim_support_grading.csv", True),
            ("unsupported_claim_rate", "share of sentences", "per prompt/model version", "human grading: templates/claim_support_grading.csv", True),
            ("quote_match_rate", "share of quoted spans", "string match in cited passage", "eval-answers rows", False),
            ("quotes_human_verified_against_source", "count of pages/segments", "not seeded", "templates/quote_verification_log.csv (seeded rows excluded)", True),
            ("abstention_precision", "ratio", "per threshold version", "archive.cli eval-answers", False),
            ("abstention_recall", "ratio", "per threshold version", "archive.cli eval-answers", False),
            ("correct_not_in_archive_rate", "ratio", "unanswerable + false premise", "archive.cli eval-answers", False),
            ("misattributed_quote_not_in_archive_rate", "ratio", "widely circulated misattributed quotes", "archive.cli eval-answers (category misattributed_quote)", False),
            ("correct_refusal_rate", "ratio", "opinion-bait questions", "archive.cli eval-answers", False),
        ],
    },
    "multilingual": {
        "title": "Multilingual quality (EN, HI, MR)", "spec": "10.2 Translation; 5.5", "priority": "P1",
        "sample_unit": "30-50 passages per language rated by a named bilingual reviewer; per-language questions",
        "metrics": [
            ("translation_adequacy_hi", "1-5 mean", "Sarvam vs one alternative", "templates/translation_ratings.csv", True),
            ("translation_fluency_hi", "1-5 mean", "Sarvam vs one alternative", "templates/translation_ratings.csv", True),
            ("translation_adequacy_mr", "1-5 mean", "Sarvam vs one alternative", "templates/translation_ratings.csv", True),
            ("translation_fluency_mr", "1-5 mean", "Sarvam vs one alternative", "templates/translation_ratings.csv", True),
            ("approved_without_edit_share", "ratio", "per language", "templates/translation_ratings.csv", True),
            ("edit_distance_to_approved", "chars (mean)", "per language", "templates/translation_ratings.csv", True),
            ("retrieval_mrr_hi", "ratio", "Hindi questions only", "archive.cli eval-retrieval", False),
            ("retrieval_mrr_mr", "ratio", "Marathi questions only", "archive.cli eval-retrieval", False),
            ("hindi_query_finds_english_source", "ratio", "Hindi questions whose positive is English text", "archive.cli eval-retrieval", False),
        ],
    },
    "latency": {
        "title": "Visitor latency", "spec": "10.2 Cost and speed; 3.4", "priority": "P1",
        "sample_unit": "requests (cache misses for Ask); provider time reported separately",
        "metrics": [
            ("ask_p50_ms", "ms", "with vs without answer cache", "Langfuse / answer_log", False),
            ("ask_p95_ms", "ms", "with vs without answer cache", "Langfuse / answer_log", False),
            ("ask_provider_p50_ms", "ms", "external LLM time only", "answer_log.provider_latency_ms", False),
            ("ask_provider_p95_ms", "ms", "external LLM time only", "answer_log.provider_latency_ms", False),
            ("search_p50_ms", "ms", "visitor load alone", "load_test.py", False),
            ("search_p95_ms", "ms", "visitor load alone", "load_test.py", False),
            ("page_open_p50_ms", "ms", "visitor load alone", "load_test.py", False),
            ("page_open_p95_ms", "ms", "visitor load alone", "load_test.py", False),
        ],
    },
    "tokens_cost": {
        "title": "Tokens and cost", "spec": "10.2 Cost and speed; 6.1", "priority": "P1",
        "sample_unit": "answered questions that called the LLM",
        "metrics": [
            ("input_tokens_per_question", "tokens (mean)", "top-k values", "Langfuse / answer_log", False),
            ("output_tokens_per_question", "tokens (mean)", "max_tokens cap", "Langfuse / answer_log", False),
            ("cost_per_answer_usd", "USD", "by model", "answer_log.cost_usd", False),
            ("cost_per_day_usd", "USD", "daily alert threshold", "answer_log.cost_usd", False),
            ("answer_cache_hit_rate", "ratio", "with vs without cache", "answer_log.cache_hit", False),
            ("cached_token_share", "ratio", "provider prompt caching, if reported", "Langfuse", False),
            ("tokens_follow_up_vs_first", "ratio", "follow-up vs first question", "Langfuse", False),
            ("llm_calls_per_session_outside_ask", "count (target 0)", "target 0", "Langfuse + API logs", False),
        ],
    },
    "tablet": {
        "title": "Tablet battery and network", "spec": "10.2 Tablet; 6.3", "priority": "P1",
        "sample_unit": "timed runs on the physical kiosk tablet (Android battery stats)",
        "metrics": [
            ("battery_pct_per_hour_active", "%/h", "with vs without lazy loading and cache", "templates/tablet_battery_run.csv", False),
            ("battery_pct_per_hour_attract_loop", "%/h", "idle attract loop", "templates/tablet_battery_run.csv", False),
            ("battery_pct_per_hour_screen_sleep", "%/h", "screen asleep", "templates/tablet_battery_run.csv", False),
            ("network_bytes_per_session", "bytes", "with vs without cache", "templates/tablet_battery_run.csv", False),
            ("charge_limit_mode", "text", "on/off, if the model supports it", "device settings record", False),
        ],
    },
    "storage": {
        "title": "Storage", "spec": "10.2 Storage; 6.4", "priority": "P1",
        "sample_unit": "items and pages in the archive at measurement time",
        "metrics": [
            ("bytes_per_page_master", "bytes", "master only", "archive.cli storage-report", False),
            ("bytes_per_item_all_layers", "bytes", "master + delivery + derivatives", "archive.cli storage-report", False),
            ("bytes_delivery_total", "bytes", "delivery copies", "archive.cli storage-report", False),
            ("bytes_derivatives_total", "bytes", "derivatives", "archive.cli storage-report", False),
            ("dedup_savings_bytes", "bytes", "exact duplicates refused at intake", "intake duplicate records", False),
            ("kiosk_cache_bytes_vs_budget", "bytes", "exhibit manifest total_bytes vs budget_bytes", "GET /api/visitor/exhibit/manifest", False),
        ],
    },
    "offline": {
        "title": "Offline kiosk access", "spec": "10.2 Offline; 3.3; 4.7; 6.5", "priority": "P1",
        "sample_unit": "published, fully public exhibit items, network off",
        "metrics": [
            ("share_exhibit_items_usable_offline", "ratio", "scripted test with network off", "templates/offline_check.csv", False),
            ("ask_shows_needs_connection", "pass/fail", "network off", "templates/offline_check.csv", False),
            ("online_only_items_absent_from_cache", "pass/fail", "rights-sensitive items never cached", "templates/offline_check.csv", False),
            ("lease_expiry_hides_cached_items", "pass/fail", "after lease_expires_at", "templates/offline_check.csv", False),
            ("withdrawal_applied_on_reconnect", "pass/fail", "before any cached item is shown", "templates/offline_check.csv", False),
        ],
    },
    "server_capacity": {
        "title": "Edge-server capacity", "spec": "10.2 Edge-server capacity; 3.4", "priority": "P1",
        "sample_unit": "scripted load test; latency targets fixed BEFORE the run in templates/latency_targets.json",
        "metrics": [
            ("search_p95_ms_visitor_only", "ms", "visitor load alone", "load_test.py", False),
            ("search_p95_ms_with_ingestion", "ms", "visitor load + ingestion", "load_test.py", False),
            ("page_open_p95_ms_visitor_only", "ms", "visitor load alone", "load_test.py", False),
            ("page_open_p95_ms_with_ingestion", "ms", "visitor load + ingestion", "load_test.py", False),
            ("ask_p95_ms_visitor_only", "ms", "provider time separate", "load_test.py", False),
            ("ask_p95_ms_with_ingestion", "ms", "provider time separate", "load_test.py", False),
            ("ingestion_pages_per_hour", "pages/h", "during visitor load", "worker job log", False),
            ("cpu_peak_pct", "%", "visitor + ingestion", "host metrics", False),
            ("ram_peak_gb", "GB", "visitor + ingestion", "host metrics", False),
            ("swap_used_gb", "GB", "visitor + ingestion", "host metrics", False),
            ("disk_io_peak_mb_s", "MB/s", "visitor + ingestion", "host metrics", False),
            ("langfuse_on_vs_off_box_delta_p95_ms", "ms", "Langfuse on vs off the machine", "load_test.py twice", False),
            ("kiosks_simulated", "count", "planned number of kiosks", "load_test.py --sessions", False),
        ],
    },
    "backup_restore": {
        "title": "Checksum-verified restore", "spec": "10.2 Backup; 6.5; 8.3", "priority": "P1",
        "sample_unit": "full restores to a clean machine",
        "metrics": [
            ("restore_success", "pass/fail", "clean target DB and empty file roots", "verify_restore_log.py on RESTORE_LOG.json", False),
            ("restore_time_seconds", "s", "-", "RESTORE_LOG.json", False),
            ("files_restored", "count", "-", "RESTORE_LOG.json", False),
            ("manifest_checksum_mismatches", "count (target 0)", "SHA-256 vs backup MANIFEST.json", "RESTORE_LOG.json", False),
            ("db_file_rows_checked", "count", "file_version rows vs restored files", "RESTORE_LOG.json", False),
            ("db_file_rows_failed", "count (target 0)", "file_version rows vs restored files", "RESTORE_LOG.json", False),
            ("target_was_clean_machine", "yes/no", "a different machine, not the edge server", "operator record", False),
        ],
    },
    "training_baseline": {
        "title": "Training preparation and base-model baseline", "spec": "7.3; 8.3; 10.2", "priority": "P1",
        "sample_unit": "held-out TEST split questions (from the 10.1 set, never used in training)",
        "metrics": [
            ("dataset_manifest_sha256", "text", "frozen dataset version", "archive.cli freeze-dataset", False),
            ("training_eligible_passages", "count", "-", "archive.cli freeze-dataset", False),
            ("independent_works", "count", "gate: training_gate.json", "dataset gate_report", False),
            ("base_reranker_mrr_test", "ratio", "base model only; no trained model", "archive.cli eval-retrieval on test split", False),
            ("base_reranker_ndcg_at_k_test", "ratio", "base model only; no trained model", "archive.cli eval-retrieval on test split", False),
            ("minimum_data_gate_met", "yes/no", "training-gate-v1", "dataset gate_report.met", False),
        ],
    },
    "trained_reranker": {
        "title": "Trained reranker vs base [P2, gate]", "spec": "7.3; 10.2", "priority": "P2",
        "gated": True,
        "sample_unit": "held-out test split; identical first-stage candidates for both models",
        "metrics": [
            ("mrr_base", "ratio", "base reranker", "paired_bootstrap.py", False),
            ("mrr_trained", "ratio", "trained reranker", "paired_bootstrap.py", False),
            ("mrr_delta", "ratio", "trained - base, with CI", "paired_bootstrap.py", False),
            ("ndcg_at_k_delta", "ratio", "trained - base, with CI", "paired_bootstrap.py", False),
            ("recall_at_candidate_k_first_stage", "ratio", "unchanged first stage", "eval-retrieval", False),
            ("rerank_p95_ms_delta", "ms", "trained - base", "load_test.py", False),
            ("model_size_mb", "MB", "trained model", "model registry", False),
        ],
    },
    "trained_retriever": {
        "title": "Trained retriever vs base [P2, gate]", "spec": "7.3; 10.2", "priority": "P2",
        "gated": True,
        "sample_unit": "held-out test split; each model with its own full index",
        "metrics": [
            ("recall_at_k_delta", "ratio", "trained - base, with CI", "paired_bootstrap.py", False),
            ("mrr_delta", "ratio", "trained - base, with CI", "paired_bootstrap.py", False),
            ("retrieval_p95_ms_delta", "ms", "trained - base", "load_test.py", False),
            ("reindex_seconds", "s", "trained model index", "re-embedding job", False),
            ("model_size_mb", "MB", "trained model", "model registry", False),
        ],
    },
}

REQUIRED_AREAS = tuple(AREAS)


def blank_metric(unit: str, comparison: str, method: str, human_graded: bool) -> dict[str, Any]:
    m: dict[str, Any] = {"status": UNMEASURED, "value": None, "n": 0, "unit": unit, "comparison": comparison,
                         "method": method, "breakdown": {}, "ci_low": None, "ci_high": None,
                         "measured_at": None, "evidence": None, "notes": ""}
    if human_graded:
        m.update({"human_graded": True, "graders": [], "seeded_rows_excluded": None})
    return m


def blank_results() -> dict[str, Any]:
    areas: dict[str, Any] = {}
    for key, spec in AREAS.items():
        area = {k: v for k, v in spec.items() if k != "metrics"}
        area["metrics"] = {name: blank_metric(unit, comp, how, hg) for name, unit, comp, how, hg in spec["metrics"]}
        if spec.get("gated"):
            area["gate"] = {"required": True, "met": None, "gate_version": None, "gate_report": None,
                            "rule": "Shown only if the spec 7.3 minimum-data gate is met; otherwise leave UNMEASURED."}
        areas[key] = area
    return copy.deepcopy({
        "template_version": TEMPLATE_VERSION,
        "rules": [
            "Every metric stays UNMEASURED (value null, n 0) until it is actually measured.",
            "A MEASURED metric needs value, n > 0, measured_at, method and evidence (a result file or log path).",
            "Human-graded metrics list named graders and exclude seeded fixture rows (reviewer 'fixture-seed').",
            "Synthetic fixture results are smoke tests, never spec 10 evidence.",
            "No improvement is claimed without a measured baseline and a confidence interval.",
            "Trained-model areas stay UNMEASURED unless the spec 7.3 minimum-data gate is met.",
        ],
        "run": {
            "date": None,
            "dataset": {"name": None, "items": None, "pages": None, "questions": None, "is_synthetic_fixture": None},
            "versions": {"gate_version": None, "sufficiency_threshold_version": None, "prompt_version": None,
                         "embedding_model": None, "reranker_model": None, "llm_model": None, "ocr_engine": None,
                         "index_version": None, "code_commit": None},
        },
        "areas": areas,
    })


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", required=True, help="output path for the blank template")
    args = ap.parse_args()
    print(write_json(args.write, blank_results()))


if __name__ == "__main__":
    main()

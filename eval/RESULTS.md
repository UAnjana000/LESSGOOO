# Evaluation results (spec §10)

**As of 2026-09-26, nothing in this table has been measured.** Every field is UNMEASURED, and every sample size is blank. No percentage, saving, or improvement may be quoted from this project until a row here is MEASURED, with a sample size and an evidence file, and `python eval/check_results.py` passes on the filled results JSON.

Regenerate the full table from a filled results file:

```powershell
python eval/check_results.py eval/results/results-<date>.json --markdown
```

## What each area needs before it can be measured

| Area | Status | n | What is missing |
| --- | --- | --- | --- |
| OCR accuracy (CER, WER) | UNMEASURED | | The 30–50 hand-transcribed, double-checked real pages (§10.1) do not exist yet. The 7 synthetic fixture pages are smoke-test only. |
| OCR gate and Sarvam fallback | UNMEASURED | | Needs the same real page set. The gate is still `gate-v0-uncalibrated`. There is no Sarvam key in the running stack, so the fallback arm cannot run. |
| Archivist review load | UNMEASURED | | No timed reviews. Seeded fixture approvals do not count. |
| Retrieval | UNMEASURED | | The §10.1 question set is empty (`eval/questions/retrieval.template.json`). The harness exists as `archive.cli eval-retrieval`. |
| Cited-answer support | UNMEASURED | | No LLM is configured (Ask runs in extractive mode). No human grading sheet exists, and there are no real misattributed-quote questions. |
| Direct-quote checks against the source | UNMEASURED | | The only quote verifications are three seeded fixture pages (`fixture-seed`). No named person has compared a real scan or recording. |
| Multilingual quality | UNMEASURED | | The Hindi and Marathi translations were written by the build agent and approved by the seed script, not by a named bilingual reviewer. There is no Sarvam key for machine translation. |
| Latency | UNMEASURED | | No load run, and no LLM traffic. |
| Tokens and cost | UNMEASURED | | No LLM configured. Langfuse is not configured either (traces go to a local JSONL file). |
| Tablet battery and network | UNMEASURED | | Needs the physical Lenovo tablet. |
| Storage | UNMEASURED | | `archive.cli storage-report` has not been run for the record. |
| Offline access | UNMEASURED | | No network-off scripted run on a kiosk. |
| Edge-server capacity | UNMEASURED | | No latency targets set beforehand (`templates/latency_targets.json`), and no load run. |
| Checksum-verified restore | UNMEASURED | | No backup or restore has been run. No `RESTORE_LOG.json` exists. |
| Training preparation and base-model baseline | UNMEASURED | | No reviewed labels or held-out questions. No dataset version has been frozen from real training-cleared items, because every real source's training permission is `unknown`. |
| Trained reranker or retriever [P2] | UNMEASURED | | Must stay unmeasured unless the §7.3 minimum-data gate (`training-gate-v1`) is met. It is not met: no fine-tuning, and no improvement claim. |

## Full results table

| Area | Metric | Status | Value | n | Comparison | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| OCR accuracy | cer_local | UNMEASURED |  |  | local OCR only |  |
| OCR accuracy | wer_local | UNMEASURED |  |  | local OCR only |  |
| OCR accuracy | wer_local_plus_sarvam_fallback | UNMEASURED |  |  | local + Sarvam on failed pages |  |
| OCR accuracy | wer_sarvam_all_pages | UNMEASURED |  |  | Sarvam on every test page (comparison only) |  |
| OCR quality gate and Sarvam fallback | fallback_rate | UNMEASURED |  |  | gate v(n) vs v(n+1) |  |
| OCR quality gate and Sarvam fallback | bad_page_recall | UNMEASURED |  |  | gate v(n) vs v(n+1) |  |
| OCR quality gate and Sarvam fallback | good_pages_sent_unnecessarily | UNMEASURED |  |  | gate v(n) vs v(n+1) |  |
| OCR quality gate and Sarvam fallback | calibration_pages | UNMEASURED |  |  | per class and language |  |
| Archivist review load | minutes_per_page_full_review | UNMEASURED |  |  | full review |  |
| Archivist review load | minutes_per_page_sampled_batch | UNMEASURED |  |  | sampled batch review |  |
| Retrieval (base models only) | recall_at_k_keyword | UNMEASURED |  |  | keyword only |  |
| Retrieval (base models only) | recall_at_k_semantic | UNMEASURED |  |  | semantic only |  |
| Retrieval (base models only) | recall_at_k_hybrid | UNMEASURED |  |  | hybrid (RRF) |  |
| Retrieval (base models only) | recall_at_candidate_k_hybrid | UNMEASURED |  |  | pool passed to the reranker |  |
| Retrieval (base models only) | mrr_hybrid_rerank | UNMEASURED |  |  | after reranking |  |
| Retrieval (base models only) | ndcg_at_k_hybrid_rerank | UNMEASURED |  |  | after reranking |  |
| Retrieval (base models only) | cross_lingual_choice | UNMEASURED |  |  | multilingual embeddings vs query translation |  |
| Cited-answer support and answer behaviour | claim_support_rate | UNMEASURED |  |  | per prompt/model version |  |
| Cited-answer support and answer behaviour | unsupported_claim_rate | UNMEASURED |  |  | per prompt/model version |  |
| Cited-answer support and answer behaviour | quote_match_rate | UNMEASURED |  |  | string match in cited passage |  |
| Cited-answer support and answer behaviour | quotes_human_verified_against_source | UNMEASURED |  |  | not seeded |  |
| Cited-answer support and answer behaviour | abstention_precision | UNMEASURED |  |  | per threshold version |  |
| Cited-answer support and answer behaviour | abstention_recall | UNMEASURED |  |  | per threshold version |  |
| Cited-answer support and answer behaviour | correct_not_in_archive_rate | UNMEASURED |  |  | unanswerable + false premise |  |
| Cited-answer support and answer behaviour | misattributed_quote_not_in_archive_rate | UNMEASURED |  |  | widely circulated misattributed quotes |  |
| Cited-answer support and answer behaviour | correct_refusal_rate | UNMEASURED |  |  | opinion-bait questions |  |
| Multilingual quality (EN, HI, MR) | translation_adequacy_hi | UNMEASURED |  |  | Sarvam vs one alternative |  |
| Multilingual quality (EN, HI, MR) | translation_fluency_hi | UNMEASURED |  |  | Sarvam vs one alternative |  |
| Multilingual quality (EN, HI, MR) | translation_adequacy_mr | UNMEASURED |  |  | Sarvam vs one alternative |  |
| Multilingual quality (EN, HI, MR) | translation_fluency_mr | UNMEASURED |  |  | Sarvam vs one alternative |  |
| Multilingual quality (EN, HI, MR) | approved_without_edit_share | UNMEASURED |  |  | per language |  |
| Multilingual quality (EN, HI, MR) | edit_distance_to_approved | UNMEASURED |  |  | per language |  |
| Multilingual quality (EN, HI, MR) | retrieval_mrr_hi | UNMEASURED |  |  | Hindi questions only |  |
| Multilingual quality (EN, HI, MR) | retrieval_mrr_mr | UNMEASURED |  |  | Marathi questions only |  |
| Multilingual quality (EN, HI, MR) | hindi_query_finds_english_source | UNMEASURED |  |  | Hindi questions whose positive is English text |  |
| Visitor latency | ask_p50_ms | UNMEASURED |  |  | with vs without answer cache |  |
| Visitor latency | ask_p95_ms | UNMEASURED |  |  | with vs without answer cache |  |
| Visitor latency | ask_provider_p50_ms | UNMEASURED |  |  | external LLM time only |  |
| Visitor latency | ask_provider_p95_ms | UNMEASURED |  |  | external LLM time only |  |
| Visitor latency | search_p50_ms | UNMEASURED |  |  | visitor load alone |  |
| Visitor latency | search_p95_ms | UNMEASURED |  |  | visitor load alone |  |
| Visitor latency | page_open_p50_ms | UNMEASURED |  |  | visitor load alone |  |
| Visitor latency | page_open_p95_ms | UNMEASURED |  |  | visitor load alone |  |
| Tokens and cost | input_tokens_per_question | UNMEASURED |  |  | top-k values |  |
| Tokens and cost | output_tokens_per_question | UNMEASURED |  |  | max_tokens cap |  |
| Tokens and cost | cost_per_answer_usd | UNMEASURED |  |  | by model |  |
| Tokens and cost | cost_per_day_usd | UNMEASURED |  |  | daily alert threshold |  |
| Tokens and cost | answer_cache_hit_rate | UNMEASURED |  |  | with vs without cache |  |
| Tokens and cost | cached_token_share | UNMEASURED |  |  | provider prompt caching, if reported |  |
| Tokens and cost | tokens_follow_up_vs_first | UNMEASURED |  |  | follow-up vs first question |  |
| Tokens and cost | llm_calls_per_session_outside_ask | UNMEASURED |  |  | target 0 |  |
| Tablet battery and network | battery_pct_per_hour_active | UNMEASURED |  |  | with vs without lazy loading and cache |  |
| Tablet battery and network | battery_pct_per_hour_attract_loop | UNMEASURED |  |  | idle attract loop |  |
| Tablet battery and network | battery_pct_per_hour_screen_sleep | UNMEASURED |  |  | screen asleep |  |
| Tablet battery and network | network_bytes_per_session | UNMEASURED |  |  | with vs without cache |  |
| Tablet battery and network | charge_limit_mode | UNMEASURED |  |  | on/off, if the model supports it |  |
| Storage | bytes_per_page_master | UNMEASURED |  |  | master only |  |
| Storage | bytes_per_item_all_layers | UNMEASURED |  |  | master + delivery + derivatives |  |
| Storage | bytes_delivery_total | UNMEASURED |  |  | delivery copies |  |
| Storage | bytes_derivatives_total | UNMEASURED |  |  | derivatives |  |
| Storage | dedup_savings_bytes | UNMEASURED |  |  | exact duplicates refused at intake |  |
| Storage | kiosk_cache_bytes_vs_budget | UNMEASURED |  |  | exhibit manifest total_bytes vs budget_bytes |  |
| Offline kiosk access | share_exhibit_items_usable_offline | UNMEASURED |  |  | scripted test with network off |  |
| Offline kiosk access | ask_shows_needs_connection | UNMEASURED |  |  | network off |  |
| Offline kiosk access | online_only_items_absent_from_cache | UNMEASURED |  |  | rights-sensitive items never cached |  |
| Offline kiosk access | lease_expiry_hides_cached_items | UNMEASURED |  |  | after lease_expires_at |  |
| Offline kiosk access | withdrawal_applied_on_reconnect | UNMEASURED |  |  | before any cached item is shown |  |
| Edge-server capacity | search_p95_ms_visitor_only | UNMEASURED |  |  | visitor load alone |  |
| Edge-server capacity | search_p95_ms_with_ingestion | UNMEASURED |  |  | visitor load + ingestion |  |
| Edge-server capacity | page_open_p95_ms_visitor_only | UNMEASURED |  |  | visitor load alone |  |
| Edge-server capacity | page_open_p95_ms_with_ingestion | UNMEASURED |  |  | visitor load + ingestion |  |
| Edge-server capacity | ask_p95_ms_visitor_only | UNMEASURED |  |  | provider time separate |  |
| Edge-server capacity | ask_p95_ms_with_ingestion | UNMEASURED |  |  | provider time separate |  |
| Edge-server capacity | ingestion_pages_per_hour | UNMEASURED |  |  | during visitor load |  |
| Edge-server capacity | cpu_peak_pct | UNMEASURED |  |  | visitor + ingestion |  |
| Edge-server capacity | ram_peak_gb | UNMEASURED |  |  | visitor + ingestion |  |
| Edge-server capacity | swap_used_gb | UNMEASURED |  |  | visitor + ingestion |  |
| Edge-server capacity | disk_io_peak_mb_s | UNMEASURED |  |  | visitor + ingestion |  |
| Edge-server capacity | langfuse_on_vs_off_box_delta_p95_ms | UNMEASURED |  |  | Langfuse on vs off the machine |  |
| Edge-server capacity | kiosks_simulated | UNMEASURED |  |  | planned number of kiosks |  |
| Checksum-verified restore | restore_success | UNMEASURED |  |  | clean target DB and empty file roots |  |
| Checksum-verified restore | restore_time_seconds | UNMEASURED |  |  | - |  |
| Checksum-verified restore | files_restored | UNMEASURED |  |  | - |  |
| Checksum-verified restore | manifest_checksum_mismatches | UNMEASURED |  |  | SHA-256 vs backup MANIFEST.json |  |
| Checksum-verified restore | db_file_rows_checked | UNMEASURED |  |  | file_version rows vs restored files |  |
| Checksum-verified restore | db_file_rows_failed | UNMEASURED |  |  | file_version rows vs restored files |  |
| Checksum-verified restore | target_was_clean_machine | UNMEASURED |  |  | a different machine, not the edge server |  |
| Training preparation and base-model baseline | dataset_manifest_sha256 | UNMEASURED |  |  | frozen dataset version |  |
| Training preparation and base-model baseline | training_eligible_passages | UNMEASURED |  |  | - |  |
| Training preparation and base-model baseline | independent_works | UNMEASURED |  |  | gate: training_gate.json |  |
| Training preparation and base-model baseline | base_reranker_mrr_test | UNMEASURED |  |  | base model only; no trained model |  |
| Training preparation and base-model baseline | base_reranker_ndcg_at_k_test | UNMEASURED |  |  | base model only; no trained model |  |
| Training preparation and base-model baseline | minimum_data_gate_met | UNMEASURED |  |  | training-gate-v1 |  |
| Trained reranker vs base [P2, gate] | mrr_base | UNMEASURED |  |  | base reranker |  |
| Trained reranker vs base [P2, gate] | mrr_trained | UNMEASURED |  |  | trained reranker |  |
| Trained reranker vs base [P2, gate] | mrr_delta | UNMEASURED |  |  | trained - base, with CI |  |
| Trained reranker vs base [P2, gate] | ndcg_at_k_delta | UNMEASURED |  |  | trained - base, with CI |  |
| Trained reranker vs base [P2, gate] | recall_at_candidate_k_first_stage | UNMEASURED |  |  | unchanged first stage |  |
| Trained reranker vs base [P2, gate] | rerank_p95_ms_delta | UNMEASURED |  |  | trained - base |  |
| Trained reranker vs base [P2, gate] | model_size_mb | UNMEASURED |  |  | trained model |  |
| Trained retriever vs base [P2, gate] | recall_at_k_delta | UNMEASURED |  |  | trained - base, with CI |  |
| Trained retriever vs base [P2, gate] | mrr_delta | UNMEASURED |  |  | trained - base, with CI |  |
| Trained retriever vs base [P2, gate] | retrieval_p95_ms_delta | UNMEASURED |  |  | trained - base |  |
| Trained retriever vs base [P2, gate] | reindex_seconds | UNMEASURED |  |  | trained model index |  |
| Trained retriever vs base [P2, gate] | model_size_mb | UNMEASURED |  |  | trained model |  |

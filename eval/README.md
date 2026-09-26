# Evaluation pack (spec §10)

These files are templates, standalone scripts, and an empty results table. As of 2026-09-26, nothing has been measured; see [RESULTS.md](RESULTS.md).

## Layout

| Path | Purpose |
| --- | --- |
| `RESULTS.md` | The §10 results table. Every field is UNMEASURED until filled from a checked results file. |
| `templates/results_template.json` | Blank results file. It has every §10.2 field, each with `status: UNMEASURED`, `value: null` and `n: 0`. Copy it to `results/`; never edit the template. |
| `templates/*.csv` | Sheets for people to fill: claim-support grading, quote verification against the scan or recording, translation ratings, review time, tablet battery, offline checks, host metrics. |
| `templates/latency_targets.json` | Capacity targets, fixed before the §3.4 load test. |
| `templates/ocr_ground_truth.template.json` | Format for the 30–50 real hand-transcribed pages (§10.1). |
| `questions/*.template.json` | Formats for the retrieval question set, the answer-behaviour set, and training labels. |
| `results/` | Output of `archive.cli eval-*` and of these scripts. The API container mounts `./eval` at `/eval`. |
| `tests/` | Tests for the scripts: `python -m pytest eval/tests -q`. |

## Scripts

All of them use only the Python standard library and never import or modify `backend/`.

| Script | Use |
| --- | --- |
| `results_schema.py` | The single definition of all fields. `--write` regenerates the blank template. |
| `check_results.py` | Rejects a results file that quotes a number without a sample size, method, or evidence. It also rejects trained-model numbers unless the §7.3 gate is met, differences without a confidence interval, and human-graded metrics that lack named graders or still include seeded rows. `--markdown` prints the table. |
| `calibrate_gate.py` | Proposes OCR gate thresholds from the calibration half of an `eval-ocr` result and reports them on the test half. It refuses synthetic fixture input unless `--allow-synthetic` is given, and it writes a proposal only. |
| `summarize_grading.py` | Turns the grading sheets into metric blocks. Rows from `fixture-seed` or `is_seeded_fixture=true` are dropped. |
| `paired_bootstrap.py` | `--baseline-only` gives the P1 base-model baseline with a confidence interval. The comparison mode (P2) refuses to run unless the dataset's gate report says `met: true`. |
| `check_training_leakage.py` | Fails if a held-out §10.1 question appears in the training labels. |
| `verify_restore_log.py` | Converts `RESTORE_LOG.json` into the checksum-verified restore fields. |
| `load_test.py` | Simulated kiosk sessions for the §3.4 capacity benchmark. Ask is off by default. |

## Order of work

1. Record the rights basis for each real source (`fixtures/manifests/example_real_sources.manifest.json` is the template). Nothing below can use real material until then.
2. Build the ground truth: OCR pages, the question set, and the translation passages (§10.1). Named people write and check each one.
3. Run inside the API container: `python -m archive.cli eval-ocr /eval/questions/<ocr_gt>.json`, then `python eval/calibrate_gate.py ...` on the host. The backend owner adopts the thresholds and bumps the gate version.
4. Run `eval-retrieval` (base models only) and `eval-answers`. Then grade the answers in `claim_support_grading.csv` and run `summarize_grading.py`.
5. Set `latency_targets.json`, then run `load_test.py` with visitor load alone and again with ingestion running. Record host metrics.
6. Run `archive.cli backup`, then `archive.cli restore` onto a different, clean machine, then `verify_restore_log.py`.
7. Copy `templates/results_template.json` into `results/`, fill in only what was measured, run `check_results.py`, and regenerate `RESULTS.md`.

## Rules

- Anything not measured stays UNMEASURED, with a blank or zero sample size.
- Results on the synthetic fixtures are smoke tests, never §10 evidence.
- A seeded approval or seeded quote check (`fixture-seed`) is not evidence that a person checked a real source. Direct quotations count only after a named person compares the page with the scan, or the segment with the recording, and logs it in `quote_verification_log.csv`.
- NDLI is for discovery and linking only. A downloadable NDLI file is not licensed for redistribution or training, and never goes into any evaluation or training set.
- No fine-tuning happens in round one unless the minimum-data gate in `backend/archive/datasets/training_gate.json` is met. There is no improvement claim without a measured baseline and a confidence interval.
- `archive.cli eval-answers` does not send conversation history yet, so it does not exercise follow-up questions.

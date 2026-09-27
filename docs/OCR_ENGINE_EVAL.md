# Local OCR engine evaluation

**Question.** Is Tesseract 5 (`eng`/`hin`/`mar`, pytesseract, `--oem 1 --psm 3`, `backend/archive/ingest/ocr_local.py`) the best *local* OCR for this archive’s real English and Hindi BAWS–MEA and CAD pages in `data/incoming/`? Switch only if another engine is measurably better.

**Decision (2026-09-27).** Keep Tesseract. Do not switch the local engine to PaddleOCR or EasyOCR. For Hindi, use the tessdata_best **Devanagari** script model and page-segmentation **auto** (PSM 6 on single-column pages, PSM 3 when a column gutter is detected). That route lives on the separate image `ambedkar-archive/api:ocr-deva` (`backend/Dockerfile.ocr-deva`). `ambedkar-archive/api:local` is unchanged and still falls back to Debian `hin` if Devanagari is not installed.

---

## Decision rule (locked before the scored numbers)

Written to `data/ocr_eval/decision_rule.txt` at about 13:45 IST on 2026-09-27, before the Tesseract-variant and PaddleOCR score tables were read.

**Baseline:** `t-fast-prod` — production `ocr_local.run_ocr`, Debian tessdata_fast `eng`/`hin`, `--oem 1 --psm 3`, production preprocessing.

**Primary evidence:** the degraded (rescan-like) set, per language. Clean renders are secondary.

**A. Switch engine** (globally, or as a per-language route) only if all hold for that language:

1. Degraded-set mean CER at least 20% lower (relative) than `t-fast-prod`, **and** the paired bootstrap 95% CI of the CER difference lies entirely below 0.
2. No regression: on no language × set (clean/degraded) is the candidate worse than `t-fast-prod` by more than 5% relative with a paired CI entirely above 0.
3. Latency: mean CPU time ≤ 60 CPU-seconds per page (300 DPI input, production preprocessing) — at least 240 pages/hour on 4 capped cores, so a 1,000-page volume finishes in one off-hours window (spec §3.4). Peak memory must fit a 3 GB container cap.
4. Output: word-level boxes and a confidence usable by the quality gate (spec §4.3). Line-level confidence copied onto words is a limitation, not a blocker, only if 1–3 hold with a wide margin.

**B. Tesseract tuning** (tessdata_best, PSM, language string, raw vs preprocessed): adopt a variant only if it is at least 10% better (relative CER) on the degraded set of some language with the paired CI below 0, no language × set regresses under A2, and CPU per page stays within the A3 budget.

**C.** Otherwise keep the production configuration unchanged.

---

## Sample

Built by `eval/ocr_engine/build_sample.py` (seed `20260927`) into gitignored `data/ocr_eval/`. 60 unique pages, each rendered clean at 300 DPI and again with a seeded rescan-like degradation (skew, blur, noise, 150/200 DPI, JPEG). 120 page-images scored per full-sample run.

| Source file | Language | Pages | Class |
|---|---|---|---|
| `baws/mea_Volume1.pdf` | en | 8 | Born-digital BAWS–MEA |
| `baws/mea_Volume13.pdf` | en | 8 | Born-digital BAWS–MEA |
| `cad/cad_04-11-1948_en_sansad.pdf` | en | 7 | Scanned CAD |
| `cad/cad_25-11-1949.pdf` | en | 7 | Scanned CAD |
| `baws/mea_VolumeH1.pdf` | hi | 10 | Born-digital BAWS–MEA Hindi (legacy Devanagari font) |
| `cad/cad_04-11-1948_hindi.pdf` | hi | 10 | Scanned CAD Hindi |
| `cad/cad_25-11-1949_hindi.pdf` | hi | 10 | Scanned CAD Hindi |

Eight candidate pages were skipped (too short, or Hindi legacy-font share below 0.9). No Marathi PDFs were in the incoming set, so Marathi was not scored. A small two-column / table check set was built separately (`eval/ocr_engine/build_multicol.py`) for the gutter detector only.

Harness (not committed page images): `eval/ocr_engine/run_engine.py`, `score.py`. Host: Docker, 4 CPUs, typically 1.5 GB for Tesseract and 3 GB for Paddle/EasyOCR, Linux under WSL2.

---

## Reference method

- **English:** PDF text layer, Unicode, assembled in visual line order.
- **Hindi:** the PDF text layer is **not** used as raw Hindi. Kruti Dev / Walkman Chanakya runs are converted to Unicode by `eval/ocr_engine/krutidev.py`; Latin-font runs stay as they are. On this sample, leftover Latin after conversion was 0.
- **Kruti Dev text layers are not valid Hindi references.** The converted layer is a proxy for ranking engines, not the spec §10 hand-transcribed set. It can understate or distort CER when conversion is imperfect. Character-class recall (ASCII digit `1`, embedded Latin letters) is the more trustworthy Hindi signal, and it matches the live-stack error patterns in `docs/E2E_REAL_DATA.md` bug 2.
- Scoring (`eval/ocr_engine/score.py`): NFC, typographic folding, page-mean CER/WER (Levenshtein) and bag-of-words error, bootstrap 95% CI (10,000 samples), paired bootstrap CI of CER vs `t-fast-prod`. A page is labelled “bad” at CER > 0.05 for gate calibration only.

---

## Results

Page-mean CER/WER from `data/ocr_eval/score-final.log` and `score-tess-final.log`. `dCER` is candidate − baseline (negative = fewer errors). Times are mean wall / CPU seconds per page.

### Baseline and candidates (full 30+30 pages per language unless noted)

| Run | Group | n | CER | 95% CI | WER | dCER vs `t-fast-prod` [CI] | s/pg | CPU s/pg |
|---|---|---|---|---|---|---|---|---|
| **t-fast-prod** (baseline, `hin`, PSM 3) | en clean | 30 | 0.0311 | [0.0037, 0.0808] | 0.0431 | — | 17.47 | 12.16 |
| | en degraded | 30 | 0.0625 | [0.0122, 0.1285] | 0.0765 | — | 12.62 | 9.13 |
| | hi clean | 30 | 0.0404 | [0.0112, 0.0927] | 0.0792 | — | 10.58 | 8.58 |
| | hi degraded | 30 | 0.0433 | [0.0109, 0.0993] | 0.0715 | — | 44.94 | 16.46 |
| **t-fast-auto** (Debian `hin`, PSM auto) | en degraded | 30 | 0.0316 | [0.0047, 0.0806] | 0.0449 | −0.0309 [−0.0776, −0.0010] | 2.75 | 2.23 |
| | hi degraded | 30 | 0.0366 | [0.0084, 0.0892] | 0.0648 | −0.0067 [−0.0193, +0.0001] | 2.86 | 2.23 |
| **t-fast-psm6** | en degraded | 30 | 0.0086 | [0.0042, 0.0135] | 0.0206 | −0.0540 [−0.1167, −0.0056] | 6.77 | 4.91 |
| | hi clean | 30 | 0.0488 | [0.0096, 0.1237] | 0.0882 | +0.0085 [−0.0081, +0.0341] | 6.59 | 4.63 |
| **t-best-cli** (tessdata_best `hin`) | hi degraded | 30 | 0.0473 | [0.0143, 0.1050] | 0.0914 | +0.0041 [+0.0017, +0.0063] | 17.87 | 11.97 |
| **t-best-hineng** (`hin+eng`) | hi degraded | 30 | 0.0511 | [0.0193, 0.1066] | 0.0920 | +0.0078 [+0.0019, +0.0123] | 24.28 | 19.86 |
| **t-devafast-auto** (fast Devanagari, PSM auto; hi only) | hi degraded | 30 | 0.0347 | [0.0077, 0.0867] | 0.0637 | −0.0086 [−0.0219, +0.0002] | 2.62 | 1.75 |
| **t-devabest-auto** (best Devanagari, PSM auto; hi only) | hi clean | 30 | 0.0348 | [0.0094, 0.0843] | 0.0820 | −0.0056 [−0.0132, +0.0004] | 7.48 | 6.12 |
| | hi degraded | 30 | **0.0329** | [0.0058, 0.0849] | 0.0622 | **−0.0104 [−0.0243, −0.0006]** | 6.46 | 5.33 |
| **paddle-v5** (PP-OCRv5 mobile, CPU) | en clean | 30 | 0.0061 | [0.0020, 0.0113] | 0.0129 | −0.0250 [−0.0698, −0.0013] | 34.59 | **136.41** |
| | en degraded | 30 | 0.0085 | [0.0041, 0.0139] | 0.0226 | −0.0540 [−0.1162, −0.0067] | 13.69 | 54.25 |
| | hi clean | 30 | 0.0372 | [0.0130, 0.0835] | 0.0869 | −0.0032 [−0.0119, +0.0040] | 21.35 | **83.22** |
| | hi degraded | 30 | 0.0553 | [0.0243, 0.1134] | 0.1310 | **+0.0121 [+0.0022, +0.0221]** | 8.46 | 34.06 |

Peak RSS: Tesseract full runs ~0.5–0.7 GB container; Paddle ~2.0 GB; EasyOCR smoke ~2.2 GB.

### Hindi character-class recall (aligned to the converted reference)

CAD Hindi is the class that failed live review (`docs/E2E_REAL_DATA.md` bug 2: digit `1` → `॥`/`।`, English quotes → Devanagari junk).

| Run | CAD hi clean digit `1` (n=40) | CAD hi clean Latin (n=248) | CAD hi degraded digit `1` | CAD hi degraded Latin |
|---|---|---|---|---|
| t-fast-prod (`hin`) | **0.00** | **0.00** | **0.00** | **0.00** |
| t-fast-auto (`hin`, PSM auto) | **0.00** | **0.00** | **0.00** | **0.00** |
| t-devafast-auto | 1.00 | 0.68 | 0.98 | 0.50 |
| **t-devabest-auto** | **1.00** | **0.88** | **0.95** | **0.88** |
| paddle-v5 | 0.65 | 0.99 | 0.85 | 0.85 |

Debian `hin` never reads CAD digit `1` or embedded English, which is why those pages still pass the current quality gate. The Devanagari script model fixes both classes. Paddle is strong on Latin but weaker on digit `1` than tessdata_best Devanagari, and it loses on Hindi CER.

### Engines not fully scored

| Engine | What ran | Why it is not a switch candidate |
|---|---|---|
| EasyOCR 1.7.2 | Smoke, 2 clean pages (`canvas=1600`) | 237 and 526 CPU-s/page, ~2.2 GB. Exceeds the 60 CPU-s budget before a 120-page run. |
| Surya | Install only | No completed page run. Not needed once Paddle failed A2/A3 and Tesseract Devanagari met B. |
| Paddle 3.3.x + oneDNN | Smoke only | 3.3.x failed with oneDNN (`ConvertPirAttribute2RuntimeAttribute`). Full run used PaddlePaddle 3.2.2 / PaddleOCR 3.7.0, image `ambedkar-archive/ocr-eval:bench-p322`. The earlier `awesome_vaughan` container had disappeared; `paddle-v5` later completed 120/120 pages. |

---

## Applying the rule

**Paddle as a global or Hindi route — no.** Hindi degraded CER is 28% *worse* than baseline (0.0553 vs 0.0433) with CI entirely above 0 → fails A2. English clean CPU 136 s/page and Hindi clean CPU 83 s/page fail A3. English-only routing still fails A3 on clean pages.

**EasyOCR — no.** Smoke latency is far above A3.

**Tesseract `hin+eng` and tessdata_best `hin` — no.** Both regress Hindi degraded CER with CI above 0.

**PSM 6 on every page — no.** English degraded improves a lot, but Hindi clean two-column CAD pages get worse (the gutter check flags real CAD/MEA tables). Rule B allows it (Hindi clean CI is not entirely above 0), but the Hindi error is the live-stack failure mode, so it is not adopted alone.

**PSM auto** (PSM 6 unless `has_column_gutter`, then 3) on Debian `hin` (`t-fast-auto`): English degraded CER drops 49% with CI below 0; Hindi does not regress. It does **not** fix digit `1` / Latin on CAD Hindi.

**tessdata_best Devanagari + PSM auto** (`t-devabest-auto`): Hindi degraded CER 0.0329 vs 0.0433 = **24% relative drop**, paired CI entirely below 0, CPU 5.3–6.1 s/page, ~0.65 GB. Meets rule B. Independently, CAD digit-`1` recall goes 0 → 0.95–1.00 and Latin 0 → 0.88 — the errors that passed the live gate.

So: keep Tesseract; route Hindi through Devanagari + auto. English stays `eng`. `api:local` keeps Debian `hin` + PSM 3 so the running stack does not require a new traineddata file. The evaluated Hindi route is `ambedkar-archive/api:ocr-deva` (`ARCHIVE_OCR_TESSERACT_LANG_HI=Devanagari`, `ARCHIVE_OCR_TESSERACT_PSM=auto`). If that model is missing, `ocr_local.tesseract_lang` / a `TesseractError` retry fall back to `hin`.

---

## Quality-gate recommendations (for the backend engineer)

Live CAD/BAWS Hindi Tesseract-`hin` output passed the current gate while remaining unusable (`docs/E2E_REAL_DATA.md` bug 2; items 13/14/19). Mean confidence vs CER is already correlated (Spearman about −0.8 on `t-fast-prod` Hindi) but the following **pattern checks** are not in the gate and would have caught those pages:

1. **Danda inside numerals.** Flag when `।` or `॥` sits inside an ASCII/Devanagari digit run (`॥948`, `॥949`, `॥935`, header “page numbers” such as `478` for `4178`). This is the digit-`1` failure. The Devanagari model largely removes it; the gate should still reject a relapse.
2. **Mixed-script junk.** On a Hindi page, flag a high density of Devanagari letters aligned to a region that the layout/text-layer (or a Latin-letter detector) treats as English, or a collapse of Latin-letter recall in a line that clearly contains a quotation. Embedded English on CAD Hindi was rendered as Devanagari junk (E2E pages 85, 166, 181, 194, 248) and still passed.
3. **Known lexical substitutions** as weak signals, not sole fails: `कौ` for `की`, `सांविधान` for `संविधान` in running headers.
4. **Dropped anusvara.** Item 19 (BAWS Hindi) dropped anusvara systematically (~7% WER) and still passed. A language-specific check (expected anusvara rate vs a Hindi reference lexicon, or vs the converted text layer when that layer is *not* used as GT) belongs on the calibration half of a future hand-transcribed set.
5. **Do not treat Kruti Dev PDF text as a Hindi reference** when calibrating the gate. Item 19’s Kruti Dev layer is mojibake; the pipeline correctly ignored it. Converted layers are ranking proxies only.

Sarvam read the same pages with correct numerals, anusvara and English quotations. Until the gate grows these checks, Hindi CAD batches will keep failing sampled review even when local CER looks “fine.”

**Implemented (2026-09-27).** `backend/archive/ingest/quality.py` now computes three extra signals and `apply_gate` uses two of them. `danda_in_numerals` fails the page when `।` or `॥` is glued into an ASCII or Devanagari digit run (`॥949`, `4।178`); a sentence-final year such as `1949।` does not match. `mixed_script_junk` fails a Hindi or Marathi page when a quoted span of 16+ characters is almost all Devanagari, has almost no Latin letters, and has a very low Hindi lexicon hit rate (destroyed English quotations), or when three or more tokens mix Latin and Devanagari in the same word. `weak_ocr_hits` counts standalone `कौ`, `सांविधान`, `सविधान`, and `मे` (not `कौन` / `कौशल` / `सांविधानिक`) and only raises review priority — those tokens never fail the gate by themselves. Thresholds `max_danda_in_numerals` and `max_mixed_script_junk` are 0 in `gate_thresholds.json`. Header truncations such as `478` for `4178`, and English-as-Devanagari that is not inside quotation marks, are still undetectable without a page-number or text-layer reference. Unit tests: `TestHindiOcrPatterns` in `backend/tests/test_unit_gate_and_validation.py`.

---

## How to apply (no rebuild of `api:local`)

```text
docker build -f backend/Dockerfile.ocr-deva -t ambedkar-archive/api:ocr-deva backend
```

That image `ADD`s `Devanagari.traineddata` (tessdata_best script model) on top of `ambedkar-archive/api:local` and sets the two `ARCHIVE_OCR_*` variables. Settings: `ocr_tesseract_lang_hi`, `ocr_tesseract_psm` in `backend/archive/config.py`. Unit tests for PSM auto, per-language models, missing-model fallback and runtime retry: `backend/tests/test_unit_ocr_local.py`.

---

## Limitations

- Hindi references are converted legacy-font text layers, not the spec §10 30–50 hand-transcribed pages. Treat CER as a ranking metric; treat CAD digit/`Latin` recall and the E2E scan review as the Hindi decision evidence.
- No Marathi pages in the incoming sample.
- EasyOCR and Surya were not scored on the full 120-page set (latency / no run).
- Paddle word boxes often carry line-level confidence only.
- Degraded pages are synthetic rescans, not the Internet Archive DLI scans in spec §8.2 item 2.
- Wide CER CIs: a few very bad pages dominate English `t-fast-prod`. Paired CIs are the switch criterion, not the unpaired mean CI.
- `t-devabest-auto` was Hindi-only (60 pages). English was not re-run under Devanagari (it is not used for English).
- The live `ambedkar-archive` api/worker still run `api:local` (`hin`, PSM 3) unless an operator retags to `ocr-deva`. This evaluation did not restart those containers.

---

## Skills used

- `senior-computer-vision` — engine/runtime trade-off, CPU-only edge constraint, word-box/confidence contract.
- `statistical-analyst` — decision rule locked before looking at scores; paired bootstrap CI; relative CER thresholds; “statistically separated” ≠ “ship” when Hindi regresses or CPU misses the budget.
- `verification-before-completion` — claims below are from existing `run.json` / `score-*.log` / `hindi_classes.json` artifacts, not from a re-run of the 7-engine benchmark.

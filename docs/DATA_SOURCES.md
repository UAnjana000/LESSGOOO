# Data sources and rights register (acquisition log)

First checked 2026-09-26; updated 2026-09-27 by the data-acquisition agent. **These are not rightsholder decisions.** A person must confirm each row and file the written permission document (spec §8.1).

Source bytes live only in `data/incoming/` (gitignored by `/data/`). Tracked manifests in `intake/` hold metadata only.

## Rights basis (2026-09-27)

On 2026-09-27 the user stated they have academic permission to download and use the sources named in the spec. It is recorded as follows:

- **Basis and evidence:** "User-asserted academic permission, stated 2026-09-27; written permission document not yet on file." Date checked: 2026-09-27. No rightsholder document exists in the repository, and none is claimed.
- **Display:** `allowed` for the academic prototype demo, on the strength of that statement.
- **External processing:** `allowed`. This covers the Sarvam OCR fallback for low-confidence pages in the prototype.
- **Training:** `allowed`. At 11:10 IST the statement did not cover training, so training was first recorded as `not_allowed`. At 11:12 IST the user said the permission also covers model training. The recorded basis is: "User-asserted academic permission covering model training, stated 2026-09-27; written permission document not yet on file."
- **Permission alone does not make text training data.** Only approved passages from fully reviewed pages, or from batches that passed sampling, can enter the training-eligible corpus (spec §4.10). Fine-tuning also needs the §7.3 minimum-data gate. Nothing has been trained.
- **NDLI stays discovery and links only.** The user's permission covers the source rightsholders' material, not NDLI's own records. No NDLI file has been downloaded.

**Versioning.** The database keeps one `rights_record` row per `source_key` and has no version column. Re-importing a manifest updates that row, and the audit log (`rights.update`) keeps the previous permissions. The three Constituent Assembly Debates (CAD) records therefore carry `record_version: 2` in `intake/cad_lok_sabha.manifest.json`, with version 1 (2026-09-26, all `not_allowed`) kept verbatim under `superseded_versions`. `intake/cad_intake_checks.manifest.json` holds an exact copy of version 2, so importing it cannot revert the row.

**Access level.** Sarvam runs only when the rights allow external processing **and** the item is not `restricted` (`archive.rights.external_processing_allowed`). The new items, and the CAD items in the manifest, are therefore `public_online_only`: shown online, never cached on kiosks. **Items 12–14 are already in the database as `restricted`.** Re-importing does not change existing items, so staff must change their access level before Sarvam or visitor display can apply to them. The two intake-check test items stay `restricted`.

## Open questions

1. **Written permission document.** Obtain it from each rightsholder and attach it to the rights records: Education Department, Govt. of Maharashtra, and Dr. Ambedkar Foundation (MoSJE) for *Writings and Speeches*; the Lok Sabha Secretariat (Speaker's permission, per https://elibrary.sansad.in/copyright-policy) for CAD. Until then every row rests on the user's statement alone.
2. **Training permission.** Confirm that the written document explicitly names model training. If it does not, set `training_permission` back to `not_allowed`.
3. **Kiosk caching.** Decide whether `public` (cached on kiosks, needed for offline exhibits) is acceptable for any item once the document is on file.
4. **Existing items 12–14.** Staff must change their access level from `restricted` if they should use Sarvam or be shown to visitors.

## Files in `data/incoming/`

SHA-256 values were recomputed from the bytes on disk on 2026-09-27. No two files share a checksum. For the MEA files, the server's `Content-Length` equals the local byte count.

### Full official files (preservation copies, not in any manifest)

| File | Source URL | Rights holder | Edition / volume | Lang | Bytes | PDF pages | Text layer | SHA-256 |
|---|---|---|---|---|---|---|---|---|
| `baws/mea_Volume1.pdf` | https://www.mea.gov.in/images/CPV/Volume1.pdf | Education Dept., Govt. of Maharashtra (compilation); Dr. Ambedkar Foundation (reprint) | *Writings and Speeches* Vol. 1; 1st ed. 1979; 3rd Foundation reprint Aug 2020; ISBN 978-93-5109-172-1 | en | 11,151,911 | 516 | Unicode (Century Schoolbook) | `fb7c5fe1ce9f575417d31d05748445798e8b05d18882c1246a598f19e877c7b8` |
| `baws/mea_Volume13.pdf` | https://www.mea.gov.in/images/CPV/Volume13.pdf | As Vol. 1 | *Writings and Speeches* Vol. 13; same imprint; ISBN 978-93-5109-184-4 | en | 23,211,889 | 1,278 | Unicode (Century Schoolbook) | `e6362ece69ba1adb2140b6f845fc44924408aa8de245bd68f2644ba2dc8ce546` |
| `baws/mea_VolumeH1.pdf` | https://www.mea.gov.in/images/CPV/VolumeH1.pdf | Dr. Ambedkar Foundation (Hindi translation) | *Dr. Ambedkar Sampoorna Vangmay* Khand 1; 13th ed. Aug 2020; ISBN 978-93-5109-150-9 | hi | 16,370,713 | 302 | **Legacy-font mojibake** (Kruti Dev 010, Walkman Chanakya); 0 Devanagari characters extracted | `26d973cead368498914507fe1ca191869093b9d3981bd0f2bd0cd7c0ab52d278` |
| `cad/cad_04-11-1948_en_sansad.pdf` | https://sansad.in/uploads/const_Assmbly_Debates_Volume7_4_November1948_64efedfedd.pdf | Lok Sabha Secretariat | CAD Vol. VII, sitting of 4 Nov 1948; retyped electronic text (Word file, 2012) | en | 1,432,526 | 211 | Unicode (Verdana) | `e0cb2ca1ce1132033f4b15ac14ddb873ccb89a45b3adc0ce9153c026f4ff9bac` |
| `cad/cad_25-11-1949.pdf` | https://eparlib.sansad.in/handle/123456789/763285 (via IA mirror) | Lok Sabha Secretariat | CAD Vol. XI, 6th reprint 2014 | en | 453,283 | 62 | Unicode | `b91746973cdc627d27b2bae85e39ca212f00a26068a44ab0204c4adf52d981bf` |
| `cad/cad_04-11-1948_hindi.pdf` | https://eparlib.sansad.in/handle/123456789/763480 (via IA mirror) | Lok Sabha Secretariat | CAD Hindi version Vol. 7 | hi | 482,126 | 96 | Legacy-font mojibake | `137dbb69795d3298348dcae298eabffbd1453312836c59f7f7e6bc3de85f4bb7` |
| `cad/cad_25-11-1949_hindi.pdf` | https://eparlib.sansad.in/handle/123456789/763515 (via IA mirror) | Lok Sabha Secretariat | CAD Hindi version Vol. 11 | hi | 511,731 | 92 | Legacy-font mojibake | `04c2f6ac64b3c9659065d8f7208ebf27341a5ffa8764f56f20ad00ef053adcb4` |

The last three rows were fetched on 2026-09-26 and are in `intake/cad_lok_sabha.manifest.json`.

### Excerpts for ingestion (`intake/baws_mea_cad1948.manifest.json`)

Full volumes are too slow to ingest on this machine. `textlayer.extract_pdf` renders every page of the PDF for each page it processes, so cost grows with the square of the page count. At the measured rate (62 pages in 507 s), a 516-page volume would take about 9 hours. The excerpts were cut with `pypdf` (`PdfWriter.add_page`, pages copied unchanged). Their checksums differ from the originals, and each item's `capture` block records the source file, its SHA-256, and the PDF page range. Together the four excerpts are 100 pages, against 250 pages for the three CAD items ingested on 2026-09-26.

| Item key | File (`data/incoming/…`) | Source pages (PDF → printed) | Pages | Bytes | Text layer | doc_class | SHA-256 |
|---|---|---|---|---|---|---|---|
| `baws-en-vol01-castes-in-india` | `baws/excerpts/baws_en_vol01_castes-in-india_pdf018-037.pdf` | 18–37 → 3–22 | 20 | 215,172 | Unicode; 19/20 pages have text (page 2 is the blank back of the title page) | born_digital | `e06a517831c1b3ede4f476972bc0bac8961f654b587c5ab46b718cf51e37c196` |
| `baws-en-vol13-speech-1949-11-25` | `baws/excerpts/baws_en_vol13_speech-1949-11-25_pdf1239-1251.pdf` | 1239–1251 → 1206–1218 | 13 | 166,475 | Unicode; 13/13 | born_digital | `ba3405967fda412252df25e710656686234ff11c64caa05c7ba12895f42d2a49` |
| `baws-hi-khand01-bharat-mein-jatipratha` | `baws/excerpts/baws_hi_khand01_bharat-mein-jatipratha_pdf020-041.pdf` | 20–41 → 3–24 | 22 | 200,042 | **Kruti Dev mojibake**: 0 Devanagari characters, 1,425 Kruti Dev pattern hits; 21/22 pages have text (page 2 is blank) | printed (local OCR `hin`; Sarvam fallback permitted) | `169c905cdc90555c5d1acbc4ed1644d4a5680d590d6200463a344f326105cd8d` |
| `cad-1948-11-04-en` | `cad/excerpts/cad_04-11-1948_en_proceedings_pdf001-045.pdf` | 1–45 (the sitting; appendices omitted) | 45 | 370,402 | Unicode; 45/45 | born_digital | `cc2cbf13ddd6c3b45ae54f8949d0fdd66ae3cd7e7f86001e6368d9e20ce83edd` |

Why these excerpts:

- **Vol. 1, "Castes in India".** Spec §8.1 item 1 asks for one chapter of Vol. 1.
- **Vol. 13, 25 Nov 1949 speech.** A second witness for the demo question on hero-worship (spec §8.5 step 6). The primary source remains the Lok Sabha report `cad-1949-11-25-en`.
- **Hindi Khand 1, same chapter.** Covers the Hindi and English pair and the legacy-font OCR path. The Hindi is the Foundation's translation, never Dr. Ambedkar's own words.
- **4 Nov 1948 sitting.** Dr. Ambedkar's introduction of the Draft Constitution (spec §8.1 item 3) is on excerpt pages 30–42. This file is the Secretariat's retyped text, not a facsimile of the printed volume, so it has no printed page numbers.

**Validation (2026-09-27).** `python -m archive.cli validate-manifest` was run from `backend/.venv` on all three manifests: `{"valid": true, "errors": []}`, exit 0 each time. A separate check confirmed that every file path resolves from `intake/`, SHA-256 matches, and `page_labels` length equals the page count. The only mismatch is the deliberate one in the `intake-check-checksum-mismatch` test item. **Ingestion was not run.**

## Source register

| # | Source (spec §8.1) | Bytes fetched | Rights holder | Display | Training | External processing | Evidence and notes |
|---|---|---|---|---|---|---|---|
| 1 | *Writings and Speeches* Vol. 1 (en), official MEA listing https://www.mea.gov.in/books-writings-of-ambedkar | **Yes** (2026-09-27) | Education Dept., Govt. of Maharashtra; Dr. Ambedkar Foundation | allowed | allowed | allowed | User-asserted academic permission, 2026-09-27; no document on file. The spec's URL https://www.mea.gov.in/images/attach/amb/volume_01.pdf now redirects to `https://www.mea.gov.in/error.htm` (HTTP 200, HTML). Earlier (2026-09-26) this row was BLOCKED for lack of any reuse grant; the Foundation's published terms still grant none. |
| 1a | *Writings and Speeches* Vol. 13 (en), same listing | **Yes** | As row 1 | allowed | allowed | allowed | As row 1 |
| 1c | *Sampoorna Vangmay* Khand 1 (hi), same listing | **Yes** | Dr. Ambedkar Foundation | allowed | allowed | allowed | As row 1. Translation. |
| 1b | Same set, MoSJE upload on the Internet Archive — https://archive.org/details/Dr.BabasahebAmbedkarWritingsAndSpeechespdfsAllVolumes | No (not needed) | As row 1 | — | — | — | The official MEA copy was reachable, so this third-party re-host was not used |
| 2 | Vol. 1, DLI scan — https://archive.org/details/in.ernet.dli.2015.7747 | No | Education Dept., Govt. of Maharashtra (`dc.rights`) | — | — | — | Not fetched. Third-party host, and outside this round's prototype-sized scope. Candidate for the spec §8.1 item 2 OCR comparison. |
| 3a | CAD, en, 25 Nov 1949, Vol. XI | Yes (2026-09-26) | Lok Sabha Secretariat | allowed (v2) | allowed (v2) | allowed (v2) | v2 on 2026-09-27: user-asserted academic permission. v1 (2026-09-26, all not_allowed) is kept in the manifest. Imported as item 12, which is still `restricted` in the database. |
| 3b | CAD, hi, 4 Nov 1948, Vol. 7 | Yes (2026-09-26) | Lok Sabha Secretariat | allowed (v2) | allowed (v2) | allowed (v2) | As 3a. Item 13. |
| 3c | CAD, hi, 25 Nov 1949, Vol. 11 | Yes (2026-09-26) | Lok Sabha Secretariat | allowed (v2) | allowed (v2) | allowed (v2) | As 3a. Item 14; its 2026-09-26 ingestion did not complete (Docker engine failure). |
| 3d | CAD, en, 4 Nov 1948, Vol. VII — https://sansad.in/uploads/const_Assmbly_Debates_Volume7_4_November1948_64efedfedd.pdf | **Yes** (2026-09-27) | Lok Sabha Secretariat | allowed | allowed | allowed | User-asserted academic permission. eparlib.sansad.in was unreachable (see below) and the IA eparlib mirror has no English 1948 sittings. Fetched from the official sansad.in host (server Last-Modified 2022-09-15). |
| 3e | CAD Vol. 1 — https://archive.org/details/eparlib.nic.in.760449 | No (not needed) | Lok Sabha Secretariat | — | — | — | Does not contain the target speeches |
| 4 | Marathi printed pages | No | — | — | — | — | The MEA listing carries English and Hindi volumes only. No official Marathi volume was found in this round. |
| 5 | Photograph | No | — | — | — | — | The spec names no specific official source, so none was fetched |
| 6 | Audio/video | No | — | — | — | — | The spec names no specific official source. The Foundation site has audio and video galleries, but the spec does not name them, so they were not fetched |
| 7 | Handwritten manuscript | No | Holding institution | — | — | — | Needs the institution's permission |
| — | NDLI — https://ndl.iitkgp.ac.in/ | **No — links only** | Respective source organisations | not_allowed | not_allowed | not_allowed | Unchanged. Spec §8.1: discovery and links only. The user's permission does not extend to NDLI's records. |

## Sources that failed (2026-09-27)

| URL | Error |
|---|---|
| https://www.mea.gov.in/images/attach/amb/volume_01.pdf (spec link; also `Volume_13.pdf`, `Volume_03.pdf`) | Redirects to `https://www.mea.gov.in/error.htm` (HTML, 16,981 bytes). Replaced by `https://www.mea.gov.in/images/CPV/…` from the official listing. |
| https://eparlib.sansad.in/ (ports 443 and 80) | `Failed to connect … after 21 s: Could not connect to server` |
| https://eparlib.nic.in/, https://loksabha.nic.in/… | `Could not resolve host` |
| http://164.100.47.194/Loksabha/Debates/cadebatefiles/C04111948.html | Connection timeout |
| https://ambedkarfoundation.nic.in/ | Connection timeout |
| https://drambedkarwritings.gov.in/ | TLS failure with certificate verification ("Could not establish trust relationship"); loads only with verification off. Used only to read link lists; no bytes were taken from it. |

## Findings from the 2026-09-26 local test (history)

- **Legacy-font Hindi PDFs.** Both Hindi CAD files, and now Hindi Khand 1 of *Writings and Speeches*, use non-Unicode Devanagari fonts. The text layer extracts as Latin mojibake (for example `Hkkjr esa tkfrizFkk` for "भारत में जातिप्रथा"), yet the importer's text-layer check marked most CAD Hindi pages "reliable". Item 14 was declared `born_digital` specifically to test this, so its text-layer output must not be approved.
- **The gate is uncalibrated.** Its version is `gate-v0-uncalibrated`, so pass/fail counts are not an OCR quality claim (spec §4.3, §10).
- **Whole-PDF processing is slow.** See the excerpt note above.
- **Sarvam was never called** on 2026-09-26, because items were `restricted` with `external_processing: not_allowed`. Rights now allow it, but items 12–14 are still `restricted` (see Access level).
- **Nothing is published.** Display permission alone does not publish anything: pages still need review, and `review.item_ready_for_publication` applies. Nothing has been quote-verified.

## Skills used (2026-09-27)

| Skill | Where it came from | What it changed |
|---|---|---|
| `pdf` | Local: `~/.claude/skills/synced/…/pdf/SKILL.md` | Used `pypdf` for page counts, metadata, font inspection and text-layer checks. Excerpts were cut with `PdfWriter.add_page`, which copies pages unchanged. |
| `data-quality-auditor` | Local plugin: `~/.claude/plugins/cache/claude-code-skills/engineering-advanced-skills/2.2.0/data-quality-auditor/SKILL.md` | Its tabular scripts and quality score do not apply to PDFs. Its checks did: a uniqueness check (no duplicate SHA-256 across `data/incoming/`), a validity check (every excerpt page renders; text present per page; script type), and confidence tags. Verified: checksums, page counts, text-layer script and fonts, byte counts against the server's `Content-Length`. Likely: the retyped CAD text matches the printed report. Assumed: nothing. |
| `verification-before-completion` | Local plugin: `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.4.1/…` | Before recording any result, the agent re-hashed every file from disk, re-ran `validate-manifest` on all three manifests, checked file paths, checksums and page labels, and diffed CAD rights v1 against git `HEAD`. It also removed a volume subtitle the file did not confirm. |
| `deep-research` | Local: `~/.claude/skills/synced/…/deep-research/SKILL.md` | Its coordinator mode needs subagents, which this agent could not spawn, so the skill's fallback applied: the agent researched directly. It checked official hosts first (MEA, sansad.in, Foundation) and recorded third-party mirrors only as byte sources. |
| `find-skills` | Local: `~/.agents/skills/find-skills/SKILL.md` | Local skills covered the task, so nothing was installed from skills.sh. |

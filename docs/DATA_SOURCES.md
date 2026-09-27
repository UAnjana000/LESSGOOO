# Data sources and rights register (acquisition log)

Checked 2026-09-26 by the data-acquisition agent. **These are not human rights decisions.** A person must confirm each row before any display or training use (spec §8.1).

Source bytes live only in `data/incoming/` (gitignored by `/data/`). Tracked manifests in `intake/` hold metadata only.

## Candidate sources

| # | Source (spec §8.1) | Bytes fetched | Rights holder | Display | Training | External processing (Sarvam/LLM) | Evidence | Test result |
|---|---|---|---|---|---|---|---|---|
| 1 | *Writings and Speeches* Vol. 1, MEA PDF — https://www.mea.gov.in/images/attach/amb/volume_01.pdf | **No — BLOCKED** | Education Dept., Govt. of Maharashtra (edition); Dr. Ambedkar Foundation (reprint) | — | — | — | Foundation terms (http://drambedkarwritings.gov.in/content/page/terms--and-conditions.php) grant no reuse. MEA copyright page could not be retrieved (404). A generic GIGW reuse grant would exclude third-party copyright anyway. | Not imported. The importer also refuses the template entry: `URL import requires download_permitted=true`. |
| 1b | Same set, MoSJE upload on the Internet Archive — https://archive.org/details/Dr.BabasahebAmbedkarWritingsAndSpeechespdfsAllVolumes | **No — BLOCKED** | As row 1 | — | — | — | No licence on the item. The uploader is a third party. | Not imported |
| 2 | *Writings and Speeches* Vol. 1, DLI scan — https://archive.org/details/in.ernet.dli.2015.7747 | **No — BLOCKED** | `dc.rights`: Education Department, Government of Maharashtra | — | — | — | IA metadata shows no licence. The DLI record names the Govt. of Maharashtra as rights holder. | Not imported |
| 3a | CAD, English, 25 Nov 1949, Vol. XI (6th reprint 2014) — https://eparlib.sansad.in/handle/123456789/763285 (mirror https://archive.org/details/eparlib.nic.in.763285) | **Yes**, `data/incoming/cad/cad_25-11-1949.pdf`, SHA-256 `b91746973cdc627d27b2bae85e39ca212f00a26068a44ab0204c4adf52d981bf` | Lok Sabha Secretariat | not_allowed | not_allowed | not_allowed | https://eparlib.sansad.in/help/copyright-policy.jsp allows non-commercial research and private study with attribution; other reuse needs permission. Seen via the search index; direct fetch failed. https://elibrary.sansad.in/copyright-policy (fetched directly) says all copyrights are reserved and reproduction needs the Speaker's permission. The mirror's CC-PD tag is **not** relied on. | Imported as item 12, 62 pages. 60 pages took the text-layer route (in batch review). 2 pages failed the local OCR gate and went to full review. No Sarvam call. |
| 3b | CAD, Hindi version, 4 Nov 1948, Vol. 7 — https://eparlib.sansad.in/handle/123456789/763480 | **Yes**, `cad_04-11-1948_hindi.pdf`, SHA-256 `137dbb69795d3298348dcae298eabffbd1453312836c59f7f7e6bc3de85f4bb7` | Lok Sabha Secretariat | not_allowed | not_allowed | not_allowed | As 3a | Imported as item 13, 96 pages, local Tesseract `hin`. 78 pages passed the gate (batch review); 18 failed (full review). No Sarvam call. |
| 3c | CAD, Hindi version, 25 Nov 1949, Vol. 11 — https://eparlib.sansad.in/handle/123456789/763515 | **Yes**, `cad_25-11-1949_hindi.pdf`, SHA-256 `04c2f6ac64b3c9659065d8f7208ebf27341a5ffa8764f56f20ad00ef053adcb4` | Lok Sabha Secretariat | not_allowed | not_allowed | not_allowed | As 3a | Imported as item 14, 92 pages. **Ingestion did not complete:** after about 2.5 h, Docker Desktop's engine failed (`error waiting for container: unexpected EOF`; API returns 500). Page state is unverified. |
| 3d | CAD, English, 4 Nov 1948, Vol. VII | **No** | Lok Sabha Secretariat | — | — | — | Primary eparlib.sansad.in was unreachable (connection refused / timeout). No IA mirror was found. | Not fetched |
| 3e | CAD Vol. 1 (spec link) — https://archive.org/details/eparlib.nic.in.760449 | No (not needed) | Lok Sabha Secretariat | — | — | — | Same terms as 3a | Does not contain the target speeches |
| 4 | Marathi printed pages | No | — | — | — | — | No source with a recorded rights basis was found | Not fetched |
| 5 | Photograph | **No — BLOCKED** | Unknown | — | — | — | No documented public-domain status or written permission | Not fetched |
| 6 | Audio/video, incl. Foundation audio on drambedkarwritings.gov.in | **No — BLOCKED** | Dr. Ambedkar Foundation / broadcasters | — | — | — | Foundation terms grant no reuse | Not fetched |
| 7 | Handwritten manuscript | **No — BLOCKED** | Holding institution | — | — | — | Needs institution permission | Not fetched |
| — | NDLI — https://ndl.iitkgp.ac.in/ | **No — links only** | Respective source organisations | not_allowed | not_allowed | not_allowed | https://ndl.iitkgp.ac.in/terms prohibits data mining, copying and public display without the source's permission | The importer refuses discovery-only content |

## Findings from the local test

- **Legacy-font Hindi PDFs.** Both Hindi CAD files use a non-Unicode Devanagari font. The text layer extracts as Latin mojibake (for example `vad 7 la[;k`), yet the importer's text-layer check marks most pages "reliable". Item 14 was declared `born_digital` specifically to test this, so its text-layer output must not be approved.
- **The gate is uncalibrated.** Its version is `gate-v0-uncalibrated`, so pass/fail counts are not an OCR quality claim (spec §4.3, §10).
- **Whole-PDF processing is slow.** `textlayer.extract_pdf` renders every page of the PDF for each page it processes: 62 pages took 507 s, and 96 pages took 816 s.
- **Sarvam was never called.** Items are `restricted` with `external_processing: not_allowed`, so failed pages went to `needs_full_review` even though `ARCHIVE_SARVAM_API_KEY` was set.
- **Nothing is publishable.** `display_permission` is `not_allowed`, and `review.item_ready_for_publication` refuses publication in that case. Nothing was quote-verified.

# SACC Handoff & Multi-Agent Coordination Log

## Active Environment & Repository State
- **Repo Path**: `/Users/daplug/Documents/SACC`
- **Active Branch**: `codex/takeout-recovery-m1`
- **Remote**: `git@github.com:Ballinonabudget/SACC.git`
- **Active Environment**: macOS Apple Silicon M1, Python 3.13.15 virtualenv (`.venv-poc-313`)
- **Last Verified Test Run**: 106 of 106 unit tests passing (`PYTHONPATH=tests:. .venv-poc-313/bin/python -m unittest discover tests`), including 15 focused triage/Library regressions.
- **Latest Local Repair**: `9a80000` plus the accompanying handoff update; committed locally, not pushed. The app on port 5174 is running the repaired code.
- **Coordination Protocols**: Defined in `SACC_ANTIGRAVITY_RESPONSIBILITIES_AND_CROSSCHECK.md` and `SACC_CODEX_RESPONSIBILITIES_AND_CROSSCHECK.md`.

---

## Major Completed Milestones (as of 2026-11-01)

### 1. Google Takeout Full Recovery Execution (Completed)
- **Scope**: Full 87,982 planned Google Photos Takeout media items.
- **Location**: `/Users/daplug/Documents/SACC_Data/recovery/denivic/`
- **Results**:
  - `metadata_write_readback_passed`: 63,558 files successfully enriched with EXIF timestamps and GPS tags.
  - `manifest_only_format`: 21,513 files recorded in manifest (formats where direct EXIF write is unsupported or unnecessary).
  - `unchanged_needs_review`: 2,911 items flagged for manual/visual review.
  - Recovery ledgers & SQLite state saved at: `/Users/daplug/Documents/SACC_Data/recovery/denivic/recovery-run.sqlite3`.
  - Originals on NAS and source archives remain 100% byte-for-byte untouched.

### 2. SACC Recovery Library Catalog & Backend (Completed)
- Initialized and populated library catalog: `/Users/daplug/Documents/SACC_Data/library/staging/sacc-library.sqlite3`.
- Ingested all 87,982 records into catalog occurrences table.
- Built `sacc_takeout/` package:
  - `library.py`: SQLite adapter for catalog initialization, recovery import, search queries, pagination, and atomic optimistic review decisions.
  - `organization.py`: Immutable layout planning, preview generation, and reversible copy-on-write (COW) folder restructuring.
  - `importer.py`, `locations.py`, `trip_preview.py`, `full_recovery.py`: Robust streaming processors with safety invariants (`private_root` enforcing no accidental writes to source/repo trees).

### 3. SACC Frontend Library View (`SCAA/sacc/library-view.jsx`)
- Built standalone React component for browsing recovered media directly on the local origin:
  - Full server-driven pagination and multi-facet filtering (media type, capture year/month, GPS presence, review reason, store).
  - Inspection dialog for EXIF dates, GPS coordinates, store inferences, and source history.
  - Bounded multi-select review workflow with optimistic concurrency control (`review_revision`).
  - Safe organization plan preview.

### 4. Full-Library Vision Triage on Apple Silicon M1 (Automatic suggestions)
- Script: `scripts/triage_full_library.py` (executed via PyTorch MPS on Apple M1 GPU with open-vocabulary YOLO-World v2).
- **Local execution**: Repair retries used existing model weights with external networking blocked. No media was uploaded.
- **Current detections after repair**: 43,542 `non_personal`, 29,181 `personal`, 15,244 `unknown`, and 15 `error`; total 87,982. Effective privacy is `unknown` for errors, giving 15,259 unknown privacy labels.
- These are model suggestions, not reviewed privacy decisions or promotion approvals. Human privacy reviews remain zero; `remote_eligible` remains zero throughout the catalog. Labels describe catalog rows, not a completed physical folder organization.
- Original triage recorded 284 failures and marked 14 trailing items unknown without inference. All 298 were retried once: 283 succeeded, including all 14 tail items; 15 remained failed.
- Remaining failures already existed before this repair: 12 JPEGs report truncated image data, two Sony RAW files are unsupported by this decoder, and one occurrence has unknown media type. Keep them flagged for source comparison or a supported preview workflow; never overwrite originals to force inference.

### 5. Focused Catalog Safeguard Repair (2026-11-01, completed locally)
- See `docs/SACC_TRIAGE_REPAIR.md` for scope, commands, validation and rollback.
- Verified before-repair backup: `/Users/daplug/Documents/SACC_Data/backups/library-before-safeguards-2026-11-01_223312_EST/sacc-library.sqlite3`.
- Restored 9,611 hidden metadata warnings; 9,793 rows had attention projections corrected overall. The earlier 2,150 count covered only the `unchanged_needs_review` subset. The projection repair itself changed zero privacy labels.
- Machine suggestions survive note edits/source refresh; explicit human privacy overrides take precedence. Metadata concerns and triage uncertainty both retain attention. The UI identifies automatic suggestions separately from human decisions.
- Failed/pending items can be retried; partial batches are actually inferred; per-file failures are isolated. Attempts, policy/model/source identity and audit events are retained.
- Canonical path guards now cover relative, symlink, stored and default paths in legacy media/ingestion routes, including backup/calibration/validation copies.
- Live verification: SQLite `quick_check=ok`, zero foreign-key violations, 87,982 occurrences, 87,757 unique media, unchanged retained metadata/file locators/source history/PoC rows, zero hidden metadata warnings. There are 24,947 attention rows and 10,091 automatic audit events; these events do not count as human review.
- Original media, recovery ledger, organization state and production shoe records were not modified. No external Antigravity review has been sent or claimed.

### 6. Privacy-Separated Organization Preview (2026-11-02, completed; not applied)
- Nitty selected the local organization preview. Used existing `LibraryDB.layout_rows` privacy filters and `organization.create_plan` with separate destination roots; no application code changed. The CLI's generic preview does not itself choose privacy-specific destination roots.
- Preview overview: `/Users/daplug/Documents/SACC_Data/library/organization-plans/preview-2026-11-02/README.md`; machine-readable results and validation are in the adjacent `summary.json`.
- `organized/sneakers/`: 43,542 automatic `non_personal` candidates (37,689 images, 5,853 videos), plan `4396b65d9ae41926b9f9feb34d27cae8bf77cbe1e65b6f18ac92a734314fe55a`.
- `organized/personal/`: 29,181 `personal` occurrences (24,389 images, 4,792 videos), plan `4af0c802b593688132d874f24e8e9394521d3516c3fa08cd035987ec87b11a54`.
- Both sealed plans are under `/Users/daplug/Documents/SACC_Data/library/organization-plans/<plan_id>/`. All 15,259 unknown occurrences remain excluded in the review queue. No held rows in either selected plan.
- Verified plan digests, exact privacy membership, no overlap, all selected review revisions, absent output media, and same-filesystem APFS placement. Catalog file SHA-256 unchanged; zero organization links and zero remote eligibility. Only private plan artifacts and empty destination roots were created; no media cloned, copied, uploaded or promoted. Clonefile execution and full source-hash readback remain apply-time checks.
- Before any separately authorized apply, revalidate current privacy membership as well as revisions: the generic plan does not continuously enforce its privacy bucket. Automatic labels remain suggestions, not human export/promotion approval.
- Typesafe documentation research completed at Nitty's request; assessment and sources are in the preview folder's `TYPESAFE_EVALUATION.md`. Potential second-opinion experiment only; image support is experimental. No SDK, credential access, inference calls or uploads. No production integration or Anti-Gravity approval is claimed.
- **Operator decision (2026-11-02): do not use Typesafe for SACC.** Retain the assessment as research history only; no pilot or integration is planned. Continue with local triage and operator review.

### 7. Remaining Media Exception Investigation (2026-11-02, completed; no catalog changes)
- Investigated all 15 failed occurrences against their exact ZIP members on the NAS, opened read-only. Private evidence and report: `/Users/daplug/Documents/SACC_Data/library/media-exception-audit/2026-11-02/README.md`; offline operator gallery: adjacent `review.html`.
- **12 JPEGs:** ZIP CRC and recorded original source SHA-256 verified. Source and recovered files both fail strict Pillow/libjpeg decoding; first JPEG scan marker through EOF is byte-identical. Sources lack an end-of-image marker in that payload and end with about 1.0–4.8 MB of zero bytes. Recovery did not introduce this damage. Only 160x120 embedded thumbnails were recoverable. Same-name/media-hash and filename-stem catalog searches found no healthy replacements; other backups remain unsearched.
- **2 Sony RAW files:** source and recovered bytes match. Extracted strict-decodable 1920x1080 embedded previews and generated separate strict-decodable 6000x4000 JPEG renders with macOS `sips`. Same-stem, same-capture-time counterparts already in the catalog contain JPEG data despite `.ARW` filenames and decode at 4898x3265. Neither previews nor rendering establish complete RAW sensor-data integrity.
- **1 `.MP` file:** confirmed as a short HEVC video; both video streams decode successfully. Primary stream is 1920x1080, about 0.998 seconds. Saved a byte-identical `.mp4` working copy and a separate frame. A likely same-stem JPEG companion exists; no automatic association or merge was performed. The catalog's unknown media type reflects an extension-recognition gap.
- Source copies, embedded previews, RAW renders and video derivatives are private local artifacts only. No media was viewed through a cloud service, uploaded, promoted, organized or assigned a new privacy decision. All 15 retain unknown privacy and existing failed triage records; the 12 JPEGs remain damaged and flagged.
- Final verification: catalog and recovery-ledger SHA-256 unchanged; all 15 recovered hashes and identities unchanged; all three source ZIP identities unchanged (whole ZIPs were not rehashed). Gallery validation confirmed 15 cards and image references, all referenced files present and no remote URLs. No application code changed; no unit-test rerun was needed for this forensic inspection. No Anti-Gravity implementation approval or QA is claimed.

---

## Do Not Change / Guardrails
- **Byte-for-byte immutability**: Original Takeout ZIP archives and NAS source videos (`/Volumes/The Final Cut X`) must never be modified.
- **Personal Privacy Guarantee**: Any media tagged `privacy = 'personal'` must never be sent to cloud APIs (Gemini/Vertex) or promoted to the production shoe database (`sacc_app.db`).
- **Safety Invariant**: All staging and recovery operations must use `private_root` outside the repository and watched folders.
- **Working Tree Protection**: Do not run destructive Git commands (`git restore .` or `git clean -fd`) without cross-agent coordination.

---

## Next Recommended Tasks (Priority Order)

1. **Review Diagnosed Media Exceptions (source investigation complete)**:
   - Open the private `media-exception-audit/2026-11-02/review.html` noted above. Do not repeat unchanged source comparisons. Keep the 12 damaged JPEGs flagged; seek better originals in other authorized local backups if available. RAW and video working previews are ready for local operator review. A separate engineering increment for RAW derivatives and verified `.MP` video recognition requires the normal design/review process before production changes.
2. **Operator Review in SCAA UI**:
   - Launch or view SACC at `http://localhost:5174/SACC.html`.
   - Use the **Library** tab filters (`Privacy: Personal`, `Privacy: Non-personal`, `Privacy: Unknown`) to audit classifications and manually flip any items as desired.
3. **Review Existing Copy-on-Write Organization Preview (generation complete)**:
   - Review the two plans recorded above; do not regenerate unchanged previews. Applying clones is a separate operator-authorized step, with current privacy/revision validation required first.
4. **Separate future production increment**:
   - Validate explicit human approval and promotion behavior before ingesting reviewed sneaker records into `sacc_app.db`. Automatic `non_personal` suggestions alone do not authorize cloud processing or promotion. Legacy price/date/drop synchronization defects remain outside this repair.

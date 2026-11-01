# Trip and store-stop preview — 2026-10-30

The bounded trip preview is implemented and independently reviewed: **PASS**.
It adapts the relevant Outlet Plug sequencing principles without changing that
repository. Denivic is confirmed as the first export to process.

GPS and active confirmed branch evidence come first. Capture times and filename
sequence support grouping. Photos and videos share one timeline. A store change
can split a stop even when mall GPS is identical. A longer pause can stay within
one stop when stable GPS or the same exact confirmed branch supports continuity.
Brand names alone cannot identify a branch, and inferred locations never become
measured camera coordinates or anchors for another inference.

## What the real preview found

| Measurement | Result |
|---|---:|
| Existing source-verified sample records | 200 |
| Nearby registered sidecar-cache records | 390 |
| Total metadata records inspected | 590 |
| Sample records missing GPS | 50 |
| Missing-GPS sample records with usable dates | 43 |
| Weak one-sided hints | 3 |
| Still unresolved | 47 |
| Unresolved: no nearby original location anchor | 37 |
| Unresolved: conflicting source evidence | 3 |
| Unresolved: uncertain capture dates | 7 |
| Proposed trips / stops | 193 / 203 |
| Truncated context windows | 0 |
| New store assignments / GPS writes | 0 / 0 |
| New media extractions or rewrites | 0 |

The three hints are opportunities for inspection, not three recovered locations.
There are no new confirmed branches. Actual branch accuracy is unevaluated.
Cached neighbors supply local metadata context; their media bytes and embedded
tags were not read or reverified by this preview. Random sample points are sparse,
so these trip/stop counts are not a complete count of real shopping visits.

Screenshots are exempt from missing-GPS requirements once identified in an
explicit local review. None has been identified by media ID in this real sample;
missing GPS or a PNG extension alone does not establish that a file is a screenshot.

## How to read the new files

Keep the original `review.csv` for individual metadata checks. The separate
`trip_preview.csv` is a proposed grouping sheet, with one row per proposed stop.
Both are under the same batch reports folder:

`/Users/daplug/Documents/SACC_Data/recovery/milestone1/reports/2ec7131b299ec7b0667019c7c1307e3c8a96df7d4b91bdeae652c37dc74506a0/`

1. Open `trip_summary.md` for the short scope statement, or use the table above
   for detailed counts. No need to repeat the 200-file spot check.
2. In `trip_preview.csv`, read `trip` and `stop` together. Separate stop numbers
   mean separate proposed segments; neither number is a confirmed location tag.
3. Read `start_utc` and `end_utc` as UTC. No camera timezone was invented. Use
   first/last filenames and photo/video counts to recognize a sequence.
4. `missing_gps` counts items lacking observed GPS. `screenshots_gps_not_expected`
   counts explicitly confirmed screenshots. A zero store-reference field does
   not mean the store is known; an empty field means no confirmed supporting label.
5. Read `review_reasons`. `unlocated_temporal_bundle_not_store_evidence` is only
   a time bundle. `contains_unverified_cached_context` distinguishes cached
   neighbors. No action in Numbers automatically changes the database.

Evidence IDs, per-item proposals, provenance and reasons are in local
`trip_preview.json`. This file and the CSV remain local because they contain
private names, dates and location context. This engineering summary is sanitized.

## Completed changes and validation

Added `sacc_takeout/trip_preview.py`, the CLI `trip-preview` command, and focused
synthetic tests. The engine separates trips from stops, protects exact branch
transitions and historical validity, rejects ambiguous/tied/conflicting anchors,
limits inference to original evidence and respects screenshot exclusions.

The adapter opens the existing manifest read-only, validates recorded sample
provenance and reads bounded cached context. It cannot initialize or migrate a
database. The global 5000-neighbor cap fails conservatively if exceeded.

All 44 repository tests pass. The independent reviewer also passed ten targeted
scenario assertions and recorded final PASS in `SACC_TAKEOUT_TRIP_PREVIEW_REVIEW.md`.
The real run preserved the manifest SHA-256 exactly, all 67 pre-existing working
files, the checked Outlet Plug source hashes and its Git status. Detailed proof
and test logs are in the private milestone output root. No live DB/API changes,
network analysis, media uploads, schema migrations or new dependencies occurred.

## Next work and unresolved issues

The sample spot checks are accepted as qualitative user review. Next, build a
separate full-recovery workflow for the Denivic export, including large-video
streaming, bounded temporary space, restart verification and a reviewable run plan.
The existing dry-run command retains its 200-file cap. The proposed next stage is
documented in `SACC_TAKEOUT_FULL_RECOVERY_DESIGN.md` and independently approved
with notes, all reconciled. It is not a completed command or permission to start
full recovery. The next implementation begins with a read-only plan and a bounded
pilot using existing sample copies; the full-run approval comes after measured
results and independent implementation QA.

The real historical store-directory snapshot is still unavailable. It is needed
for named branch suggestions and reuse of confirmed local tags, not for preserving
existing GPS. Date/format conflicts stay in review. Export completeness is still
unconfirmed; a later export can be compared without replacing the current batch.
Video/HEIC/RAW embedding and the live SACC media-ID bridge remain separate work.
No full-library recovery, quarantine, final naming, classification or live import
has run.

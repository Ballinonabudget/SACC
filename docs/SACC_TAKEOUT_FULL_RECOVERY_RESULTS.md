# Recovery runner results — 2026-10-31

The reviewed local runner is built: immutable plans, separately scoped approvals,
bounded ZIP64/file streaming, two-pass source/conflict checking then metadata
writing, durable progress/publication recovery, reports and review refreshes.
No paid AI calls are needed. Original milestone caps remain unchanged.

Final validation: **78 tests passed**, and independent implementation QA returned
**PASS** with no remaining code blockers. Additional independent probes exercised
review-refresh rollback/budget/no-op behavior and deferred post-publication cleanup.
Changes remain uncommitted on `codex/takeout-recovery-m1`, preserving the existing
dirty working tree. Code/test fingerprints are recorded in the QA document.

## Pilot result

| Measurement | Result |
|---|---:|
| Already-extracted sample files selected | 12 |
| Source bytes | 36,311,250 |
| JPEG metadata write/readback successes | 11 |
| Video retained with canonical metadata, unchanged bytes | 1 |
| Processing errors | 0 |
| Initial processing duration | 3.985 seconds |
| New original-ZIP payload reads | 0 |
| Repeated copies/writes on resume | 0 |
| Remote calls / live imports | 0 / 0 |
| Pre-existing working files preserved | 67 |

Each staged source SHA was rechecked against the original recorded hash. All 12
staged-source hashes/mtimes and the original milestone SQLite SHA remained unchanged.
Resume was tested with source-copy and metadata-write functions patched to fail
if called; it reused all results and the same report snapshot with unchanged
cumulative source-byte accounting. Originals were not moved, renamed or rewritten.

This pilot tests the new runner on existing sample files. It does not measure NAS
throughput or prove real 5.5 GiB video behavior. Exact original JSON byte packaging,
large bounded streams and PNG GPS/description injection are covered by synthetic
tests. The pilot's sidecars are canonical snapshots, not reconstructed originals.
The count 11 means metadata write/readback passed, not 11 newly recovered GPS readings
or 11 confirmed store identities. The aggregate alone does not establish which
individual files already had GPS; fresh GPS insertion is proven by synthetic tests.

## Prepared full plan — not executed or approved

Input: all 38 Denivic ZIP parts, account kept separate from future accounts.
Selection: 87,982 occurrences including album/export copies and one unknown format;
407,786,951,500 planned uncompressed media bytes (379.78 GiB).

Output: `/Users/daplug/Documents/SACC_Data/recovery/denivic`.
Plan ID: `d470c73c64ceea445e682cfe973216c70e35a05242d9ec157c43247b601b72f0`.
Budget: 454.42 GiB free, including reserve/temporary/metadata overhead. The planning
snapshot had about 674.4 GiB free; execution must check again. Planning only copied
inventory/review metadata into the new ledger; no full-library media were extracted.

The full run would preserve source ZIPs, retain working media and canonical
metadata, embed safe supported JPEG/PNG fields, and keep conflicts/unsupported
formats in review. Video/HEIC/RAW embedding remains manifest-only. No duplicate
quarantine, final Finder rename, classification, shoe identification, store
confirmation or live SACC import is included in this execution scope.

## Review and remaining steps

The design was independently APPROVED WITH NOTES and reconciled before coding.
Implementation review found and corrected tool-monitoring after output EOF,
copied-review-history capacity accounting and atomic review-refresh publication.
Deferred transient-cleanup failures preserve committed outputs and resume as
cleanup only, without rereading sources or replaying old raw publication updates.
Tests and final independent QA are documented in
`SACC_TAKEOUT_FULL_RECOVERY_IMPLEMENTATION_QA.md`; the runbook documents the exact
commands, integrity distinctions, pause/resume and resource behavior.

The next execution gate is Nitty's approval of this exact full plan after reviewing
the pilot and independent QA. Do not infer full authorization from naming approval
or the instruction to build/test the runner. Folder organization, reversible
renaming and SACC browsing/search integration remain subsequent builds; exact
shoe identification through eligible-media API calls comes last.

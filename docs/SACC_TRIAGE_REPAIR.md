# Focused triage repair — 2026-11-01

The user explicitly authorized repairing the backed-up catalog in the current
chat. This restores the previously reviewed Library invariants; it does not
authorize organization, shoe promotion, remote inference, or changes to originals.
Base: fe82dfe. Backup: SACC_Data/backups/library-before-safeguards-2026-11-01_223312_EST.

The 91 existing tests missed the new triage writer. It clears metadata attention,
does not integrate machine labels with Library reviews, skips failed rows on
resume, and records trailing rows without inference. Relative paths also bypass
the legacy media guard.

Plan: retain Library schema v1 and use a versioned additive triage extension.
Preserve legacy detections, raw metadata, source history, human overrides, file
locators, and remote_eligible=0. Record processing status, attempts, policy/model
provenance and source identity separately from suggested category. Derive effective
privacy from human override then machine suggestion. Combine metadata attention
with triage uncertainty; neither can clear the other. Advance review revisions
and record machine changes without calling them human review.

An explicit transactional repair restores projections. The 14 verified legacy
tail records may be marked pending only with matching end-of-catalog, batch
remainder, and zero-evidence signatures. Missing/failed/pending records are
processed once per invocation. Partial batches are actually inferred; one bad
input is isolated from its batch. Signals finish the current inferred batch.
Model files are local and external networking is blocked during inference.

Canonical path checks protect relative, absolute, symlink and stored/default
paths at file consumers, including the PoC ingestion bridge. No general remote
access is added. Changes are limited to triage/Library projection, their protected
file paths, regression tests and current handoff documentation.

Validation: first use synthetic fixtures for flags, manual/automatic label
precedence, note/clear/source refresh, stale revisions, migration idempotence,
tail/error retry, batch isolation, interruption and path guards. Apply the repair
to a disposable backup copy and reconcile retained tables/metadata. Then take the
app briefly offline, apply the same transaction to the live catalog, restart the
updated app, retry the bounded exceptions, and check aggregates/integrity.

Rollback: stop writers; retain the current catalog; restore the verified SQLite
backup with correct WAL handling and restore the pre-repair source checkpoint.
No rollback deletes or rewrites original media. Legacy pricing/drop fixes remain
a separate increment. No external Antigravity review has been claimed or sent;
the user's requested focused repair is validated locally and the external review
requirement remains recorded for subsequent coordination.

## Applied results

Code commit: `9a80000`. The original working checkout was fast-forwarded and the
local app restarted on port 5174. Changes are committed locally, not pushed.
The live catalog matched the verified backup before mutation. The repair first
passed on a disposable backup copy, including an idempotent repeat and a local
16-item inference smoke check. The final synthetic suite passed 106 tests.

The live transaction changed 9,793 attention projections, restoring 9,611 hidden
metadata warnings without changing privacy labels. The original 2,150 finding
was one subset. It marked 14 proven legacy tail items pending. A bounded local
retry processed those 14 and 284 previous errors exactly once: 283 succeeded,
15 remained failed. All 14 tail items succeeded. No full-library rerun occurred.

Remaining failures already had `error` records in the pre-repair snapshot:
12 JPEG decodes report truncated image data, two Sony RAW images are unsupported
by this decoder, and one occurrence has unknown media type. These are retained
as unknown privacy with attention and a failed processing status. Do not clear
them by allowing truncated-image loading or overwriting source files. Compare
original Takeout sources and evaluate separate preview copies next.

Final counts: 87,982 occurrences; 87,757 unique media; 87,967 successful detections;
15 failed; zero pending or missing detections. Categories: 43,542 non_personal,
29,181 personal, 15,244 unknown, 15 error. Effective privacy maps errors to unknown
(15,259). There are 24,947 attention rows, 9,793 repair audit events and 298 retry
audit events. Human review count and remote eligibility are both zero.

Read-only reconciliation found `quick_check=ok`, zero foreign-key violations,
zero projection mismatches, zero hidden metadata warnings, unchanged retained
occurrence fields, and identical media/source-history/import/PoC tables. No
original media, recovery ledger or organization state was written. This is a
catalog reconciliation, not a new byte-level audit of every source file.
Live API checks confirmed health, Library sessions, occurrence count, automatic
label provenance, updated frontend delivery and absolute/relative legacy video
path rejection (403); unauthenticated Library reads still return 401.

The explicit repair command used was:

```sh
.venv-poc-313/bin/python scripts/triage_full_library.py --db /Users/daplug/Documents/SACC_Data/library/staging/sacc-library.sqlite3 --repair --legacy-tail 14 --apply
```

The bounded retry command used was:

```sh
.venv-poc-313/bin/python scripts/triage_full_library.py --db /Users/daplug/Documents/SACC_Data/library/staging/sacc-library.sqlite3 --weights /Users/daplug/Documents/SACC/yolov8s-worldv2.pt --limit 298
```

Exit status 2 from retry means retained retryable exceptions, not a transaction
failure. Future retries should follow diagnosis of these 15 files; repeating
inference alone will not restore missing JPEG bytes or add decoder support.

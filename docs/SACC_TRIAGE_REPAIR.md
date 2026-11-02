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

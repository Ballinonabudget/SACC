# Per-file metadata readback deferral — 2026-10-31

Nitty asks to finish the batch and revisit failed metadata writes at the end.
Current runner stops on any metadata exception. Proposed narrow change: only an
explicit expected-tag readback mismatch from the candidate writer becomes a
retained, unchanged `review` outcome; processing continues with the next item.
Original byte identity, readback requirements and original source ZIPs are preserved.

Implementation and independent QA: **PASS, 86 tests passed**. The exact paused
historical DateCreated item was retained unchanged using the reviewed operator
assertions, with error-only evidence and unchanged attempt/read counters. The
approved batch was resumed from 47,740 terminal outcomes (41,249 successful writes,
6,491 retained review outcomes), leaving 40,242 items for metadata processing.
No code, source-copy or approval-scope expansion occurred during restart. Runtime
evidence and reviewed source hashes are in the local readback-deferral audit.

## Implementation and impacts

Add a typed `MetadataReadbackMismatch(ValueError)` for the existing expected-tag
comparison in recovery_io.py. Catch it only around restore_candidate, before
publication. Recheck the owned raw output against persisted original SHA, size,
mtime and matched-sidecar hash. If any check fails, stop normally; do not defer.
If intact, atomically append the exact failure/evidence, set unchanged_needs_review
and review state, and retain the source/canonical observations. Mark the owned
candidate intent cleanup_pending; never adopt its unverified candidate or label
the file a successful metadata rewrite. Account for remaining transient allocation.
Existing cleanup-only recovery handles that intent without replaying publication.

No schema, filename, original metadata, API, account, selection, tool-version or
approval-scope change. Existing approved recovery remains the same batch. Changes:
recovery_io.py, full_recovery.py and focused synthetic tests. Known already-paused
DateCreated/Description mismatches may receive the same operator-reviewed unchanged
disposition only after identical integrity checks and a recorded event.

Other exceptions (disk space, corruption, source changes, preservation mismatch,
tool execution/timeout, publication errors) still stop. No broad catch-and-skip,
forced successful readback, relaxed timestamp comparison or silent field removal.
No automatic retry loop over review files at the end: final reports enumerate
them for a separate reviewed repair pass. Reports distinguish successful writes
from unchanged review outcomes. Monitoring continues to report actual counts.

## Tests and rollback

Synthetic mixed batch: first/middle date, GPS or description readback failures
retain raw hashes and annotations while later items finish. Prove source/sidecar
corruption, generic tool/OS/ENOSPC and preservation errors still halt. Check cleanup-
only resume, reports, retry counters and existing full-suite regressions. Final
independent QA precedes restart. Code rollback restores stop-on-mismatch behavior;
the reviewed raw copies and audit events remain intact.

## Review resolution

Independent review and engineering reconciliation are recorded below. No user
clarification is needed for this scope.

### Engineering reconciliation

Independent decision APPROVED WITH NOTES; all notes accepted, none rejected.
Add bounded exact expected/observed evidence for new typed failures and a distinct
report reason/count. Historical failures have only their original recorded error;
any unchanged disposition is an explicit exact-plan/item/operator action, never
substring auto-skipping. Validate raw and sidecar again before atomic commit of
item/result/output/event/cleanup-only intent; preserve attempt counters. Test
transaction rollback, safe continuation, cleanup-only resume and hard-stop errors.

### Independent design review — 2026-10-31

Reviewer: independent Codex agent, using Nitty's authorized Anti-Gravity
substitution. Reviewed this proposal and current writer, publication/recovery and
report code only; no private media or detailed real records were inspected.

#### Decision

**APPROVED WITH NOTES.** Reconcile the following implementation details before
coding. The user-requested continuation is compatible with retaining a verified
raw copy as an explicit unsuccessful metadata-write outcome. Independent QA must
pass before restarting the batch.

#### What looks correct

The exception is narrowly typed at expected-tag comparison, before publication.
Raw/sidecar integrity is rechecked; the candidate cannot become an adopted output.
Other failure classes keep the existing stop behavior. Later repair remains a
separate reviewed action, without an implicit retry loop or relaxed verification.

#### Missing requirements

Persist a distinct reason such as `metadata_readback_mismatch` so final reports
can enumerate these files separately from unsupported formats and generic review
items. Do not count them as successful writes. Preserve attempt counters and the
original failed attempt rather than resetting them or fabricating a success.

#### Data concerns

For new typed failures, retain the compared field and bounded expected/observed
values (including an explicit missing-value representation), original exception,
source identity and policy/action provenance locally. Never infer expected or
observed values for a historical failure whose ledger contains only its error text.
The existing paused-item disposition must be an explicit operator action bound to
the exact plan/item and allowlisted recorded failure; ordinary generic exceptions
must not become deferrable through substring matching.

#### Edge cases

Raw hash/size/mtime, sidecar hash and owned intent checks must happen before the
review transition. If these checks or cleanup fail, preserve their existing failure
semantics. Budget remaining transient blocks even when candidate cleanup is
deferred. A crash must never expose review state with an adoptable ready intent.

#### API/cost concerns

No network or provider change. Bound persisted failure evidence within the existing
record limits; missing or malformed tool output is not a tag mismatch exception.

#### Architecture concerns

Commit item/result/output changes, failure audit event and cleanup-only intent
state in one transaction. A cleanup-pending intent must never replay publication
or the former raw-state update. Normal resume must leave deferred review files
unchanged and continue unfinished items without new source reads for those files.

#### Testing gaps

Exercise date/GPS/description mismatches before later successful items; assert
exact raw/sidecar preservation, evidence, reports and counters. Inject source and
sidecar tampering, preservation mismatch, generic errors and capacity failures to
prove they still stop. Cover crash/rollback at the deferral transaction and
cleanup-only resume, plus the explicitly selected historical-error disposition.

#### Suggested changes

Implement the narrow exception and atomic retained-review path with the above
audit details; retain strict readback comparisons and existing integrity checks.

#### Questions requiring resolution

None requiring user input for this scoped change.

#### Blocking issues

None for design approval after reconciliation. Implementation QA remains required
before batch restart; this review does not validate any private failed file.

### Independent implementation QA — 2026-10-31

Reviewer: independent Codex agent, using the same user-authorized Anti-Gravity
substitution. Reviewed the two changed implementation files, focused synthetic
tests and reconciled design. All execution in this QA used temporary synthetic
fixtures. No private real media, filenames, GPS, per-file records or original
source ZIP payloads were inspected. No real disposition or batch restart was
performed by this reviewer.

#### Result

**PASS.** The scoped deferral change is ready for the engineer's exact-item
historical disposition and continuation of the already approved batch, subject to
the unchanged runtime integrity checks. This QA does not expand execution scope
or treat unresolved metadata writes as repaired.

#### Requirement coverage

- `MetadataReadbackMismatch` is raised only at the existing expected-tag
  comparisons. The runner catches it only around the unpublished candidate writer;
  ordinary exceptions, including an identical generic error string, still stop.
- Raw SHA/size/mtime, packaged-sidecar SHA and owned pre-publication intent are
  validated before retaining the file. Review state, original output metadata,
  bounded failure evidence, audit event and cleanup-only intent commit atomically.
- New failures preserve field/expected/observed values, with JSON null for a missing
  observed value. They receive `metadata_write_readback_failed` and the distinct
  `readback_failures_retained_for_review` report count. No success verification is
  attached, no unverified candidate is published and attempts are not reset.
- Resume cleans only registered transient work, preserves the deferred raw file
  and continues unfinished items. The described historical operator procedure
  binds exact plan/item/approval, recorded error and started intent under the run
  lock, recording `historical_error_only` without invented expected/observed values.

#### Tests performed

Independently ran `.venv-poc-313/bin/python -m unittest discover -s tests -q`:
**86 tests passed in 10.033 seconds**, including all 78 prior tests and eight new
deferral tests. `git diff --check` passed.

Independent additional probes verified:

- Three typed date/GPS/description failures followed by a successful item, exact
  evidence/report counts, unchanged raw/sidecar hashes and cleanup-only resume
  with source reads and metadata rewrites patched to fail.
- Generic same-text ValueError, preservation mismatch, timeout, tool error,
  ordinary I/O and ENOSPC all stop before the next item.
- Raw and sidecar tampering with unchanged file size and mtime still fails SHA
  verification and cannot commit a deferred-review outcome.
- Injected audit failure rolls back item/result/output, evidence/event and intent
  transition together; ordinary retry completes from retained raw files.
- Postcommit transient inspection failures of both OSError and ValueError preserve
  the committed review and pause safely; resume processes only remaining items.
- The explicit historical-error-only procedure works on a synthetic paused item,
  preserving original failure evidence and attempt counts without fabricated
  readback data.

The committed focused tests also exercise actual synthetic writer exception
typing, candidate nonpublication, raw mtime corruption and oversized evidence.

#### Problems found

One defect was reproduced and fixed: a transient allocation/inspection exception
after committing review could reach the generic handler and downgrade the item to
`metadata_error`. The guarded accounting path now raises `CapacityPause`, retains
committed review state and clears the transient watch list. Independent retests
and the new regression pass. No remaining blocking defect was found.

#### Data issues

The cause of each real date/GPS/description mismatch remains unresolved. Its raw
copy and original observations remain available for the later repair pass. This
QA validates handling and preservation, not the correctness of any private failed
file's metadata. Historical error-only evidence remains explicitly less detailed
than a new typed candidate comparison.

#### Edge cases

Deferral is terminal review for this processing pass; it is not an automatic retry
loop. Corruption, source changes, missing/changed sidecars, preservation errors,
malformed tool output, publication failures and space failures retain stop behavior.
Failure evidence is bounded to 1 MiB and cannot be partially committed. Cleanup
intents cannot adopt or replay an unverified candidate.

#### API/cost issues

No new API/model calls or source extraction are introduced. Existing capacity,
attempt, source-read, tool-output and timeout limits remain in force.

#### Regression concerns

All prior tests pass. The change is limited to two implementation files and one
new synthetic test file; this reviewer edited only this document's review/QA
sections. The earlier full-runner QA remains historical; the identities below
identify this reviewed delta. No original or live database was changed by QA.

#### Recommended fixes

None remaining for this scope. Retain the explicit deferred-file list and counts
for the user's requested repair pass after the batch finishes.

#### Retest required

**NO** for the frozen files below. Material code or scope changes require matching
validation. The real historical disposition must still execute its exact identity,
error and integrity assertions; it was reproduced only synthetically here.

#### Reviewed source identity

| Repository-relative file | SHA-256 |
|---|---|
| `sacc_takeout/full_recovery.py` | `3d8bdf6021f3ea8814925856dd8e9cd0586ff3ee9bdf0897918452ee9f80a22a` |
| `sacc_takeout/recovery_io.py` | `522e377293dd6ce686dfb8748f3c3d500507216898c74cc02fc7c22b248f3dcd` |
| `tests/test_takeout_readback_deferral.py` | `d939e9002af457bec367ea94fb166414c9a01a4511cb32c955fbc27a722a7694` |

Aggregate SHA-256:
`a0ecfe54f0e0b76459be22c6add06d9bf062691b2cb1ec79a6227b3b9a722703`.
Exact formula: map the three relative paths above to their lowercase SHA-256 hex
strings as `hashes`, then use
`hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()`.
No newline is appended. This document is excluded from that digest.

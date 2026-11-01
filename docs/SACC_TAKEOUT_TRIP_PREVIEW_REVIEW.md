# ANTI-GRAVITY DESIGN REVIEW — bounded trip preview

Date: 2026-10-30. Reviewer: independent Codex agent, using Nitty's authorized
Anti-Gravity substitution. No private media or Outlet Plug files were inspected
or changed for this review.

## Decision

**APPROVED WITH NOTES.** Record the reconciliation, then implement this bounded
proposal-only preview. No additional user decision is needed before coding.

## What looks correct

- The verified 200-item sample plus bounded cached neighbors can provide useful
  context without expanding extraction or claiming a complete trip reconstruction.
- Trips and store stops are separate concepts. Pauses are evidence, not automatic
  store changes; exact branch/context and observed movement remain stronger.
- Both-sided anchoring protects no-GPS files at branch transitions. Shoe brand,
  IMG numbers and nearest mall coordinates cannot establish a store by themselves.
- Proposals preserve observed GPS, screenshots and privacy rules, retain evidence
  IDs, and remain `needs_review`. The existing assignment/confirmation flow stays
  the only route to a confirmed store.

## Missing requirements

No architectural requirement is missing. Make these existing invariants explicit:

1. Use a read-only SQLite connection/adapter and reject a missing or incompatible
   manifest. Do not let normal manifest initialization create/migrate a database
   during a preview. Only separate report files and the output lock may change.
2. “Verified sample” means source-byte verification, not automatically trustworthy
   dates/GPS. Conflicting, invalid or uncertain capture/GPS evidence and disputed
   duplicate observations must not become trusted anchors. Cached-sidecar-only
   context remains lower-evidence context; no unobserved embedded checks are implied.
3. Proposal-derived membership or inferred labels must never become anchors for
   another inference. Evaluate a no-GPS run against original positive anchors so
   a chain of uncertain files cannot extend a five-/90-minute window indefinitely.

## Data concerns

- A confirmed store-version label must be active and undisputed, match the target
  account/context, and cover the target's historical capture date. Validity for an
  anchor's date alone does not establish validity for another item at a date boundary.
- Preserve overlapping occurrence provenance without treating album/export copies
  as independent votes. Known shared media IDs can identify repeated evidence;
  unknown hashes cannot be declared identical merely from names/timestamps.
- For timestamp ties or contradictory anchors in the same temporal neighborhood,
  return ambiguity rather than choosing by filename or occurrence-ID sort order.
- Device identity must be real. Two unknown device IDs or the same camera model
  do not establish a common capture stream. IMG sequences remain weak when stream
  identity is unknown; resets/wraps and time/name disagreement weaken them further.

## Edge cases and defaults

Five minutes for cached neighbors and 90 minutes for positive continuity are
reasonable configurable preview bounds, not calibrated accuracy thresholds.
Document the separate trip-gap, stop-pause and GPS-distance defaults and compare
against elapsed UTC time. A long-pause rule cannot override a hard branch/account/
date/GPS boundary. Missing dates stay unresolved rather than being filename-dated.

One-sided hints must be visibly weaker than compatible bracketing. They may point
to existing reviewed context for inspection, but cannot present a newly inferred
store as confirmed or disguise missing contradictory-side evidence.

## API/cost concerns

No network or model calls are needed. Keep detailed timestamps, names, coordinates
and candidate/evidence references local. Back up only sanitized aggregates/docs.
Do not modify Outlet Plug or reuse its canonical writer for this experiment.

## Architecture concerns

The 5000-entry cap must be deterministic and auditable. Report targets/windows
whose context was truncated; an incomplete window must not masquerade as genuinely
one-sided or unambiguous. Prefer marking affected inferences unresolved rather
than selecting a favorable anchor from a capped prefix. Bounds apply across the
whole preview, not once per target. Keep cached and verified counts separate.

Retain confidence/evidence categories and reasons as qualitative proposal labels;
do not manufacture statistical accuracy. Real branch accuracy remains unevaluated.

## Testing gaps

The proposed scenarios cover the major cases. Add explicit tests for exact-bound
and over-bound time windows, same-time contradictory anchors, unknown versus
different known devices, same-media repeated evidence, disputed/revoked parents,
target-date historical incompatibility, and truncation hiding a transition.
Assert that inferred rows cannot anchor later rows, no observed GPS changes, and
preview generation performs no source-member reads or database mutations.

## Suggested changes

Accept these notes, implement the pure engine and read-only adapter, and return
the focused tests/reports for QA. Label results as sparse, bounded opportunities
for local review, with sample/context/target denominators and unresolved reasons.

## Questions requiring resolution

None for this preview. Exact branch labels, historical directory completeness,
account confirmation and any full-recovery approval remain separate requirements.

## Blocking issues

**None within this bounded proposal-only scope.** This approval does not authorize
media processing, actual assignments or full-library recovery.

## Initial implementation QA — 2026-10-30

Reviewer: the same independent Codex reviewer authorized as the Anti-Gravity
substitute. This review used code, synthetic fixtures and the aggregate real
`trip_summary.json` only. No private media or detailed real GPS records were read.

**FAIL — targeted corrections pending.** The initial 41-test suite passed under
`.venv-poc-313/bin/python -m unittest discover -s tests -v`, but independent
synthetic probes found the following gaps. These do not require more real media.

1. **Confirmed no-GPS branch boundaries can be skipped.** Foot Locker GPS at
   12:00, confirmed JD without GPS at 12:01, unknown no-GPS media at 12:02, and
   Foot Locker GPS at 12:04 initially proposed Foot Locker for the unknown item.
   The new intervening-context guard addresses that bracketed case. Its interval
   must also include the target time: with only the 12:00 anchor, an interval made
   from anchors alone still misses the JD transition before the 12:02 target.
2. **Recorded source verification is not validated by the adapter.** A synthetic
   complete result with `source_verified: false` and a source hash inconsistent
   with its media row was still counted and labeled `verified_sample`, supplying
   usable GPS. Validate the recorded verification flag, source hash and
   media/account linkage before assigning that provenance. No ZIP reread is needed.
3. **Confirmed context without GPS cannot anchor a nearby unknown item.** Two
   active, historically compatible confirmed JD records without GPS bracketing
   an unknown no-GPS item currently produce `no_observed_gps_anchor_in_window`
   and three separate stops. The requested context inference should accept exact
   confirmed branch evidence as an original anchor, with the same conflict,
   history, account and review safeguards. It must not create measured coordinates.

The planned per-stop missing-GPS counts are also absent from JSON/CSV. Add these
for review or record an explicit reconciliation of that small output omission.

Read-only enforcement, snapshot/schema validation, global cap abstention,
observed-GPS preservation and explicit cache provenance otherwise look correct.
The synthetic adapter test confirms the database hash is unchanged and a write
through the read-only connection is rejected.

The inspected real aggregate contains 200 sample records plus 390 cached
neighbors, with no truncation. Of 50 sample items missing GPS, three receive weak
one-sided hints and 47 remain unresolved (37 without anchors, three with source
conflicts, seven with uncertain dates). It reports zero assignments, zero GPS
writes and zero extracted/rewritten media. Branch accuracy remains unevaluated;
these are review opportunities, not recovered locations.

Retest the targeted fixes and append the final QA decision below. Full-library
recovery and actual assignment remain outside this review's authorization.

## Final implementation QA — 2026-10-30

**PASS for the bounded, read-only trip preview.** This decision supersedes the
initial implementation failure above. Reviewer remains the independent Codex
agent authorized to substitute for Anti-Gravity; no actual Anti-Gravity review
is claimed. No private media or detailed real GPS records were inspected.

All reported defects are resolved:

- Original confirmed branch context can anchor a proposal without measured GPS.
  Intervening exact-branch evidence interrupts earlier anchors, and the boundary
  interval includes the target. Contradictory bracketing stays unresolved.
- Bracketing requires positive comparable evidence across both sides: compatible
  observed GPS or the same target-valid confirmed branch. A branch-only anchor
  plus an unrelated GPS-only anchor is explicitly incomparable, not agreement.
- The adapter rejects complete records with absent/false recorded verification,
  inconsistent source hashes or media/account linkage. Type, size and stable
  media identity are checked against persisted rows without source-member reads.
- Short unlocated bundles retain unresolved location status and cannot become
  inference anchors. Prior conflicts, uncertain dates, screenshots and different
  known devices cannot be absorbed by this weaker grouping rule.
- Stop JSON/CSV now includes missing-GPS and screenshot-exemption counts.

Independent validation:

- `.venv-poc-313/bin/python -m unittest discover -s tests -v`: **44 tests passed**.
- Ten additional synthetic scenario assertions passed, covering the original
  boundary failures, context-only anchors, incomparable evidence, prior-conflict
  separation, the unknown-device bridge and valid unlocated bundles. Input
  dictionaries stayed unchanged and no coordinates were synthesized.
- Adapter tests reject database writes, preserve the database byte hash, reject
  invalid provenance and unknown batches, and abstain when context is truncated.
  Existing screenshot, historical-date, transitive-revocation, cap and recovery
  regressions remain passing. `git diff --check` passed.

The final aggregate report was inspected directly: **590 inputs** (200 verified
sample records plus 390 explicitly unverified cached neighbors), **193 proposed
trips / 203 proposed stops**, and no context truncation. Of 50 sample items missing
GPS, three have one-sided hints and 47 remain unresolved: 37 without anchors,
three with conflicting source evidence and seven with uncertain dates. It reports
zero new assignments, zero observed-GPS writes and zero extracted/rewritten media.
Trip/stop counts include sparse and unlocated groups; they are not a validated
reconstruction of store visits. Real branch accuracy remains unevaluated.

Reviewed source snapshot:

| Repository-relative file | SHA-256 |
| --- | --- |
| `sacc_takeout/trip_preview.py` | `5ebaab36f42bce8e16d4ec75b7c2f89f551daa00dbd589f7feacb06523f53415` |
| `scripts/takeout_recovery.py` | `1b6c856ec001a96cb3b2b77338cde6b2e0803b2af7557f9cb2377f1369b84b40` |
| `tests/test_takeout_trip_preview.py` | `a93e3c1766a115510cf49b838a06944b6997c6fd8754a2b74a4595ad5b6c480e` |

For exactly those three path-to-hash entries, SHA-256 of UTF-8
`json.dumps(hashes, sort_keys=True, separators=(',', ':'))` is
`ccfada63d38ca69956c92a6e571ea5047d5d8009a59a61dfed9d6bf81e6c26f6`.

**Remaining blockers for this preview: none.** Cached context remains unverified,
thresholds remain preview defaults, and no real store labels or branch accuracy
are established by these results. Full-library recovery, actual assignment and
live SACC import remain separate reviewed operations; this PASS authorizes none
of them.

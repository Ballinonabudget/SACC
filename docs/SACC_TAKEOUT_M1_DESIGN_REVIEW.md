# ANTI-GRAVITY DESIGN REVIEW

Date: 2026-10-29. Reviewer: independent Codex review agent, explicitly authorized
by Nitty as the substitute for Anti-Gravity. This is not a review performed by
the Anti-Gravity application.

Reviewed proposal: `docs/SACC_TAKEOUT_M1_DESIGN.md`, SHA-256
`5cdcec309cc6a00af019ac0354f5426221ace447eeb625f0465699b01668a85c`.

## Decision

**APPROVED WITH NOTES.**

The first milestone can proceed after Codex records its reconciliation. The
architecture is appropriate for a bounded, local, reversible metadata experiment.
The notes below make existing design invariants concrete for implementation and
QA; they do not require another user decision before coding. This approval does
not authorize full-library recovery, live database import, final naming,
quarantine, or remote media analysis.

## What looks correct

- Source archives are read-only; only a persisted sample is staged under a
  separate private output tree. No archive member path becomes an extraction path.
- Batch-wide matching addresses the documented cross-ZIP sidecar distribution.
  Account, batch, source occurrence, original hash, and album provenance remain
  separate from working paths and mutable metadata decisions.
- Observed coordinate evidence is separate from inferred store assignment.
  Conflicts, unknown accuracy, uncertain dates, overlapping stores, and historical
  uncertainty remain explicit review states. A shoe brand is insufficient evidence.
- Stable store version and visit/member IDs allow mixed photos and videos to stay
  connected after folder separation. Mapping correction/revocation is part of
  the model rather than an undocumented manual overwrite.
- A separate recovery database avoids forcing unclassified media into the PoC's
  non-null shoe relationship or the legacy filename-stem identity.
- Batched local ExifTool reads and bounded copy writes fit the task without
  image recompression or any cloud dependency. Unsupported embedding formats
  retain the canonical manifest and explicit status.
- The proposed local lookup and versioned SACC export contract fit this milestone.
  Deferring the live application import follows the user's explicit approval gate.

## Missing requirements

No missing requirement requires an architectural redesign. Make these details
explicit in the reconciliation and user-facing run documentation:

1. A dry run stages read-only sample copies and writes reports/manifests; it does
   not embed metadata. The separately requested bounded copy-verification step
   may write at most 12 supported working copies. Report these counts separately.
2. Recovered-copy modification time should match a trustworthy selected UTC
   capture instant and be verified, as required by the build order. Preserve
   original timestamps. Do not apply the old helper's `-P` behavior blindly.
   Unknown-offset capture times must not acquire an invented UTC conversion.
3. Record proposed output paths separately from actual existing working paths.
   No report should imply that final folder organization or live search import
   already happened.

## Data concerns

- Archive size/mtime and central-directory checks validate inventory freshness,
  not cached JSON contents. For the selected sample, reread the matched sidecars
  from their actual ZIP members, verify CRC, compare to cached documents, and
  retain a sidecar content hash. Record cache/input/configuration identity so a
  changed cache cannot silently reuse prior recovery decisions.
- Resolve duplicate member paths by occurrence identity, not by a dictionary
  overwrite. An indistinguishable match must remain ambiguous; raw observations
  from separate exports or albums must not become an arbitrary last-writer-wins
  canonical date/GPS record.
- Confirmed source field provenance is not a guarantee of sensor measurement or
  geographic accuracy. Keep `geoData`, `geoDataExif`, and embedded evidence labels;
  preserve raw spans without treating them as horizontal accuracy.
- The fixed random sample does not cover every known anomaly. A 200/200 structural
  match result is not proof of historical correctness or full-library completeness.
  Keep fixture results, real-sample measurements, and unavailable ground truth distinct.
- A later export comparison must distinguish path inventory additions/missing
  entries from hash-proven content identity. Unhashed entries are not proven new,
  missing content, or exact duplicates. Keep provisional accounts separate.

## Edge cases

Read-only synthetic probes independently reproduced these existing-code issues:

- Competing `a.jpg(1).json` and `a(1).jpg.json` proposals for `a(1).jpg` are reduced
  to one by the existing exact-title fallback. Preserve the conflict before any
  fallback; do not reimport a selected match from the old CSV as unquestioned truth.
- `sacc_poc.takeout.capture_time({'photoTakenTime': False})` raises AttributeError,
  and a boolean timestamp becomes a valid epoch-second value.
- `sacc_poc.takeout.location()` accepts boolean latitude/longitude as numeric GPS.

Treat malformed mappings, booleans, non-finite values, partial GPS coordinate
pairs, and unreadable files as explicit per-item results. Reuse existing code only
where its contract is safe. Unknown/malformed metadata must not abort the whole
sample or produce credible-looking default coordinates/dates.

## API/cost concerns

- No paid API, geocoder, remote video analyzer, or model call is needed. Avoid
  importing `IngestionService`, which initializes the remote pipeline.
- Keep detailed JSONL, photos/videos, descriptions, precise GPS, local frame
  context, and source filenames out of Drive backups and committed docs. Only
  sanitized engineering documents and aggregate reports may be backed up.
- Default every new media record to unknown privacy and remote eligibility false.
  Later stage results must not cause dispatch as a side effect of persistence.

## Architecture concerns

- Persist a single selected occurrence list and run/configuration identity before
  staging. Rerunning with a different seed or increased limit must not extend the
  already-selected batch sample. Enforce the 200-member bound across retries,
  including after partial failures, rather than only per invocation.
- Mark an item complete only after staged/output hashes, expected tag readback,
  source reread hash, and manifest transaction succeed. Existence alone is not
  completion. Keep error attempts inspectable and safely retryable.
- Preserve observations and append review decisions. Current assignments can be
  derived from the latest active decision, but revocation must invalidate reused
  confirmations and dependent inherited assignments, including transitive reuse.
- A visit should represent a conservative store stop, not an entire mall outing.
  No-GPS inheritance needs an explicit confirmed membership/evidence link; time
  proximity alone is not enough. Mixed accounts and uncertain dates should not
  be merged into a confirmed stop automatically.
- Validate historical version intervals and exact branch IDs at assignment time.
  An unknown opening date is a review condition; a new confirmed mapping must
  carry evidence for the capture period rather than silently overriding history.
- Keep the existing live SACC schema untouched. Publish a validated envelope with
  `image`/`video`, path/size/MIME/review fields compatible with `media_assets`, plus
  recovery fields and nullable shoe identity. Document the future ID bridge;
  do not claim that the existing API accepts this entire envelope directly.

## Testing gaps

The proposed tests cover the broad cases. Add concrete negative assertions for:

1. Cache document modification with unchanged archive stat, duplicate ZIP member
   names, conflicting structural matches, malformed/boolean metadata.
2. Interrupted staging, interruption after copy creation but before DB commit,
   corrupted staged/output bytes on resume, and changed sample/configuration.
3. Sidecar/embedded GPS agreement and disagreement, positive/negative references,
   partial pairs, invalid accuracy, timezone-aware agreement, offset-free dates,
   and preservation of unrelated camera tags.
4. Every intended written date/GPS/description tag and recovered mtime read back;
   unsupported formats are explicitly manifest-only rather than reported restored.
5. Persisted photo/video visit timeline after path updates; a store/signage
   transition splits stops; revoking a confirmation invalidates all its dependents;
   no store pin is ever copied to observed GPS.
6. Real 200-file run followed by resume with no additional sample members or
   duplicate provenance rows, and documented source-byte comparison results.

Candidate coverage, reviewed accuracy, and cross-store errors must have explicit
denominators. Use null/not evaluated when no real directory or labeled decisions
exist; never use zero errors to imply verified perfect accuracy.

## Suggested changes

Accept the notes above in a short reconciliation, then implement the isolated
package, CLI, schema/contract validation, fixtures, and focused tests. Keep the
existing dirty discovery and live pipeline files untouched where possible.
Document privacy defaults, format support, CLI resume/error semantics, selected
sample identity, and exact next approval gate alongside the real dry-run report.
Return the implementation and evidence for independent post-implementation QA.

## Questions requiring resolution

None before this bounded milestone. Before a full pass, Nitty must review the
actual dry-run results and confirm the account mapping and scope. Export
completeness and historical directory gaps remain explicit limitations.

## Blocking issues

**None for the proposed first milestone.** The review gate is satisfied by this
user-authorized independent review, followed by Codex's required reconciliation.
No implementation or private media inspection was performed by this reviewer.

## Evidence inspected

Requested plan/start prompt/build order, discovery report, both operating manuals,
the proposal, `scripts/takeout_match_inventory.py`, `scripts/takeout_read_sidecars.py`,
`sacc_poc/takeout.py`, `sacc_poc/database.py`, `sacc_poc/ingestion.py`, and legacy
`db.py` schema. Synthetic probes used in-memory values only. The implementation
agent separately reported a current read-only check of all 38 ZIP central
directories against 179,786 recorded Google Photos entries; that result was not
independently rerun against private archives by this reviewer.

# ANTI-GRAVITY DESIGN REVIEW — Denivic full-recovery workflow

Date: 2026-10-30. Reviewer: independent Codex agent, using Nitty's authorized
Anti-Gravity substitution. This is a design review, not an actual Anti-Gravity
session. Only the proposal, current bounded APIs/tests and planning aggregates
were reviewed. No private media, detailed real records or Outlet Plug files were
read or changed. No full-recovery implementation or execution was performed.

## Decision

**APPROVED WITH NOTES.** Record the accepted clarifications below in the design
before implementation. Implementation QA, a concrete measured pilot and explicit
approval of the exact full-run plan remain required before full execution.
Denivic processing priority is already confirmed; do not ask it again.

The revised design was reread after the engineer incorporated the major review
clarifications: first stream, hash and collect all planned observations into one
managed tree of raw working copies; reconcile complete hash groups; then embed
eligible copies in a second logical pass. The revised capacity estimate, raw/final
state distinction, PNG test gate and final-path/unknown-format contracts are also
present. Remaining notes below belong in reconciliation and acceptance criteria.

## What looks correct

- Milestone caps remain intact. Separate plan/pilot/run commands and an isolated
  versioned ledger avoid turning the existing dry run into an implicit full run.
- Original occurrence/media IDs, account separation and occurrence-level evidence
  preserve album and photo/video relationships without depending on folder names.
- Unsupported/conflicting content is retained locally, with no fabricated GPS,
  shoe identity, store confirmation or remote eligibility.
- The source-stat wording correctly distinguishes archive size/mtime agreement
  from payload verification and whole-archive byte integrity.

## Missing requirements

Make approval scope mechanically explicit: immutable occurrence selection, maximum
files/bytes, input/output identities, policy/tool versions and plan digest. Pilot
approval cannot authorize full mode, and repeated pilot/resume invocations cannot
grow the approved selection. Plan/status must not extract media, initialize the
milestone manifest or create an approval record. A changed plan requires fresh
approval; ordinary retry of the same approved plan does not.

## Data concerns

The two-pass clarification resolves late duplicate discovery: a raw copy is only
`source_verified_only`, not metadata-safe. Compare all occurrence observations,
including existing evidence for shared hashes, before eligibility is finalized.
Do not select the first sidecar as a winner. Later-export conflicts must invalidate
effective derived projections/dependent confirmations while preserving historical
evidence and already reviewed outputs. No automatic rewriting is implied.

Snapshot existing screenshot decisions, media links and any reused confirmation/
revocation dependencies with their identities and provenance. Define how later
review projections refresh without mutating the milestone database or changing
the approved processing scope. A partial graph cannot establish active reusable
confirmation evidence.

Plan-only validation may bind indexed names, sizes, CRCs and cached-document
identity; raw sidecar SHA-256 becomes established only when its bytes are read.
State the source-integrity mode precisely in reports. A single streamed CRC/SHA
read is not the milestone's separate original-member reread.

## Edge cases and risks

Replace the fixed 1 GiB metadata allowance. The measured provisional allowance of
162,090 bytes per occurrence gives 14,261,002,380 bytes for 87,982 occurrences.
Payload + twice the largest member + that allowance + 50 GiB reserve equals
487,518,807,722 bytes, approximately **454.0 GiB**, against the reported 674.9 GiB
free snapshot. This arithmetic was independently checked; the estimate is not a
guaranteed bound or disk reservation.

Account for copied sidecars, metadata growth, filesystem allocation, SQLite
journal/WAL, report temporaries, orphan recovery candidates and ExifTool output.
Use one active item initially unless the capacity model explicitly covers more.
Track actual allocated bytes and remaining demand; never double-count already
verified raw copies as an additional extraction tree. Handle mid-write ENOSPC as
well as preflight shortages. Cleanup may remove only ledger-owned transients.
Rename the payload measurement to “planned uncompressed source bytes”; metadata
embedding means it is not a maximum recovered-output size.

## API/cost concerns

No network/provider dependency is introduced. Keep the worker independent of the
old ingestion/venue jobs. Bound sidecar parsing, ExifTool output/log buffers and
timeouts as well as media streaming. Oversized/malformed metadata must remain an
explicit retained/review outcome, not silent omission or unlimited memory use.

## Architecture concerns

Persist an owned publication intent containing source/final hashes, expected
size/tags/mtime, occurrence and plan identity before publication. Flush the
candidate, atomically rename on the same filesystem, durably commit the ledger,
and cover directory/SQLite durability. Atomic rename alone does not establish
power-loss durability. Adoption must verify the expected owned artifact; an
existing filename alone is insufficient.

Define raw-publication, metadata-publication and review states separately enough
to distinguish a retained unchanged copy from a failed copy. Only verified owned
raw candidates from this plan may be replaced during embedding. A failed retry
must retain the prior valid file. Media, original JSON and canonical record must
all be accounted for before completion is claimed. Incremental report retries
must not duplicate records or counts.

The v1 SACC envelope must reference the actual retained final path, final file size
and validated MIME/type, with original size/hash/path separate in recovery
provenance. The current validator accepts only image/video: keep the unknown-format
occurrence in canonical recovery records and an explicit unsupported report,
rather than failing the whole export or inventing a supported type. Do not reuse
the current sample exporter wholesale; it retains all records in memory and has
sample-specific paths/counts.

## Testing gaps

The proposed tests are appropriate. Add explicit coverage for:

- A duplicate discovered late preventing an earlier metadata-safe claim; changed
  evidence on a later export invalidating dependent projections.
- Crash points around publication intent, rename, directory durability, ledger
  commit and report export; orphan adoption, stale output and interrupted writes.
- Pilot cap persistence and approval-mode isolation; plan/status with payload reads
  patched to fail; unchanged original bounded APIs and privacy defaults.
- Large-member/ZIP64 streaming, tool/metadata buffer bounds, actual budget overruns
  and ENOSPC after processing starts.
- Final-path/final-size contracts, unknown-format retention and review-state counts.

Each enabled writer format needs a real synthetic roundtrip. The current repository
has JPEG copy roundtrip coverage, but no PNG roundtrip in the recovery tests; add
PNG date/GPS/description and preservation checks before calling that full-mode
writer proven. Existing sample copies test less than a new source/archive run.
Any additional real pilot must have its own explicit bounded scope and report
which formats and large-file behavior it actually exercised.

## Suggested changes

Reconcile the two logical passes, revised capacity estimate, publication protocol,
review-graph handling and envelope exceptions in the design. Implement/test the
plan and bounded pilot paths first. Present the exact reviewed plan and measured
pilot outcomes before requesting full-run approval; do not replace that with a
general “continue” interpretation.

## Questions requiring resolution

No user question blocks this design. Export completeness and real historical
branch labels remain unknown; neither prevents preserving observed metadata.
Resolve the implementation details above in reconciliation and acceptance tests.

## Blocking issues

**None for design approval after reconciliation.** Full execution remains blocked
by the deliberately outstanding implementation, QA, concrete pilot/plan review
and explicit run approval. This document grants no full-run authorization.

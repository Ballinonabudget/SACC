# SACC REVIEW REQUEST — trip and stop preview

2026-10-30. User has spot-checked the sample, says it looks good, and requests
Outlet Plug-style time/filename/context grouping to locate media without GPS.
That is qualitative acceptance, not per-item date/store labels or approval to
overwrite originals, import live data, or infer measured camera GPS.

## Current behavior and researched evidence

SACC `locations.propose_stops` groups only adjacent trustworthy dates with GPS
on both files, a 20-minute gap limit and 150m distance, leaving no-GPS items alone.
The 200 random sample points are sparse and cannot reconstruct whole trips alone.

Read-only reference: `/Users/daplug/Documents/Outletplug/AGENTS.md`, ownership,
master index, recent changelog, `scripts/shared-ingest/rules.mjs`,
`inc/ingest-sequence.php`, `inc/ingest-store-groups.php`,
`inc/trip-discover-stops.php` and the 2026-10-15 sequence audit/tests. WordPress
is that project's canonical writer; no Outlet Plug file or live service will change.
Its actual worker prioritizes capture timestamps, uses IMG sequence/ties with
uncertainty, groups complete shoe sequences before visit segmentation, preserves
pauses inside sequences, and checks robust GPS/history/signage before store reuse.
The audit documents overlapping mall stores where nearest-pin selection is wrong.
Its 90s/180s defaults and shoe-label logic are not copied as universal SACC rules.

## Proposed behavior and implementation

New isolated `trip_preview.py`: pure proposal engine plus manifest adapter;
`trip-preview` CLI; synthetic regression tests; report/runbook. No replacement
of approved stop construction, schema changes, API calls, media writes, or live
assignments. Reuse existing UTC/GPS validation, reviewed screenshot policy,
active assignment invalidation and private output/lock helpers.

The adapter reads verified sample results and, for missing-GPS sample targets,
nearby registered matched sidecar metadata within five minutes on either side.
Read only the existing recovery database, never ZIP payloads or remote APIs.
Keep occurrence IDs for unhashed context, with nullable media IDs and explicit
`registered_sidecar_cache` provenance. Do not imply those neighboring bytes or
embedded tags were reverified. Limit context to 5000 entries and flag truncation.
Keep overlapping album/export occurrences rather than deduplicating by filename.

Engine input preserves capture UTC, date certainty, account, device ID when
actually known, original filename, observed GPS, confirmed store-version/context
and supporting evidence IDs. No fabricated device identity from a camera model.
Photos/videos share one ordered timeline. Missing/uncertain dates produce review
hints, not an invented timestamp. IMG numbering is supporting evidence within a
compatible capture stream; it never proves a store/trip by itself. Screenshot
confirmations exclude screenshots from GPS anchoring/inheritance.

Produce separate trips and store-stop proposals. Hard boundaries: conflicting
confirmed branch/signage context, incompatible accounts/dates, or observed GPS
movement beyond a configurable tolerance. A two-to-five-minute pause can suggest
a boundary, but is not proof. Long pauses (up to a bounded 90-minute continuity
window) may stay in the same proposed stop when positive stable GPS or the same
confirmed exact branch/context supports continuity. Nike shoe brand alone is not
such evidence. Never merge two distant Nike branches because their brands match.
Use an overall trip-gap limit separately from store-stop boundaries.

For a no-GPS file, inspect BOTH neighboring anchors within the bounded window.
Compatible anchors can propose a shared stop; different branches or GPS movement
leave the middle file unresolved and prevent chaining it across a transition.
One-sided time/filename hints are weaker and cannot manufacture a store identity.
Every proposal stays `needs_review`, preserving anchor IDs and reasons. Inferred
store-version labels may only reference active compatible confirmed evidence;
no store pin is inserted into observed coordinates. Final assignment still uses
the existing reviewed membership/confirmation path, with revocation dependencies.

## Outputs, impacts and rollback

Private `trip_preview.json`, `trip_preview.csv` and aggregate `trip_summary.json/md`
alongside the batch reports. Friendly trip/stop numbers, start/end capture times,
first/last original names, photo/video/missing-GPS counts, proposed anchor/store
references and review reasons. Detailed GPS/filenames remain local. Sanitized
engineering docs/aggregate results only may be backed up. No database writes
other than opening the existing manifest; no stage/visit/assignment mutations.
Rollback is removing/regenerating these separate proposal outputs.

## Risks, test strategy and acceptance

Test Foot Locker→JD around a 5-minute gap, identical mall GPS with explicit store
transition, no-GPS bracketed by same/different stores, 30/60-minute same-branch pause,
Nike brand without branch evidence, distant Nike branches, GPS jumps across a
no-GPS run, clock/filename conflicts, missing dates, repeated/reset IMG numbers,
different devices/accounts, mixed photos/videos, confirmed screenshots, weak
cache-only context, truncation and no source/observation/assignment writes.
Run the full suite and independent QA. Real preview reports coverage/opportunities
without claiming branch accuracy or confirming any user decision. Full recovery
remains a separate reviewed operation; no new library extraction in this step.

## Open questions and review decision

No question blocks this local preview. Exact real store labels, historical directory
and account confirmation remain needed before full recovery/live import. Review
this bounded design before implementation using the authorized independent reviewer.

## Review Resolution — before implementation

Independent design review: APPROVED WITH NOTES. All notes accepted; none rejected.
Use SQLite mode=ro/query_only and validate the existing schema without initializing
a normal Manifest. Keep untrusted dates/GPS, duplicate disputes, timestamp ties,
unverified cached provenance and unknown devices explicit. Only original observed
evidence can anchor a proposal, never an inferred member. Check inherited branch
references against active confirmations, account and target historical date.
Repeated media IDs do not create additional votes. Apply one deterministic global
context cap; mark all affected target windows unresolved if truncated. Add exact-
boundary, repeated-evidence, uncertainty and read-only tests. No user decision is
needed for this bounded preview; existing full-recovery gates remain in place.

## Implementation reconciliation — 2026-10-30

Accepted every independent QA finding; none rejected. Original active confirmed
branch context can anchor no-GPS neighbors without creating measured coordinates.
Bracketing requires positive agreement: compatible observed GPS or the same exact
historically valid branch, rather than merely an absence of conflicting fields.
The intervening-context interval includes the target and anchors. Validate recorded
source-verification/hash/account/media linkage before calling a sample verified.
JSON and CSV include per-stop missing-GPS and screenshot-exempt counts.

Short consecutive clean unlocated records can form a temporal review bundle,
without identifying a store. Every member must have a usable date, no conflicting
source evidence, no original location anchor, and only the no-nearby-anchor reason.
The whole bundle may contain at most one known device identity; an unknown device
between two different known devices cannot bridge them. Disputed evidence and
screenshots cannot be absorbed by this weak bundling rule. No inferred member
becomes an anchor. Final independent QA is PASS, with 44 tests and ten targeted
scenario assertions; see the companion review for exact source fingerprints.

Nitty confirmed on 2026-10-30: process the Denivic export first. This records input
priority for the next stage, without changing the existing manifest/account IDs,
inferring an account email, asserting export completeness or approving a full run.

# SACC REVIEW REQUEST — Denivic full-recovery workflow

2026-10-30. **APPROVED WITH NOTES; reconciled. Design only, not implemented or
authorized to run.** This is the next
increment after the completed 200-file milestone and bounded trip preview. Follow
the required independent design review and reconciliation before implementation,
then independent QA before presenting a concrete full-run approval request.

## Problem, current behavior and desired behavior

Nitty reviewed several sample photos and found their GPS correct, accepted the
sample qualitatively, and explicitly confirmed that the Denivic export goes first.
The automated local importer works, but its 200-member and 2 GiB/member limits
are deliberate milestone bounds. Removing those limits alone would create an
unreviewed full recovery tool and demand excessive temporary storage. A usable
full workflow needs bounded streaming, format-specific status, restart verification
and review of exactly which input/output paths and policies it will use.

The desired next increment recovers working copies and canonical local metadata
for the first export. It does not require AI to inspect every ZIP, file dragging,
manual renaming or paid model calls. Preserve GPS already present, add only safe
supported metadata, and keep conflicts explicit. Photos and videos retain the same
stable media/occurrence/visit relationships independently of future folder paths.

## Confirmed input and measured planning evidence

Source: the 38-part export `takeout-20230401T201259Z` in
`/Volumes/The Final Cut X/Google Photo (Denivic)`. Existing internal account ID
`provisional-denivic` remains stable; this historical ID does not require a new
account or imply a guessed email. User confirmation establishes processing order.
Export completeness remains unknown; do not merge a future second account into it.

Read-only manifest/stat/capacity snapshot on 2026-10-30, with zero media reads:

| Measurement | Snapshot |
|---|---:|
| Source archive size/mtime fingerprints still matching | 38 / 38 |
| Photo occurrences | 73,349 |
| Video occurrences | 14,632 |
| Unknown-format occurrences | 1 |
| Total media/unknown occurrences | 87,982 |
| Uniquely matched sidecars | 86,523 |
| Ambiguous matches / no unique match | 5 / 1,454 |
| Planned uncompressed source bytes before deduplication | 407,786,951,500 (about 379.8 GiB) |
| Largest media member | 5,891,881,321 (about 5.5 GiB) |
| Members exceeding current 2 GiB limit | 11 |
| Current free space on proposed destination volume | about 674.9 GiB |
| Proposed free-space budget estimate | about 454.0 GiB |

The no-unique-match total includes the unknown-format occurrence; it is not
directly comparable to the discovery count limited to recognized media. Counts
include album/export copies, with no assumed deduplication savings. ZIP size/mtime
agreement is not a full byte-integrity check. Cached sidecar matches do not prove
historical dates, camera GPS or the integrity of unprocessed media payloads.

Proposed output: `/Users/daplug/Documents/SACC_Data/recovery/denivic`, outside
the repository, source export, watched folders and cloud-sync folders. Keep the
existing milestone output unchanged. Planning proof is local at
`/Users/daplug/Documents/SACC_Data/recovery/milestone1/next-stage-preflight.json`.
Recheck input fingerprints, mounts and free space immediately before any run.

## Proposed architecture and affected files

Keep milestone `dry-run`, `verify-copies` and trip preview caps unchanged. Add a
separate full-recovery module and CLI entry points for plan, bounded pilot, run,
status and resume. Proposed files: `sacc_takeout/full_recovery.py`, a dedicated
progress-store module, `scripts/takeout_recovery.py`, focused tests/fixtures and
this runbook/design family. Reuse canonical IDs, metadata proposals, matching,
safe-path/atomic helpers, ExifTool reads/writes and stage-extension contracts.
Refactor common helpers only when required; preserve the original capped APIs.

Plan creation must be read-only with respect to the current manifest and sources.
It snapshots the existing account, batch, inventory hash, archive fingerprints,
occurrence/sidecar references, output root, policy versions, cutoff date, format
allowlist, limits and capacity calculation into an immutable plan plus digest.
No plan command extracts media or silently sets full-run approval. Store human
approval separately against that exact plan digest; changed inputs or policy
require a new plan. Do not add a default mode that processes the whole library.

Bind exact occurrence selection, maximum distinct files/source bytes, retry/read
budgets, input/output identities and tool/policy versions to that digest. A pilot
has its own immutable approved selection and cumulative counters across invocations;
repeating/resuming it cannot grow the selection or grant full mode. Retrying the
same approved plan does not require repeated approval, but exceeding its attempt/
byte budget pauses. Plan/status cannot create an approval record, extract payloads
or initialize the milestone manifest. Human approval must come from the actual
user decision, never from a default CLI flag or the worker's own action.

Use an isolated versioned progress SQLite database in the new root. Import source
references without modifying the milestone manifest. Reuse original occurrence IDs
and media-ID hash formula so later reconciliation does not break photo/video links.
The new progress store is a recovery ledger, not another live SACC database.
Its schema/creation/transactions require the same fail-closed handling and foreign
keys as the milestone. Explicit migration/version handling is required before
supporting any future schema. No migration of the existing milestone/live DB.

Snapshot screenshot decisions, media links and any reused confirmation, dependency,
revocation and dispute records with stable IDs, provenance and a review cutoff.
Preserve the full validation graph before considering any confirmation active;
partial graphs are unusable as positive evidence. Later review refreshes produce
a new projection version and audit event without changing processing scope,
source observations, the milestone database or already reviewed output bytes.
Invalidate reused derived evidence when an ancestor becomes disputed/revoked.

## Data flow, restart and storage

Process a bounded queue, grouped by archive and member index. Reuse a small bounded
set of read-only ZIP handles instead of reparsing each central directory for every
file. Validate indexed names/sizes/CRC and live sidecar documents against the plan;
cross-part sidecars remain part of one export. Reject unsafe entry paths, archive
changes, size overruns, corrupt CRC, unsafe destinations or unexpected output files.
Resolve output names from stable occurrence IDs, never archive traversal paths.

Use two logical passes over the same managed working tree. First stream/hash all
planned source occurrences and collect source, sidecar and embedded observations.
Publish these owned raw copies only as `source_verified_only`, never as metadata
restored or safe for downstream promotion. Reconcile complete original-hash groups
and conflicting occurrence observations before the second, metadata-writing pass.
An incomplete source pass cannot silently establish that no later duplicate conflict
exists; leave affected work raw/review-held until it completes or a revised plan
explicitly defines the excluded scope and remaining uncertainty.

Stream each payload through a fixed-size buffer into an owned temporary file,
computing original SHA-256 and checking declared size/CRC. Validate the staged hash
before metadata writing. Batches of ExifTool reads remain bounded. Source streams
are read-only. Record original and final hashes separately; final metadata bytes
are not the pre-restoration deduplication key. Clearly report that full-member CRC/
SHA is measured during recovery while whole-archive byte hashes are not implied.
Reports must explicitly distinguish this streamed CRC/SHA mode from the milestone's
separate original-member reread. Plan-only cached-document identity is not a raw
sidecar SHA; establish that SHA only from bytes actually read during recovery.

At most one source temporary and its candidate output, plus bounded metadata
buffers, are needed per active item. Do not retain a second complete extraction
tree. The capacity estimate is all occurrence bytes plus twice the largest member,
a measured metadata/report allowance and reserve=max(50 GiB, 10% of payload bytes).
Current measurements: largest sample result 7853 bytes; largest registered matched
sidecar 2121 bytes; sample exports 12512.035 bytes per record. Provisional allowance
per occurrence is
`ceil(max(128KiB,2*max(64KiB,2*largest_sample_result)+sample_exports_per_record+largest_registered_sidecar+16KiB))`:
162090 bytes, or 14,261,002,380 bytes for this inventory (about 13.3 GiB).
This is an estimate, not a guaranteed upper bound. Include actual ExifTool candidate
growth, raw sidecar copies, SQLite journal/WAL, report temporaries and filesystem
allocation overhead in runtime accounting; measure allocated as well as logical
bytes. Pause safely when the budget or free-space margin is exceeded, including
handling ENOSPC between checks. Recompute estimates in the concrete plan.
Start with one active item. Recheck remaining-byte demand and
free space before every item; insufficient space pauses without publishing a
partial file. Destination free space is a snapshot, not a reservation.

Plan member bounds must include the measured largest item; do not silently skip
the 11 large videos or bypass size checks globally. Treat a member larger than its
planned bound as a failure. Never read an entire video into memory. CRC failures,
NAS disconnects and metadata tool failures leave retryable explicit errors.

Publish a final recovery outcome only after hash/tag/mtime readback succeeds (or an
explicit unchanged-copy review outcome is verified), using atomic same-filesystem rename and a committed
ledger entry. Persist states that distinguish pending, source-verified, proposed,
published, review-held and failed, with attempts and policy/plan identity. Raw
publication and final recovery publication must be distinct durable states. Crash
between publication and commit must be handled by validation/adoption of the
owned output, not blind overwrite or duplicate creation. Resume validates output
hash, size and metadata/mtime evidence. Changed completed outputs stay blocked
for inspection. Atomically replacing an owned raw working file is allowed only
during its first metadata conversion, after revalidating its recorded original
hash and unpublished/retry state under the worker lock. Retain that raw copy until
the candidate passes readback. Completed, externally changed or reviewed outputs
are never silently overwritten. Fsync published files and their parent directories;
the ledger must support crash recovery between filesystem publication and commit.
Before rename, commit a durable owned publication intent with plan/occurrence ID,
source/final hashes, expected size/tags/mtime, candidate and destination identities.
Flush the candidate, rename on the same filesystem, fsync affected directories,
then durably commit the published outcome. Configure/test SQLite durability and
its parent-directory handling explicitly. Adoption verifies this intent and all
expected artifacts rather than trusting a filename. Distinguish raw publication,
unchanged retained review outcomes, successful metadata writes and failures.
Retain any prior valid output when a retry fails. Remove only
owned transient files after validated publication; keep all source ZIPs and
retained working outputs. No deletion/quarantine of duplicate or edited assets.

Later exports or corrections can introduce new duplicate metadata conflicts.
Invalidate effective derived projections and dependent location reuse, marking
affected historical outcomes stale/needs-review with their original evidence and
policy retained. Preserve already published/reviewed bytes; do not silently rewrite
them to whichever sidecar arrived last. Reconciliation is a separate reviewed action.

## Metadata, format and privacy policy

Canonical per-file metadata always includes raw observations, source/sidecar
hashes, selected capture instant/source, timezone uncertainty, observed GPS and
accuracy, review reasons, proposed/final working paths and embed/readback status.
Copy the matched original JSON into the local recovery package with provenance;
retain unmatched/ambiguous references without fabricating a match. Do not label
cached-only observations source-verified until their bytes have actually been read.
Media, original matched JSON and canonical record must all reconcile before an
occurrence is complete. Bound sidecar sizes/parsing, ExifTool stdout/stderr/logs,
metadata buffers and timeouts as well as the media buffer. Oversized/malformed
metadata is retained with an explicit review/error outcome; no silent truncation
or unbounded buffering is allowed.

Start with the JPEG writer and enable PNG only after explicit PNG roundtrip tests
cover date, GPS, description and preservation of existing metadata; existing JPEG
coverage does not establish PNG behavior. Add safe XMP capture date and missing
GPS/description only under the existing conservative eligibility rules; retain
camera metadata and do not overwrite conflicting values. Date/GPS/match/type
conflicts produce unchanged working copies plus review records. Unknown timezone
does not justify inventing a camera offset. Unsupported image/video formats keep
their bytes, canonical sidecars and explicit manifest-only status. Any capture
mtime update requires a safe selected date and must be read back separately.
Video/HEIC/RAW embedding needs separate format-specific tests before enablement;
do not claim every file is embedded merely because it has a canonical record.

Confirmed screenshots do not require GPS, but retain capture/privacy/conflict
checks and existing observations. Do not classify all PNGs or all no-GPS items as
screenshots. Read existing local screenshot decisions by stable media ID; later
review can update the projection without changing original observations.

All media default to privacy unknown and remote eligibility false. No AI, geocoder,
cloud upload, old venue-anchor job or external API is needed. Only sanitized docs
and aggregate reports are backed up. File names, coordinates, descriptions,
thumbnails, detailed manifests and the media stay local.

## Store/visit model and SACC compatibility

Recovery does not invent store confirmations. Preserve separate observed GPS and
inferred exact branch labels, historical version IDs, visit IDs and evidence.
Retain related photo/video IDs through later type/date folder separation. The
bounded trip engine can operate on recovered context later; a full timeline needs
a bounded/indexed extension rather than an unbounded pairwise scan.

Export the versioned `sacc.takeout.media.v1` JSONL contract and local SQL lookup
fields, without fake shoe/SKU values. Photo/video filtering, local context and
two-axis sneaker/privacy classification attach stage records by stable media ID.
Actual SACC search integration needs a later reviewed additive media-ID bridge;
the shoe-required PoC table and legacy stem keys are not suitable generic targets.
Every envelope must point at the existing published recovery file and its final
size/MIME, with original archive/member provenance and original SHA kept separately.
Do not export a staged path that was removed during conversion. The unknown-format
occurrence is retained as raw bytes plus a canonical review record and separate
unsupported-format report; it cannot pass through the image/video-only v1 validator
unchanged. Every planned occurrence must reconcile to an explicit outcome, including
unknown/unsupported and failed entries; export counts must explain exclusions.
No REST endpoint, live schema, API key or environment variable changes here.

## Tests, acceptance and rollout

Before implementation: independent explicit APPROVED or APPROVED WITH NOTES and
written reconciliation. Before full execution: independent implementation QA and
Nitty's approval of the concrete plan, output location, scope and measured pilot.
Account priority is already confirmed; do not ask that question again.

Meaningful tests must cover cross-part matching, 5+ GiB streaming without whole-file
buffering (bounded synthetic streams), CRC/size/fingerprint mismatches, symlinks
and traversal, low space before/mid-run, resume and every crash/publication boundary,
corrupt/changed completed outputs, changed plans/policies, identical content with
conflicting metadata discovered late in the source pass, later-conflict invalidation,
JPEG and PNG roundtrips, unsupported formats, date/GPS conflicts, screenshots, exact
SACC contract compatibility with existing final paths/sizes, unknown-format report
coverage, separate accounts and zero source/live-DB writes.
Plan mode must be proven not to extract. A bounded local pilot uses synthetic
files and existing sample copies first; reading additional real media requires
an explicitly approved bounded pilot scope. Do not turn a pilot into a full run.

Report discovered/planned/completed/review-held/error/remaining counts, processed
bytes, retries and per-format embedded/manifest-only outcomes. Export reports
incrementally from committed ledger state rather than retaining every result in
memory or reusing the sample exporter wholesale. Counters count distinct states/
occurrences separately from attempts and bytes read. Publish deterministic report
snapshots atomically with a ledger watermark; retries/crashes cannot append duplicate
rows or imply more completed files. No invented recovery
accuracy percentage. Only a reviewed real pilot can establish format outcomes.

## Risks, rollback and remaining decisions

Main risks: NAS interruption, source archive changes, unexpectedly large members,
disk consumption, partial publication, ambiguous historical dates and formats
ExifTool cannot safely write. The ledger, streaming limits, atomic publication,
explicit review outcomes and repeatable readback address these; they do not prove
full export completeness or identify missing source files.

Rollback is stopping the worker and retaining its separate ledger/outputs for
inspection. The originals, milestone artifacts and live SACC/Outlet Plug remain
unchanged. No destructive rollback command is needed.

No decision blocks design review. An approved historical store directory is still
needed for real branch naming, but does not block copying/retaining observed GPS.
Final organization, naming, duplicate/edited quarantine, privacy classification,
cloud analysis and live search synchronization remain later reviewed stages.

## Review resolution — 2026-10-30

Independent decision: **APPROVED WITH NOTES**, recorded in
`SACC_TAKEOUT_FULL_RECOVERY_DESIGN_REVIEW.md`. All notes accepted; none rejected.

- Use two logical passes over one tree and reconcile complete hash groups before
  metadata eligibility. Later conflicts invalidate effective derived evidence
  while preserving historical observations and completed/reviewed outputs.
- Replace the fixed 1 GiB allowance with the measured estimate and actual runtime
  accounting. The revised 487,518,807,722-byte budget is about 454.0 GiB, including
  reserve; it is neither an output-size ceiling nor a disk reservation. Start at
  concurrency one and handle ENOSPC and transient growth explicitly.
- Persist immutable pilot/full approval scopes and cumulative caps. Preserve
  complete review/dependency snapshots and versioned refresh semantics. Keep
  cached identity, streamed payload verification and separate reread claims distinct.
- Persist durable publication intent before rename; verify adoption and filesystem/
  SQLite durability at every crash boundary. Bound metadata/tool buffers too.
- Test PNG explicitly before enablement. Export actual final paths/sizes, keep
  unknown formats in canonical/unsupported reports, and reconcile all outcomes.
  Derive idempotent counters/report snapshots from committed ledger states.

Final implementation order: plan and scoped-pilot paths first, crash/large-file/
format/approval tests, independent implementation QA, measured approved pilot,
then present the concrete full-run plan to Nitty. No new user question blocks
coding. Implementation, pilot and full execution are not performed by this design.
Outstanding risks remain incomplete exports, untested full-mode runtime behavior,
unsupported embedding formats, historical uncertainty and real branch data gaps.

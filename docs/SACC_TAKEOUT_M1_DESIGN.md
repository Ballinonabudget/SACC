# SACC REVIEW REQUEST

Date: 2026-10-29. Status: **APPROVED WITH NOTES by the user-authorized independent Codex reviewer; reconciled before implementation.**

## Task

First milestone only: resumable ZIP importer, local recovery manifest, deterministic
200-file metadata/GPS dry run, and tested store/visit interfaces. Originals remain
unchanged. Full recovery, live database import, classification, final naming,
quarantine, and remote media analysis are outside this milestone.

## Current behavior

`scripts/takeout_read_sidecars.py` caches JSON by archive fingerprint.
`scripts/takeout_match_inventory.py` matches across all ZIP parts without fuzzy
or cross-album guesses. The existing sample (seed 20261029) has 200 files, including
35 videos, totaling 854,916,277 source bytes. Matching alone has not validated
embedded metadata, GPS, dates, or media integrity.

`sacc_poc/takeout.py` has useful capture parsing and ExifTool patterns, but its
restoration resume check trusts existence and its GPS selector omits conflicts.
The live PoC requires a shoe/SKU record before adding media. The legacy `clips`
table assumes video filenames are relational keys. Neither fits unclassified
personal Takeout media. Existing dirty files will remain unchanged.

## Proposed behavior

Read all ZIP central directories and cached sidecars together, verifying archive
size/mtime and entry CRC/size/path against discovery. Register a provisional
account identifier (identity unconfirmed), immutable export batch, and all source
occurrences. Stage only the selected 200 media members, with SHA-256 of original
uncompressed bytes and CRC validation. Never extract using archive member paths.
Read embedded tags locally with batched ExifTool. Produce SQLite plus versioned
JSONL records and an aggregate Markdown/JSON report. Detailed paths, coordinates,
and descriptions stay in the private local output tree.

Every selected file receives an explicit result: complete proposal, review needed,
or error. Sample selection, configuration, source inventory identity, progress,
errors, and output hashes are persisted. Resume reuses only validated completed
records and verified staged/output hashes. Failures remain retryable; partial
files cannot count as complete. A later export adds provenance, never replaces
the current batch. Same-name files do not imply equal content.

## Proposed implementation

New isolated `sacc_takeout` package and `scripts/takeout_recovery.py` CLI; reuse
the existing cross-part matcher after checking ambiguity behavior. The CLI has
inventory/dry-run/report functions and a hard maximum of 200 sampled members per
batch. It offers no full-library apply command. Optional bounded copy verification
is capped at 12 supported sample images, separate from dry-run proposals.

Storage defaults outside the repository and watched inboxes, under local
`SACC_Data/recovery`. Reject output inside any source parent, repo ingestion areas,
configured watched inboxes, unsafe archive paths, and symlink escapes. Use a
single-run file lock, transactions, temporary files, atomic rename, restrictive
permissions, bounded reads, and a free-space check immediately before staging.
No imports of cloud dispatchers, no .env loading, no external geocoder or tiles.

### Metadata policy

- Preserve every source observation, including raw sidecar values and grouped
  ExifTool tags. Store selected values, source fields, reasons, and review flags.
- Prefer valid `photoTakenTime` (UTC instant); never substitute upload
  `creationTime`. Compare offset-aware embedded times as instants. Preserve
  offset-free wall-clock times and explicitly mark timezone uncertainty; do not
  invent a timezone. ZIP member time is an untrusted final fallback, not camera
  capture evidence. Pre-2005, future, invalid, and conflicting dates need review.
- Validate finite coordinate ranges. Preserve `geoDataExif`, `geoData`, embedded
  GPS, altitude and accuracy if supplied. Zero/zero Takeout placeholders are
  recorded as missing/suspicious, not a measured location. Configurable distance
  tolerance compares observations; missing accuracy remains unknown. Conflicting
  GPS is not silently resolved. Observed GPS and inferred store pins are separate.
  Takeout latitudeSpan/longitudeSpan are retained raw; they do not establish
  measured horizontal accuracy without documented evidence.
- JPEG/PNG copy verification uses ExifTool, keeps original camera/time fields,
  writes supported XMP date/description and missing GPS only when unambiguous,
  then reads every requested tag back. UTC XMP does not assert a camera timezone.
  No correction of conflicting metadata. Unsupported formats retain complete
  manifest metadata and an explicit embedding status. Video/RAW writes deferred.
- Hash selected ZIP media before and after inspection/copy verification by
  rereading those members; compare archive size/mtime before/after. This verifies
  selected source bytes, not byte integrity of all 380 GiB of ZIPs.

### Database impact and SACC integration contract

Create only a separate versioned recovery SQLite database. Tables:

| Entity | Identity and purpose |
|---|---|
| accounts | Provisional stable ID, display label, identity confirmation state |
| batches / archives | Account, export ID, archive fingerprints and provenance |
| occurrences | Stable account/batch/archive/member ID, original path, album path, matching evidence; unprocessed entries have no invented media hash |
| media | Stable account + original SHA-256 ID, media type; identical bytes link occurrences without discarding album/export evidence |
| recovery_results | Per occurrence observations, selected metadata, review reasons, paths, hashes, stage/error state |
| store snapshots / versions | Immutable read-only directory payload, source IDs, retailer, branch, venue, aliases, type, address, coordinates, active intervals, provenance |
| visits / visit_members | Stable stop ID, mixed photo/video members, timeline, evidence, confidence; independent of paths |
| confirmations / assignments | Append-only reviewer decisions, historical store version, explicit supporting media/context and dependencies, revocations/corrections |
| media_links / stage_results | Live/motion relationship evidence; extension point for video filtering and two-axis sneaker/privacy classification |

Versioned JSONL exports map `media_type` to existing SACC `image`/`video`, original
source path to `source_path`, selected working path to proposed `file_path`, size,
MIME type, and review fields to PoC equivalents. Preserve account/batch/hash/date/
observed-GPS/store/visit fields in the recovery envelope. Unknown SKU stays null;
do not create fake shoe identities or auto-call `IngestionService`. Later approved
integration can add a media-ID bridge to `media_assets.id` / `clips.id` and join
the recovery entities, without changing current filename-based relations.

No live schema migration or API endpoint changes now. No claim that current SACC
search already queries this manifest. Local manifest lookup/reporting is provided.
Phase 2 video decisions and Phase 3 classification attach versioned stage results
to stable media IDs without changing recovery. Default privacy is unknown and
remote eligibility false; missing/uncertain/mixed/personal always remains local.

### Store directory and shared visit contract

Explicit JSON import from an approved read-only export; no Outlet Plug code edits
or live integration. Validate schema version, snapshot/source IDs and provenance,
unique version IDs, coordinate ranges, ISO dates and non-overlapping intervals
per branch. Unknown dates/coordinates are allowed with review flags. Retain closed
and historical branches; store and venue IDs are distinct. Synthetic fixtures are
clearly marked and must not be represented as real Florida branch coordinates.

GPS proposes all nearby candidates within configurable distance plus supplied
accuracy. No unconditional nearest-store assignment. Filter against capture dates;
unknown opening dates stay historically uncertain. A confirmation identifies an
exact store version and capture interval, area, reviewer and local signage/video
evidence. Shoe brand alone cannot confirm a store. Reuse only compatible reviewed
context and dates; a changed mapping invalidates dependent assignments.

Visit construction is conservative: split on substantial gaps, movement, explicit
store/signage transitions and uncertain dates. A mall can contain multiple stops.
No automatic four-hour/export-folder grouping. Missing-GPS media may inherit a
store only through an evidenced confirmed stop; never gain invented observed GPS.
An explicit component identifier may link motion/live pairs; basename alone is
only a proposal requiring review. Visit timeline queries order both media types
by capture time and retain IDs when output paths change.

## Files/systems affected

New `sacc_takeout/{__init__,manifest,metadata,locations,importer}.py`,
`scripts/takeout_recovery.py`, focused tests, synthetic fixtures and docs.
Existing discovery matcher may receive a narrowly isolated fix only if needed;
prefer a conservative wrapper to preserve pre-existing uncommitted work.
No changes to live database/API/UI, watcher, cloud pipeline, or Outlet Plug.

Read-only inspection reproduced an ambiguity defect in the existing matcher:
`a.jpg(1).json` and `a(1).jpg.json` both propose `a(1).jpg`, but an exact-title
fallback then selects one. The importer must retain this as ambiguous and suppress
fallback for a media path with competing structural proposals. Add a regression
case without modifying the existing uncommitted discovery file.

## Risks and edge cases already identified

Cross-part sidecars; duplicate member paths and ambiguous titles; missing/truncated
names; edited originals; identical bytes across albums/accounts/batches; malformed
JSON; stale/tampered cache; partial/corrupt ZIPs; interruption/disk exhaustion;
source mutation; output corruption; missing tools; GIF/RAW/video formats; device
clock skew and DST; personal coordinates; two nearby retailers, two distant same-
retailer branches and multiple mall stores; unknown/historical/missing branches.

Account identity, current export completeness and real historical store directory
remain unconfirmed. Do not claim coverage or accuracy from absent ground truth.

## Test plan and acceptance checks

Synthetic split ZIP integration tests: suffix/title matching, ambiguity and folder
isolation, restart/error recovery, changed source rejection, original hashes,
later batch and album provenance, traversal/symlink/path protections and hard caps.
Metadata tests: invalid/non-finite/zero/conflicting GPS, accuracy, offset-aware and
naive dates, suspicious dates, no upload-time substitution, missing fields and
unsupported formats. Local ExifTool fixture round-trip verifies requested values
and unchanged originals. Real 200-file run verifies source hashes and resume.
Location tests distinguish nearby Nike/adidas, distant same-chain branches,
multi-retailer mall stops, historical/unknown dates, no-GPS inheritance, mixed
photo/video visits after path changes, transitions, revocation and dependencies.

Report separately: GPS coverage, candidate coverage, reviewed accuracy (null until
labeled), unresolved items, cross-store errors (null until labeled), source integrity,
copy readback and resumability. Run existing local tests for regressions.

## Migration and rollback

Recovery schema version 1 is additive and isolated. Refuse incompatible versions.
Rollback means stop the importer and retain/archive its private output directory;
source ZIPs and live DB are unchanged. Rebuild proposals from immutable observations.
Never delete original or previously reviewed evidence. Preserve existing working
tree changes using a baseline fingerprint audit; no automatic commit or reset.

## Questions for Anti-Gravity

Does the design safely distinguish dry-run proposals from bounded copy verification?
Are the provenance, date/GPS conflict policies, SACC mapping and conservative visit
boundaries sufficient for this milestone? Identify blocking gaps before coding.

**Do not implement until this review returns APPROVED or APPROVED WITH NOTES.**

## Review dispatch status

Anti-Gravity opens to a first-run consent screen; no terms or data collection
settings were accepted or changed. Nitty explicitly authorized: “Use an
independent Codex review agent instead.” The independent reviewer has been
assigned the repo's required review process and is inspecting this proposal.
Review returned APPROVED WITH NOTES; all notes are accepted in
`SACC_TAKEOUT_M1_RECONCILIATION.md`. Implementation may now proceed within the
first milestone. This is an authorized reviewer substitution, not a review by
the Anti-Gravity application.

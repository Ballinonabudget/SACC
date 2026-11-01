# Takeout recovery milestone 1

Update2026-10-31: the separate full-plan runner is documented in
`SACC_TAKEOUT_FULL_RECOVERY_RUNBOOK.md`. The milestone commands below retain their
200-file/12-copy caps. New full commands require their own immutable plan and
scope approval; no full-library run is authorized by this milestone runbook.

The importer produces an inspectable, local metadata proposal before any full
recovery or live SACC import. Python's standard library handles ZIP streaming,
SHA-256, resumable SQLite transactions and JSON/CSV output. ExifTool performs
batched reads (40 paths per process) and bounded writes without recompressing
images. Tests use Pillow to create synthetic media; runtime does not require it.

## Commands

From `/Users/daplug/Documents/SACC`:

```sh
.venv-poc-313/bin/python scripts/takeout_recovery.py dry-run \
  --discovery /Users/daplug/Documents/SACC_Data/discovery/2026-10-29 \
  --output /Users/daplug/Documents/SACC_Data/recovery/milestone1 \
  --account provisional-denivic --batch takeout-20230401T201259Z
```

`dry-run` stages the persisted selection of at most 200 media members and writes
metadata proposals. It does not embed metadata into those staged files. The
initial selection is seed 20261029, matching discovery's original sample. The
selection, size limit, seed, date-policy cutoff, policy version and input/cache
identity persist before media staging. Retry the same command; the date cutoff
automatically remains the initial date. Different sample settings or changed
inputs for the same batch are rejected. Every attempt is logged.

The report's `batch_id` is the manifest ID. The input `--batch` above is an export
label. The following commands use the manifest ID:

```sh
.venv-poc-313/bin/python scripts/takeout_recovery.py verify-copies \
  --output /Users/daplug/Documents/SACC_Data/recovery/milestone1 \
  --batch 2ec7131b299ec7b0667019c7c1307e3c8a96df7d4b91bdeae652c37dc74506a0

.venv-poc-313/bin/python scripts/takeout_recovery.py lookup \
  --output /Users/daplug/Documents/SACC_Data/recovery/milestone1 \
  --query IMG --limit 20
```

Copy verification is a separate, explicit bounded experiment. It selects at most
12 eligible JPEG/PNG occurrences and persists that selection across failures. It
writes an XMP UTC capture date, missing GPS and missing description when safe,
preserves original camera/date fields, sets recovered-copy mtime to the selected
UTC instant, and reads back every intended tag and mtime. Conflicts block copying.
Video, HEIC, GIF and RAW metadata remain in the manifest for this milestone.
An uncommitted copy from an interruption is regenerated temporarily and adopted
only when bytes, tags and mtime match. A changed completed artifact is preserved
and produces an explicit error requiring inspection; it is never overwritten.

`report --batch <manifest-id>` rebuilds outputs from persisted results. `lookup`
searches original member paths and returns local catalog records ordered by capture
date. Detailed metadata/description/GPS queries can use SQLite's `recovery_catalog`
view and `recovery_results.result_json`. No API server or live DB is opened.

## Outputs and resume semantics

The output root is private (0700), outside source, repository and watched folders.
Source ZIPs are opened read-only. Source member paths are never used as extraction
paths; staged paths contain stable occurrence IDs. Unsafe paths, ZIP symlinks,
output symlinks, cloud-synced/watched roots and insufficient disk space are rejected.
A file lock prevents concurrent commands against the same output root.

- `recovery.sqlite3`: versioned account, batch, archive, original occurrence,
  content identity, album provenance, observations, statuses and append-only events.
- `staged/<batch-id>/`: original sample bytes; source and staged hashes must agree.
- `verified/<batch-id>/`: only bounded working copies with embedded metadata.
- `reports/<batch-id>/recovery.jsonl`: all 200 per-occurrence proposals, raw source
  field evidence, selected values/reasons, conflicts, paths and source/readback hashes.
- `review.csv`: 200 readable rows for local review, including capture/GPS sources,
  flags, proposed paths and source-integrity results. CSV text is formula-escaped.
- `summary.json` / `summary.md`: aggregate counts without private coordinates.
- `sacc_payloads.jsonl`: validated versioned integration envelopes (contract below).

Missing/ambiguous sidecars and malformed metadata become explicit review results.
Processing errors remain retryable. Existence alone never means completion.
Completed staging/copy bytes and copy mtime are verified on resume. Source SHA-256
is established by streaming the original ZIP member, then rereading it after
metadata inspection; ZIP CRC and archive size/mtime are also checked. This does
not hash or claim byte integrity of all 380 GiB of archives.

Original observations are stored per occurrence. Equal bytes can share a media ID
within an account while retaining every export/album observation. Conflicting
dates/GPS across identical content block automatic stop grouping and flag existing
dependent visits for review. Disputed/revoked confirmations invalidate transitive
dependent assignments and cannot be reused until reviewed.

## SACC integration contract

Every envelope has `schema: sacc.takeout.media.v1`, stable `media_id` and
`occurrence_id`, a `media_asset` object, full `recovery` evidence and independent
`stage_extensions`. The code validates generated envelopes before export.

| Field | Current SACC mapping / meaning |
|---|---|
| media_asset.media_type | Existing `media_assets.media_type`: `image` or `video` |
| media_asset.file_path | Actual staged local path, not a proposed final name |
| media_asset.source_path | Original ZIP locator: archive path plus member; not a directly playable filesystem path |
| media_asset.file_size_bytes / mime_type | Existing SACC size/MIME fields |
| storage_backend / storage_key | Local working storage and stable media identity |
| confidence / needs_review / review_reason | Existing SACC review fields; pending import is explicit |
| shoe_id | Null until an actual reviewed shoe link exists |
| recovery.account_id / source_sha256 / source | Account, original content hash, export/member/album provenance |
| recovery.capture / observed_gps | Source observations and selected values, distinct from inferred store pins |
| recovery.store_assignment | Exact branch/version/venue, status/evidence/confidence (unassigned now) |
| recovery.paths.proposed_final | Proposal only; final organization has not run |

These envelopes are not posted to the existing API. PoC `media_assets` requires a
shoe ID and the legacy `clips` table uses filename stems. After review/approval,
an additive bridge can map `media_id` to `media_assets.id` / `clips.id`, attach
reviewed shoe identities, and join visit/store records for live search. There is
no fake SKU or unclassified-media import into the live DB in this milestone.

Phase 2 video filtering and Phase 3 classification attach versioned `stage_results`
to the stable media ID. Classification has independent sneaker and privacy axes;
mixed content is possible. Privacy defaults to unknown and remote eligibility is
always false. Saving a stage result never dispatches an API job. Explicit motion/
live-photo component identifiers can create `media_links`; matching basenames alone
cannot establish a relationship. Actual classification and automatic component
review are later phases.

## Read-only store-directory contract and visits

Import an approved JSON export using `import-directory --directory <json-path>`.
The source file and Outlet Plug are read-only. A synthetic example is in
`tests/fixtures/takeout_store_directory.synthetic.json`; its coordinates and branch
names are test scenarios, not real directory data or a deployed integration.

Required top-level fields: `schema_version: 1`, `snapshot_id`, `source`, `provenance`,
and `stores`. Every store requires stable `version_id`, `store_id`, `retailer`,
`branch`, `store_type`, `provenance`. Optional fields include distinct `venue_id`,
address, aliases, latitude/longitude, and inclusive ISO `valid_from` / `valid_to`.
Coordinates must be a valid complete pair or both null. Version intervals for the
same branch cannot overlap inside a snapshot. Unknown dates remain unknown.
Snapshots are immutable; use a new snapshot ID for a later directory export.

`locations.candidates` returns all nearby branches with distance and historical
status. It never auto-selects the nearest pin. Explicit reviewed local signage,
video or user branch evidence can confirm a historical store version. Nearby
retailers and distant same-chain branches stay distinct. Unknown opening dates
need historical evidence before confirmation; shoe brand alone is insufficient.

Sample-based visit proposals split on gaps, movement, retailer-context changes,
uncertain dates or missing GPS. They are conservative hints, not confirmed visits.
Confirmed membership requires explicit evidence; a no-GPS member can inherit a
store only through that reviewed relationship. Store assignment never changes
observed GPS. Mixed photo/video timelines use IDs and remain linked after path
updates. Reviewer decisions, dependencies and revocations are retained for audit.
The map/review UI and large-scale mapping reuse remain later milestones.

## Later exports, tests and rollback

Use a new export label and discovery directory with the same output root/account.
Old batches are retained. `compare --old-batch <id> --batch <id>` reports path
additions/missing paths and separately reports hash-proven sampled overlap.
Unhashed entries cannot be asserted to be new/missing content. Different accounts
have separate identities even for identical bytes.

Run `.venv-poc-313/bin/python -m unittest discover -s tests -v`.
No live DB migrations, API/config changes or additional runtime dependencies are
required. Rollback means stopping the importer and retaining its separate output
tree for audit; originals/live databases require no reversal. The CLI intentionally
has no full-library apply command. Nitty must review the dry-run results and confirm
scope/account mapping before that separate capability is implemented or run.

## Screenshot GPS exception (2026-10-30)

Confirmed screenshots have GPS marked `not_expected_screenshot`. Missing GPS alone
does not put them in location review. Capture date, privacy and all other checks
continue, and existing coordinates/conflicts are preserved. Neither PNG format,
dimensions, filename nor missing GPS alone identifies a screenshot.

Explicit local review uses the existing append-only stage interface:

```python
db.add_stage_result(media_id, 'local_context', 'screenshot-review-v1', {
    'context_type': 'screenshot_review', 'is_screenshot': True,
    'reviewer': 'reviewer name', 'evidence': 'Identified during local visual review',
})
```

A later `is_screenshot: False` decision reverses the exemption. Every screenshot
decision has its own identity, so true→false→true re-confirmation remains auditable.
The latest valid inserted decision controls the report projection; raw recovery
results are preserved. `report` refreshes the exports without reprocessing media.
CSV columns `media_subtype` and `gps_requirement` are appended. Expected-GPS
coverage excludes confirmed screenshots from numerator and denominator; original
all-media GPS coverage remains available separately. No actual sample screenshots
have been marked from the user's general observation alone.

## Read-only trip and stop preview (2026-10-30)

```bash
.venv-poc-313/bin/python scripts/takeout_recovery.py trip-preview \
  --output /Users/daplug/Documents/SACC_Data/recovery/milestone1 \
  --batch 2ec7131b299ec7b0667019c7c1307e3c8a96df7d4b91bdeae652c37dc74506a0
```

This reads the existing database in SQLite read-only/query-only mode. It validates
the schema and recorded source-verification provenance without creating tables,
changing assignments or reading ZIP/media payloads. It writes only separate
`trip_preview.json/csv`, `trip_summary.json/md` and the output lock. A missing or
incompatible database is rejected. The original `review.csv` remains separate.

Defaults: neighbors within five minutes on either side; 5000 cached neighbors
globally; short stop pause five minutes; positive continuity up to 90 minutes;
trip gap three hours; overall trip span twelve hours; observed movement tolerance
150m. These are preview bounds, not calibrated accuracy claims. CLI options
`--neighbor-seconds` (1..3600) and `--context-limit` (0..5000) adjust context.
Truncation is reported and leaves affected targets unresolved.

Observed GPS and original active exact branch confirmations may anchor a proposal.
Both-sided evidence must positively agree, and historical/account/context checks
still apply. One-sided hints are weaker. Inferred labels never supply coordinates
or become anchors. Clean short no-GPS sequences may form an unlocated temporal
bundle for review; this does not identify a store. Conflicting source evidence,
different known devices and screenshots cannot be bridged by that weak rule.

Cached neighbors are explicitly `registered_sidecar_cache`, with occurrence IDs
and nullable media IDs. They are not newly verified media. Confirmed screenshots
are excluded from GPS inference. Detailed outputs stay local. The results and
step-by-step reading guide are in `SACC_TAKEOUT_TRIP_PREVIEW_RESULTS.md`.

Nitty confirmed Denivic is first on 2026-10-30. Full recovery still needs its own
reviewed implementation and an approved concrete run plan. No full-run command
has been added by the trip-preview work.

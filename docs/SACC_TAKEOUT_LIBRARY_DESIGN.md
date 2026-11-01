# SACC recovery library integration — 2026-11-01

Design proposal for the next user-authorized build. Review/reconciliation precede
implementation; independent QA precedes delivery. No full-library physical rename,
live shoe/pipeline database migration, cloud identification or Outlet Plug write
is authorized by this implementation increment. All real recovery media remain local.

## Problem and existing architecture

Recovery is complete:87,982 occurrences,63,558 metadata writes/readbacks,21,513
manifest-only formats and2,911 unchanged review outcomes (including5 readback
exceptions). The existing app cannot browse these records without identified shoes.
The real launcher uses main.py FastAPI with one origin/port5174 and SCAA/SACC.html;
CLAUDE.md's Flask/two-port description is historical. PoC media_assets requires
shoe_id; legacy clips/proxies/JSON rely on stems. Do not invent shoes or repurpose
those keys. All existing dirty files must be preserved with minimal additive hooks.

## Desired behavior and components

Add a real “Library” tab to SACC with server-paginated photo/video/unknown lists,
date/type/review/GPS/store filters, detail inspection and local media preview.
Add an exception-review workflow, append-only local decisions and an organization/
naming preview using the already approved direction. Exact shoe identification
and AJ1 aliases remain later enrichment, not a dependency for this library.

New modules: sacc_takeout/library.py (SQLite adapter/import/query/reviews),
library_api.py (FastAPI router), organization.py (immutable layout plan/journal),
scripts/sacc_library.py, SCAA/sacc/library-view.jsx and focused tests. Minimal
main.py changes register the router before static mount and allow SACC_APP_DB
override for isolated app-state tests. SACC.html adds tab/script/render hook;
existing frontend/backend code is otherwise preserved. Existing launcher continues
to load main:app; no parallel replacement application or remote provider dependency.

## Database and import

Use SQLite backup to create an isolated copy of var/sacc_multimodal.db under
/Users/daplug/Documents/SACC_Data/library/staging/sacc-library.sqlite3. Add versioned
library_* tables only; retain copied shoe/media tables and their row contents.
Original sacc_app.db, PoC DB, legacy DBs, recovery ledgers and recovered objects
must remain unchanged. An isolated app-state backup is used for browser testing.
Default library path targets this local staging store (override SACC_LIBRARY_DB).
Never initialize a library DB or import on a GET/app module import.

Tables: library_batches (plan/snapshot identities and roots), library_media
(account+original-SHA identity, privacy unknown, remote eligibility false),
library_occurrences (one per source occurrence, including unknown format),
library_review_events/effective overrides (optimistic revision, notes/evidence),
library_store_versions/snapshots, library_visits/members and preserved context
evidence. Shoe links are separate future many-to-many records, not mandatory FKs.
Physical recovered path, original path and proposed/organized path are separate.

Stream import from the completed recovery ledger with a read-only snapshot. Validate
plan identity, completion/counts and current final report hashes/watermark; reapply
existing screenshot/revocation projections without rewriting source observations.
Check path containment/no symlinks and actual output size/mtime. Do not rehash380GiB
merely to ingest metadata. Record integrity scope accurately. Account/occurrence/
media linkage is validated; report originals and derived fields remain distinct.
Unknown format is retained and unpreviewable rather than coerced to image/video.

Import is transactional/idempotent by plan+snapshot, never duplicates occurrences
or overwrites local review decisions. Stream records in bounded memory; index date,
type, review, account and store fields; use parameterized SQL/FTS with query limits.
An interrupted import rolls back; retry reuses the same source identity. Import
all87,982 real records into the isolated copied DB for reviewable delivery. Live
database promotion/import remains an explicit later approval, not an automatic step.

## Search and reviews

API prefix /api/library. GET endpoints: status, facets, paginated items, detail,
local asset/download and stored organization plans. POST endpoints: append review
decision, import approved directory snapshot, create organization preview. A fixed
configured recovery root is used for imports; clients cannot select arbitrary DBs
or files. Review evidence/reviewer is mandatory; stale revisions return409.

Filters include q (original name/description/store alias), image/video/unknown,
capture year/month, review outcome/reason, GPS present/missing/not expected and
confirmed store. UTC capture instants remain UTC unless a timezone is established;
date-only user corrections are explicit calendar-date overrides, not invented UTC
instants. Preserve raw dates and conflicts. Distinguish source integrity, embedded
metadata write/readback, canonical metadata, user-reviewed labels and branch status.

Allow local note, screenshot flag, privacy label, reviewed calendar date, exact
store confirmation and clearing an override. These change the library projection
only, not embedded media or recovery records; no generic “fixed all metadata” action.
For store confirmation require an imported historical version, compatible capture
date and explicit evidence. Unknown opening dates require historical evidence.
Allow explicit selected mixed photo/video membership only, with individual evidence;
do not auto-label an entire mall, time window or brand. Revocation/dispute must
invalidate dependent reuse. No propagation from shoe brand, nearest pin or a still
to all videos. Real store catalogue is not supplied: show unknown stores and an
honest empty confirmed-store filter until user-reviewed data is imported/entered.

## Local serving and user interface

Bind servers to loopback. All library routes validate loopback host/client and
origin; reject foreign Origin/Sec-Fetch-Site. Use a server-generated session token
and HttpOnly SameSite=Strict cookie established by a same-origin session endpoint;
mutations also require a CSRF header. Media URLs use IDs, not paths or query tokens.
Allow trusted legacy local origin5173 only if explicitly needed; prefer same-origin.
Serve only validated registered files below configured recovered/organized roots,
with no symlink traversal, correct MIME, nosniff and safe download filenames.
Do not render descriptions as HTML or embed arbitrary SVG/HTML/unknown formats.
Videos use standard local range responses; HEIC/RAW show a clear download fallback
unless a local supported preview exists. No geocoder/map tiles or media uploads.

UI: overview counts; list/grid toggle; search/filter/pagination; loading, empty,
offline/error states; selected-item preview/detail, GPS/source/review explanations;
review form with evidence and conflict feedback; organization preview with path/
count/storage/held reasons. Reuse existing SACC visual conventions. No giant client
download of87,982 rows. Synthetic media only in AI-visible browser screenshots.

## Organization and naming architecture

Implement, test and expose preview; do not apply a full real layout automatically.
Approved shape: Library/Photos|Videos/YYYY/BRANCH-readable-name/MM/
YYYY-MM-DD_BRANCH_SUBJECT_ID.ext. Use only trusted or explicitly reviewed dates
and exact confirmed branches. Uncertain dates go undated; unknown branches remain
Store-Unknown. Photos use Photo, videos Subject-Unknown unless confirmed store
context supports Store-Broll. No shoe names until identified. Use collision-checked
12-character occurrence-ID suffixes, extend deterministically if necessary. Preserve
media ID, all provenance, companion/visit relationships and naming-policy revision.

Recovery objects/reports must remain valid after organization. Therefore create
organized working outputs separately rather than moving/deleting recovered objects.
Use macOS APFS clonefile copy-on-write clones (not hardlinks sharing mutable data).
Clone-only mode must fail if unsupported; cp-c silently falls back and is not used.
Explicit full-copy mode requires enough capacity and approval; no silent380GiB
fallback. Test real small APFS clone independence; actual full layout is only a
preview in this build. Disk reserve/actual allocation still checked; COW growth
after editing is not claimed to be free or reserved.

Immutable plans bind selected IDs, review revisions/source hashes, destination,
strategy and sanitized paths. Journal attempts/owned temporary candidates/expected
hashes before publishing. Fail on stale reviews, untrusted paths, collisions,
changed sources, unexpected destination or insufficient space. Publish atomically
without overwrite; validate/adopt owned crash artifacts; preserve source bytes.
Catalog organized locators synchronize idempotently from published journal rows;
until synchronization, original recovered locators remain usable. Recovery ledger
is never rewritten. Rollback removes only unchanged journal-owned generated outputs
and restores catalog locators; edited outputs are preserved and block rollback.
Media objects and shared visits survive any path change. Apply/rollback are tested
on synthetic fixtures and require a concrete reviewed plan before real execution.

## Tests, rollback and delivery

Meaningful checks: copied legacy tables unchanged, streaming/idempotent import,
interrupted import rollback, query combinations/pagination/date edges, unknown formats,
privacy/source-vs-inferred GPS, stale review concurrency, screenshot reversal,
historical branches and revocation, malicious paths/CORS/CSRF/XSS, valid asset ranges,
organization collisions/stale plans/clone independence/crash adoption/rollback edits,
and regression tests for all recovery milestones. Synthetic browser validation
must exercise filters/details/review/preview and verify layout at narrow/wide sizes.

Run a separate local preview server using isolated app/PoC/library copies. Preserve
any existing server process. Verify aggregate real import counts without exposing
private images/GPS to model tools. Completion means functioning SACC tab, all real
records in the copied library DB, tested APIs/review/organization preview and
synthetic apply/rollback, plus independent QA, local runbook and sanitized Drive
backups. No blocker requires user clarification to start this scoped build.

Rollback: stop preview, retain/remove its isolated database and new generated test
artifacts. Revert only this build's minimal main.py/SACC.html hooks if needed;
preserve all pre-existing diffs. Existing working media and live DBs need no undo.

## Review resolution

Independent review: **APPROVED WITH NOTES**, recorded in
SACC_TAKEOUT_LIBRARY_REVIEW.md. All identified notes are accepted; none rejected.
Reconciliation is complete before implementation. Reconciled clarifications:

- Protect the real main:app with a shared loopback/client/Host/Origin/fetch-site
  boundary. Generic media bridges (including /api/video) reject query/JSON path,
  folder, root, file or DB parameters within or above protected recovery/library
  roots. The library cookie/CSRF boundary cannot be bypassed through old routes.
- Before importing main in preview/tests, configure separate SACC_APP_DB,
  SACC_POC_DB and SACC_LIBRARY_DB backups; PoC initializes/migrates on import.
- Review actions target explicitly selected occurrences with optimistic revisions,
  not all hash duplicates implicitly. Shared media IDs remain stable; privacy
  labels never enable remote dispatch. Date changes invalidate historically
  incompatible store labels and stale any organization plan. Every review is audited.
- Import binds report hashes and ledger watermark within one source read snapshot,
  preserves local reviews and prior source-snapshot references, and revalidates
  historical store overrides. Import integrity is stat/report-based, not a new
  full-media SHA verification. Legacy tables and live DBs stay unchanged.
- Organization verifies final published output SHA, not pre-embedding source SHA;
  compares case/Unicode-normalized destinations, publishes without overwrite and
  uses compare-and-swap when syncing/reverting locators so old rollback cannot
  undo a newer plan. Copy-on-write outputs keep recovery paths valid. Actual full
  layout application is gated on a concrete reviewed plan; fixtures exercise it now.

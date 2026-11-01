# Takeout naming, folders and SACC search proposal

2026-10-30. Naming direction approved by Nitty; no files renamed or live schemas
changed. Nitty wants footage searchable by capture
year/month, exact historical store branch and shoe model for B-roll and Outlet Plug.
Independent technical design review remains required before implementation.

## User approval and sequencing clarification — 2026-10-30

Nitty explicitly approves the descriptive naming/folder direction and later SACC
aliases such as AJ1. First recover/preserve metadata, resolve supported locations
and organize/isolate the products. Exact shoe identification through API calls is
last, after the required local privacy review. This approval does not authorize a
full-library run, cloud uploads, immediate physical renames or live DB changes.

Initial subject tokens can be `Store-Broll`, `Multi-Shoe`, `Photo` or
`Subject-Unknown`. Shoe-specific filenames/search aliases are optional later
enrichment after identification, without changing permanent IDs. A video can show
LeBron and Jordan products together; do not force one model into every filename.
Stills, held shoes and box labels can provide identification evidence and candidate
links to nearby video. Require compatible time/visit/product context and supporting
video evidence before asserting that a particular shoe is visible in that video.
Never propagate every still's shoe label to every video in a store visit.

Location is a first-pass objective, not a promise to label all media. Preserve
observed GPS; assign exact stores only with sufficient reviewed evidence. Keep
uncertain locations in review and confirmed screenshots exempt from missing-GPS
requirements. No fabricated coordinates or guessed branch names.

The next implementation is the reviewed full-recovery plan/pilot workflow in
`SACC_TAKEOUT_FULL_RECOVERY_DESIGN.md`. Naming is settled at the requirements level;
no further naming clarification is needed now. Shoe enrichment is not a prerequisite
for recovery or date/store browsing.

## Meaning of the sample verification counts

All 200 sample sources passed byte-hash verification and had metadata inspected.
150 sample items had valid selectable GPS observations; that is not human
confirmation of the historical place or store. The 12 verified working copies are
the bounded metadata-writing test: write recovered XMP capture date, read it back
and check capture-based filesystem mtime. Existing GPS on those 12 was retained.
The real test does not claim 12 newly recovered GPS positions or 12 visually
identified shoes. Other sample files were not selected for this extra write test;
their existing metadata is not invalid merely because copy status is unverified.

The full workflow must give every occurrence an explicit processing/integrity
outcome and validate each field actually written by reading it back. Unsupported
embedding formats retain canonical metadata and explicit manifest-only status.
Geographic/store correctness and shoe identity are separate evidence/review states.
Future UI/report wording should distinguish source integrity, metadata write/readback,
observed-GPS validation and confirmed store identity rather than a single ambiguous
"verified" label. User review focuses on exceptions, not manually checking all files.

## Recommended convention

Readable filename with a persistent ID:

`YYYY-MM-DD_BRANCH_SUBJECT_ID.ext`

Illustrative examples, not observations about real footage:

- `2015-06-21_NC192_Air-Jordan-1-Chicago_7c2a91d4e6b0.mov`
- `2015-06-21_NC192_Store-Broll_9d4a21c6b730.mov`

Alternative compact convention: `2015-06-21_NC192_7c2a91d4e6b0.mov`.
Recommend the descriptive convention for useful Finder/FCP filenames. Exact
camera model, full GPS, every shoe tag and SKU do not need to inflate filenames.
Keep those in the canonical record. Existing approved legacy media keep their
current names until a separately reviewed migration/relink plan covers them.

`NC192` is an existing SACC label for the historical Nike Clearance US-192 branch.
It is a readable filename token, not a replacement for stable store/version IDs.
Keep The Loop, Vineland and other branches distinct. A venue code alone cannot
identify a Nike branch within that venue. Use only reviewed store assignments;
unresolved retail branches use `Store-Unknown`, with candidates retained locally.
Do not assign a store from the shoe brand. Personal content gets no inferred
retail label from nearby media and stays in the private/local classification.

Use the reviewed capture date, never import date, upload date, shoe release year
or today's date. Persist its calendar/timezone basis: use UTC when only UTC is
known, and a confirmed local timezone only when supported. SACC may display both
without inventing an offset. Unresolved dates use `Undated` pending review.

Use a verified specific shoe subject when one dominates. Otherwise use a broad
truthful label such as `Air-Jordan-1`, `Store-Broll`, `Multi-Shoe` or `Subject-Unknown`.
Do not invent a colorway/SKU. All confirmed shoes remain independently searchable,
including multiple shoes in one video. Later tag corrections update database/display
labels first; filename changes use an explicit reversible rename plan.

## Physical folders and app collections

Proposed refinement of the earlier year/month layout, after classification and
branch/date review:

```text
Library/Videos/2015/NC192_Nike-Clearance-192/06/
Library/Photos/2015/NC192_Nike-Clearance-192/06/
```

Use a stable, unique branch slug from the reviewed directory. Unknown branches
stay `Store-Unknown`; undated media stay under `undated` without guessed year/month.
Personal/mixed/uncertain privacy handling remains local and is separate from store
identity. Classification, privacy and review status remain explicit database fields.

SACC collections can also show Store → Year, Shoe → Year or Year → Store without
duplicating files. Photos and videos share visit IDs despite separate folders.
This folder refinement is a proposal and does not change any current output path.

## Search contract and examples

Structured indexed fields/facets, independent of filename spelling:

- Media type; capture year/month/date range and date confidence.
- Retailer; exact store ID/branch, historical version, venue and store type.
- Shoe brand; normalized model family, variant, colorway and optional style code.
- Shared visit; content type such as store B-roll, shoe detail or box/label.
- Sneaker presence, personal/mixed/unknown/non-personal privacy, shoebox and review.

Keep original names/paths, account/batch, observed GPS, inference evidence and
correction history. Search aliases may include `AJ1`, `Jordan 1`, `Air Jordan 1`,
`NC192`, `Nike 192` and `Nike Clearance 192`; aliases resolve to canonical entities,
not new duplicate store/shoe records. Capture year and shoe release year are separate.

Target app queries:

1. Videos + capture year 2015 + Nike Clearance 192 → that branch's footage.
2. Air Jordan 1 → every tagged matching photo/video across stores and years.
3. Air Jordan 1 + capture year 2017 + Nike Vineland → that intersection, if confirmed.

Videos need many-to-many shoe associations; one primary filename subject cannot
represent every shoe shown. Optional reviewed time spans can later locate a shoe
inside a long video. Store/shoe tag corrections must not require renaming to fix search.
Outlet Plug reuse is through reviewed export contracts; no Outlet Plug writes here.

## Integration, implementation gates and verification

Affected future systems: recovery rename planner/journal, directory aliases, SACC
media-ID bridge, multi-shoe relationships, indexed search/filter API and review UI.
No live migration, endpoint or classifier is implemented by this proposal.

Legacy SACC/Final Cut helpers use filename stems as links. Before renaming recovered
outputs, implement/review an additive stable-ID bridge and update relevant JSON,
proxy and database path references as one recoverable operation. Do not casually
rename existing editor-linked media. SACC can keep an editable descriptive display
title alongside the persistent media identity.

IDs must be registered unique, not trusted merely because a short hash prefix looks
unique. Use full account-scoped source-hash media IDs internally. The display suffix
can begin at 12 hex characters with deterministic extension on collision. Distinct
retained occurrences/renditions need separately unique output identities when they
share a media ID; do not overwrite or discard duplicate provenance. Extension/type
conflicts need review. Sanitize/reserve path components and enforce byte-length
limits. Preserve originals and log before/after paths, IDs, plan and approval.

Implementation requires the repo's independent design review/reconciliation, tests,
then a concrete rename preview before any approved application to working copies.
Test historical branch separation, alias search, multi-shoe matches, unknown dates/
stores, timezone year boundaries, privacy filtering, collisions, duplicate occurrences,
path safety and crash-safe rename/relink/rollback. Existing milestone data and dirty
working-tree files stay unchanged. Rollback uses the journal; no source ZIP mutation.

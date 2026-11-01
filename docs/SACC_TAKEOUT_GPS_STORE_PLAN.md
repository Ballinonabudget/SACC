# SACC metadata and store location build plan

Implementation brief for Nitty and Codex
Updated October 29 2026

## The decision

Restore metadata and GPS first. Keep photos and videos linked by visit while organizing them into separate media groups. Use GPS to narrow the venue, then use a confirmed store mapping and local video or photo context to identify the branch. Confirming one store should help organize the rest of that visit.

The aim is broad reuse of confirmed locations. The suggested 90 percent coverage is a goal to measure, not an established result. Files without trustworthy location evidence stay in Needs Review.

## Build order

1. Build the importer and recovery manifest. Register account and export batch, combine sidecar matching across ZIP parts, hash source bytes, and preserve original paths and album links. Accept a later full Takeout without replacing the current export.
2. Restore dates and available GPS on working copies. Record the source and confidence of each value. Review suspicious dates and location conflicts before applying changes.
3. Build the store catalogue and shared visit records. Read the existing store directory, propose GPS matches, and link photos and videos from the same visit before final folder organization.
4. Quarantine redundant working copies, then organize Photos and Videos by year and month. Keep shared visit and store links in the manifest and database after files are separated.
5. Classify Sneakers, Personal, Other, and Needs Review locally. Flag shoeboxes and use local video context to resolve store questions. Personal or uncertain content stays local.
6. Review results, apply approved filenames, and connect the organized sneaker library to SACC search. Repeat with Account 2 using the same tools.

## Preserve the evidence

Keep original ZIPs and media unchanged. Record observed latitude and longitude, source tag or JSON field, capture time, timezone evidence, and accuracy when the source supplies it. Validate coordinate ranges and flag suspicious or conflicting values. Do not invent precision, GPS readings, or timezones.

Compare sidecar GPS, including geoDataExif and geoData, with embedded image or video coordinates. Preserve the raw values and identify the selected value and reason. Missing GPS does not mean a file is unusable: it may receive an inferred store assignment from a confirmed related visit, with that inference clearly recorded.

<!-- pagebreak -->

## How a location becomes a store

GPS supplies nearby candidates. Use configurable distance tolerances and any available accuracy evidence, rather than requiring identical coordinates or choosing the nearest pin unconditionally. Keep outlet or mall identity separate from individual store identity.

A distant branch should be easy to distinguish. The International Drive Nike location and the Highway 192 Nike location must have different store IDs. Nearby Nike and adidas stores also remain separate. A mall coordinate may establish the venue while leaving Footaction, Finish Line, or another retailer unresolved.

Use readable store signage, storefront context, local video frames, and user confirmation to distinguish nearby stores. Shoe brand is supporting evidence: an adidas shoe alone does not establish an adidas shop, because a multi-brand retailer can sell it. Conflicting retail context must trigger review rather than a forced Nike or adidas assignment.

## Confirm once and reuse carefully

Show a representative video or photo, candidate stores, observed GPS, and the capture timeline. Nitty chooses the correct branch and confirms the visit. Save that confirmation as reusable evidence tied to the store, area, capture period, and relevant context.

Reuse reviewed store-area mappings across other visits and export batches when location, historical dates, and context agree. Let Nitty review and confirm an unambiguous batch together. Overlapping stores or changed conditions still need separate evidence. Measure how much of the library this resolves without requiring a decision for every shoe.

Propose the same store for other media in that visit when time, coordinates, and context agree. Split visits on movement, substantial time gaps, changed signage, or another store boundary. A single mall visit may contain several store stops. Do not label an entire export folder or a four-hour window as one store.

For media without GPS, inherit a store only when a confirmed visit link provides enough evidence. Record the source media or confirmation that supported the inference. Never write the store pin into the camera GPS field as though it were measured there. Corrections must identify and reconsider dependent assignments.

## Preserve historical store identity

Import a read-only snapshot of the existing directory with stable source IDs and provenance. Record the retailer, branch, venue, address, store type, coordinates, aliases, and known active dates. Keep historical location versions when a branch moves or changes type.

Match the directory against the media capture date. A newer store cannot explain an older visit unless historical evidence supports it. Unknown opening dates are unknown, not proof the store existed then. Retain closed branches and old names; allow a historical store to be added through review.

Keep this work inside SACC. Reuse Outlet Plug directory data through an explicit read-only import or export contract; do not modify Outlet Plug code or assume its current directory is a complete historical record.

<!-- pagebreak -->

## Keep photos and videos connected

Every item needs a stable media ID, account and batch ID, original hash and path, recovered capture time, and final output path. Store observed GPS separately from the inferred store location. Keep venue ID, store ID and historical version, visit ID, assignment status, evidence, confidence, and reviewer decision.

A visit view must show both photos and videos in capture order. Separating folders must not break these links. Live or motion-photo components retain their relationship. Uncertain dates, device clock differences, and GPS jumps weaken visit grouping and require review.

The location review screen should provide a map and a list with branch names, venue, store type, historical status, and filters by date and confidence. Selecting a visit should reveal linked photos and videos. Show overlapping store candidates clearly. Keep personal locations out of the store map by default, and keep raw personal coordinates local. A local map or list must remain usable without external tiles or geocoding.

## The first implementation milestone

Extend the existing discovery tools into a resumable importer and metadata dry run. Produce a 200-file report showing proposed date and GPS recovery, missing values, conflicts, source fields, and unchanged source-file checks. Also propose the store catalogue import contract and shared visit records.

Build and test the first location suggestions against local fixtures. If the real directory is not yet available, provide a validated import interface and clearly labeled test data. Do not invent real store coordinates or claim a live integration exists. A full extraction and recovery pass waits for the established data review and approval.

The repo currently states that GPS-only geofencing was removed from fcp_namer.py. venue_anchor.py also assigns a folder-level location through remote video analysis. This proposal introduces a separate reviewed GPS and visit workflow. Existing cloud anchor calls must not process the personal Takeout library automatically.

## Acceptance checks

- GPS recovery distinguishes observed coordinates, missing GPS, and inferred store assignments; unsupported embedding formats retain complete manifest metadata.
- Nearby Nike and adidas stores, two distant Nike branches, and multiple retailers in one mall remain distinct in tests.
- A mixed photo and video visit shares its confirmed store after output folders are separated; a store transition creates a new stop.
- Historical and missing stores, uncertain dates, missing accuracy, and conflicting metadata produce explicit review results.
- Re-running resumes safely. Duplicate exports preserve provenance. A changed confirmation can be audited and reversed.
- Report GPS coverage, candidate coverage, reviewed store accuracy, unresolved items, and cross-store errors separately. High coverage must not hide incorrect branch assignments.

<!-- pagebreak -->

## Codex starting prompt

Work inside /Users/daplug/Documents/SACC. Read docs/SACC_TAKEOUT_GPS_STORE_PLAN.md, docs/SACC_TAKEOUT_BUILD_ORDER.md, docs/SACC_TAKEOUT_DISCOVERY_2026-10-29.md, and docs/SACC_TAKEOUT_CHATGPT_CODEX_HANDOFF.md. Read any applicable AGENTS.md and the repo operating and review instructions. Inspect the dirty working tree and preserve other agents' changes. Use a codex/ branch and reuse existing ingestion and metadata code where practical.

Start with the importer, manifest, and a 200-file metadata and GPS recovery dry run. Preserve original exports. Match sidecars across all ZIP parts and support a later complete export. Record observed GPS separately from inferred store locations. Include missing GPS, conflicting metadata, suspicious dates, provenance, and readback validation. Do not fabricate coordinates.

Propose the store directory import contract and shared visit model now so separating Photos and Videos preserves their relationships. GPS narrows venue and branch candidates; confirmed store mappings, local video or signage evidence, capture dates, and retail context resolve ambiguity. Keep nearby Nike/adidas shops and distinct Nike branches separate. Shoe brand alone is insufficient. Respect historical stores and date ranges. Keep missing or uncertain locations in review.

Provide a design proposal with affected files, database and API impact, migration/rollback approach, edge cases, tests, and acceptance checks. Follow the repo's Anti-Gravity cross-check process before implementation. After review and reconciliation, implement only the first milestone with meaningful tests and resumable manifests. Reuse approved directory data read-only and leave Outlet Plug unchanged. Do not launch old cloud venue-anchor jobs on Takeout media.

Keep personal and uncertain media and their GPS local. No full extraction, full metadata rewrite, quarantine, final rename, or live database import until the dry-run results have been reviewed and approved. Report what was built, tests, limitations, and the next concrete approval needed. Keep replies short and ask one question at a time only when needed.

## Supporting sources

This brief records Nitty's requirements from October 29 2026. The local discovery report and build order provide the archive findings and original recovery sequence. The following Outlet Plug documents are design references; their descriptions are not verification of current deployed behavior.

- Batch ingest brief version 3: https://drive.google.com/file/d/1bTU2EA9l2iGgaK3dlhsTv4EHeDDhhRxy/view
- Store picker UX fix: https://drive.google.com/file/d/1LGWNW_kQZ1PUJMLX673ugBApILpnzaS9/view
- Store map rebuild: https://drive.google.com/file/d/1UT3n0A1rKSpJilNzENPtcuR46HV-UPTq/view

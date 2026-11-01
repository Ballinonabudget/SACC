# SACC Takeout — build order

Updated 2026-10-29. This is the implementation order, not permission to run a full recovery pass.

The priority is a usable library: Photos and Videos, correct dates and GPS, store locations, then Sneakers / Personal / Other. Restore metadata on working copies before creating the final folders so files land in the right year and month. Keep photos and videos linked through shared visit records after folder separation. Keep original exports unchanged. The detailed GPS requirements are in `docs/SACC_TAKEOUT_GPS_STORE_PLAN.md`.

## 1. Build the importer and recovery manifest first

Extend the discovery tools in this repo. Register each account and export batch separately, inventory every ZIP part, and match media and JSON across the whole batch. Preserve original paths and album memberships. Hash unchanged source bytes before metadata restoration so later duplicate checks can use the original content.

Support dry runs, progress, error reporting, and restart without repeating completed work. Use a separate staging/output tree outside SACC's watched ingestion folders so importing a personal library cannot accidentally trigger remote analysis. Check available space immediately before extraction and account for staging, outputs, and quarantine.

Completeness of the current 38-part Denivic batch remains unconfirmed. The importer must accept a later export, compare it with the existing manifest, and report added/missing files without replacing the old export. Code development can proceed while the complete library is being obtained. Confirm the account mapping before a full run.

First reviewable deliverable: an account/batch inventory and a 200-file metadata recovery dry run showing proposed dates, date sources, matches, conflicts, and output paths. No original file changes.

## 2. Restore metadata onto working copies

Match sidecars across ZIP boundaries before writing anything. Choose a validated `photoTakenTime` first, existing embedded capture metadata second, and original file modified time only as a clearly marked last resort. Flag suspicious dates, timezone conflicts, and uncertain matches for review. The two MP4 sidecars dated 1962 need review; do not silently accept or invent replacement dates.

Restore dates and available GPS/description fields where the file format supports them. Use format-appropriate image and video tags; do not assume every video or RAW format supports the same embedded fields. Keep the complete canonical metadata in the manifest and associated sidecar even when it cannot be embedded. Preserve existing metadata that is not being corrected, and do not invent camera details or timezone offsets.

Verify written tags by reading them back. Compare a small set of working copies with their source records before requesting approval for the full pass. A structurally matched sidecar does not establish that its historical date is correct.

## 3. Build GPS store mapping and shared visit records

Import the existing store directory read-only with stable branch IDs, venue IDs, and historical versions. GPS narrows candidates; confirmed mappings, capture dates, local signage/video evidence, and retail context resolve the store. Keep nearby Nike/adidas shops and distant branches of the same chain distinct. Shoe brand alone does not identify a retailer. Uncertain stores stay in review.

Confirm a store once per stop, then propose it for related photos and videos with compatible time, GPS, and context. Split stops on store transitions; do not treat a whole mall or export folder as one store. Store missing or observed GPS separately from an inferred store assignment, and preserve evidence and correction history. Never fabricate camera GPS from a store pin. New stores cannot explain old footage without historical support.

## 4. Quarantine edited copies and exact duplicates

Use the pre-restoration hashes to identify exact duplicates. Keep every original ZIP and source file. Quarantine only redundant working copies and retain their source/album links in the manifest.

For an edited copy, first establish that its corresponding original exists. If it does not, retain the edited copy and flag it. Every quarantined working file must have a manifest record linking it to the retained file. Nothing is permanently deleted.

## 5. Organize Photos and Videos by date

Create the final type and date structure using the reviewed metadata:

```text
Library/
  Photos/YYYY/MM/
  Videos/YYYY/MM/
  Photos/undated/
  Videos/undated/
  Review/unknown-format/
Quarantine/
  edited/
  duplicates/
```

GIFs stay with Photos and carry an animation flag. Live/motion-photo companion clips go under Videos but retain a link to their associated photo. This classification does not authorize dropping either component. Unrecognized formats stay in Review. Type separation and dates come before sneaker classification.

## 6. Sort sneaker, personal, other, and uncertain items locally

Build the local classifier and a quick review screen for both photos and videos. Photos use local image analysis; videos use local frames sampled across the clip. Frame sampling is evidence for classification, not proof that the whole clip contains no personal content.

Track two separate facts: whether an identifiable sneaker is present, and whether personal/family content is present or uncertain. An item can contain both. Keep personal and mixed/uncertain items local. A person visible in a retail scene does not automatically establish that a file is personal.

Show primary groups under each media type: Sneakers, Personal, Other, and Needs Review. Inside Sneakers, flag shoebox present / absent / uncertain. Use manifest records and the review UI first; any later folder placement is automatic and reversible. The user should not need to drag or rename files manually.

Validate on a few hundred user-labeled items before classifying the full library. Measure sneaker precision/recall and personal-content misses separately. Items with insufficient evidence stay in review rather than being forced into a bucket. Full-run progress and corrections must be resumable.

Cloud analysis is optional, later enrichment. It is not required for initial organization. Personal, mixed, or uncertain privacy status must block cloud uploads. Videos remain local in this first build. Any later remote video analysis needs a separate privacy review; sampled frames alone cannot clear a full clip for upload.

## 7. Add final names and SACC records

After the date and classification review, propose and approve a filename convention, then apply it automatically to working outputs. Store a stable ID, original filename/path, final path, account/export batch, original hash, date and its source, classification, confidence, review status, and linked media/album records.

Connect the reviewed sneaker items to SACC's browsing and search. Personal items remain separated from the shoe pipeline and remote processing. Keep an oldest-to-newest view. Exact shoe model, style-code identification, and external lookups come after the library is organized.

## 8. Repeat with Account 2 and reconcile later exports

Use the same tested importer, rules, manifest, and review workflow. Preserve provenance across accounts and exports. Compare hashes and retained records before adding another copy; do not assume equal names mean equal files or merge records merely because their capture dates agree.

## Current stop point

Discovery is complete within the recorded search limits. The full library is not confirmed. No full extraction, metadata writes, quarantine, classification, rename, or database import has been started by this plan. Next implementation work is step 1: the importer/manifest and a reviewable metadata recovery dry run.

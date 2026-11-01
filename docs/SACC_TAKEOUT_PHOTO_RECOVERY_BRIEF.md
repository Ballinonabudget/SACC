# SACC — Google Takeout Photo Recovery Brief

Hand-off doc for Claude Code. Written 2026-10-29. Extends the existing SACC project (see SACC_V2_WORKFLOW.md); do not start a new repo. Work inside the existing SACC project.

Local copy: put this file in the SACC repo docs folder. Drive copy is the backup. Keep both in sync.

---

## 1. Goal

Turn Nitty's old Google Photos Takeout exports into a clean, dated, sorted library so SACC can find every identifiable sneaker photo, oldest to newest, and later connect them to shoe records.

Final shape of the library:

1. Correct dates and metadata restored onto every original photo/video
2. Edited copies removed (quarantined, not deleted)
3. Split by type: videos / photos
4. Photos split by year and month (e.g. 2014/01)
5. Photos sorted into: shoes (with shoebox / without), personal, other
6. Renamed consistently and connected to the SACC database

## 2. Inputs and scope

- Takeout is already downloaded. It lives on the Synology drive. Agent must find the folder (path not yet confirmed; see Open Questions).
- Two Google accounts. **Account 1 first, as the practice run.** Account 2 later, using the exact same tooling and behavior.
- Nitty has not uploaded to Google Photos since 2020, so content should be pre-2020/2021. Do not assume; verify from the data.
- Practice range: the earliest date a findable shoe photo exists (2013/2014 or earlier) through the latest.

## 3. Non-negotiable rules

- **Never modify the original Takeout files.** Work on copies or write to a separate output tree. Originals stay read-only.
- **Nothing is permanently deleted.** "Remove edited photos" means move to a quarantine folder with a manifest. Nitty approves any real deletion.
- **Personal photos never leave the machine.** The personal / family classification must run locally. Only photos already judged shoe-candidates (or uncertain non-personal ones) may go to a cloud API.
- Every step is resumable and logged (manifest file or SQLite table), since there will be tens of thousands of files.
- Dry-run mode for every step that moves, renames, or writes metadata.

## 4. Phases

### Phase 0: Discovery (read-only)
- Locate the Takeout folder on the Synology; report path, size, whether zips are extracted, how many files by extension.
- Count media files vs JSON sidecars. Report files with no sidecar and sidecars with no media.
- Report earliest and latest dates found. No changes to any file.

### Phase 1: Metadata merge (JSON sidecar to EXIF)
- Takeout stores the real date, GPS, and description in a JSON sidecar next to each file; the media files' own EXIF is often missing or wrong.
- Match each media file to its sidecar. Known quirks to handle and verify against the real data:
  - Sidecar naming varies by export (older `photo.jpg.json`, newer `.supplemental-metadata.json`, and truncated long names).
  - Duplicate suffixes like `(1)` where the sidecar name and media name disagree.
  - Same photo appearing in multiple album folders.
- Date priority: sidecar `photoTakenTime` first (not `creationTime`, which is upload time); fall back to existing EXIF; last resort file mtime. Record which source was used per file.
- Write the date (and GPS, if present) into EXIF/XMP, and set the file modified time to match. exiftool is the likely tool; a maintained Takeout-fixer (e.g. gpth) is an acceptable alternative if it behaves; agent should test on a small sample and compare before committing to one.
- Output: a per-file record in the manifest: original path, sidecar path, date source, final date, GPS yes/no.

### Phase 2: Edited-copy removal
- Edited versions (typically named with `-edited`) do not carry the original's metadata. Identify them and confirm the original exists before touching them.
- Move to `quarantine/edited/` with a manifest entry linking edited file to its original. If no original exists, leave the edited file in place and flag it.
- Also detect exact duplicates by hash; quarantine extras, keep one, record the link.

### Phase 3: Organize by type and date
- Separate videos from photos by extension/mime type (note: motion/live-photo clips and GIFs need a rule; agent should ask or choose and document).
- Photos into `YYYY/MM` folders using the Phase 1 final date.
- Files with unknown dates go to `undated/` and are reported.

### Phase 4: Shoe / personal / other sort (photos only)
Layered, cheapest first, same idea as the SACC Stage 0 cheap classifier:
1. **Local pass (free, on-device):** a CLIP-style or similar local model splits into obvious shoe, obvious people/personal, and unsure. Personal is decided here and stays local.
2. **Cloud pass (Gemini, existing SACC setup):** only shoe-positive and unsure non-personal photos. Questions: is a sneaker clearly visible, is it identifiable, is a shoebox/label visible and readable, is it a store setting.
3. Output classes: `shoe_with_box`, `shoe_no_box`, `personal`, `other`, plus a confidence score and the model that decided. Low-confidence items go to a quick review queue (SACC's keyboard-driven review UI pattern).
- Use batch mode for the cloud calls if the Gemini setup supports it. Log cost per run.
- Start with a small labeled sample (a few hundred photos Nitty confirms by hand) to measure accuracy before running the full set.

### Phase 5: Rename and connect
- Rename convention is TBD with Nitty (see Open Questions). Proposed starting point: `YYYY-MM-DD_HHMMSS_<shortid>.<ext>`, with the original filename preserved in the manifest and DB.
- Connect each file to the SACC database: file record with final date, source (account 1/2), classification, confidence, hash, original path. Shoe-identification (style code, model) is a later step that reuses the shared shoe-ID service work; not in scope here.

### Phase 6: Repeat for account 2
- Same code, same config, new input path. Compare results and fix anything the practice run missed.

## 5. Deliverables

- Scripts/CLI inside the SACC project with a dry-run flag and resumable manifest
- A short run report per phase (counts, errors, date-source breakdown, cost)
- Quarantine folder + manifest, never deleted
- Updated project docs noting this workflow

## 6. Open questions (ask Nitty before building the affected phase)

1. Exact Synology path to the Account 1 Takeout, and whether it is still zipped.
2. Where the existing SACC project lives and which machine this runs on.
3. Rename convention he wants.
4. How to treat live-photo clips, GIFs, screenshots, and memes (separate bucket or "other").
5. How strict "identifiable shoe" should be for Account 1 practice run.
6. Preferred local model/tooling, if he has a preference, given the editing machine vs coding machine split.

## 7. Suggested first session

Phase 0 discovery only: find the folder, produce the inventory report, test the sidecar matching on a 200-file sample, and report back before any file is written or moved.


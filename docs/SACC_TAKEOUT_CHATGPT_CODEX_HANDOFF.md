# SACC — Takeout Photo Recovery: Hand-off for ChatGPT / Codex

Written 2026-10-29. Owner: Nitty. This doc is self-contained. If you can also read the companion files below, do, but you do not need them to start.

Companion files (Google Drive root, and SACC repo docs folder if present):
- `SACC_TAKEOUT_PHOTO_RECOVERY_BRIEF.md` : full phase-by-phase plan (more detail than this doc)
- `SACC_V2_WORKFLOW.md` : the existing SACC master spec (triage-first design, Stage 0 cheap classifier, keyboard review UI)

If the SACC repo has an `AGENTS.md`, read it first and follow it. If it conflicts with this doc, the repo's AGENTS.md wins on code conventions; this doc wins on the goal and the safety rules below.

---

## 1. What we are doing

Nitty has old Google Photos Takeout exports (two Google accounts) on his Synology NAS. He wants to:

1. Restore the real dates and metadata onto every photo and video
2. Remove edited copies (they lack the original's metadata) by quarantining them
3. Split videos from photos, then photos by year and month
4. Find every photo with an identifiable sneaker, oldest to newest, and flag which have a shoebox
5. Separate personal photos (him, family) so they stay out of the shoe pipeline
6. Rename files consistently and connect them to the SACC database

Account 1 is the practice run. Account 2 comes after, using the same tools.

Nitty has not uploaded to Google Photos since 2020, so content should be roughly pre-2020/2021. Verify from the data; do not assume.

## 2. Safety rules (non-negotiable)

- **Never modify, move, or delete the original Takeout files.** Read-only. All work happens on copies or in a separate output tree.
- **Nothing is permanently deleted.** "Remove edited photos" means move to a quarantine folder plus a manifest. Ask Nitty before any real deletion.
- **Personal photos must not be sent to any cloud API.** Classify personal vs shoe locally first. Only shoe-candidate or uncertain non-personal photos may go to the Gemini API.
- **Do not ask Nitty to paste passwords, keys, or tokens into chat.** The SACC project already has a Gemini key in its own environment file; use that, and do not print or echo it.
- Every step must have a **dry-run mode**, be **resumable**, and write a **manifest** (CSV or SQLite) of what it did. Expect tens of thousands of files.
- Report before changing: show counts and a sample, get a go-ahead, then run the full pass.

## 3. Where to look

You are expected to find the Takeout yourself. Nitty does not remember the exact path.

1. The Synology should be mounted on the Mac as a network volume. On macOS, check `/Volumes/`. List it and look for the NAS share.
2. Search that volume (and the user's home folder, in case of a local copy) for folders or archives named like `Takeout`, or for `.zip` files with `takeout` in the name. Example: `find /Volumes -maxdepth 4 -iname "*takeout*" 2>/dev/null`
3. If the NAS is not mounted or you cannot see it, **stop and tell Nitty** which volumes you can see, and ask him to mount the share (Finder, Go, Connect to Server) rather than guessing. Do not search outside the NAS and home folder.
4. Takeout may be split across many zip files per account (often numbered). Report all parts you find and which account each belongs to (Nitty will confirm the account for each, since the zips may not say).
5. The SACC project itself (the existing repo with the Gemini pipeline) should be on the coding Mac. Find it; do not create a new repo.

Takeout zips: unzip into a working directory on a drive with enough free space, leaving the zips untouched. Check free space first and report it.

## 4. Build order

**Step 0: Discovery (do this first, change nothing)**
- Locate the Takeout zips/folders, report path, number of parts, total size, free space for extraction.
- After extraction: count media files by extension and JSON sidecars. Report media with no sidecar and sidecars with no media. Report earliest and latest dates found.
- Test sidecar matching on a **200-file sample** and report the match rate and any odd naming patterns.
- Stop and report to Nitty before going further.

**Step 1: Metadata merge**
- Match each media file to its JSON sidecar. Known quirks to verify against the real data: different sidecar naming across export versions, truncated long filenames, `(1)`-style duplicate suffixes where the sidecar and media names disagree, and the same photo appearing in several album folders.
- Date priority: sidecar `photoTakenTime` first (not `creationTime`, which is upload time); then existing EXIF; then file modified time as last resort. Record which source was used for every file.
- Write date (and GPS if present) into EXIF/XMP and set file modified time to match. exiftool is the expected tool, or a maintained Takeout-fixer such as gpth. Test on a small sample and compare results before choosing.

**Step 2: Edited copies and duplicates**
- Identify edited versions (usually a `-edited` suffix). Confirm the original exists first. Move to `quarantine/edited/` with a manifest linking each to its original. If no original exists, leave it and flag it.
- Detect exact duplicates by hash. Keep one, quarantine the rest, record the link.

**Step 3: Organize**
- Videos vs photos by file type. Decide a rule for live-photo clips and GIFs, document it, and tell Nitty.
- Photos into `YYYY/MM`. Unknown dates into `undated/` and report them.

**Step 4: Shoe / personal / other (photos only)**
- Local pass first (a CLIP-style or similar on-device model): obvious shoe, obvious personal, unsure. Personal is decided here and stays local.
- Cloud pass (Gemini, existing SACC setup) only for shoe-positive and unsure non-personal photos. Ask: is a sneaker clearly visible, is it identifiable, is a shoebox or label visible and readable, does it look like a store.
- Output classes: `shoe_with_box`, `shoe_no_box`, `personal`, `other`, each with a confidence score and which model decided.
- Low-confidence items go to a quick review queue (reuse SACC's keyboard-driven review UI pattern if practical).
- Before the full run, have Nitty hand-label a few hundred photos and measure accuracy on them. Use batch mode for cloud calls if available. Log cost per run.

**Step 5: Rename and connect**
- Rename convention is not decided. Propose one and get Nitty's approval. Suggested starting point: `YYYY-MM-DD_HHMMSS_<shortid>.<ext>`, with the original filename kept in the manifest and database.
- Add records to the SACC database: final date, account (1 or 2), classification, confidence, file hash, original path. Shoe identification (style code, model) is a later step and is out of scope here.

**Step 6: Account 2**
- Same code, new input path. Compare results with Account 1 and fix gaps.

## 5. Working with Nitty

- He dictates, so expect run-on messages. Ask one clear question at a time and keep replies short.
- He wants minimal manual file handling. Do the setup work yourself; do not hand him steps that make him move or rename files.
- Every doc or spec you produce for this project should be saved in two places: locally in the SACC repo docs folder, and as a backup in his Google Drive root. If you cannot reach Drive, tell him and give him the file to place.
- Other agents (Claude Code) may also work in this repo. Check git status and recent commits before starting, work on a branch, and keep commits small so the agents do not collide.

## 6. Open questions to ask Nitty (only when the step needs the answer)

1. Exact NAS path and mount status (you will find this yourself if mounted)
2. Which Google account each zip batch belongs to
3. Rename convention
4. How to treat screenshots, memes, GIFs, and live-photo clips (own bucket, or "other")
5. How strict "identifiable shoe" should be for the practice run
6. Which machine this runs on, and whether the NAS is reachable from it

## 7. Report back after Step 0

Short summary only: where the zips are, sizes, free space, file counts by type, date range, sidecar match rate on the 200-file sample, and anything strange. Then wait for Nitty's go-ahead.


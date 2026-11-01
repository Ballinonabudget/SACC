# SACC Takeout discovery — 2026-10-29

Discovery only. No source media, ZIPs, metadata, filenames, or SACC databases were changed. No photos or videos were uploaded to any API. ZIP media was not extracted. JSON sidecars were read locally into a separate resumable audit cache.

## Main export

- NAS: `/Volumes/The Final Cut X` (Synology SMB share).
- Export folder: `/Volumes/The Final Cut X/Google Photo (Denivic)`.
- Batch: `takeout-20230401T201259Z`, parts **001–038**, contiguous numbering. Account identity is unconfirmed; the folder label is not proof of a Google account.
- ZIP size: **408,054,477,570 bytes (380.03 GiB)**. Declared uncompressed payload: **407,999,247,510 bytes (379.98 GiB)**.
- All 38 central directories and all 91,804 Google Photos JSON documents were readable; JSON reads passed ZIP CRC checks. Full media payload integrity has not been tested.
- Completeness is unverified: every found part is near the 10 GiB split target, 5,258 sidecars have no resolved media partner, and a 156,760,935-byte `Unconfirmed 783334.crdownload` also exists. These observations do not prove a missing part.

## Counts across the 38 ZIPs

Google Photos scope only; album copies are included and have not been deduplicated.

| Type | Count |
|---|---:|
| Photos, GIFs, and RAW images | 73,349 |
| Videos | 14,632 |
| Total recognized media | 87,981 |
| Per-media JSON sidecars | 91,781 |
| Other Google Photos JSON documents | 23 |
| Unclassified `.MP` file | 1 |

| Extension | Count |
|---|---:|
| `.3g2` | 36 |
| `.3gp` | 31 |
| `.arw` | 6 |
| `.avi` | 5 |
| `.dng` | 14 |
| `.gif` | 62 |
| `.heic` | 6,535 |
| `.jpeg` | 1,535 |
| `.jpg` | 60,784 |
| `.json` | 91,804 |
| `.m4v` | 10 |
| `.mov` | 12,647 |
| `.mp` | 1 |
| `.mp4` | 1,900 |
| `.mpg` | 2 |
| `.nef` | 260 |
| `.png` | 4,150 |
| `.tif` | 1 |
| `.tiff` | 1 |
| `.webp` | 1 |
| `.wmv` | 1 |

All ZIP payloads together have 183,192 file entries. The additional 3,406 entries belong to Google Voice; they are outside the photo recovery scope.

## Dates and matching

- All 91,781 per-media sidecars contain parseable `photoTakenTime` timestamps. Upload `creationTime` was not substituted.
- Earliest: **1962-10-08 21:57:19 UTC**. Latest: **2022-12-26 17:27:31 UTC**.
- The two 1962 records describe MP4 videos and need human date review. Five sidecars are dated before 2005 (two in 1962, three in 2000). Do not silently correct or assume these are camera capture dates.
- The export includes substantial 2021 and 2022 material; the pre-2020 assumption is false for this batch. Only two sidecars carry a 2019 date, another coverage anomaly to review.
- Full-set uniquely resolved matches: **86,523 / 87,981 media entries (98.34%)**.
- **1,458 media entries lack a uniquely validated sidecar match**; **5,258 media sidecars lack a resolved media partner**. These are unresolved counts, not proof of absence: unusual/truncated names, conflicts, and missing files still need investigation. All 75 `-edited` names are among the unresolved media.
- Deterministic 200-file sample (seed `20261029`): **200/200 matched (100%)**, all with a parseable capture date. 180 used a direct filename pair, 19 needed duplicate-suffix repositioning, and one needed a colon-to-underscore title check. This measures structural matching, not visual or historical-date accuracy.
- Across the full set, 9,066 matches needed duplicate-suffix repositioning, 79 had observed title-character substitutions (`:`, `&`, or apostrophe to underscore), and 34 used an exact title within the same folder. No fuzzy or cross-album matching was used.
- **52,480 matched pairs span different ZIP parts**. Matching ZIPs independently would produce many false missing-sidecar reports.

## Existing extracted copies

- NAS `Google Photo (Denivic)/Takeout`: 4,682 files, 10,736,762,626 bytes. Its paths and file sizes exactly match ZIP **004**; this is not a complete extraction. It has 1,750 photos, 349 videos, and 2,583 sidecars. Standalone sample match rate: 117/200 (58.5%), illustrating the missing cross-part context.
- NAS `Google Photo (Denivic)/Takeout 2`: empty.
- Home `Library/Mobile Documents/com~apple~CloudDocs/Takeout`: 8,274 files, 10,737,448,178 bytes. Its paths and sizes exactly match ZIP **001**. No byte-hash equivalence was asserted. The local content-read attempt stalled on an iCloud JSON file and was stopped; a complete filename/size inventory was obtained instead.
- NAS `Miscel/Google Takeout test/2023-04-06-14h09-demo/Takeout`: 219 files, 170,234,599 bytes (86 JPG, 6 PNG, 1 GIF, 3 MP4, 4 MOV, 30 MP3, 88 HTML, 1 VCF); no JSON sidecars. Existing demo output, kept separate.
- Repo `var/takeout/restored/Takeout`: 12 pre-existing restored images (11 JPG, 1 JPEG), 21,406,031 bytes. These are existing outputs, not a new account batch.

## Other local ZIPs

| Path | Bytes | Contents |
|---|---:|---|
| `/Users/daplug/Downloads/takeout-20261008T204123Z-1-001.zip` | 2,123,247 | 122 YouTube playlist CSVs and 5 JPGs |
| `/Users/daplug/ArchiveTrial/objects/accounts/1/metadata/takeout-0e5b9eb30e0c7b84ba359d157d60b610efa9f9facf3e7296a86c8e58719bafe2.zip` | 2,123,247 | Same member paths/counts/sizes as the YouTube ZIP; byte identity not asserted |
| `/Users/daplug/Downloads/takeout-20261008T235534Z-001.zip` | 57,411 | One `archive_browser.html` file |

None contains a Google Photos export. A distinct second photo-account batch was not identified.

## Free space

Snapshot after the audit; values rounded. A full extraction needs approximately 380 GiB before recovery copies, quarantine, and later outputs.

| Volume | Free |
|---|---:|
| Mac internal | 0.66 TiB (679 GiB) |
| Sam Tsung | 0.70 TiB (713 GiB) |
| Synology | 2.04 TiB (2088 GiB) |

## Every NAS ZIP part found

All names are under `/Volumes/The Final Cut X/Google Photo (Denivic)/`.

| Archive | Bytes | File entries |
|---|---:|---:|
| `takeout-20230401T201259Z-001.zip` | 10,738,855,268 | 8,274 |
| `takeout-20230401T201259Z-002.zip` | 10,739,982,747 | 13,449 |
| `takeout-20230401T201259Z-003.zip` | 10,739,234,340 | 9,978 |
| `takeout-20230401T201259Z-004.zip` | 10,738,237,185 | 4,682 |
| `takeout-20230401T201259Z-005.zip` | 10,738,183,139 | 4,472 |
| `takeout-20230401T201259Z-006.zip` | 10,738,731,660 | 7,417 |
| `takeout-20230401T201259Z-007.zip` | 10,739,893,915 | 13,404 |
| `takeout-20230401T201259Z-008.zip` | 10,738,867,430 | 8,246 |
| `takeout-20230401T201259Z-009.zip` | 10,738,989,171 | 8,779 |
| `takeout-20230401T201259Z-010.zip` | 10,738,816,462 | 7,809 |
| `takeout-20230401T201259Z-011.zip` | 10,738,394,416 | 5,531 |
| `takeout-20230401T201259Z-012.zip` | 10,737,973,654 | 3,263 |
| `takeout-20230401T201259Z-013.zip` | 10,738,170,352 | 4,176 |
| `takeout-20230401T201259Z-014.zip` | 10,737,940,991 | 3,009 |
| `takeout-20230401T201259Z-015.zip` | 10,737,534,711 | 582 |
| `takeout-20230401T201259Z-016.zip` | 10,737,528,240 | 561 |
| `takeout-20230401T201259Z-017.zip` | 10,737,639,726 | 1,246 |
| `takeout-20230401T201259Z-018.zip` | 10,737,534,161 | 593 |
| `takeout-20230401T201259Z-019.zip` | 10,737,759,623 | 1,965 |
| `takeout-20230401T201259Z-020.zip` | 10,737,780,133 | 2,077 |
| `takeout-20230401T201259Z-021.zip` | 10,737,815,883 | 2,235 |
| `takeout-20230401T201259Z-022.zip` | 10,738,697,175 | 7,161 |
| `takeout-20230401T201259Z-023.zip` | 10,738,175,941 | 4,283 |
| `takeout-20230401T201259Z-024.zip` | 10,737,797,600 | 2,191 |
| `takeout-20230401T201259Z-025.zip` | 10,737,972,336 | 3,122 |
| `takeout-20230401T201259Z-026.zip` | 10,737,914,428 | 2,843 |
| `takeout-20230401T201259Z-027.zip` | 10,738,027,988 | 3,449 |
| `takeout-20230401T201259Z-028.zip` | 10,738,080,369 | 3,730 |
| `takeout-20230401T201259Z-029.zip` | 10,737,912,710 | 2,897 |
| `takeout-20230401T201259Z-030.zip` | 10,738,225,105 | 4,521 |
| `takeout-20230401T201259Z-031.zip` | 10,738,111,261 | 3,915 |
| `takeout-20230401T201259Z-032.zip` | 10,737,851,612 | 2,482 |
| `takeout-20230401T201259Z-033.zip` | 10,737,862,665 | 2,560 |
| `takeout-20230401T201259Z-034.zip` | 10,737,883,636 | 2,764 |
| `takeout-20230401T201259Z-035.zip` | 10,738,123,504 | 4,141 |
| `takeout-20230401T201259Z-036.zip` | 10,738,538,530 | 6,539 |
| `takeout-20230401T201259Z-037.zip` | 10,739,348,521 | 10,957 |
| `takeout-20230401T201259Z-038.zip` | 10,738,090,982 | 3,889 |

## Search scope and audit evidence

Name search completed across the mounted NAS and `/Users/daplug`: 33,886 NAS directories and 105,049 home directories. The NAS search excluded generated Final Cut `Render Files` caches; application `.app` bundles under `Old Black Box` were also excluded. `/Volumes/The Final Cut X/#recycle` was inaccessible (permission denied). Symlink targets were not traversed. These exclusions limit any claim of exhaustiveness. No search was made on `Sam Tsung` because the agreed scope was the NAS and home folder. All **41 Takeout ZIPs found** (38 photo-export parts plus three local non-photo exports/copies) are recorded in `all_takeout_archives.csv`. No additional photo-export ZIP batch was identified. Microsoft Office Takeout Menu templates were name-search false positives, not exports.

Audit data stays local, outside the Git repo:

- `/Users/daplug/Documents/SACC_Data/discovery/2026-10-29/archives.json` — complete ZIP-part manifest, sizes and source mtimes.
- `zip_entries.jsonl` — all ZIP entries, CRCs and sizes.
- `sidecars/` — resumable per-archive JSON cache/status.
- `nas_archives_matches.csv` and `nas_archives_unmatched_sidecars.csv` — per-file matching evidence.
- `nas_archives_sample_200.csv` — reproducible 200-file sample.
- `nas_archives_summary.json` — full summary.
- `extracted_entries.jsonl`, `additional_entries.jsonl` — existing extraction inventories.
- `local_extracted_entries.jsonl` and `local_extracted_summary.json` describe an **incomplete** content-read attempt and are not the complete local inventory; use `additional_entries.jsonl` for that.

Repo tools: `scripts/takeout_read_sidecars.py` supports `--dry-run` and resumes completed archive caches; `scripts/takeout_match_inventory.py` rebuilds audit manifests from those caches and supports `--dry-run` without writing manifests. Both only read source data. Matching was checked against exact-name, suffix-repositioning, ambiguity, and folder-isolation cases; synthetic ZIP checks verified unchanged source bytes and cache resume.

## Stop point

No extraction, metadata merge, quarantine, reorganization, classification, rename, or database import has been authorized by this discovery result. Confirm that the Denivic batch is the intended Account 1 practice export and approve the next recovery dry run before continuing. Resolve archive-completeness questions and review anomalous dates before applying metadata changes.

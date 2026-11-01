# Takeout milestone 1 results — 2026-10-29

The approved first milestone is implemented on `codex/takeout-recovery-m1`:
resumable local importer, recovery manifest, 200-file metadata/GPS dry run,
bounded metadata-copy verification, SACC export contract and store/visit interfaces.
The user-authorized independent Codex reviewer supplied the required design
review; all notes were accepted before implementation. Independent implementation
QA returned **PASS**, with **29/29 tests passing** and no unresolved milestone
implementation defects. Details are in `SACC_TAKEOUT_M1_IMPLEMENTATION_QA.md`.

## Real sample evidence

| Measurement | Result |
|---|---:|
| Sample files, identical to discovery seed 20261029 | 200 |
| Photos / videos | 165 / 35 |
| Sample source bytes staged | 854,916,277 |
| Completed proposals / processing errors | 200 / 0 |
| Selected media source SHA-256 values matched on reread | 200 / 200 |
| Valid UTC photoTakenTime values | 200 / 200 |
| GPS available / selected without conflict | 150 / 200 (75%) |
| Missing GPS | 50 |
| Date conflicts requiring review | 14 |
| Invalid embedded date fields | 16 |
| Files with offset-free embedded time evidence | 187 |
| GPS observations without measured accuracy | 150 |
| Detected format differs from extension | 3 |
| Verified working copies | 12 |
| Completed files reused on resume | 200 / 200 |
| Media uploaded / remote analysis calls | 0 / 0 |

Flags overlap and do not sum to 200. All 200 remain in review because metadata
uncertainty is retained. A valid source timestamp is not proof of historical
correctness. Offset-free embedded times remain wall-clock observations; no
camera timezone was invented. The three extension mismatches contain JPEG data;
they are flagged for review, not silently renamed or declared corrupt.

All 12 real working copies wrote and read back XMP DateCreated and capture-based
mtime. Their existing GPS was retained. Missing-GPS and description injection
were verified against synthetic JPEG fixtures, not asserted as real-sample writes.
HEIC and video embedding remain manifest-only in this milestone. Original ZIP
members and existing extracted sources were not modified.

The manifest registers 38 archives and 87,982 media/unknown occurrences (including
one unknown .MP). Only the fixed 200 recognized sample members were staged or
content-hashed. There are 200 media IDs and 12 persisted copy selections. Resume
did not grow the sample, add duplicate provenance rows, or rewrite completed media.

## Local review artifacts

Private root: `/Users/daplug/Documents/SACC_Data/recovery/milestone1`.

Manifest batch ID:
`2ec7131b299ec7b0667019c7c1307e3c8a96df7d4b91bdeae652c37dc74506a0`.

Under `reports/<batch-id>/`:

- `review.csv`: 200 rows of proposed dates/GPS, source fields, flags, actual staged
  paths, proposed final paths, source-integrity results and copy statuses.
- `recovery.jsonl`: full per-file observations, match evidence, raw values,
  source hashes and readback validation.
- `sacc_payloads.jsonl`: 200 validated versioned envelopes mapped to SACC fields.
- `summary.json` / `summary.md`: aggregate results suitable for backup.

Detailed files, coordinates and all media remain local. Only sanitized engineering
docs and aggregate results are backed up to Drive. SQL state is in
`recovery.sqlite3`. Commands, schema mapping, privacy defaults, resume/error
semantics and rollback are in `SACC_TAKEOUT_M1_RUNBOOK.md`.

## Store/visit validation and limitations

Synthetic tests distinguish nearby Nike/adidas, distant Nike branches, multiple
mall retailers, historical versions and unknown dates. A confirmed mixed photo/
video visit retains its shared store after paths change to Photos and Videos.
Transitions create separate stops. No-GPS inheritance requires reviewed membership;
revoked or disputed evidence invalidates transitive reused assignments. No store
pin is written to observed GPS. Conflicting album/export observations remain
separate and block automatic grouping.

The real store directory is not supplied. Candidate coverage, reviewed store
accuracy and cross-store error rates are therefore **not evaluated**, with null
values and explicit denominators in the report. No live Outlet Plug integration
or real branch-coordinate mapping is claimed. The current 196 proposed stops use
only the sparse sample; they are not a complete real-visit reconstruction.

Account identity and export completeness remain unconfirmed. Full archive byte
integrity has not been checked; source-integrity evidence covers the selected
uncompressed members plus size/mtime and central-directory checks of all 38 ZIPs.
Historical anomalies such as the known 1962 videos are not guaranteed to appear in
the random sample; fixture tests exercise suspicious-date handling separately.

## Next approval gate

Review the per-file dry-run flags, especially the 14 date conflicts, invalid date
values, format mismatches and missing GPS. Confirm account identity and intended
export scope before approving a separate full-library recovery capability/run.
No full extraction, full metadata rewrite, quarantine, final rename, personal
classification or live SACC database import has run. Shared IDs and extension
records prepare those later stages without coupling recovery to shoe identification.

## Final verification

The final audit validates 200 JSONL records, 200 CSV review rows and 200 SACC
envelopes. SQLite integrity check is `ok`, with zero foreign-key errors. Source
verification and copy readback evidence remain in the private manifest. All 67
pre-existing working-tree files match the baseline SHA-256 snapshot. No changes
were made to live DB/API/watcher/cloud code or Outlet Plug. New implementation
files passed whitespace and Python compilation checks. Changes remain uncommitted
on the milestone branch so the existing dirty tree is preserved for review.

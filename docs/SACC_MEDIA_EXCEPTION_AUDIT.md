# Media exception investigation — November 2, 2026

The 15 outstanding triage failures have been investigated. This was local
forensic inspection using existing tools, with no application or catalog changes.
The failed records remain visible and their effective privacy remains unknown.

## Results

| Items | Finding | Available local working material |
|---|---|---|
| 12 Sony JPEGs | Damage already exists in the original Takeout members; recovered compressed image data is identical | 160x120 embedded thumbnails only |
| 2 Sony RAW files | Current Pillow decoder does not support these files; native local rendering succeeds | 1920x1080 embedded previews and 6000x4000 JPEG renders |
| 1 `.MP` file | Short HEVC video missed by extension-based media typing | Byte-identical MP4 working copy and a decoded frame |

For the JPEGs, ZIP CRC and the original source hashes recorded during recovery
match. Both strict Pillow and strict libjpeg decoding fail on the originals and
recovered objects. Bytes from the first JPEG scan marker to EOF are identical;
the sources contain large zero-filled tails and lack an end-of-image marker in
that payload. These are not merely unsupported files. Loading truncated images
must not be used to clear their integrity warnings. No healthy alternatives were
found through exact-name/media-hash and filename-stem catalog searches; this does
not exclude better originals in other backups.

For the RAW files, extracted source hashes equal the recovered hashes. Separate
native renders pass strict JPEG decoding. Existing counterparts with matching
stems and capture times contain JPEG data under `.ARW` names. Those counterparts
and the native renders are not proof of full RAW sensor-data integrity.

For the `.MP` file, both video streams decode without error. The primary stream
is 1920x1080 and about 0.998 seconds long. A likely same-stem still-photo companion
exists, but no automatic association was made. A single frame cannot establish
whole-video privacy.

## Private evidence and operator review

All artifacts are outside the repository in:

`/Users/daplug/Documents/SACC_Data/library/media-exception-audit/2026-11-02/`

- `review.html`: offline page with 15 local preview cards; no mutation controls.
- `README.md`: detailed findings and next actions.
- `results.json`: source comparisons, decoder outcomes and derivative provenance.
- `baseline.json`: before-inspection catalog/ledger hashes and file identities.
- `alternate-candidates.json`: bounded search for other catalog representations.
- `source-copies/` and `previews/`: local inspection material; keep private.

These files can contain personal imagery and metadata. No media was uploaded or
viewed through a cloud service. No new privacy decisions, triage results, layout
links, organization applies or production promotions were recorded.

## Validation and follow-up

Catalog and recovery-ledger SHA-256 hashes are unchanged. All 15 recovered hashes
and file identities are unchanged. The three source ZIP identities are unchanged;
the whole ZIP files were not rehashed. All gallery references exist locally and
the page has no remote URLs. No application code changed or unit tests reran.

Operator review can now use the private previews. Preserve the JPEG warnings and
look for better originals in other authorized local sources. Supporting RAW
preview derivatives and recognizing `.MP` video in production is a separate
engineering increment requiring the repository's design and Anti-Gravity review
process. No implementation approval or cross-agent QA is claimed by this report.

# Full-recovery runner — 2026-10-31

The local runner is implemented separately from the capped milestone commands.
Python and ExifTool perform the work; no model/API calls are required. The full
Denivic run has not been approved or started. Final implementation QA is recorded
separately in `SACC_TAKEOUT_FULL_RECOVERY_IMPLEMENTATION_QA.md`.

## Current prepared plans

| Scope | Root | Files / source bytes |
|---|---|---:|
| Completed existing-sample pilot | `/Users/daplug/Documents/SACC_Data/recovery/denivic-pilot` | 12 / 36,311,250 |
| Unapproved ZIP recovery plan | `/Users/daplug/Documents/SACC_Data/recovery/denivic` | 87,982 / 407,786,951,500 |

Full plan ID:
`d470c73c64ceea445e682cfe973216c70e35a05242d9ec157c43247b601b72f0`.
Pilot plan ID:
`c19c5d78f5465a0b4d31e0f0e01435ea46ad1f01ea765e28df4be63a2d7a7a68`.

The full source is the 38-part Denivic export already registered in the milestone
manifest. Source occurrence IDs, original hashes/account identities, album paths
and complete review/dependency snapshots are retained. No file selection grows
on retry. The output roots are local and outside the source, repo and watched/cloud
folders. Planning requires a new empty root; existing plans are never overwritten.

## Commands

Run from `/Users/daplug/Documents/SACC`. Inspect the prepared plan without payload
reads, approval changes or database initialization:

```sh
.venv-poc-313/bin/python scripts/takeout_recovery.py full-status \
  --output /Users/daplug/Documents/SACC_Data/recovery/denivic
```

For another export, `full-plan --source-root <existing-milestone-root> --batch
<manifest-batch-id> --output <new-root>` registers metadata-only ZIP recovery.
`--mode pilot --source-kind sample --max-files 12 --max-bytes 134217728` instead
selects a fixed bounded subset of already source-verified staged samples. These
caps are cumulative across invocations. A pilot cannot authorize full mode.

`full-approve` records an actual human decision with exact `--plan-id`, `--scope`,
`--reviewer` and `--evidence`. Planning and execution never create approvals
implicitly. The full plan has no approval receipt: do not add one until Nitty has
reviewed and approved this concrete scope and the pilot/QA results.

After that approval is separately recorded, `full-run` requires exact plan ID and
explicit `--scope full` (or `pilot` for the bounded pilot). Repeat the same command
to resume; it validates existing outputs rather than overwriting them. Optional
`--max-items N` pauses after N item phases in that invocation, without changing
selection. Ctrl-C preserves progress. Exit2 means paused/failed work; inspect
`full-status` and local reports. No GUI is included in this increment.

`full-report --plan-id <id>` exports a committed metadata snapshot. `full-refresh-reviews
--source-root <same-milestone-root> --plan-id <id>` appends a complete updated review
projection without changing processing scope or media bytes. Identical review
content is a no-op. Refresh activation and conflict/dependency invalidation are
atomic, space-checked, and roll back together on failure.

## Processing and output

First stream/hash/check all selected media, read original matched sidecars and
embedded tags, and publish owned raw copies as source-verified-only. Then reconcile
all original-hash groups and existing evidence before allowing metadata writing.
These are two logical passes through one managed tree, not two library extractions.
The worker initially uses one active item and at most two ZIP handles.

JPEG/PNG writers restore eligible XMP capture dates and missing GPS/description,
preserve existing fields/pixels, set capture mtime and read back written fields.
Conflicts retain unchanged copies for review. Video, HEIC, GIF and RAW embedding
remain manifest-only; their bytes and canonical metadata are retained. This runner
does not set a new capture mtime for unsupported/held files. A manifest-only outcome
is not a failed extraction or a successful embedded-metadata rewrite.

Source ZIPs never open writable. New ZIP recovery streams each member once with
CRC/SHA and validates copied bytes; it does not claim a separate original-member
reread or whole-archive byte hash. The existing-sample pilot instead rechecks the
already staged bytes against recorded original SHA values. Its JSON packages are
clearly labeled canonical snapshots, not exact original JSON bytes. Synthetic
cross-part ZIP tests exercise exact source-JSON packaging.

- `plan.json`: immutable scope, input fingerprints, tools/policy, capacity and digest.
- `recovery-run.sqlite3`: separate versioned progress, attempts, cumulative read
  reservations, source observations, review snapshots and durable publication intents.
- `objects/`: retained working copies named by occurrence ID; final Finder naming
  and Photos/Videos folder organization are later modules.
- `metadata/`: original ZIP JSON or explicitly labeled pilot canonical snapshots.
- `reports/snapshot-<watermark>-v<review-version>/`: streamed `recovery.jsonl`,
  `review.csv`, `sacc_payloads.jsonl`, `unsupported.jsonl`, and `summary.json`.
- `report.json` / `report.md`: latest committed report pointer and short status.

Output path/size/MIME in each SACC envelope refer to the retained published file.
Unknown formats are retained in canonical records/unsupported reports rather than
inventing an image/video type. No fake shoe IDs or live imports are permitted.
All media remain privacy unknown/local and remote-ineligible. Screenshots retain
the existing explicit-review exemption from missing-GPS requirements.

## Failure and resource behavior

Candidates have durable owned publication intents before final rename. Recovery
validates expected hashes, tags, mtime and ownership before adopting interrupted
outputs. Changed completed files are preserved and blocked for inspection. Only
registered transient directories may be cleaned up. A post-commit cleanup failure
is recorded as cleanup-pending; it does not downgrade a successfully published
file. Resume retries cleanup only. No quarantine or source deletion.

Update 2026-10-31: expected-tag candidate readback mismatches now retain the raw
file unchanged in review and continue the batch, after verifying raw and sidecar
integrity. Exact failure evidence and separate report counts remain available for
a later reviewed repair pass. See `SACC_TAKEOUT_READBACK_DEFERRAL.md`. They are not
counted as successful writes. Other source/metadata errors still stop.

Other source/metadata errors stop at a retryable boundary; the entire selected source
pass must complete before metadata writes. Up to three attempts per item/phase
and an immutable source-read budget prevent unbounded retries. An exhausted budget
requires inspection rather than silently extending the plan. Datetime/GPS conflicts
are review outcomes, not fabricated corrections.

The full plan budgets 487,933,445,802 bytes (454.42 GiB), including a 50 GiB reserve,
temporary candidates, measured ledger baseline and metadata/report allowance.
This is an estimate, not a reservation or maximum output size. Actual allocation,
SQLite/journal growth, remaining payload, metadata buffers and tool output/timeouts
are bounded/checked. ENOSPC pauses safely; reports may defer while status remains
available from the ledger. Recheck free space at execution; a changed ExifTool
version, input fingerprint or plan requires a new reviewed plan.

Later duplicate conflicts invalidate effective projections/dependent confirmations
without rewriting historical published bytes. Review refreshes do not expand the
selected account/export scope. Detailed names, GPS, media and ledgers stay local;
only sanitized docs and aggregate results are backed up to Drive.

## Validation and remaining scope

Run `.venv-poc-313/bin/python -m unittest discover -s tests -v`. Final validation:
78 tests passed and independent implementation QA returned PASS. Tests cover actual
JPEG/PNG roundtrips, bounded simulated5+GiB and small real ZIP64 streams, approvals,
crash boundaries, output tampering, both ENOSPC phases, duplicates, unknown formats,
review refresh/dependency revocation, preserved sources and capped original APIs.
Large real NAS video throughput has not been measured by the staged-copy pilot.

No final naming, folder organization, classification, shoe API calls, actual store
assignments, live SACC schema/search integration or Outlet Plug changes occur here.
Stop/retain the isolated output for rollback; originals and live databases require
no reversal.

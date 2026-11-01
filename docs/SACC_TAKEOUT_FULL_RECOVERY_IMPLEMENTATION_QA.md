# ANTI-GRAVITY IMPLEMENTATION QA — full-recovery runner

Date: 2026-10-31. Reviewer: independent Codex agent, using Nitty's authorized
substitution for Anti-Gravity. This is independent implementation QA, not an
actual Anti-Gravity session. Review covered the approved/reconciled full-recovery
design, implementation, synthetic tests, runbook/results and sanitized pilot
proof. No private media or detailed real records were inspected. No implementation,
Outlet Plug, original media or live SACC database was changed by this reviewer.

## Result

**PASS.** The reviewed runner and bounded existing-sample pilot satisfy the
approved implementation scope. All identified code defects were corrected and
retested. This result does **not** approve or execute full-library recovery.

The full plan remains unapproved: `87,982` pending occurrences,
`407,786,951,500` planned uncompressed media bytes, zero reserved source reads and
zero completed items in the inspected aggregate proof. Its exact plan ID is
`d470c73c64ceea445e682cfe973216c70e35a05242d9ec157c43247b601b72f0`.
Nitty's approval of that concrete scope after pilot/QA review remains required.

## Requirement coverage

- Separate immutable plan and progress ledger preserve the original milestone
  limits. Exact plan/scope approval is checked before execution; pilot approval
  cannot authorize full mode, and retries cannot expand the persisted selection.
- Metadata-only planning/status do not read payloads or approve work. Source
  account, occurrence/media identities, original paths, review evidence and full
  confirmation/revocation dependencies survive working-folder changes.
- Two logical passes publish source-verified raw copies first, reconcile complete
  original-hash groups and existing observations, then embed only eligible copies.
  Conflicting sidecars do not silently select a winner. Later conflicts invalidate
  effective projections while preserving previously published bytes.
- Owned publication intents, hash/size/mtime checks and directory/ledger durability
  support crash adoption. Unexpected or changed outputs are retained and blocked.
  Deferred transient cleanup does not downgrade or replay committed media state.
- Streaming, bounded ZIP handles/tool output, cumulative attempts/read reservations,
  measured ledger overhead and runtime allocation/free-space checks cover the
  approved resource controls. Source and metadata ENOSPC preserve recoverable work.
- JPEG/PNG writers preserve originals, validate writes and retain existing fields.
  Unsupported or conflicting media remain local with canonical metadata and an
  explicit review outcome. No inferred store location is written as observed GPS.
- SACC v1 exports use the actual final path, size and supported MIME/type, with
  original provenance separate. Unknown formats remain in canonical/unsupported
  reports. Live import/search integration and later classification are outside
  this runner's scope; no fake shoe identities or automatic store assignments arise.
- Atomic review refresh preserves complete evidence, applies duplicate/dependency
  invalidation together, respects screenshot policy and leaves source/media bytes
  unchanged. Identical review content is a byte-preserving no-op.

## Tests performed

Independently ran:

```sh
.venv-poc-313/bin/python -m unittest discover -s tests -q
```

**78 tests passed in 8.466 seconds:** 44 prior milestone/screenshot/trip tests,
11 new I/O tests and 23 new runner tests. `git diff --check` also passed.

Coverage includes actual synthetic JPEG/PNG ExifTool date/GPS/description
roundtrips, preservation of pixels and existing fields, synthetic cross-part ZIP
recovery and exact sidecar bytes, small real ZIP64 entries, bounded tool output
and timeouts, EOF monitoring, immutable approval/caps, both publication phases and
crash boundaries, changed inputs/outputs, unknown formats, both ENOSPC phases,
duplicate conflicts, source preservation, report idempotence and review graphs.

Additional independent temporary-fixture probes passed:

1. Injected reconciliation failure during refresh rolled back active version/hash,
   copied rows, events and invalidations together.
2. Capacity failures during snapshot copy and after reconciliation/precommit both
   rolled back the same complete state. Successful retry activated conflicts.
3. Two identical refreshes preserved ledger SHA-256, row/event counts, original
   source-manifest SHA and published output hashes.
4. A one-item pilot with twenty prior observations containing 30,000-character
   descriptions measured over 1 MiB of copied ledger history and completed within
   its revised capacity budget.
5. Four injected postcommit cleanup failures across source and metadata phases
   left both fixture items complete. Resume cleaned only transients while source
   reads and metadata writes were patched to fail; final hashes/results and
   cumulative read accounting remained unchanged.

## Problems found

Resolved and retested during review:

- Tool capacity monitoring stopped when output pipes closed before process exit.
- Small pilot allowance omitted the potentially much larger copied review history.
- Review refresh could activate a snapshot before conflict reconciliation committed.
- Refresh lacked bounded growth checks and could append unchanged snapshots.
- Postcommit cleanup failure could downgrade valid metadata output into a retry
  expecting the former raw hash; cleanup-pending recovery now performs cleanup only.

Incomplete source dependency graphs also fail closed under the added foreign-key
validation and regression test. No remaining implementation blocker was found.
The results wording was corrected to avoid equating eleven successful metadata
writes with eleven newly recovered GPS readings.

## Data issues

The following real-run evidence comes from inspection of the engineer's sanitized
`/Users/daplug/Documents/SACC_Data/recovery/milestone1/full-build-pilot-proof.json`.
It was not established by opening or rerunning private per-file media in this QA.

| Pilot measurement | Inspected result |
|---|---:|
| Persisted existing staged items | 12 |
| Source bytes rechecked against recorded SHA | 36,311,250 |
| JPEG metadata write/readback successes | 11 |
| Video retained with manifest metadata | 1 |
| Processing errors | 0 |
| Initial duration | 3.985 seconds |
| Selected GPS observations | 10 / 12 |
| New original-ZIP payload reads | 0 |
| Remote calls / live imports / new store assignments | 0 / 0 / 0 |

Pilot plan ID:
`c19c5d78f5465a0b4d31e0f0e01435ea46ad1f01ea765e28df4be63a2d7a7a68`.
Resume retained twelve terminal items, unchanged cumulative read reservations and
the same report snapshot. The proof records all twelve original staged-file hashes
and mtimes unchanged, 67 pre-existing working files unchanged, and original
milestone manifest SHA unchanged:
`ab9be9686ac790ea87ea50dc544f429eac80fd40525682f32253d6611f7675b1`.

Metadata write/readback success does not establish fresh GPS insertion, historical
date correctness or branch accuracy. The pilot reports two missing-GPS items,
one date-conflict flag and one invalid-embedded-date flag; reason counts overlap.
Real branch accuracy remains unmeasured. Existing evidence is retained for local
review, and personal/uncertain media remain remote-ineligible.

## Edge cases

The staged-copy pilot establishes neither original-ZIP/NAS throughput nor real
multi-gigabyte video performance. The greater-than-5-GiB test drives the bounded
streaming algorithm with synthetic reader/sink/hash substitutes; the real ZIP64
fixture is small. Original JSON byte packaging and PNG embedding were tested with
synthetic fixtures. Pilot JSON files are explicitly canonical snapshots, not
reconstructed original sidecar bytes. Video/HEIC/RAW embedding remains disabled.

The full plan's measured budget is `487,933,445,802` bytes (about 454.42 GiB),
including reserve and temporary/metadata overhead. This is an estimate rather than
a reservation. Runtime space checks, source fingerprints and tool-version checks
must still pass when an approved execution starts. Whole ZIP byte hashes are not
claimed; full mode uses member CRC/SHA verification during one source stream.

## API/cost issues

No network/model/provider dependency is introduced. Inspected pilot and full-plan
aggregates record zero remote calls and live imports. Tool duration/output and
metadata buffers are bounded; a full run still requires local disk and processing
time whose real NAS throughput has not been measured here.

## Regression concerns

The prior 44 tests remain passing. This reviewer changed only this QA document;
pre-existing dirty changes and original milestone outputs were left untouched.
The 67-file preservation claim is the inspected engineer-provided aggregate proof,
not an independent rehash of those files in this final QA. Store/visit behavior is
preserved as snapshot/projection data; no live database migration or search import
was tested or represented as complete.

## Recommended fixes

No further code fix is required for the reviewed scope. Present the exact full
plan, pilot evidence and these limitations for the outstanding execution decision.
Preserve local review outcomes and unsupported-format distinctions in that report.

## Retest required

**NO** for this frozen implementation. New code, changed source/tool identities or
material scope changes require appropriate validation. Full-run approval remains
a separate gate and is not granted by this QA result.

## Reviewed source identity

SHA-256 of the frozen implementation and new test files:

| Repository-relative file | SHA-256 |
|---|---|
| `sacc_takeout/full_recovery.py` | `ce5783f7929d99f12d72606919c12f85a96b2b452d1cc06d1d3f6397c6427755` |
| `sacc_takeout/recovery_store.py` | `981a87b34301ad61cc26bd2de8d384bbd5c886ac84c5a74331d71ac2309b9c95` |
| `sacc_takeout/recovery_io.py` | `4c1f7131f5972af9cfbd3f8756417a7d25935cc3f5102812f63d75af0513c6bb` |
| `scripts/takeout_recovery.py` | `10bfb867637370795553a04d70490edeaae15af9f4d961564181a08db2a80c46` |
| `tests/test_takeout_full_recovery.py` | `0b3d568fb73b8e9ab27daf2263fadb13c10a3c7f8ebe0e45df96b83b8ebe3b9b` |
| `tests/test_takeout_full_io.py` | `c54d7846798b5486e98a72ef9f324fb6775ddfee852fc4ce72db97de035b95e1` |

Aggregate digest:
`fda9a3d61d69ed4678ce1d0ad33e27f493e32a0e34ec25b959c541ea318da6d1`.
Exact formula: construct `hashes` mapping the six relative path strings above to
their lowercase SHA-256 hex strings, then compute
`hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()`.
No newline is appended; the aggregate excludes this QA document.

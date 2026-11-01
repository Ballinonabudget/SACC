# SACC Takeout milestone 1 preflight (historical)

This records the initial pre-implementation checks. The completed milestone is
reported in `SACC_TAKEOUT_M1_RESULTS.md`; the initial review blocker was resolved
through Nitty's explicit independent-reviewer authorization.

2026-10-29. Branch: `codex/takeout-recovery-m1`.

## Completed

Read the requested plan/start prompt, build order, discovery report, recovery
handoff, CLAUDE.md, and both operating/cross-check manuals. No applicable
AGENTS.md was found in the repository or its ancestor directories.

Prepared `docs/SACC_TAKEOUT_M1_DESIGN.md`: proposed resumable importer, local
SQLite/JSONL recovery manifest, stable media/branch/visit IDs, read-only historical
store directory contract, SACC integration mapping, modular stage extensions,
metadata conflict policy, rollback and acceptance checks.

Recorded fingerprints for 67 pre-existing working-tree files in a separate local
audit file. Existing uncommitted changes remain in place. No source media or live
database writes, extraction, metadata recovery, rename, quarantine or cloud media
analysis occurred.

## Read-only checks

| Check | Result |
|---|---|
| Existing suite: `.venv-poc-313/bin/python -m unittest discover -s tests -v` | 12 passed |
| Existing inventory matcher in `--dry-run` mode | Reproduced discovery counts |
| Media entries / unique structural matches | 87,981 / 86,523 |
| Matches across ZIP parts | 52,480 |
| Selected sample structural matches | 200 / 200 |
| Sample composition | 165 photos, 35 videos |
| Sample uncompressed bytes | 854,916,277 (about 815 MiB) |
| Sidecars with valid nonzero GPS fields | 150 / 200 (75%) |
| Available local space at check | About 679 GiB |
| ExifTool | Installed, version 13.55 |
| 38 archive size/mtime fingerprints vs discovery | All unchanged |
| 38 cached sidecar status fingerprints | Complete, no recorded errors, match current size/mtime |
| Live ZIP central directories vs discovery | All 179,786 Google Photos entry paths/sizes/CRCs match across 38 ZIPs |

The GPS count is a sidecar preflight count, not verified recovered GPS. It does
not compare embedded image/video coordinates or prove geographic accuracy.
Archive size/mtime checks do not prove full byte identity. Source-byte hashing
and metadata readback belong to the implementation's forthcoming dry run.
No 200-file metadata/GPS recovery report has been produced yet.

A synthetic read-only probe found an existing matcher ambiguity: competing
suffix-repositioned and direct sidecars can be reduced to one by exact-title
fallback. The new importer must preserve that conflict for review. This is
documented in the design and has not been patched before design approval.

## Review blocker and unresolved items

Anti-Gravity opens to a first-run terms/data-use consent screen. No consent was
given. Nitty subsequently authorized an independent Codex review agent as its
substitute, and that review is underway. The repo requires an APPROVED or
APPROVED WITH NOTES design review and reconciliation before implementation.

The batch account identity and completeness remain unconfirmed. A real historical
store-directory export is not yet supplied. These do not block coding after review;
use a provisional account identity and clearly synthetic location fixtures. Real
store accuracy and cross-store error rates cannot be claimed without ground truth.

Full-library extraction/recovery, live database import, quarantine and final names
remain gated on a completed dry-run report and explicit user approval.

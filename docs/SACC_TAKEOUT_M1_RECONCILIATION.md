# Review Resolution

2026-10-29. Independent Codex review was explicitly authorized by Nitty as the
Anti-Gravity substitute. Decision: APPROVED WITH NOTES; see
`SACC_TAKEOUT_M1_DESIGN_REVIEW.md`. This note precedes implementation.

- Accepted feedback: all review notes. Persist one immutable sample/configuration
  per account/batch before staging; no seed/limit changes may increase its scope.
  Reread selected sidecars from the ZIP, compare cached JSON, retain SHA-256 and
  CRC evidence. Keep competing structural sidecar candidates unresolved. Reject
  boolean/malformed/non-finite metadata explicitly. Verify all written tags and
  trustworthy recovered-copy UTC mtime; preserve source bytes/timestamps. Separate
  proposed final paths from actual staged/copy paths. Preserve export/album
  provenance and distinguish path comparison from sampled hash evidence.
- Rejected feedback: none.
- Reason for rejected feedback: not applicable.
- Final implementation plan: isolated local package and CLI; private SQLite and
  JSONL manifest; bounded dry-run sample; separately bounded 12-copy verification;
  conservative store/visit model and synthetic tests; no live database/API changes.
  Default privacy is unknown, remote eligibility false. Invalidate transitive
  confirmation/assignment dependencies on revocation. No-GPS inheritance requires
  explicit confirmed membership evidence. Report real measurements separately from
  synthetic fixture outcomes and unavailable store ground truth.
- Remaining risks: account identity and export completeness are unconfirmed;
  no approved historical store directory is supplied. Raw private paths, metadata,
  coordinates, and media stay local. Only engineering docs and aggregate reports
  are backed up to Drive. Full recovery, live import, quarantine and final naming
  still require review and explicit approval of the completed dry-run results.

Coding authorization checklist: requirements/repo/working tree/current architecture,
proposal/review/reconciliation, database/API impact, tests and rollback all reviewed.
No Outlet Plug changes are planned. Existing dirty files remain untouched.

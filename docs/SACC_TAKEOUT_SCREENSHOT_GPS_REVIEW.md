# ANTI-GRAVITY DESIGN REVIEW — screenshot GPS exception

Date: 2026-10-30. Reviewer: independent Codex review agent, using Nitty's explicit
authorization to substitute for Anti-Gravity. No private media was inspected.

## Decision

**APPROVED WITH NOTES.**

The narrow report/export exception implements the user's request without changing
source observations or expanding the recovery scope. Record the reconciliation,
then proceed. No new user decision is needed before implementing this change.

## What looks correct

- Only explicitly confirmed screenshots lose the missing-GPS requirement.
  PNG format, missing coordinates, names and dimensions are not classifiers.
- The projection preserves actual coordinates, invalid/conflicting GPS flags,
  capture-time checks, other metadata warnings and privacy defaults.
- Append-only local review evidence and a reversible projection avoid rewriting
  original recovery observations or rerunning the 200-file sample.
- Existing all-media coverage stays intact; expected-GPS coverage is a separate
  measure. No real sample screenshot is asserted without review evidence.

## Missing requirements

No architectural requirement is missing. Make the following concrete in code and
tests so the stated reversibility and reporting semantics hold:

1. Each new human decision needs its own append identity, including a true → false
   → true sequence with the same reviewer/evidence/version. Existing
   `add_stage_result` hashes the complete payload and uses INSERT OR IGNORE, so
   replaying the original true payload would otherwise leave false as the latest
   decision. Use a new decision/event identifier or equivalent monotonic append
   semantics for screenshot reviews, without changing unrelated stage idempotency.
2. Latest means deterministic insertion order. Second-resolution `created_at`
   alone is insufficient when several decisions happen in the same second; use
   an authoritative sequence such as the existing rowid as the tie-breaker.
3. Validate exact boolean values and nonblank reviewer/evidence. Ignore malformed
   historical records when projecting, and reject malformed new review writes.
   Restrict a screenshot exemption to image media, not video/unknown assets.

## Data concerns

- Preserve the unmodified stored result and include the effective policy status
  and supporting review ID/evidence in exports, so removing `gps_missing` is
  explainable. Projection must not mutate its input object or persist altered
  recovery observations accidentally.
- For expected-GPS coverage, exclude confirmed screenshots from both the
  denominator and its available/selected numerators, including screenshots that
  happen to contain real GPS. Keep original all-media numerators unchanged.
  A zero expected denominator should yield a null/not-applicable rate, not 100%.
- Distinguish confirmed screenshot count from missing-GPS warnings actually
  exempted. An item with coordinates can be a confirmed screenshot without
  requiring removal of any warning.

## Edge cases

Test true → false and true → false → true, same-second decisions, unchanged/raw
result comparison, malformed newer records, screenshot with real coordinates,
screenshot with invalid/conflicting GPS, and an ordinary PNG/missing-GPS photo.
A changed screenshot decision may affect every occurrence sharing the same stable
media ID; that is consistent with screenshot status being a content property.

## API/cost concerns

None introduced. No classification/inference API, source writes or extra extraction
is needed. A screenshot exemption must never set remote eligibility or clear
privacy, shoe identity, live-import or other approval gates.

## Architecture concerns

The existing `local_context` extension is appropriate. Keep validation limited to
`context_type=screenshot_review`, preserving other local-context use. Additive CSV
columns and explicit projection provenance preserve the current contract. Document
that raw SQLite recovery reasons remain original evidence, while projected reports
apply the latest screenshot policy.

## Testing gaps

Add focused tests for decision ordering/validation, effective versus raw reasons,
all-media versus expected-GPS coverage, CSV/JSONL/envelope projection, reversal,
and no privacy changes. Run the existing regression suite. Implementation QA can
use synthetic assets and local databases; no private screenshot classification or
new recovery run is required.

## Suggested changes

Accept these notes in the reconciliation, implement the small helper and export
integration, then return the changes for independent QA. Preserve the earlier
milestone report as historical evidence and identify regenerated projections with
their policy metadata.

## Questions requiring resolution

None before implementation. Actual screenshot identification remains a separate
explicit local-review action; the absence of such decisions is not permission to
guess which real files qualify.

## Blocking issues

**None.** Approval is limited to the screenshot missing-GPS exception and does not
authorize full-library recovery or alter the existing user approval boundary.

---

# ANTI-GRAVITY IMPLEMENTATION QA — screenshot GPS exception

Date: 2026-10-30. Same user-authorized independent Codex reviewer. Scope is only
the reviewed screenshot policy addition; the original milestone QA remains a
historical record of the earlier implementation.

## Result

**PASS.** No concrete unresolved defect identified in this narrow change.

## Requirement coverage

- Only a valid explicit screenshot-review decision on image media exempts GPS.
  Video/unknown media, absent decisions and malformed decisions do not receive
  the exemption. No filename, extension, dimension or missing-GPS heuristic exists.
- Exact boolean and nonblank reviewer/evidence validation reject invalid new
  screenshot decisions. UUID event identities and descending rowid ordering make
  true → false → true reversible even with identical payloads in the same second.
  Malformed newer historical/directly inserted records are ignored defensively.
- The projection removes only `gps_missing`. Other date/GPS review flags, actual
  coordinates, raw observations and privacy/remote-eligibility fields remain.
  A deep copy prevents mutation of input results; stored recovery JSON is unchanged.
- Exports identify the screenshot subtype, effective GPS requirement, policy
  version and supporting decision ID. CSV columns are additive. SACC envelopes
  retain their live-import and privacy restrictions.
- Expected-GPS numerator and denominator both exclude confirmed screenshots,
  including screenshots with actual GPS; original all-media GPS coverage remains
  unchanged. A zero expected denominator produces a null rate. Summary wording
  describes screenshots exempt from the requirement, not fabricated missing-data
  recoveries.

## Tests performed

Independent regression command:

```sh
.venv-poc-313/bin/python -B -m unittest discover -s tests -v
```

**31 tests passed.** The two new focused tests cover multiple cases: explicit and
image-only behavior, validation, reversal/reconfirmation, malformed newer rows,
preserved raw metadata/GPS/conflicts/privacy, CSV fields, envelope status, and
coverage denominators.

An additional reviewer-only synthetic probe confirmed that a screenshot with
real GPS retains all-media coverage of 1/1 while expected-GPS coverage becomes
0/0 with a null rate. That export ran with source-member reading and recovery
result writing patched to fail if invoked; neither occurred. Stored raw result
JSON was byte-for-byte unchanged.

Reviewed `review_policy.py`, the stage-write and export integrations, the focused
tests, policy reconciliation, and runbook addendum. No private media or per-file
personal metadata was inspected, and no real sample files were classified.

## Problems found

None outstanding. The design-review ordering/reconfirmation concern is addressed
by unique screenshot-event IDs and authoritative insertion order. Existing generic
stage-result idempotency remains unchanged.

## Data, API/cost and regression concerns

No source-media processing, extraction, classifier, schema migration, cloud call,
or live import was introduced. Actual sample screenshot counts must remain
unconfirmed until explicit local review identifies items. This policy exception
does not clear unrelated metadata or privacy requirements or authorize full recovery.

## Recommended fixes

None for this reviewed change.

## Retest required

**NO** unless implementation or scope changes after this review.

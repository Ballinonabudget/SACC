# Screenshot GPS policy — review request

2026-10-30. User requirement: “screenshot don't have GPS so we can omit those
from the GPS requirements.”

## Task and current behavior

Current proposals flag every missing GPS observation as `gps_missing`. Screenshot
classification is not yet implemented; neither PNG format nor missing GPS proves
that an item is a screenshot. The existing 200-file results remain valid historical
evidence and contain no per-item screenshot confirmations.

## Proposed behavior and implementation

Exempt confirmed screenshots from the missing-GPS review requirement. Preserve
capture dates, all other metadata checks, original observations, and privacy
defaults. Do not discard real coordinates if a screenshot happens to contain them.
Retain actual GPS conflicts/invalidity for review; remove only `gps_missing`.

Use the existing append-only `local_context` stage records for explicit local
screenshot review (`context_type=screenshot_review`, boolean `is_screenshot`,
nonempty reviewer/evidence). Latest valid decision wins; a later false decision
reverses the exemption. No filename/extension/dimension guessing, no classifier
or live database migration in this change. Unconfirmed items retain current rules.

Apply the policy as a report/export projection over preserved recovery results,
without rewriting observations, changing sample membership or rerunning media.
Reports label exempt items `not_expected_screenshot`, add screenshot/GPS-requirement
columns at the end of CSV, and report expected-GPS coverage separately from existing
all-media GPS coverage. No real sample items will be exempted until identified.

## Affected files and impacts

New `sacc_takeout/review_policy.py`; small integration in `manifest.py` stage
validation and `importer.py` export. Focused tests and runbook update. No schema,
API, cloud, source-file, live import, extraction, rename or Outlet Plug changes.
Rollback is a later explicit false screenshot decision or removal of the projection
in a later version; preserved observations and prior reports remain recoverable.

## Risks, tests and acceptance

Avoid false classification of ordinary PNGs, missing-GPS photos and screen-shaped
photos. Validate boolean/reviewer/evidence fields. Test missing GPS exemption only
for explicit confirmation, preservation of date/GPS conflicts and actual coordinates,
reversal by a later decision, unchanged raw results, CSV fields and separate coverage
denominators. Run the existing regression suite and independent implementation QA.
Full recovery remains subject to the existing approval boundary.

## Review status

APPROVED WITH NOTES by the user-authorized independent Codex reviewer; see
`SACC_TAKEOUT_SCREENSHOT_GPS_REVIEW.md`.

## Review Resolution (before implementation)

All notes accepted; none rejected. Screenshot decisions use unique append IDs
(unlike generic deduplicated stage outputs), with insertion order determining the
latest valid decision, including identical true→false→true re-confirmations in the
same second. Exemption is image-only. Validate exact booleans and nonblank reviewer/
evidence. Ignore malformed legacy/directly inserted decisions defensively. Tests
will cover those cases, preservation of raw GPS/conflicts/privacy, separate coverage
numerators/denominators and zero expected-GPS denominator. No schema/API migration
or source-media processing is needed. Existing record identities remain unchanged.

## Implementation outcome

Implemented and independently QA reviewed: **PASS; 31/31 tests pass**. New
`review_policy.py` projects the rule over unchanged recovery observations. The
existing append-only stage interface records reversible screenshot decisions;
CSV/JSONL exports include the resulting GPS requirement and separate coverage.
No actual sample item has been classified from the general user observation,
and no full-library recovery, source change or live database import was run.

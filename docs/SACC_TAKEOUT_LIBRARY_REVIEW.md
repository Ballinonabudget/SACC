# ANTI-GRAVITY DESIGN REVIEW — recovered-media library

Date: 2026-11-01. Reviewer: independent Codex agent, using Nitty's authorized
Anti-Gravity substitution. This is not an actual Anti-Gravity session. Reviewed
`SACC_TAKEOUT_LIBRARY_DESIGN.md`, the current `main.py` FastAPI app, PoC schema/API,
app-state initialization, frontend/launcher hooks and recovery/location contracts.
No implementation was performed and no private media was opened or processed.
Only this review document was changed.

## Decision

**APPROVED WITH NOTES.** The engineer explicitly accepted all clarifications below
before this decision. Record them in design reconciliation before implementation.
No user clarification or additional design gate is needed for the described
isolated build. Independent implementation QA remains required before delivery.
This approval does not authorize real full-library organization or live DB promotion.

## What looks correct

- The actual integration target is `main:app` and the existing SACC frontend. The
  proposed additive tables avoid fabricating mandatory shoe records.
- Account/media/occurrence identities and shared photo/video evidence survive
  physical folder changes. Originals, recovery objects/ledgers and copied legacy
  table contents remain preserved.
- Real metadata import goes to an isolated SQLite backup; API import/preview and
  local review do not imply live promotion, cloud classification or a physical rename.
- The organization engine produces independent COW outputs, with explicit failure
  when clone support is absent. No silent full-copy fallback is acceptable.

## Missing requirements

Define review scope in the API and UI as explicitly selected occurrences, with a
bounded selection and per-occurrence optimistic revisions. The accepted limit is
100. A shared original hash or account/media link is not implicit permission to
propagate a date, branch or privacy decision to other occurrences. Privacy remains
local and remote eligibility false even after a non-personal label.

GET/module import must not initialize or migrate the library. Missing setup should
produce a clear unavailable/setup state. Preview servers must configure
`SACC_APP_DB`, `SACC_POC_DB` and `SACC_LIBRARY_DB` to distinct isolated targets
**before importing `main`**: the existing `AppDB()` and global PoC `MultimodalDB()`
constructors perform database initialization/migration at import time.

## Data concerns

Bind imported records to one consistent read-only ledger snapshot, exact plan,
review version and report watermark/hash set. Reject stale or mismatched reports.
Reimport must preserve local review events/overrides, occurrence uniqueness and
prior provenance while revalidating conflicts and historical compatibility.
Report the import's integrity scope as metadata/report verification plus output
path/size/mtime checks; it is not a new 380 GiB payload SHA verification.

Keep observed GPS, source dates, embedding outcomes, canonical metadata and local
decisions distinct. Calendar-date corrections must retain their precision without
inventing a UTC instant. Accepted date changes clear incompatible branch overrides
with an audit event and stale any affected organization plan. Clearing/disputing
confirmation must also invalidate dependent reuse. Preserve complete context
graphs, not only currently positive assignments.

No real store directory is available. Empty/unknown store UI is correct. Imported
historical versions and explicit evidence are required for exact confirmation;
mixed photo/video membership is selected explicitly. Synthetic branches must never
be seeded into the real imported catalogue as factual locations.

## Edge cases

Organization identity must bind the published final-file hash/size, separate from
the original pre-embedding media hash. Use deterministic collision checks covering
case and Unicode normalization on the target filesystem, byte-length limits and
safe path components. Names must preserve unknown dates/branches/subjects honestly.

Clone candidate publication must be atomic and refuse overwrite; a temporary
publication link must never hardlink the recovered source to the organized file.
Validate/adopt only owned crash artifacts. Rollback verifies generated output
hashes and preserves edited outputs. Catalog locator updates/rollback use
compare-and-swap so an old plan cannot clear a newer organized locator. Original
recovery locators remain usable during interrupted catalog synchronization.

## API/cost concerns

Use bounded records, request bodies, queries, selections and pagination; parameterized
SQL alone does not make arbitrary FTS syntax valid. Define errors for invalid queries
and stale review revisions. No media uploads, geocoder/map requests or automatic
shoe-identification calls belong in this increment. Keep private content out of
URLs, diagnostic logs, external asset parameters and AI-visible browser captures.

## Architecture concerns

Protect the real application boundary, not only the new router. The current
`/api/video` accepts arbitrary directory/file parameters; it must not bypass the
library's serving policy. The accepted reconciliation adds shared loopback client,
Host, Origin and Sec-Fetch validation and protects configured recovery/library
roots, including ancestor/symlink paths, from legacy generic media/path bridges.
Exercise this against `main:app`, including static/legacy routing and global CORS.

The session bootstrap must itself reject foreign origins. Use the HttpOnly strict
session cookie for library reads/media and a separate same-origin CSRF response
token/header for mutations; do not put tokens in media URLs. Serve registered IDs
through validated roots with no symlink traversal, safe MIME/attachment behavior,
nosniff and private/no-store caching. Unknown/SVG/HTML content must not render inline.
Test actual range behavior rather than assuming the framework version supports it.

## Testing gaps

The proposed tests are appropriate. Acceptance must include:

- Full real import aggregate reconciliation, interrupted/repeated import, bounded
  memory, stable pagination and preservation of copied legacy tables/local reviews.
- Same hash in multiple occurrences/accounts, explicit review scope, stale revisions,
  screenshot reversal, date/store incompatibility and transitive revocation.
- Main-app startup with all isolated DB settings; missing-library GETs; foreign
  Host/client/Origin/Fetch metadata; missing/bad CSRF; legacy serving bypasses;
  malicious paths, filenames, descriptions, FTS input and valid/invalid ranges.
- Actual small APFS clone independence, unsupported cloning without fallback,
  Unicode/case collisions, stale plan/source, publication crash adoption, edited
  rollback refusal and newer-plan locator preservation. All apply/rollback media
  fixtures remain synthetic.
- Synthetic-only wide/narrow browser validation of loading, empty/error states,
  pagination, details, review conflict feedback and organization preview. Inspect
  real metadata only through sanitized aggregates in model-visible tools.

## Suggested changes

Implement the reconciled contracts in the existing FastAPI/frontend entry points,
with the new library isolated from mandatory shoe links and legacy basename keys.
Give the user one usable Library tab and an explicit organization preview; retain
the separate reviewed-plan gate for any later real apply or live promotion.

## Questions requiring resolution

None requiring user input for this increment. Real store labels, future enrichment
and physical organization are intentionally unresolved data/later execution work,
not reasons to block the authorized library build.

## Blocking issues

**None after the accepted reconciliation is recorded.** The import-time database
side effects and legacy media bypass were the material integration concerns;
the accepted isolation/shared-boundary changes address them. Their implementation
and the remaining acceptance criteria must be demonstrated in QA.

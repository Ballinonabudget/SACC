# SACC Library search design

November 8, 2026. Proposed for Anti-Gravity review.

## SACC review request

### Task

Make footwear discoverable from whatever the operator remembers about a sighting. A search for `Kobe` should work across years and locations. The operator can then narrow the results by store, capture years, silhouette, colorway, category, or exact style code. This is the next Library pilot following the folder preview.

### Current behavior

- The Library searches original names, source descriptions, review notes, and aliases for confirmed stores. It supports one capture year and one store filter. The index has no structured shoe associations for recovered media.
- The ten real files in the folder preview all have GPS coordinates. The staging catalog has 67,647 items with coordinates and no confirmed stores. The reviewed historical store directory is empty. A capture coordinate provides evidence for a location candidate, and branch confirmation is a separate review decision.
- The multimodal PoC has a SKU-based shoe catalog. Its media table allows one shoe per file path, so it cannot express a wall photo with several independently searchable shoes.

### Proposed behavior

| Operator action | Expected result |
| --- | --- |
| Search `Kobe` | Return media tagged with the Kobe line or any of its known models and colorways. Start across all years and stores. |
| Add Nike Factory I-Drive or Nike Clearance Marketplace | Filter to the selected confirmed branch. Switch, clear, or add branches without losing the shoe query. A venue filter can group its confirmed branches. |
| Check 2015, 2016, and 2017 | Include captures from those years. Unchecking a year immediately removes its results and resets pagination. Provide All years and a separate Undated option. Selecting zero years yields zero results until the operator chooses a year or resets. |
| Search `Kobe 11 Bruce Lee` and select Nike Clearance Marketplace | Show every matching sighting at that branch with its capture month and year. Show the media within each sighting when a reviewed visit association exists. |
| Enter a full style code | Use normalized exact equality, preserving leading zeros. Accept equivalent case, spacing, or hyphenation where the code format permits it. Keep different codes distinct. |
| Filter to a brand-specific store | Default to its reviewed brand scope, such as Nike and Jordan for Nike Clearance or Adidas for an Adidas store. Show the scope in the UI and offer All brands for documented exceptions. General retailers and venue-wide filters start with All brands. |
| Search `Jordan 11` | Return both a solo still and a wall shot containing a reviewed Jordan 11 tag. Show each occurrence once even if several shoes in that image match. |

Single-shoe stills use the most specific supported display title, such as **Kobe 11 Bruce Lee**. Group stills use a descriptor such as **Multiple Shoes**, **Jordan Multiples**, or **Nike Multiples**. Every individually identifiable shoe in the group gets its own association. A partly identified wall can show a group descriptor and confirmed individual tags while the remaining shoes await review. Videos use the same relationships and can optionally record where a shoe appears in the clip.

### Proposed implementation

1. **Establish a reviewed fixture.** Select a small set of already reviewed SACC media with distinguishable shoes and branch evidence. Include a single-shoe still, a group still, a repeated sighting, and a price label. Use synthetic fixtures to exercise cases the real sample cannot substantiate. The retailer names and shoe examples above are search scenarios.
2. **Add a relational shoe catalog and media tags.** Model brand, line or athlete, silhouette, and colorway as linked identities. Link category and classification separately, since one shoe can belong to both Basketball Shoes and Nike Signature. Use canonical names plus aliases such as `AJ1`, `Jordan 1`, and `Air Jordan 1`. A line-level or model-level tag can be saved when the exact colorway or SKU is unavailable.
3. **Resolve searches against one shoe association at a time.** Resolve aliases and parent-to-child matches before joining to occurrences. Match exact style codes through an indexed key. Apply branch, capture year, media type, and store brand scope to those matches. OR together selections within a facet and AND different facets. Brand scope applies to the shoe that matched the query, including when a group still contains several brands.
4. **Review location independently.** Reuse the Library’s versioned store directory and confirmation workflow. Store and venue identities remain distinct. Use capture date, observed coordinates, and corroborating evidence to propose a historical branch. Keep location candidates visible for review and require confirmation before they appear under a named store filter.
5. **Keep repeat sightings and prices distinct.** Return each matching occurrence with its capture month and year. Group only by an existing reviewed visit or sighting relationship, and keep separate visits separate even for the same shoe and store. Attach a price or markdown observation to the specific shoe association and sighting. Record amount, currency, price kind, evidence, and review status when available. Preserve conflicting observations and show their evidence.

### Files and systems affected

- `sacc_takeout/library.py` and a migration for the Library catalog for storage, review, and search.
- `sacc_takeout/library_api.py` for local search, facets, and review requests.
- `SCAA/sacc/library-view.jsx` for shoe search, store and year selections, brand scope, result cards, and tag review.
- `sacc_takeout/locations.py` and the existing directory import for reviewed branch identities and historical validity.
- `tests/test_library.py` and focused search and migration fixtures.

### Database impact

Add versioned catalog tables for shoe hierarchy, aliases and normalized codes, occurrence-to-shoe associations, and price observations. Use occurrence IDs for capture context and retain the existing media ID for duplicate provenance. An association carries its evidence, review state, and optional video time range. Use indexed foreign keys in both directions and enforce uniqueness for equivalent associations. Keep verified branch records, original paths, and capture metadata in their existing structures.

Extend the append-only Library review history and expected-revision checks to tag changes. Persist an accepted change and its audit event in the same transaction. Reuse PoC metadata only through a reviewed mapping of stable IDs or exact codes. The pilot uses the Library catalog and keeps production ingestion separate.

### API impact

Preserve existing text, single-year, and store filters for current callers. Add a structured shoe query, multi-select capture years, branch or venue IDs, and a brand-scope option. Define the difference between omitted year filters, an explicitly empty selection, and Undated. Return matching shoe associations, capture month/year, branch and brand scope, and available price observations. Use bounded pagination and facet counts based on the active query so an empty result is easy to broaden. The UI discards stale responses after rapid filter changes.

### Data flow

Reviewed local media and corroborating evidence → reviewed shoe and branch associations → indexed Library search → results showing the matched shoes and their capture details. Start with manual, evidence-backed labels for the pilot. Any future local recognition pass produces suggestions for review. A store visit or nearby box-label photo can help find candidates, while each media association still requires its own supporting evidence.

### Risks and edge cases

- A GPS point can cover several stores, and a branch can move, close, or change names. Match against the historical branch and venue records for the capture date. Missing location remains searchable by shoe and date.
- A colorway nickname or style-code format can overlap across brands, releases, or variants. Preserve ambiguity for review and retain the original code alongside its normalized key.
- Tag corrections, partial identification, and multi-shoe matches can create duplicate results or change facet counts. Keep stable occurrence IDs and deduplicate results without merging separate visits.
- Apply retail brand scope only where the reviewed directory explicitly defines it. Surface the active scope and provide a way to widen it.
- A release year differs from a capture year. Derive capture month/year from the existing trusted date and its documented timezone basis.
- Existing privacy safeguards apply to the pilot. Use explicitly reviewed SACC content, keep media local, and preserve recovery files and source archives.

### Test plan

- In an isolated catalog, confirm that `Kobe` returns descendants and `Kobe 11 Bruce Lee` selects the right variant. Test aliases, exact-code lookup, near-match rejection, and a partially identified shoe.
- Seed one solo still and one multi-shoe still for the same model. Verify that both appear, that the group still returns once, and that it is also discoverable through its other shoe tags. Check that words from different shoe associations cannot combine to satisfy a precise shoe query.
- Check multiple years, uncheck one, clear all, and reset. Verify the result list and facet counts, including Undated and a capture near a year boundary.
- Switch between I-Drive and Marketplace, broaden to more branches, and verify that the same shoe query survives. Exercise historical branch overlap and the visible brand default and override.
- Seed two visits for the same shoe and store with different dates and price evidence. Verify that both sightings appear and their prices stay attached to the right shoe and visit.
- Verify migration and rollback on a copy, stale review conflicts, privacy isolation, existing Library filters, and query plans and response times on a staging copy with the full catalog size.
- Ask the operator to find a known pair from memory using only a shoe name, then refine by store and checked years. Compare the results with the reviewed fixture, including wall shots and repeat sightings.

### Rollback

Run the pilot against a private staging copy and keep the pre-migration catalog. Disable the new search view and reconnect the original Library if the pilot fails. Preserve the pilot catalog so reviewed tags can be recovered. Confirm counts, SQLite integrity, and existing filter behavior after restoring the original path.

### Questions for Anti-Gravity

- Which historical branch evidence and aliases are available for I-Drive, Marketplace, and the New Balance clearance locations?
- Are the proposed store scope and All brands override clear when a wall shot has multiple brands or several branches are selected?
- Can existing visit evidence support grouping repeated sightings, or should the pilot list each capture separately?
- Which real media can establish a reliable pilot fixture for group shots, exact style codes, and separately observed prices?

The SACC operating manual requires an **APPROVED** or **APPROVED WITH NOTES** review and a reconciliation note before implementation.

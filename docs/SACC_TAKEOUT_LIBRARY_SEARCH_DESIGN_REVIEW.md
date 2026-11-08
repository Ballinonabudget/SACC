# ANTI-GRAVITY DESIGN REVIEW

**Document Under Review**: `docs/SACC_LIBRARY_SEARCH_DESIGN.md`  
**Date**: November 8, 2026  
**Reviewer**: Anti-Gravity  
**Target Milestone**: SACC Footwear Library Search Pilot  

---

### Decision
**APPROVED WITH NOTES**

No material architectural, data integrity, or privacy blockers found. Codex's design proposal provides a sound, relational foundation for multi-faceted footwear search. The pilot may proceed into private staging.

---

### What looks correct
1. **Relational Shoe Catalog**: Separating canonical shoe hierarchy (`brand`, `line`, `model`, `colorway`, `sku`, `aliases`) from occurrence associations (`library_shoe_associations`) cleanly solves the 1:many limitation of the PoC media table and natively accommodates wall shots containing multiple distinct shoes.
2. **Multi-Facet Logic**: Clear specifications for multi-year selection (OR within facets, AND across facets), year toggling, and distinguishing empty selection (returns 0 results) from omitted/all years.
3. **Location Independence**: Correctly preserves branch confirmation as a separate review decision rather than conflating raw capture coordinates with confirmed retail tenants.
4. **Local Privacy Invariant**: Adheres strictly to local SQLite queries with $0 API cost and zero transmission of private media.
5. **Private Staging Isolation**: Running the pilot in an isolated staging database leaves the live catalog (`sacc-library.sqlite3`) and original media byte-for-byte untouched.

---

### Missing requirements (Addressed in Notes)
- Multi-select year queries must explicitly support the "Undated" bucket alongside discrete years.
- Solo sightings vs. multi-shoe wall shots need distinct visual indicators in search cards so the operator immediately knows if an image is a dedicated product shot or a clearance rack/shelf overview.

---

### Data concerns
- **Alias Collisions**: Informal shorthand (e.g. `Bred`, `Chicago`, `Concord`) can match across silhouettes or brands if not scoped. Shorthand aliases should be tied to the model/colorway hierarchy rather than global fuzzy tokens.
- **Leading Zeros in SKUs**: Style codes such as `012345-678` must be stored as normalized text with leading zeros preserved; exact equality must strip non-alphanumeric separators (hyphens/spaces) without mutating the original text representation.

---

### Edge cases
- **Multi-Shoe Wall Shot Matching**: A search for `Kobe 11` on a wall containing both `Kobe 11` and `KD 8` must return the wall shot once (deduplicated by `occurrence_id`), while displaying all identified shoe badges.
- **Repeat Sightings**: The same shoe seen at the same store on different dates (e.g. May 2016 vs. August 2016) must display as distinct sightings, each with its own capture month/year and observed price.
- **Empty Year Set**: Unchecking all years must immediately yield 0 results until at least one year or "All" is selected.

---

### API/cost concerns
- Zero cloud API calls. All indexing and filtering executes locally against SQLite.

---

### Architecture concerns
- The live catalog schema version should be preserved. New catalog tables (`library_shoes`, `library_shoe_associations`) should be created conditionally (`IF NOT EXISTS`) so existing databases load without requiring immediate destructive migrations.

---

### Testing gaps
- Need automated test cases asserting:
  1. Descendant matching (`Kobe` matches `Kobe 11 Bruce Lee`).
  2. Multi-year filter combinations including empty set yielding 0 results.
  3. Single occurrence deduplication for wall shots with multiple matching tags.
  4. Repeat sightings preservation across distinct calendar dates.

---

### Suggested changes
- Provide a dedicated pilot endpoint (`/api/library/pilot/search` and `/api/library/pilot/facets`) and private staging DB configuration (`SACC_LIBRARY_DB`) so testing does not perturb ongoing library operations.

---

### Blocking issues
- **None.**

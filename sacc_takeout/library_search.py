"""
SACC Library Footwear Search Engine
Relational catalog search across shoe lines, models, colorways, exact SKUs,
multi-select capture years, confirmed store branches, wall shots, and repeat sightings.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

CATALOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS library_shoes (
    id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    line TEXT,
    model TEXT NOT NULL,
    colorway TEXT,
    sku TEXT,
    category TEXT,
    display_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ls_sku ON library_shoes(sku);
CREATE INDEX IF NOT EXISTS idx_ls_line ON library_shoes(line);
CREATE INDEX IF NOT EXISTS idx_ls_model ON library_shoes(model);
CREATE INDEX IF NOT EXISTS idx_ls_brand ON library_shoes(brand);

CREATE TABLE IF NOT EXISTS library_shoe_associations (
    id TEXT PRIMARY KEY,
    occurrence_id TEXT NOT NULL REFERENCES library_occurrences(id),
    shoe_id TEXT NOT NULL REFERENCES library_shoes(id),
    tag_type TEXT NOT NULL DEFAULT 'solo', -- 'solo', 'wall_item', 'group_item'
    group_descriptor TEXT,                -- e.g. 'Multiple Shoes', 'Nike Multiples'
    confidence REAL NOT NULL DEFAULT 1.0,
    evidence TEXT,
    price_observed REAL,
    time_start_sec REAL,
    time_end_sec REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lsa_occurrence ON library_shoe_associations(occurrence_id);
CREATE INDEX IF NOT EXISTS idx_lsa_shoe ON library_shoe_associations(shoe_id);
CREATE INDEX IF NOT EXISTS idx_lsa_tag_type ON library_shoe_associations(tag_type);
"""

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def ensure_catalog_schema(con: sqlite3.Connection) -> None:
    """Ensure catalog and association tables exist."""
    con.executescript(CATALOG_SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(library_occurrences)").fetchall()}
    if "capture_type" not in cols:
        con.execute("ALTER TABLE library_occurrences ADD COLUMN capture_type TEXT DEFAULT 'in_store_photo'")
    if "camera_model" not in cols:
        con.execute("ALTER TABLE library_occurrences ADD COLUMN camera_model TEXT DEFAULT NULL")
    if "photo_resolution" not in cols:
        con.execute("ALTER TABLE library_occurrences ADD COLUMN photo_resolution TEXT DEFAULT NULL")


def format_month_year(date_str: Optional[str]) -> Tuple[str, Optional[str], Optional[int]]:
    """Convert an ISO or YYYY-MM-DD date string to ('Month Year', 'YYYY-MM', year_int)."""
    if not date_str or not isinstance(date_str, str):
        return ("Undated", None, None)
    parts = date_str.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        year = int(parts[0])
        month_idx = int(parts[1])
        if 1 <= month_idx <= 12:
            month_name = _MONTH_NAMES[month_idx]
            return (f"{month_name} {year}", f"{year}-{month_idx:02d}", year)
    if len(parts) >= 1 and parts[0].isdigit():
        year = int(parts[0])
        return (str(year), str(year), year)
    return ("Undated", None, None)


def normalize_sku(sku: Optional[str]) -> str:
    """Normalize style code by stripping hyphens, spaces, and converting to uppercase."""
    if not sku:
        return ""
    return re.sub(r"[\s\-]+", "", str(sku)).upper()


def search_footwear(
    con: sqlite3.Connection,
    q: str = "",
    years: Optional[List[str] | str] = None,
    store: str = "all",
    capture_type: str = "all",
    limit: int = 30,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Search library media occurrences by footwear attributes and facets.
    
    Rules:
    - Search text matches shoe line, model, colorway, brand, display title, exact/normalized SKU, or aliases.
    - Multiple capture years can be selected.
      * If years is explicitly an empty list `[]`, returns 0 results as per spec.
      * If years contains 'all' or is None, all years are included.
      * 'undated' matches occurrences where effective_date IS NULL.
    - Store narrows to confirmed branch id.
    - Capture type distinguishes in-store camera sightings vs. background-removed studio cutouts / stock renders.
    - Deduplicates by occurrence so multi-shoe wall shots return once with all tags attached.
    - Preserves distinct sightings across dates (repeat sightings at same store appear separately).
    """
    ensure_catalog_schema(con)

    # 1. Check for empty year set
    parsed_years: Optional[Set[str]] = None
    if years is not None:
        if isinstance(years, str):
            raw_items = [y.strip() for y in years.split(",") if y.strip()]
            parsed_years = set(raw_items)
        elif isinstance(years, (list, set, tuple)):
            parsed_years = {str(y).strip() for y in years if str(y).strip()}
        else:
            parsed_years = None

        if parsed_years is not None and len(parsed_years) == 0:
            # Explicit empty set selected -> 0 results
            return {
                "results": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "facets": _compute_facets(con, q=q, store=store, capture_type=capture_type),
            }

    where_clauses: List[str] = []
    params: List[Any] = []

    # 2. Year filter
    if parsed_years and "all" not in parsed_years:
        year_subclauses: List[str] = []
        if "undated" in parsed_years:
            year_subclauses.append("o.effective_date IS NULL")
        digit_years = [y for y in parsed_years if re.fullmatch(r"\d{4}", y)]
        if digit_years:
            placeholders = ",".join("?" for _ in digit_years)
            year_subclauses.append(f"substr(o.effective_date, 1, 4) IN ({placeholders})")
            params.extend(digit_years)
        if year_subclauses:
            where_clauses.append("(" + " OR ".join(year_subclauses) + ")")
        else:
            # Years provided but contained no valid targets
            return {
                "results": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "facets": _compute_facets(con, q=q, store=store, capture_type=capture_type),
            }

    # 3. Store filter
    if store and store not in ("all", "", None):
        if store == "unknown":
            where_clauses.append("o.store_version_id IS NULL")
        else:
            where_clauses.append("o.store_version_id = ?")
            params.append(store)

    # 4. Capture Type filter (in_store_photo vs studio_cutout)
    if capture_type and capture_type not in ("all", "", None):
        where_clauses.append("COALESCE(o.capture_type, 'in_store_photo') = ?")
        params.append(capture_type)

    # 4. Shoe Query (q)
    raw_q = (q or "").strip()
    if raw_q:
        norm_code = normalize_sku(raw_q)
        q_like = f"%{raw_q}%"
        # Match on line, model, colorway, brand, display_name, group_descriptor, sku, or aliases
        shoe_clause = """(
            s.line LIKE ? OR
            s.model LIKE ? OR
            s.colorway LIKE ? OR
            s.brand LIKE ? OR
            s.display_name LIKE ? OR
            lsa.group_descriptor LIKE ? OR
            s.sku = ? OR
            REPLACE(REPLACE(UPPER(s.sku), '-', ''), ' ', '') = ? OR
            EXISTS (
                SELECT 1 FROM json_each(s.aliases_json)
                WHERE LOWER(value) LIKE ?
            )
        )"""
        where_clauses.append(shoe_clause)
        params.extend([
            q_like,
            q_like,
            q_like,
            q_like,
            q_like,
            q_like,
            raw_q,
            norm_code,
            f"%{raw_q.lower()}%",
        ])

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Count distinct matching occurrences
    count_sql = f"""
    SELECT COUNT(DISTINCT o.id)
    FROM library_occurrences o
    JOIN library_shoe_associations lsa ON lsa.occurrence_id = o.id
    JOIN library_shoes s ON s.id = lsa.shoe_id
    {where_sql}
    """
    total = con.execute(count_sql, params).fetchone()[0]

    # Select distinct occurrence IDs ordered chronologically (newest first or chronological by date)
    items_sql = f"""
    SELECT DISTINCT o.id, COALESCE(o.effective_date, '1900-01-01') as sort_date
    FROM library_occurrences o
    JOIN library_shoe_associations lsa ON lsa.occurrence_id = o.id
    JOIN library_shoes s ON s.id = lsa.shoe_id
    {where_sql}
    ORDER BY sort_date ASC, o.id ASC
    LIMIT ? OFFSET ?
    """
    paged_params = list(params) + [limit, offset]
    matching_rows = con.execute(items_sql, paged_params).fetchall()
    matched_ids = [r[0] for r in matching_rows]

    results = []
    for oid in matched_ids:
        occurrence = _build_occurrence_search_card(con, oid)
        if occurrence:
            results.append(occurrence)

    facets = _compute_facets(con, q=raw_q, store=store, capture_type=capture_type, active_years=parsed_years)

    return {
        "results": results,
        "total": total,
        "limit": limit,
        "offset": offset,
        "facets": facets,
    }


def _build_occurrence_search_card(con: sqlite3.Connection, oid: str) -> Optional[Dict[str, Any]]:
    """Build a search result card for an occurrence, attaching all identified shoes."""
    occ_row = con.execute(
        """
        SELECT o.id, o.media_id, o.original_name, o.media_type, o.mime_type,
               o.effective_date, o.capture_utc, o.store_version_id, o.privacy,
               o.recovered_path, o.file_size_bytes,
               o.capture_type, o.camera_model, o.photo_resolution
        FROM library_occurrences o
        WHERE o.id = ?
        """,
        (oid,),
    ).fetchone()

    if not occ_row:
        return None

    r = dict(occ_row)
    date_display, ym, year = format_month_year(r["effective_date"])

    # Fetch store details if present
    store_info = None
    if r["store_version_id"]:
        s_row = con.execute(
            "SELECT id, code, label FROM library_stores WHERE id = ?",
            (r["store_version_id"],),
        ).fetchone()
        if s_row:
            store_info = dict(s_row)

    # Fetch all associated shoes for this occurrence
    assoc_rows = con.execute(
        """
        SELECT lsa.id as assoc_id, lsa.tag_type, lsa.group_descriptor,
               lsa.confidence, lsa.price_observed, lsa.time_start_sec, lsa.time_end_sec,
               s.id as shoe_id, s.brand, s.line, s.model, s.colorway, s.sku,
               s.display_name
        FROM library_shoe_associations lsa
        JOIN library_shoes s ON s.id = lsa.shoe_id
        WHERE lsa.occurrence_id = ?
        ORDER BY lsa.id ASC
        """,
        (oid,),
    ).fetchall()

    shoes_list = []
    group_descriptor = None
    has_wall_shot = False

    for a in assoc_rows:
        ad = dict(a)
        if ad["group_descriptor"]:
            group_descriptor = ad["group_descriptor"]
        if ad["tag_type"] in ("wall_item", "group_item"):
            has_wall_shot = True
        shoes_list.append({
            "assoc_id": ad["assoc_id"],
            "shoe_id": ad["shoe_id"],
            "display_name": ad["display_name"],
            "brand": ad["brand"],
            "line": ad["line"],
            "model": ad["model"],
            "colorway": ad["colorway"],
            "sku": ad["sku"],
            "price_observed": ad["price_observed"],
            "tag_type": ad["tag_type"],
            "time_start_sec": ad["time_start_sec"],
            "time_end_sec": ad["time_end_sec"],
        })

    # Determine display title
    if group_descriptor:
        display_title = group_descriptor
    elif len(shoes_list) > 1:
        display_title = "Multiple Shoes"
        has_wall_shot = True
    elif len(shoes_list) == 1:
        display_title = shoes_list[0]["display_name"]
    else:
        display_title = r["original_name"]

    preview_supported = r["mime_type"] in {
        "image/jpeg", "image/png", "image/gif", "image/webp", "video/mp4", "video/quicktime"
    }

    ctype = r.get("capture_type") or ("studio_cutout" if r["mime_type"] == "image/png" else "in_store_photo")

    return {
        "id": r["id"],
        "media_id": r["media_id"],
        "original_name": r["original_name"],
        "display_title": display_title,
        "is_wall_shot": bool(has_wall_shot),
        "group_descriptor": group_descriptor,
        "media_type": r["media_type"],
        "mime_type": r["mime_type"],
        "capture_date": r["effective_date"],
        "capture_month_year": date_display,
        "capture_year": year,
        "store": store_info,
        "privacy": r["privacy"],
        "shoes": shoes_list,
        "asset_url": f"/api/library/assets/{r['id']}",
        "preview_supported": preview_supported,
        "capture_type": ctype,
        "camera_model": r.get("camera_model"),
        "photo_resolution": r.get("photo_resolution"),
    }


def _compute_facets(
    con: sqlite3.Connection,
    q: str = "",
    store: str = "all",
    capture_type: str = "all",
    active_years: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Compute facet breakdown for years, stores, and shoe lines matching current search."""
    where_clauses: List[str] = []
    params: List[Any] = []

    raw_q = (q or "").strip()
    if raw_q:
        norm_code = normalize_sku(raw_q)
        q_like = f"%{raw_q}%"
        where_clauses.append("""(
            s.line LIKE ? OR s.model LIKE ? OR s.colorway LIKE ? OR
            s.brand LIKE ? OR s.display_name LIKE ? OR s.sku = ? OR
            REPLACE(REPLACE(UPPER(s.sku), '-', ''), ' ', '') = ? OR
            EXISTS (SELECT 1 FROM json_each(s.aliases_json) WHERE LOWER(value) LIKE ?)
        )""")
        params.extend([q_like, q_like, q_like, q_like, q_like, raw_q, norm_code, f"%{raw_q.lower()}%"])

    if store and store not in ("all", "", None):
        if store == "unknown":
            where_clauses.append("o.store_version_id IS NULL")
        else:
            where_clauses.append("o.store_version_id = ?")
            params.append(store)

    if capture_type and capture_type not in ("all", "", None):
        where_clauses.append("COALESCE(o.capture_type, 'in_store_photo') = ?")
        params.append(capture_type)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # 1. Years facet
    years_sql = f"""
    SELECT COALESCE(substr(o.effective_date, 1, 4), 'undated') as yr, COUNT(DISTINCT o.id)
    FROM library_occurrences o
    JOIN library_shoe_associations lsa ON lsa.occurrence_id = o.id
    JOIN library_shoes s ON s.id = lsa.shoe_id
    {where_sql}
    GROUP BY yr
    ORDER BY yr ASC
    """
    year_rows = con.execute(years_sql, params).fetchall()
    facets_years = [{"value": r[0], "count": r[1]} for r in year_rows]

    # 2. Stores facet
    stores_sql = f"""
    SELECT s.id, s.code, s.label, COUNT(DISTINCT o.id) as count
    FROM library_stores s
    JOIN library_occurrences o ON o.store_version_id = s.id
    JOIN library_shoe_associations lsa ON lsa.occurrence_id = o.id
    JOIN library_shoes sh ON sh.id = lsa.shoe_id
    {where_sql.replace('s.', 'sh.')}
    GROUP BY s.id
    ORDER BY s.label ASC
    """
    try:
        store_rows = con.execute(stores_sql, params).fetchall()
        facets_stores = [dict(r) for r in store_rows]
    except Exception:
        facets_stores = []

    try:
        all_store_rows = con.execute(
            "SELECT id, code, label, valid_from, valid_to FROM library_stores ORDER BY label ASC"
        ).fetchall()
        all_stores = [dict(r) for r in all_store_rows]
    except Exception:
        all_stores = []

    # 3. Lines facet
    lines_sql = f"""
    SELECT s.line, COUNT(DISTINCT o.id)
    FROM library_shoes s
    JOIN library_shoe_associations lsa ON lsa.shoe_id = s.id
    JOIN library_occurrences o ON o.id = lsa.occurrence_id
    {where_sql}
    GROUP BY s.line
    ORDER BY s.line ASC
    """
    line_rows = con.execute(lines_sql, params).fetchall()
    facets_lines = [{"value": r[0] or "Unknown", "count": r[1]} for r in line_rows]

    # 4. Capture Types facet
    capture_types_sql = f"""
    SELECT COALESCE(o.capture_type, 'in_store_photo') as ctype, COUNT(DISTINCT o.id)
    FROM library_occurrences o
    JOIN library_shoe_associations lsa ON lsa.occurrence_id = o.id
    JOIN library_shoes s ON s.id = lsa.shoe_id
    {where_sql}
    GROUP BY ctype
    ORDER BY ctype ASC
    """
    try:
        ctype_rows = con.execute(capture_types_sql, params).fetchall()
        facets_capture_types = [{"value": r[0], "count": r[1]} for r in ctype_rows]
    except Exception:
        facets_capture_types = []

    return {
        "years": facets_years,
        "stores": facets_stores,
        "all_stores": all_stores,
        "lines": facets_lines,
        "capture_types": facets_capture_types,
    }

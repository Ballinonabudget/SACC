#!/usr/bin/env python3
"""
db.py — SACC SQLite Database Layer
=====================================
Single sacc.db file replaces the scattered per-file JSON index with a
queryable, indexed, full-text-searchable relational store.

Schema
------
  clips           — one row per renamed video file (the permanent record)
  ├── id, original_file, fcp_filename, shoot_date, cam_make, cam_model
  ├── loc_code, loc_name, loc_source, loc_confidence
  ├── loc_visual, loc_audio
  ├── model, sku, size, price
  ├── proxy_file, proxy_deleted, analysed_at
  └── json_path, folder_path, created_at, updated_at

  clips_fts       — SQLite FTS5 virtual table for full-text search
  ├── mirrors: model, sku, fcp_filename, original_file,
  │            loc_code, loc_name, loc_visual, loc_audio

Usage
-----
  from db import SACCDB

  db = SACCDB("/Volumes/Team Bank 12/Sneeaker Solo/sacc.db")
  db.sync_from_folder("/Volumes/Team Bank 12/Sneeaker Solo")
  results = db.search("chicago")
  record  = db.get_by_stem("FLM-MALL_260423_Air-Jordan-1-Chicago_iPhone15ProMax_IMG_3439")
  db.patch(stem, {"loc_code": "PDM", "loc_source": "manual"})
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

VIDEO_EXTS = {".mov", ".mp4", ".MOV", ".MP4", ".mts", ".MTS"}

# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clips (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity
    stem            TEXT NOT NULL UNIQUE,   -- filename without extension (relational key)
    original_file   TEXT,                   -- renamed source filename (e.g. FLM-MALL_..._.mov)
    fcp_filename    TEXT,                   -- final FCP-compliant name
    folder_path     TEXT,                   -- absolute folder path
    json_path       TEXT,                   -- absolute path to companion JSON

    -- Shoot metadata
    shoot_date      TEXT,                   -- YYYYMMDD
    cam_make        TEXT,
    cam_model       TEXT,

    -- Location (Stage 3 manual / Stage 8 AI / Stage 10 confirmed)
    loc_code        TEXT,                   -- SACC code e.g. "PDM"
    loc_name        TEXT,                   -- full name e.g. "Paddock Mall"
    loc_source      TEXT,                   -- "manual" | "ai_confirmed" | "unknown"
    loc_confidence  TEXT,                   -- "high" | "medium" | "low" | "manual" | null
    loc_visual      TEXT,                   -- AI visual evidence text
    loc_audio       TEXT,                   -- AI audio transcript text

    -- Product (from Stage 8 Vertex AI)
    model           TEXT,                   -- e.g. "Air Jordan 1 Retro High OG"
    colorway        TEXT,                   -- e.g. "Chicago"
    sku             TEXT,                   -- e.g. "555088-101"
    size            TEXT,
    price           TEXT,
    release_date    TEXT,                   -- product release date YYYY or YYYY-MM-DD

    -- Proxy lifecycle
    proxy_file      TEXT,
    proxy_deleted   INTEGER DEFAULT 0,      -- 0=pending, 1=deleted

    -- Timestamps
    analysed_at     TEXT,                   -- ISO 8601 from Vertex AI
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Full-text search index (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS clips_fts USING fts5(
    stem,
    original_file,
    fcp_filename,
    model,
    colorway,
    sku,
    loc_code,
    loc_name,
    loc_visual,
    loc_audio,
    content='clips',
    content_rowid='id',
    tokenize='unicode61'
);

-- Keep FTS in sync via triggers
CREATE TRIGGER IF NOT EXISTS clips_ai AFTER INSERT ON clips BEGIN
    INSERT INTO clips_fts(rowid, stem, original_file, fcp_filename, model, colorway, sku,
        loc_code, loc_name, loc_visual, loc_audio)
    VALUES (new.id, new.stem, new.original_file, new.fcp_filename, new.model, new.colorway, new.sku,
        new.loc_code, new.loc_name, new.loc_visual, new.loc_audio);
END;

CREATE TRIGGER IF NOT EXISTS clips_ad AFTER DELETE ON clips BEGIN
    INSERT INTO clips_fts(clips_fts, rowid, stem, original_file, fcp_filename, model, colorway, sku,
        loc_code, loc_name, loc_visual, loc_audio)
    VALUES ('delete', old.id, old.stem, old.original_file, old.fcp_filename, old.model, old.colorway, old.sku,
        old.loc_code, old.loc_name, old.loc_visual, old.loc_audio);
END;

CREATE TRIGGER IF NOT EXISTS clips_au AFTER UPDATE ON clips BEGIN
    INSERT INTO clips_fts(clips_fts, rowid, stem, original_file, fcp_filename, model, colorway, sku,
        loc_code, loc_name, loc_visual, loc_audio)
    VALUES ('delete', old.id, old.stem, old.original_file, old.fcp_filename, old.model, old.colorway, old.sku,
        old.loc_code, old.loc_name, old.loc_visual, old.loc_audio);
    INSERT INTO clips_fts(rowid, stem, original_file, fcp_filename, model, colorway, sku,
        loc_code, loc_name, loc_visual, loc_audio)
    VALUES (new.id, new.stem, new.original_file, new.fcp_filename, new.model, new.colorway, new.sku,
        new.loc_code, new.loc_name, new.loc_visual, new.loc_audio);
END;

-- Useful indexes
CREATE INDEX IF NOT EXISTS idx_clips_loc_code   ON clips(loc_code);
CREATE INDEX IF NOT EXISTS idx_clips_sku        ON clips(sku);
CREATE INDEX IF NOT EXISTS idx_clips_shoot_date ON clips(shoot_date);
CREATE INDEX IF NOT EXISTS idx_clips_loc_source ON clips(loc_source);
"""


# ── SACCDB class ──────────────────────────────────────────────────────────────

class SACCDB:
    """Thread-safe SQLite wrapper for the SACC pipeline database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        with self._conn() as conn:
            # Add columns introduced after v1 schema (no-op if already present)
            for col, defn in [("colorway", "TEXT"), ("release_date", "TEXT")]:
                try:
                    conn.execute(f"ALTER TABLE clips ADD COLUMN {col} {defn}")
                except Exception:
                    pass

            # Rebuild FTS if colorway column is missing from the index
            needs_fts_rebuild = False
            try:
                conn.execute("SELECT colorway FROM clips_fts LIMIT 1")
            except Exception:
                needs_fts_rebuild = True

            if needs_fts_rebuild:
                conn.executescript("""
                    DROP TABLE IF EXISTS clips_fts;
                    DROP TRIGGER IF EXISTS clips_ai;
                    DROP TRIGGER IF EXISTS clips_ad;
                    DROP TRIGGER IF EXISTS clips_au;
                """)

            conn.executescript(_DDL)

            if needs_fts_rebuild:
                try:
                    conn.execute("INSERT INTO clips_fts(clips_fts) VALUES('rebuild')")
                except Exception:
                    pass

    # ── Sync from folder ────────────────────────────────────────────────────

    def sync_from_folder(self, folder: str) -> dict:
        """
        Walk <folder>/json/ and upsert every SACC JSON into the database.
        Returns a summary dict: {inserted, updated, skipped, errors}.
        """
        json_dir = os.path.join(folder, "json")
        if not os.path.isdir(json_dir):
            return {"error": f"json/ directory not found in {folder}"}

        results = {"inserted": 0, "updated": 0, "skipped": 0, "errors": []}

        for fname in sorted(os.listdir(json_dir)):
            if not fname.endswith(".json"):
                continue
            jpath = os.path.join(json_dir, fname)
            try:
                with open(jpath) as fh:
                    data = json.load(fh)

                stem = os.path.splitext(fname)[0]
                row  = _json_to_row(data, stem, jpath, folder)
                action = self._upsert(row)
                results[action] += 1

            except Exception as e:
                results["errors"].append(f"{fname}: {e}")

        return results

    def _upsert(self, row: dict) -> str:
        """Insert or update a clips row. Returns 'inserted' | 'updated' | 'skipped'."""
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, updated_at FROM clips WHERE stem = ?", (row["stem"],)
            ).fetchone()

            now = _utcnow()
            if existing is None:
                cols   = ", ".join(row.keys())
                places = ", ".join("?" for _ in row)
                conn.execute(
                    f"INSERT INTO clips ({cols}) VALUES ({places})",
                    list(row.values())
                )
                return "inserted"
            else:
                # Update all fields
                sets = ", ".join(f"{k} = ?" for k in row if k != "stem")
                vals = [v for k, v in row.items() if k != "stem"]
                vals.append(now)
                vals.append(row["stem"])
                conn.execute(
                    f"UPDATE clips SET {sets}, updated_at = ? WHERE stem = ?", vals
                )
                return "updated"

    # ── Search ──────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 50, offset: int = 0) -> list:
        """
        Full-text search across model, SKU, filename, location fields.
        Falls back to LIKE search if FTS returns nothing.
        Returns list of dicts.
        """
        if not query or not query.strip():
            return self.list_all(limit=limit, offset=offset)

        q = query.strip()

        with self._conn() as conn:
            # Try FTS5 first
            try:
                fts_q = " OR ".join(f'"{w}"*' for w in q.split())
                rows = conn.execute("""
                    SELECT c.* FROM clips c
                    JOIN clips_fts fts ON fts.rowid = c.id
                    WHERE clips_fts MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                """, (fts_q, limit, offset)).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass

            # LIKE fallback
            pattern = f"%{q}%"
            rows = conn.execute("""
                SELECT * FROM clips
                WHERE  model         LIKE ?
                   OR  sku           LIKE ?
                   OR  fcp_filename  LIKE ?
                   OR  original_file LIKE ?
                   OR  loc_code      LIKE ?
                   OR  loc_name      LIKE ?
                   OR  loc_visual    LIKE ?
                   OR  loc_audio     LIKE ?
                LIMIT ? OFFSET ?
            """, (pattern,)*8 + (limit, offset)).fetchall()
            return [dict(r) for r in rows]

    def list_all(self, limit: int = 100, offset: int = 0,
                 loc_source: str = None, loc_code: str = None) -> list:
        """Return all clips with optional filters."""
        where, params = [], []
        if loc_source:
            where.append("loc_source = ?")
            params.append(loc_source)
        if loc_code:
            where.append("loc_code = ?")
            params.append(loc_code)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM clips {clause} ORDER BY shoot_date DESC, stem LIMIT ? OFFSET ?",
                params + [limit, offset]
            ).fetchall()
            return [dict(r) for r in rows]

    def get_by_stem(self, stem: str):  # -> dict | None
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM clips WHERE stem = ?", (stem,)).fetchone()
            return dict(row) if row else None

    # ── Patch ────────────────────────────────────────────────────────────────

    def patch(self, stem: str, fields: dict) -> bool:
        """Update specific fields on a clip record. Also writes back to JSON."""
        allowed = {
            "loc_code", "loc_name", "loc_source", "loc_confidence",
            "model", "colorway", "sku", "size", "price", "release_date",
            "proxy_deleted", "fcp_filename",
        }
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return False

        clean["updated_at"] = _utcnow()
        sets = ", ".join(f"{k} = ?" for k in clean)
        vals = list(clean.values()) + [stem]

        with self._conn() as conn:
            conn.execute(f"UPDATE clips SET {sets} WHERE stem = ?", vals)

        # Write-through to JSON companion file
        row = self.get_by_stem(stem)
        if row and row.get("json_path") and os.path.exists(row["json_path"]):
            try:
                with open(row["json_path"]) as fh:
                    payload = json.load(fh)
                for k, v in clean.items():
                    if k != "updated_at":
                        payload[k] = v
                payload["_patched_at"] = _utcnow()
                with open(row["json_path"], "w") as fh:
                    json.dump(payload, fh, indent=2)
            except Exception:
                pass  # JSON write-through is best-effort

        return True

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                                  AS total,
                    SUM(proxy_deleted)                        AS proxy_deleted,
                    SUM(CASE WHEN loc_source='manual'        THEN 1 ELSE 0 END) AS loc_manual,
                    SUM(CASE WHEN loc_source='ai_confirmed'  THEN 1 ELSE 0 END) AS loc_ai,
                    SUM(CASE WHEN loc_code IS NULL OR loc_code='' THEN 1 ELSE 0 END) AS loc_unknown,
                    SUM(CASE WHEN model IS NOT NULL AND model!='' THEN 1 ELSE 0 END) AS has_model,
                    SUM(CASE WHEN sku   IS NOT NULL AND sku  !='' THEN 1 ELSE 0 END) AS has_sku
                FROM clips
            """).fetchone()
            return dict(row)

    def top_locations(self, n: int = 10) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT loc_code, loc_name, COUNT(*) AS clip_count
                FROM clips
                WHERE loc_code IS NOT NULL AND loc_code != ''
                GROUP BY loc_code
                ORDER BY clip_count DESC
                LIMIT ?
            """, (n,)).fetchall()
            return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json_to_row(data: dict, stem: str, jpath: str, folder: str) -> dict:
    """Map a SACC JSON record to a clips table row dict."""
    orig = data.get("original_file", stem)

    # Derive shoot date from filename or analysed_at
    shoot_date = ""
    date_match = __import__("re").search(r"_(\d{6,8})_", orig)
    if date_match:
        raw = date_match.group(1)
        shoot_date = f"20{raw}" if len(raw) == 6 else raw

    # Build FCP filename if not stored
    loc_code = (data.get("loc_code_confirmed") or data.get("loc_code") or "")
    fcp = data.get("fcp_filename", "")
    if not fcp and orig:
        cam   = (data.get("cam_model") or "").replace(" ", "")
        locdb = _get_locdb()
        entry = locdb.get(loc_code, {})
        custom = f"{loc_code}-{entry.get('type','LOC')}" if loc_code else "UNKNOWN"
        fcp = f"{custom}_{shoot_date}_{cam}_{stem}{os.path.splitext(orig)[1]}"

    return {
        "stem":          stem,
        "original_file": orig,
        "fcp_filename":  fcp,
        "folder_path":   folder,
        "json_path":     jpath,
        "shoot_date":    shoot_date,
        "cam_make":      data.get("cam_make", ""),
        "cam_model":     data.get("cam_model", ""),
        "loc_code":      loc_code,
        "loc_name":      _get_locdb().get(loc_code, {}).get("name", ""),
        "loc_source":    data.get("loc_source", "unknown"),
        "loc_confidence":data.get("Location_Confidence", ""),
        "loc_visual":    data.get("Location_Visual", ""),
        "loc_audio":     data.get("Location_Audio", ""),
        "model":         data.get("Model", ""),
        "colorway":      data.get("colorway", "") or data.get("colorway_name", ""),
        "sku":           data.get("SKU", ""),
        "size":          data.get("Size", ""),
        "price":         data.get("Price", ""),
        "release_date":  data.get("release_date", "") or data.get("_raw_release", ""),
        "proxy_file":    data.get("proxy_file", ""),
        "proxy_deleted": 1 if data.get("proxy_deleted") else 0,
        "analysed_at":   data.get("analysed_at", ""),
    }


_locdb_cache = None
def _get_locdb():
    global _locdb_cache
    if _locdb_cache is None:
        try:
            from fcp_namer import LOCATION_DB
            _locdb_cache = LOCATION_DB
        except ImportError:
            _locdb_cache = {}
    return _locdb_cache


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CLI validation tool ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    p = argparse.ArgumentParser(description="SACC SQLite database tool")
    p.add_argument("command", choices=["sync", "search", "stats", "validate"],
                   help="sync=ingest JSONs | search=query | stats=summary | validate=integrity check")
    p.add_argument("--folder", default="/Volumes/Team Bank 12/Sneeaker Solo",
                   help="SACC output folder to sync from")
    p.add_argument("--db",     default=None,
                   help="Path to sacc.db (default: <folder>/sacc.db)")
    p.add_argument("--query",  default="",
                   help="Search query (used with search command)")

    args = p.parse_args()

    db_path = args.db or os.path.join(args.folder, "sacc.db")
    print(f"\n  Database: {db_path}")
    print(f"  Folder  : {args.folder}\n")

    db = SACCDB(db_path)

    if args.command == "sync":
        print("  Syncing JSON files → SQLite…")
        result = db.sync_from_folder(args.folder)
        print(f"  ✓ inserted  : {result.get('inserted', 0)}")
        print(f"  ✓ updated   : {result.get('updated', 0)}")
        print(f"  - skipped   : {result.get('skipped', 0)}")
        if result.get("errors"):
            print(f"  ✗ errors    : {len(result['errors'])}")
            for e in result["errors"]:
                print(f"      {e}")

    elif args.command == "search":
        if not args.query:
            print("  --query required for search command")
            sys.exit(1)
        results = db.search(args.query)
        print(f"  {len(results)} result(s) for '{args.query}':\n")
        for r in results:
            print(f"  [{r['loc_code'] or 'UNKNOWN'}] {r['model'] or '?'} | {r['sku'] or '?'} | {r['fcp_filename'] or r['stem']}")

    elif args.command == "stats":
        s = db.stats()
        print(f"  Total clips   : {s['total']}")
        print(f"  Has Model     : {s['has_model']}")
        print(f"  Has SKU       : {s['has_sku']}")
        print(f"  Loc manual    : {s['loc_manual']}")
        print(f"  Loc AI        : {s['loc_ai']}")
        print(f"  Loc unknown   : {s['loc_unknown']}")
        print(f"  Proxy deleted : {s['proxy_deleted']}")
        print()
        print("  Top locations:")
        for loc in db.top_locations(5):
            print(f"    {loc['loc_code']:8} {loc['loc_name']:30} {loc['clip_count']} clips")

    elif args.command == "validate":
        print("  Running integrity checks…")
        rows = db.list_all(limit=10000)
        missing_json = [r for r in rows if r["json_path"] and not os.path.exists(r["json_path"])]
        no_model     = [r for r in rows if not r["model"]]
        no_loc       = [r for r in rows if not r["loc_code"]]
        print(f"  Total records     : {len(rows)}")
        print(f"  Missing JSON file : {len(missing_json)}")
        print(f"  No model detected : {len(no_model)}")
        print(f"  No location       : {len(no_loc)}")
        if not missing_json and not no_model and not no_loc:
            print("\n  ✓ All records pass integrity check")
        else:
            print("\n  ⚠ Issues found — run 'sync' to re-import updated JSONs")

    print()

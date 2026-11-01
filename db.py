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
    dominant_color  TEXT,                   -- e.g. "Red"
    secondary_color TEXT,                   -- e.g. "White"
    sku             TEXT,                   -- e.g. "555088-101"
    size            TEXT,
    price           TEXT,                   -- observed / current shelf price (Price_Observed)
    price_retail    TEXT,                   -- MSRP / suggested retail if visible
    price_type      TEXT,                   -- "retail"|"outlet"|"sale"|"hash_wall"|"unknown"
    is_hash_wall    INTEGER DEFAULT 0,      -- 1 = clearance sticker dots detected
    price_audio     TEXT,                   -- price mentioned verbally in audio
    release_date    TEXT,                   -- product release date YYYY or YYYY-MM-DD

    -- Shot context (affects metadata completeness rules)
    shot_context    TEXT DEFAULT 'unknown', -- "in_store" | "at_home" | "vlog" | "unknown"

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

-- Drop events: timestamped box-drop moments extracted by Gemini
CREATE TABLE IF NOT EXISTS drop_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_stem     TEXT NOT NULL,
    timestamp_sec REAL NOT NULL,
    confidence    REAL,
    shoe_id       TEXT,
    sku           TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (clip_stem) REFERENCES clips(stem)
);

CREATE INDEX IF NOT EXISTS idx_drop_events_clip_stem ON drop_events(clip_stem);
CREATE INDEX IF NOT EXISTS idx_drop_events_sku       ON drop_events(sku);

-- Price observations: one row per clip that contains pricing data
-- Enables longitudinal value-decay and hash-wall tracking per SKU
CREATE TABLE IF NOT EXISTS price_observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_stem       TEXT NOT NULL,
    sku             TEXT,
    model           TEXT,
    shoot_date      TEXT,
    price_retail    TEXT,           -- MSRP from hang tag or signage
    price_observed  TEXT,           -- current shelf / sticker price
    price_audio     TEXT,           -- price mentioned verbally
    price_type      TEXT,           -- "retail"|"outlet"|"sale"|"hash_wall"|"unknown"
    is_hash_wall    INTEGER DEFAULT 0,
    markdown_pct    REAL,           -- (retail - observed) / retail × 100
    source          TEXT DEFAULT 'gemini',
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (clip_stem) REFERENCES clips(stem)
);

CREATE INDEX IF NOT EXISTS idx_price_obs_clip_stem ON price_observations(clip_stem);
CREATE INDEX IF NOT EXISTS idx_price_obs_sku       ON price_observations(sku);
CREATE INDEX IF NOT EXISTS idx_price_obs_type      ON price_observations(price_type);

-- Shoes: canonical identity record — one row per SKU, immutable baseline
-- This is the anchor for the one-to-many price_observations relationship.
-- msrp and release_date are set once from the whitelist and never overwritten
-- by video observations (which may show markdown stickers, not original retail).
CREATE TABLE IF NOT EXISTS shoes (
    sku             TEXT PRIMARY KEY,
    model           TEXT NOT NULL,
    colorway        TEXT,
    brand           TEXT,
    silhouette      TEXT,
    msrp            TEXT,           -- original MSRP (fixed baseline — never overwrite)
    release_date    TEXT,           -- original release date YYYY or YYYY-MM-DD (fixed)
    release_year    INTEGER,
    notes           TEXT,
    source          TEXT DEFAULT 'whitelist',  -- "whitelist" | "gemini" | "manual"
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ── SACCDB class ──────────────────────────────────────────────────────────────

class SACCDB:
    """Thread-safe SQLite wrapper for the SACC pipeline database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
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

            # Create base tables first so ALTERs below have something to target
            # (on a fresh DB the ALTERs would otherwise silently no-op).
            conn.executescript(_DDL)

            # Add columns introduced after v1 schema (no-op if already present)
            for col, defn in [
                ("colorway",       "TEXT"),
                ("release_date",   "TEXT"),
                ("dominant_color", "TEXT"),
                ("secondary_color","TEXT"),
                ("shot_context",   "TEXT DEFAULT 'unknown'"),
                ("price_retail",   "TEXT"),
                ("price_type",     "TEXT"),
                ("is_hash_wall",   "INTEGER DEFAULT 0"),
                ("price_audio",    "TEXT"),
                ("video_width",    "INTEGER"),
                ("video_height",   "INTEGER"),
                ("orientation",    "TEXT"),  # 'vertical' | 'horizontal' | 'square'
            ]:
                try:
                    conn.execute(f"ALTER TABLE clips ADD COLUMN {col} {defn}")
                except Exception:
                    pass

            if needs_fts_rebuild:
                try:
                    conn.execute("INSERT INTO clips_fts(clips_fts) VALUES('rebuild')")
                except Exception:
                    pass

    # ── Sync from folder ────────────────────────────────────────────────────

    _BATCH_SIZE = 500  # rows per executemany call — safe under SQLite variable limit

    def sync_from_folder(self, folder: str) -> dict:
        """
        Walk <folder>/json/ and upsert every SACC JSON into the database.
        Uses batch executemany with ON CONFLICT UPSERT for high-speed ingestion
        (handles 100k+ records without hitting SQLite's variable limit).
        Returns a summary dict: {upserted, errors}.
        """
        json_dir = os.path.join(folder, "json")
        if not os.path.isdir(json_dir):
            return {"error": f"json/ directory not found in {folder}"}

        results: dict = {"upserted": 0, "errors": [], "drop_events": 0, "price_observations": 0}
        rows: list = []
        drops_by_stem: dict = {}
        price_obs_list: list = []

        for fname in sorted(os.listdir(json_dir)):
            if not fname.endswith(".json"):
                continue
            jpath = os.path.join(json_dir, fname)
            try:
                with open(jpath) as fh:
                    data = json.load(fh)
                stem = os.path.splitext(fname)[0]
                rows.append(_json_to_row(data, stem, jpath, folder))
                events = data.get("drop_events") or data.get("Drop_Events")
                if isinstance(events, list) and events:
                    drops_by_stem[stem] = events
                obs = _extract_price_obs(data, stem)
                if obs:
                    price_obs_list.append(obs)
            except Exception as e:
                results["errors"].append(f"{fname}: {e}")

        if not rows:
            return results

        cols = list(rows[0].keys())
        placeholders = ", ".join("?" * len(cols))
        update_sets = ", ".join(
            f"{c}=excluded.{c}" for c in cols if c != "stem"
        )
        sql = (
            f"INSERT INTO clips ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(stem) DO UPDATE SET {update_sets}"
        )

        with self._conn() as conn:
            for i in range(0, len(rows), self._BATCH_SIZE):
                batch = rows[i : i + self._BATCH_SIZE]
                conn.executemany(sql, [list(r.values()) for r in batch])

        results["upserted"] = len(rows)

        for stem, events in drops_by_stem.items():
            results["drop_events"] += self.insert_drop_events(stem, events)

        for obs in price_obs_list:
            if self.insert_price_observation(obs["clip_stem"], obs):
                results["price_observations"] += 1

        return results

    def sync_archive_recursive(self, root: str) -> dict:
        """
        Walk <root> and ingest every <shoot_day>/json/*.json found at any depth.
        Each row's folder_path is set to its shoot-day folder (the parent of the
        json/ dir), so videos remain locatable even though the central DB lives
        elsewhere. Decouples the unified database from per-shoot video paths.
        Returns: {folders_scanned, upserted, errors, drop_events, price_observations}.
        """
        if not os.path.isdir(root):
            return {"error": f"root folder not found: {root}"}

        results: dict = {
            "folders_scanned": 0, "upserted": 0, "errors": [],
            "drop_events": 0, "price_observations": 0,
        }
        rows: list = []
        drops_by_stem: dict = {}
        price_obs_list: list = []

        for dirpath, dirnames, _filenames in os.walk(root):
            # Skip the json/ dirs themselves and any hidden/proxy noise
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_proxy"]
            if "json" not in dirnames:
                continue
            json_dir = os.path.join(dirpath, "json")
            if not os.path.isdir(json_dir):
                continue
            results["folders_scanned"] += 1
            for fname in sorted(os.listdir(json_dir)):
                if not fname.endswith(".json"):
                    continue
                jpath = os.path.join(json_dir, fname)
                try:
                    with open(jpath) as fh:
                        data = json.load(fh)
                    stem = os.path.splitext(fname)[0]
                    rows.append(_json_to_row(data, stem, jpath, dirpath))
                    events = data.get("drop_events") or data.get("Drop_Events")
                    if isinstance(events, list) and events:
                        drops_by_stem[stem] = events
                    obs = _extract_price_obs(data, stem)
                    if obs:
                        price_obs_list.append(obs)
                except Exception as e:
                    results["errors"].append(f"{fname}: {e}")

        if not rows:
            return results

        cols = list(rows[0].keys())
        placeholders = ", ".join("?" * len(cols))
        update_sets = ", ".join(
            f"{c}=excluded.{c}" for c in cols if c != "stem"
        )
        sql = (
            f"INSERT INTO clips ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(stem) DO UPDATE SET {update_sets}"
        )

        with self._conn() as conn:
            for i in range(0, len(rows), self._BATCH_SIZE):
                batch = rows[i : i + self._BATCH_SIZE]
                conn.executemany(sql, [list(r.values()) for r in batch])

        results["upserted"] = len(rows)

        for stem, events in drops_by_stem.items():
            results["drop_events"] += self.insert_drop_events(stem, events)

        for obs in price_obs_list:
            if self.insert_price_observation(obs["clip_stem"], obs):
                results["price_observations"] += 1

        return results

    # ── Search ──────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 50, offset: int = 0,
               orientation: str = "all") -> list:
        """
        Full-text search across model, SKU, filename, location fields.
        Falls back to LIKE search if FTS returns nothing.
        orientation: 'all' | 'vertical' | 'horizontal' | 'square'
        Returns list of dicts.
        """
        if not query or not query.strip():
            return self.list_all(limit=limit, offset=offset, orientation=orientation)

        q = query.strip()
        ori_clause, ori_params = "", []
        if orientation in ("vertical", "horizontal", "square"):
            ori_clause = " AND c.orientation = ?"
            ori_params = [orientation]

        with self._conn() as conn:
            # Try FTS5 first.
            # AND between tokens — "Jordan 8" must match BOTH, not either, so
            # Kobe 8 / Air Max '86 / "860v2" don't pollute brand-keyed queries.
            # Weighted bm25 favors product-identity columns (model/colorway/sku)
            # over the long descriptive blobs in loc_visual/loc_audio. Column
            # order matches the clips_fts schema:
            #   stem, original_file, fcp_filename, model, colorway, sku,
            #   loc_code, loc_name, loc_visual, loc_audio
            try:
                # Prefix-match alpha tokens ("Jord*" → Jordan), exact-match
                # pure-digit tokens ("8" stays "8") so model number "8" doesn't
                # leak into Air Jordan 3/5/12 via SKU prefixes like "854262".
                def _term(w: str) -> str:
                    return f'"{w}"' if w.isdigit() else f'"{w}"*'
                fts_q = " AND ".join(_term(w) for w in q.split())
                rank_expr = "bm25(clips_fts, 1.0, 1.0, 1.0, 5.0, 3.0, 5.0, 1.0, 1.0, 0.3, 0.3)"
                rows = conn.execute(f"""
                    SELECT c.* FROM clips c
                    JOIN clips_fts fts ON fts.rowid = c.id
                    WHERE clips_fts MATCH ?{ori_clause}
                    ORDER BY {rank_expr}
                    LIMIT ? OFFSET ?
                """, (fts_q, *ori_params, limit, offset)).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass

            # LIKE fallback
            pattern = f"%{q}%"
            like_ori = ori_clause.replace("c.orientation", "orientation") if ori_clause else ""
            rows = conn.execute(f"""
                SELECT * FROM clips
                WHERE (model         LIKE ?
                   OR  sku           LIKE ?
                   OR  fcp_filename  LIKE ?
                   OR  original_file LIKE ?
                   OR  loc_code      LIKE ?
                   OR  loc_name      LIKE ?
                   OR  loc_visual    LIKE ?
                   OR  loc_audio     LIKE ?){like_ori}
                LIMIT ? OFFSET ?
            """, (pattern,)*8 + tuple(ori_params) + (limit, offset)).fetchall()
            return [dict(r) for r in rows]

    def list_all(self, limit: int = 100, offset: int = 0,
                 loc_source: str = None, loc_code: str = None,
                 orientation: str = "all") -> list:
        """Return all clips with optional filters."""
        where, params = [], []
        if loc_source:
            where.append("loc_source = ?")
            params.append(loc_source)
        if loc_code:
            where.append("loc_code = ?")
            params.append(loc_code)
        if orientation in ("vertical", "horizontal", "square"):
            where.append("orientation = ?")
            params.append(orientation)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM clips {clause} ORDER BY shoot_date DESC, stem LIMIT ? OFFSET ?",
                params + [limit, offset]
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Orientation backfill ────────────────────────────────────────────────

    def backfill_orientation(self, only_missing: bool = True) -> dict:
        """
        ffprobe each clip's video file and write video_width / video_height /
        orientation back to the row. Idempotent.
        Returns counts: scanned, updated, skipped_missing_file, errors.
        """
        import os, json as _json, subprocess
        ffprobe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffprobe")
        if not os.path.exists(ffprobe):
            ffprobe = "ffprobe"

        sql = "SELECT id, stem, original_file, folder_path, orientation FROM clips"
        if only_missing:
            sql += " WHERE orientation IS NULL OR orientation = ''"

        scanned = updated = skipped = errors = 0
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
            for r in rows:
                scanned += 1
                folder = r["folder_path"] or ""
                orig   = r["original_file"] or ""
                stem   = r["stem"] or ""
                # Try original_file first; fall back to stem.{mov,mp4}
                candidates = []
                if folder and orig:
                    candidates.append(os.path.join(folder, orig))
                if folder and stem:
                    candidates += [os.path.join(folder, f"{stem}.mov"),
                                   os.path.join(folder, f"{stem}.mp4"),
                                   os.path.join(folder, f"{stem}.MOV"),
                                   os.path.join(folder, f"{stem}.MP4")]
                video = next((p for p in candidates if os.path.exists(p)), None)
                if not video:
                    skipped += 1
                    continue
                try:
                    # -show_streams pulls side_data_list (Display Matrix) so we
                    # can detect rotation. Without it, iPhone/cinema files
                    # stored as 3840x2160 with rotate=-90 look horizontal even
                    # though every player shows them vertical.
                    out = subprocess.run(
                        [ffprobe, "-v", "quiet", "-print_format", "json",
                         "-select_streams", "v:0", "-show_streams", video],
                        capture_output=True, text=True, timeout=15,
                    )
                    data = _json.loads(out.stdout or "{}")
                    streams = data.get("streams", [])
                    if not streams:
                        errors += 1
                        continue
                    s = streams[0]
                    w = int(s.get("width") or 0)
                    h = int(s.get("height") or 0)
                    if w <= 0 or h <= 0:
                        errors += 1
                        continue
                    rot = 0
                    tag_rot = (s.get("tags") or {}).get("rotate")
                    if tag_rot is not None:
                        try: rot = int(tag_rot)
                        except Exception: rot = 0
                    for sd in s.get("side_data_list") or []:
                        sd_rot = sd.get("rotation")
                        if sd_rot is not None:
                            try:
                                rot = int(sd_rot)
                                break
                            except Exception:
                                pass
                    if abs(rot) % 180 == 90:
                        w, h = h, w
                    ori = "vertical" if h > w else "horizontal" if w > h else "square"
                    conn.execute(
                        "UPDATE clips SET video_width=?, video_height=?, orientation=?, "
                        "updated_at=datetime('now') WHERE id=?",
                        (w, h, ori, r["id"])
                    )
                    updated += 1
                except Exception:
                    errors += 1
        return {"scanned": scanned, "updated": updated,
                "skipped_missing_file": skipped, "errors": errors}

    def get_by_stem(self, stem: str):  # -> dict | None
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM clips WHERE stem = ?", (stem,)).fetchone()
            return dict(row) if row else None

    # ── Patch ────────────────────────────────────────────────────────────────

    def patch(self, stem: str, fields: dict) -> bool:
        """Update specific fields on a clip record. Also writes back to JSON."""
        allowed = {
            "loc_code", "loc_name", "loc_source", "loc_confidence",
            "model", "colorway", "dominant_color", "secondary_color",
            "sku", "size", "price", "release_date",
            "shot_context", "proxy_deleted", "fcp_filename",
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


    def model_breakdown(self, limit: int = 25) -> dict:
        with self._conn() as conn:
            unique_models = conn.execute(
                "SELECT COUNT(DISTINCT model) FROM clips WHERE model IS NOT NULL AND model != ''"
            ).fetchone()[0]
            unique_skus = conn.execute(
                "SELECT COUNT(DISTINCT sku) FROM clips WHERE sku IS NOT NULL AND sku != ''"
            ).fetchone()[0]
            top_models = conn.execute("""
                SELECT model, COUNT(*) AS clip_count
                FROM clips
                WHERE model IS NOT NULL AND model != ''
                GROUP BY model
                ORDER BY clip_count DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return {
                "unique_models": unique_models,
                "unique_skus":   unique_skus,
                "top_models":    [dict(r) for r in top_models],
            }

    # ── Drop events ──────────────────────────────────────────────────────────

    def insert_drop_events(self, clip_stem: str, events: list) -> int:
        """Replace all drop events for clip_stem and insert the new list."""
        if not events:
            return 0
        rows = []
        for e in events:
            if not isinstance(e, dict) or e.get("timestamp_sec") is None:
                continue
            try:
                ts = float(e["timestamp_sec"])
            except (TypeError, ValueError):
                continue
            conf = e.get("confidence")
            try:
                conf = round(float(conf), 3) if conf is not None else None
            except (TypeError, ValueError):
                conf = None
            rows.append((
                clip_stem,
                ts,
                conf,
                str(e.get("shoe_id") or "").strip(),
                str(e.get("sku")     or "").strip(),
                str(e.get("notes")   or "").strip(),
            ))
        if not rows:
            return 0
        with self._conn() as conn:
            conn.execute("DELETE FROM drop_events WHERE clip_stem = ?", (clip_stem,))
            conn.executemany(
                "INSERT INTO drop_events "
                "(clip_stem, timestamp_sec, confidence, shoe_id, sku, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def get_drops(self, sku: str = None, year: str = None,
                  min_confidence: float = None,
                  limit: int = 100, offset: int = 0) -> list:
        """Query drop events joined to clip metadata."""
        where, params = [], []
        if sku:
            where.append("(de.sku = ? OR de.shoe_id LIKE ?)")
            params.extend([sku, f"%{sku}%"])
        if year:
            where.append("strftime('%Y', c.shoot_date) = ?")
            params.append(str(year))
        if min_confidence is not None:
            where.append("de.confidence >= ?")
            params.append(float(min_confidence))
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT de.id, de.clip_stem, de.timestamp_sec, de.confidence,
                       de.shoe_id, de.sku, de.notes, de.created_at,
                       c.shoot_date, c.loc_code, c.loc_name,
                       c.folder_path, c.fcp_filename
                FROM drop_events de
                LEFT JOIN clips c ON c.stem = de.clip_stem
                {clause}
                ORDER BY c.shoot_date DESC, de.timestamp_sec
                LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()
            return [dict(r) for r in rows]

    def drop_stats(self) -> list:
        """Annual tally of drop events grouped by shoot year."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT strftime('%Y', c.shoot_date)  AS year,
                       COUNT(de.id)                  AS drop_count,
                       COUNT(DISTINCT de.sku)        AS unique_shoes,
                       COUNT(DISTINCT de.clip_stem)  AS clips_with_drops
                FROM drop_events de
                LEFT JOIN clips c ON c.stem = de.clip_stem
                GROUP BY year
                ORDER BY year DESC
            """).fetchall()
            return [dict(r) for r in rows]

    # ── Price observations ────────────────────────────────────────────────────

    def insert_price_observation(self, clip_stem: str, data: dict) -> bool:
        """
        Log a price observation for a clip. Replaces any existing row for
        the same clip_stem. Returns False if no pricing data is present.

        markdown_pct is computed against shoes.msrp (canonical MSRP) when
        available, falling back to price_retail visible in the video. This
        ensures the decay chain is always measured from the original retail
        baseline, not from an intermediate markdown.
        """
        price_observed = data.get("price_observed") or data.get("Price_Observed") or ""
        price_retail   = data.get("price_retail")   or data.get("Price_Retail")   or ""
        price_audio    = data.get("price_audio")    or data.get("Price_Audio")    or ""
        if not any([price_observed, price_retail, price_audio]):
            return False

        sku = data.get("sku") or data.get("SKU") or ""

        import re as _re

        with self._conn() as conn:
            # Prefer canonical MSRP from shoes table over video-observed retail price
            retail_for_calc = price_retail
            if sku:
                shoe_row = conn.execute(
                    "SELECT msrp FROM shoes WHERE sku = ?", (sku,)
                ).fetchone()
                if shoe_row and shoe_row["msrp"]:
                    retail_for_calc = shoe_row["msrp"]

            # Compute markdown always against canonical MSRP
            markdown_pct = None
            try:
                r_val = float(_re.sub(r"[^\d.]", "", retail_for_calc)) if retail_for_calc else 0
                o_val = float(_re.sub(r"[^\d.]", "", price_observed))  if price_observed else 0
                if r_val > 0 and o_val > 0 and o_val < r_val:
                    markdown_pct = round((r_val - o_val) / r_val * 100, 1)
            except (ValueError, TypeError):
                pass

            conn.execute(
                "DELETE FROM price_observations WHERE clip_stem = ?", (clip_stem,)
            )
            conn.execute(
                """INSERT INTO price_observations
                   (clip_stem, sku, model, shoot_date,
                    price_retail, price_observed, price_audio,
                    price_type, is_hash_wall, markdown_pct, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    clip_stem, sku,
                    data.get("model") or data.get("Model") or "",
                    data.get("shoot_date") or "",
                    price_retail,
                    price_observed,
                    price_audio,
                    data.get("price_type") or data.get("Price_Type") or "",
                    1 if (data.get("is_hash_wall") or data.get("Is_Hash_Wall")) else 0,
                    markdown_pct,
                    data.get("source", "gemini"),
                ),
            )
        return True

    def get_price_history(self, sku: str, limit: int = 50) -> list:
        """All price observations for a SKU ordered chronologically."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT po.*, c.loc_code, c.loc_name, c.folder_path
                   FROM price_observations po
                   LEFT JOIN clips c ON c.stem = po.clip_stem
                   WHERE po.sku = ?
                   ORDER BY po.shoot_date ASC
                   LIMIT ?""",
                (sku, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def shoe_lifecycle(self, sku: str) -> dict:
        """
        Aggregated lifecycle stats for a SKU: sighting count, first/last seen,
        price range, hash wall status, and inferred lifecycle stage.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT
                       COUNT(*)                                              AS sighting_count,
                       MIN(po.shoot_date)                                   AS first_seen,
                       MAX(po.shoot_date)                                   AS last_seen,
                       MAX(CASE WHEN po.price_retail  != '' THEN po.price_retail  END) AS msrp,
                       MIN(CASE WHEN po.price_observed != '' THEN po.price_observed END) AS floor_price,
                       MAX(CASE WHEN po.price_observed != '' THEN po.price_observed END) AS ceiling_price,
                       MAX(po.markdown_pct)                                 AS max_markdown_pct,
                       MAX(po.is_hash_wall)                                 AS hash_wall_confirmed,
                       GROUP_CONCAT(DISTINCT po.price_type)                 AS price_types_seen,
                       GROUP_CONCAT(DISTINCT c.loc_code)                    AS locations
                   FROM price_observations po
                   LEFT JOIN clips c ON c.stem = po.clip_stem
                   WHERE po.sku = ?""",
                (sku,),
            ).fetchone()

        if not row or not row["sighting_count"]:
            return {}

        d = dict(row)
        types = d.get("price_types_seen") or ""
        if d.get("hash_wall_confirmed") or "hash_wall" in types:
            stage = "hash_wall"
        elif "clearance" in types:
            stage = "clearance"
        elif "outlet" in types:
            stage = "outlet"
        elif "sale" in types:
            stage = "sale"
        elif "retail" in types:
            stage = "retail"
        else:
            stage = "unknown"
        d["lifecycle_stage"] = stage
        return d

    def hash_wall_clips(self, limit: int = 100) -> list:
        """All clips that document hash wall / clearance sightings."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT po.clip_stem, po.sku, po.model, po.shoot_date,
                          po.price_retail, po.price_observed, po.markdown_pct,
                          po.price_type, po.notes,
                          c.loc_code, c.loc_name, c.fcp_filename
                   FROM price_observations po
                   LEFT JOIN clips c ON c.stem = po.clip_stem
                   WHERE po.is_hash_wall = 1 OR po.price_type = 'hash_wall'
                   ORDER BY po.shoot_date DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def value_decay_report(self, min_markdown_pct: float = 30.0) -> list:
        """
        Shoes with documented value decay above min_markdown_pct.
        One row per SKU with full lifecycle summary.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT
                       po.sku,
                       MAX(po.model)            AS model,
                       MAX(po.price_retail)     AS msrp,
                       MIN(po.price_observed)   AS floor_price,
                       MAX(po.markdown_pct)     AS max_markdown_pct,
                       MAX(po.is_hash_wall)     AS hash_wall,
                       COUNT(*)                 AS sighting_count,
                       MIN(po.shoot_date)       AS first_seen,
                       MAX(po.shoot_date)       AS last_seen,
                       GROUP_CONCAT(DISTINCT c.loc_code) AS locations
                   FROM price_observations po
                   LEFT JOIN clips c ON c.stem = po.clip_stem
                   WHERE po.markdown_pct >= ?
                   GROUP BY po.sku
                   ORDER BY max_markdown_pct DESC""",
                (min_markdown_pct,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Shoe identity (canonical baseline) ───────────────────────────────────

    def populate_shoes_from_whitelist(self, whitelist: dict) -> dict:
        """
        Upsert canonical shoe records from Master_Whitelist_v1.
        msrp and release_date are written once and never overwritten by
        subsequent calls — they are the fixed historical baseline.

        Call with the dict returned by release_matcher.load_whitelist().
        Returns {"upserted": N}.
        """
        import re as _re
        rows = []
        for sku, entry in whitelist.items():
            if not isinstance(entry, dict):
                continue
            release_date = str(entry.get("release_date") or "")
            m = _re.search(r"\b(19|20)\d{2}\b", release_date)
            release_year = int(m.group()) if m else None
            raw_price = entry.get("retail_price") or entry.get("msrp") or ""
            msrp = f"${raw_price}" if raw_price and not str(raw_price).startswith("$") else str(raw_price)
            rows.append((
                sku,
                entry.get("silhouette") or entry.get("model_name") or entry.get("model") or "",
                entry.get("colorway_name") or entry.get("colorway") or "",
                entry.get("brand") or "",
                entry.get("silhouette") or "",
                msrp or None,
                release_date or None,
                release_year,
                entry.get("notes") or "",
                "whitelist",
            ))
        if not rows:
            return {"upserted": 0}
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO shoes
                   (sku, model, colorway, brand, silhouette, msrp,
                    release_date, release_year, notes, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(sku) DO UPDATE SET
                       model        = excluded.model,
                       colorway     = excluded.colorway,
                       brand        = excluded.brand,
                       silhouette   = excluded.silhouette,
                       msrp         = COALESCE(shoes.msrp, excluded.msrp),
                       release_date = COALESCE(shoes.release_date, excluded.release_date),
                       release_year = COALESCE(shoes.release_year, excluded.release_year),
                       notes        = excluded.notes,
                       updated_at   = datetime('now')""",
                rows,
            )
        return {"upserted": len(rows)}

    def ensure_shoe(self, sku: str, data: dict) -> bool:
        """
        Create a shoes record from Gemini clip data if one doesn't exist.
        Only inserts — never overwrites an existing record. Use
        populate_shoes_from_whitelist() for authoritative baseline data.
        Returns True if a new record was created.
        """
        if not sku:
            return False
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT sku FROM shoes WHERE sku = ?", (sku,)
            ).fetchone()
            if existing:
                return False
            conn.execute(
                """INSERT OR IGNORE INTO shoes
                   (sku, model, colorway, msrp, release_date, source)
                   VALUES (?, ?, ?, ?, ?, 'gemini')""",
                (
                    sku,
                    data.get("model") or data.get("Model") or "",
                    data.get("colorway") or "",
                    data.get("Price_Retail") or data.get("price_retail") or None,
                    data.get("release_date") or None,
                ),
            )
        return True

    def get_decay_chain(self, sku: str) -> dict:
        """
        Full price-decay chain for a SKU.

        Returns:
          {
            "shoe":     { sku, model, colorway, msrp, release_date, ... },
            "sightings": [
              {
                sighting_number,   -- 1st, 2nd, 3rd... appearance (by shoot_date)
                shoot_date,
                loc_code, loc_name,
                price_observed,
                price_retail,      -- what was on tag (may differ from shoes.msrp)
                price_audio,
                price_type,
                is_hash_wall,
                markdown_vs_msrp,  -- always vs shoes.msrp; null if msrp unknown
                fcp_filename,
              },
              ...
            ]
          }
        """
        import re as _re

        with self._conn() as conn:
            shoe = conn.execute(
                "SELECT * FROM shoes WHERE sku = ?", (sku,)
            ).fetchone()

            rows = conn.execute(
                """SELECT
                       ROW_NUMBER() OVER (
                           PARTITION BY po.sku ORDER BY po.shoot_date
                       )                       AS sighting_number,
                       po.clip_stem,
                       po.shoot_date,
                       po.price_retail,
                       po.price_observed,
                       po.price_audio,
                       po.price_type,
                       po.is_hash_wall,
                       po.markdown_pct,
                       po.notes,
                       c.loc_code,
                       c.loc_name,
                       c.fcp_filename
                   FROM price_observations po
                   LEFT JOIN clips c ON c.stem = po.clip_stem
                   WHERE po.sku = ?
                   ORDER BY po.shoot_date ASC""",
                (sku,),
            ).fetchall()

        shoe_dict = dict(shoe) if shoe else {"sku": sku}

        # Extract numeric MSRP once for markdown computation
        msrp_val = None
        try:
            msrp_str = shoe_dict.get("msrp") or ""
            msrp_val = float(_re.sub(r"[^\d.]", "", msrp_str)) if msrp_str else None
        except (ValueError, TypeError):
            pass

        sightings = []
        for row in rows:
            s = dict(row)
            # Compute markdown_vs_msrp — always measured from the original retail
            # baseline regardless of what was on the tag in the video
            if msrp_val and s.get("price_observed"):
                try:
                    obs = float(_re.sub(r"[^\d.]", "", str(s["price_observed"])))
                    s["markdown_vs_msrp"] = round(
                        (msrp_val - obs) / msrp_val * 100, 1
                    ) if msrp_val > 0 else None
                except (ValueError, TypeError):
                    s["markdown_vs_msrp"] = None
            else:
                s["markdown_vs_msrp"] = None
            sightings.append(s)

        return {"shoe": shoe_dict, "sightings": sightings}

    def validation_summary(self) -> dict:
        """Return a completeness tally for every key metadata field."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN sku            IS NOT NULL AND sku            != '' THEN 1 ELSE 0 END) AS has_sku,
                    SUM(CASE WHEN colorway       IS NOT NULL AND colorway       != '' THEN 1 ELSE 0 END) AS has_colorway,
                    SUM(CASE WHEN price          IS NOT NULL AND price          != '' THEN 1 ELSE 0 END) AS has_price,
                    SUM(CASE WHEN release_date   IS NOT NULL AND release_date   != '' THEN 1 ELSE 0 END) AS has_release_date,
                    SUM(CASE WHEN dominant_color IS NOT NULL AND dominant_color != '' THEN 1 ELSE 0 END) AS has_dominant_color,
                    SUM(CASE WHEN model          IS NOT NULL AND model          != '' THEN 1 ELSE 0 END) AS has_model,
                    SUM(CASE WHEN loc_code       IS NOT NULL AND loc_code       != '' THEN 1 ELSE 0 END) AS has_location,
                    SUM(CASE WHEN shot_context = 'in_store'  THEN 1 ELSE 0 END) AS ctx_in_store,
                    SUM(CASE WHEN shot_context = 'at_home'   THEN 1 ELSE 0 END) AS ctx_at_home,
                    SUM(CASE WHEN shot_context = 'vlog'      THEN 1 ELSE 0 END) AS ctx_vlog,
                    SUM(CASE WHEN shot_context = 'unknown'   THEN 1 ELSE 0 END) AS ctx_unknown
                FROM clips
            """).fetchone()
            d = dict(row)
            t = d['total'] or 1
            return {
                "total": d['total'],
                "matched_all":   sum(1 for _ in [0] if d['has_sku'] == d['total']
                                     and d['has_colorway'] == d['total']
                                     and d['has_price'] == d['total']),
                "fields": {
                    "model":         {"count": d['has_model'],        "missing": d['total'] - d['has_model'],        "pct": round(100*d['has_model']/t)},
                    "sku":           {"count": d['has_sku'],          "missing": d['total'] - d['has_sku'],          "pct": round(100*d['has_sku']/t)},
                    "colorway":      {"count": d['has_colorway'],     "missing": d['total'] - d['has_colorway'],     "pct": round(100*d['has_colorway']/t)},
                    "price":         {"count": d['has_price'],        "missing": d['total'] - d['has_price'],        "pct": round(100*d['has_price']/t)},
                    "release_date":  {"count": d['has_release_date'], "missing": d['total'] - d['has_release_date'], "pct": round(100*d['has_release_date']/t)},
                    "dominant_color":{"count": d['has_dominant_color'],"missing":d['total'] - d['has_dominant_color'],"pct": round(100*d['has_dominant_color']/t)},
                    "location":      {"count": d['has_location'],     "missing": d['total'] - d['has_location'],     "pct": round(100*d['has_location']/t)},
                },
                "shot_context": {
                    "in_store": d['ctx_in_store'],
                    "at_home":  d['ctx_at_home'],
                    "vlog":     d['ctx_vlog'],
                    "unknown":  d['ctx_unknown'],
                },
            }


# ── Helpers ───────────────────────────────────────────────────────────────────

_LOC_PREFIX_RE = __import__("re").compile(r"^([A-Z0-9]+)-[A-Z]+_\d{6,8}_")


def _json_to_row(data: dict, stem: str, jpath: str, folder: str) -> dict:
    """Map a SACC JSON record to a clips table row dict."""
    orig = data.get("original_file", stem)

    # Derive shoot date from filename or analysed_at
    shoot_date = ""
    date_match = __import__("re").search(r"_(\d{6,8})_", orig)
    if date_match:
        raw = date_match.group(1)
        shoot_date = f"20{raw}" if len(raw) == 6 else raw

    # loc_code resolution chain:
    #   1. legacy keys (pre-v2.1 JSONs from Gemini's old location extraction)
    #   2. LOC-TYPE_ prefix of the filename — primary source under v2.1 since
    #      the rename bakes in the venue verdict (--loc / GPS / anchor) before
    #      Stage 8, and Gemini stopped emitting loc_code in the rewrite.
    #   3. loc_code_anchor written by Stage 9 cross-check
    loc_code = (data.get("loc_code_confirmed") or data.get("loc_code") or "")
    loc_source = ""
    if loc_code:
        loc_source = "ai_confirmed" if data.get("loc_code_confirmed") else "json"
    else:
        m = _LOC_PREFIX_RE.match(orig)
        if m and m.group(1) in _get_locdb():
            loc_code = m.group(1)
            loc_source = "filename"
        elif data.get("loc_code_anchor"):
            loc_code = data["loc_code_anchor"]
            loc_source = "anchor"

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
        "loc_source":    data.get("loc_source") or loc_source or "unknown",
        "loc_confidence":data.get("Location_Confidence", ""),
        "loc_visual":    data.get("Location_Visual", ""),
        "loc_audio":     data.get("Location_Audio", ""),
        "model":          data.get("Model", ""),
        "colorway":       data.get("colorway", "") or data.get("colorway_name", ""),
        "dominant_color": data.get("dominant_color", ""),
        "secondary_color":data.get("secondary_color", ""),
        "sku":           data.get("SKU", ""),
        "size":          data.get("Size", ""),
        "price":         data.get("Price_Observed") or data.get("Price", ""),
        "price_retail":  data.get("Price_Retail")  or data.get("price_retail", ""),
        "price_type":    data.get("Price_Type")    or data.get("price_type", ""),
        "is_hash_wall":  1 if (data.get("Is_Hash_Wall") or data.get("is_hash_wall")) else 0,
        "price_audio":   data.get("Price_Audio")   or data.get("price_audio", ""),
        "release_date":  data.get("release_date", "") or data.get("_raw_release", ""),
        "shot_context":  data.get("shot_context", "unknown"),
        "proxy_file":    data.get("proxy_file", ""),
        "proxy_deleted": 1 if data.get("proxy_deleted") else 0,
        "analysed_at":   data.get("analysed_at", ""),
    }


def _extract_price_obs(data: dict, stem: str):
    """
    Extract a price observation dict from a SACC JSON record.
    Returns None if no pricing data is present.
    """
    price_observed = data.get("Price_Observed") or data.get("Price") or ""
    price_retail   = data.get("Price_Retail")   or data.get("price_retail") or ""
    price_audio    = data.get("Price_Audio")    or data.get("price_audio") or ""
    if not any([price_observed, price_retail, price_audio]):
        return None
    return {
        "clip_stem":      stem,
        "sku":            data.get("SKU")        or data.get("sku")        or "",
        "model":          data.get("Model")      or data.get("model")      or "",
        "shoot_date":     data.get("shoot_date") or "",
        "price_retail":   price_retail,
        "price_observed": price_observed,
        "price_audio":    price_audio,
        "price_type":     data.get("Price_Type") or data.get("price_type") or "",
        "is_hash_wall":   1 if (data.get("Is_Hash_Wall") or data.get("is_hash_wall")) else 0,
        "source":         "gemini",
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
        print(f"  ✓ upserted  : {result.get('upserted', 0)}")
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

"""Migration-managed SQLite persistence for the SACC multi-modal PoC."""

from __future__ import annotations

import os
import re
import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional


SCHEMA_VERSION = 4

_SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL UNIQUE,
    model       TEXT NOT NULL DEFAULT '',
    colorway    TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS media_assets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    shoe_id           INTEGER NOT NULL,
    media_type        TEXT NOT NULL CHECK (media_type IN ('video', 'image')),
    file_path         TEXT NOT NULL UNIQUE,
    resolution        TEXT NOT NULL DEFAULT '',
    mime_type         TEXT NOT NULL,
    is_primary        INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    storage_backend   TEXT NOT NULL DEFAULT 'local',
    storage_key       TEXT NOT NULL DEFAULT '',
    source_path       TEXT NOT NULL DEFAULT '',
    file_size_bytes   INTEGER NOT NULL DEFAULT 0,
    confidence        REAL NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    needs_review      INTEGER NOT NULL DEFAULT 1 CHECK (needs_review IN (0, 1)),
    review_reason     TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (shoe_id) REFERENCES shoes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL CHECK (status IN ('queued', 'running', 'complete', 'failed')),
    request_json  TEXT NOT NULL DEFAULT '{}',
    events_json   TEXT NOT NULL DEFAULT '[]',
    result_json   TEXT,
    error         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_shoes_sku ON shoes(sku);
CREATE INDEX IF NOT EXISTS idx_shoes_model_colorway_sku ON shoes(model, colorway, sku);
CREATE INDEX IF NOT EXISTS idx_media_assets_file_path ON media_assets(file_path);
CREATE INDEX IF NOT EXISTS idx_media_assets_shoe_type ON media_assets(shoe_id, media_type);
CREATE INDEX IF NOT EXISTS idx_media_assets_review ON media_assets(needs_review, confidence);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status_updated ON ingest_jobs(status, updated_at);

CREATE VIRTUAL TABLE IF NOT EXISTS shoes_fts USING fts5(
    sku,
    model,
    colorway,
    brand,
    content='shoes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS shoes_ai AFTER INSERT ON shoes BEGIN
    INSERT INTO shoes_fts(rowid, sku, model, colorway, brand)
    VALUES (new.id, new.sku, new.model, new.colorway, new.brand);
END;

CREATE TRIGGER IF NOT EXISTS shoes_ad AFTER DELETE ON shoes BEGIN
    INSERT INTO shoes_fts(shoes_fts, rowid, sku, model, colorway, brand)
    VALUES ('delete', old.id, old.sku, old.model, old.colorway, old.brand);
END;

CREATE TRIGGER IF NOT EXISTS shoes_au AFTER UPDATE ON shoes BEGIN
    INSERT INTO shoes_fts(shoes_fts, rowid, sku, model, colorway, brand)
    VALUES ('delete', old.id, old.sku, old.model, old.colorway, old.brand);
    INSERT INTO shoes_fts(rowid, sku, model, colorway, brand)
    VALUES (new.id, new.sku, new.model, new.colorway, new.brand);
END;
"""


def default_db_path() -> Path:
    configured = os.getenv("SACC_POC_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "var" / "sacc_multimodal.db").resolve()


class MultimodalDB:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path).expanduser().resolve() if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connection(self):
        con = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def migrate(self) -> None:
        with self.connection() as con:
            con.executescript(_SCHEMA)
            columns = {
                row["name"] for row in con.execute("PRAGMA table_info(media_assets)").fetchall()
            }
            if "review_reason" not in columns:
                con.execute(
                    "ALTER TABLE media_assets ADD COLUMN review_reason TEXT NOT NULL DEFAULT ''"
                )
            shoe_columns = {row['name'] for row in con.execute('PRAGMA table_info(shoes)')}
            for name, kind in (('name', 'TEXT'), ('release_date', 'TEXT'), ('msrp', 'REAL'),
                               ('msrp_currency', 'TEXT'), ('catalog_json', 'TEXT')):
                if name not in shoe_columns:
                    con.execute(f'ALTER TABLE shoes ADD COLUMN {name} {kind}')
            con.execute(
                """
                UPDATE media_assets
                SET review_reason='sku_confidence_below_1.0'
                WHERE needs_review=1 AND confidence < 1.0 AND review_reason=''
                """
            )
            con.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    def upsert_shoe(self, sku: str, model: str, colorway: str, brand: str) -> int:
        normalized_sku = sku.strip().upper()
        if not normalized_sku:
            raise ValueError("SKU is required for the single-entity PoC")
        with self.connection() as con:
            con.execute(
                """
                INSERT INTO shoes(sku, model, colorway, brand)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                    model=excluded.model,
                    colorway=excluded.colorway,
                    brand=excluded.brand,
                    updated_at=datetime('now')
                """,
                (normalized_sku, model.strip(), colorway.strip(), brand.strip()),
            )
            row = con.execute("SELECT id FROM shoes WHERE sku = ?", (normalized_sku,)).fetchone()
            return int(row["id"])

    def add_media_asset(
        self,
        shoe_id: int,
        media_type: str,
        file_path: str,
        resolution: str,
        mime_type: str,
        is_primary: bool = False,
        storage_backend: str = "local",
        storage_key: str = "",
        source_path: str = "",
        file_size_bytes: int = 0,
        confidence: float = 0.0,
        needs_review: bool = True,
        review_reason: str = "",
    ) -> int:
        if media_type not in ("video", "image"):
            raise ValueError(f"unsupported media type: {media_type}")
        with self.connection() as con:
            if is_primary:
                con.execute(
                    """
                    UPDATE media_assets
                    SET is_primary=0, updated_at=datetime('now')
                    WHERE shoe_id=? AND media_type=? AND file_path<>?
                    """,
                    (shoe_id, media_type, file_path),
                )
            con.execute(
                """
                INSERT INTO media_assets(
                    shoe_id, media_type, file_path, resolution, mime_type,
                    is_primary, storage_backend, storage_key, source_path,
                    file_size_bytes, confidence, needs_review, review_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    shoe_id=excluded.shoe_id,
                    media_type=excluded.media_type,
                    resolution=excluded.resolution,
                    mime_type=excluded.mime_type,
                    is_primary=excluded.is_primary,
                    storage_backend=excluded.storage_backend,
                    storage_key=excluded.storage_key,
                    source_path=excluded.source_path,
                    file_size_bytes=excluded.file_size_bytes,
                    confidence=excluded.confidence,
                    needs_review=excluded.needs_review,
                    review_reason=excluded.review_reason,
                    updated_at=datetime('now')
                """,
                (
                    shoe_id, media_type, file_path, resolution, mime_type,
                    int(is_primary), storage_backend, storage_key, source_path,
                    int(file_size_bytes), float(confidence), int(needs_review),
                    review_reason.strip(),
                ),
            )
            row = con.execute("SELECT id FROM media_assets WHERE file_path = ?", (file_path,)).fetchone()
            return int(row["id"])

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9]+", query)
        return " AND ".join(f'"{token}"*' for token in tokens)

    def search(
        self,
        query: str = "",
        media_types: Optional[Iterable[str]] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        selected_types = list(dict.fromkeys(media_types or ("video", "image")))
        if not selected_types or any(t not in ("video", "image") for t in selected_types):
            raise ValueError("media_types must contain video and/or image")
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        marks = ",".join("?" for _ in selected_types)
        params = list(selected_types)
        where = [f"EXISTS (SELECT 1 FROM media_assets ma WHERE ma.shoe_id=s.id AND ma.media_type IN ({marks}))"]

        q = query.strip()
        if q:
            like = f"%{q}%"
            fts = self._fts_query(q)
            like_clause = (
                "s.sku LIKE ? COLLATE NOCASE OR s.model LIKE ? COLLATE NOCASE "
                "OR s.colorway LIKE ? COLLATE NOCASE OR s.brand LIKE ? COLLATE NOCASE"
            )
            if fts:
                where.append(
                    "(s.id IN (SELECT rowid FROM shoes_fts WHERE shoes_fts MATCH ?) "
                    f"OR {like_clause})"
                )
                params.extend([fts, like, like, like, like])
            else:
                where.append(f"({like_clause})")
                params.extend([like, like, like, like])

        where_sql = " AND ".join(where)
        with self.connection() as con:
            total = con.execute(f"SELECT COUNT(*) FROM shoes s WHERE {where_sql}", params).fetchone()[0]
            shoes = con.execute(
                f"""
                SELECT s.* FROM shoes s
                WHERE {where_sql}
                ORDER BY s.model COLLATE NOCASE, s.colorway COLLATE NOCASE, s.sku
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
            if not shoes:
                return {"total": int(total), "count": 0, "limit": limit, "offset": offset, "results": []}

            shoe_ids = [int(row["id"]) for row in shoes]
            id_marks = ",".join("?" for _ in shoe_ids)
            assets = con.execute(
                f"""
                SELECT * FROM media_assets
                WHERE shoe_id IN ({id_marks}) AND media_type IN ({marks})
                ORDER BY is_primary DESC, id
                """,
                shoe_ids + selected_types,
            ).fetchall()

        grouped = {shoe_id: {"videos": [], "images": []} for shoe_id in shoe_ids}
        for row in assets:
            item = {
                "asset_id": row["id"],
                "path": f"/api/v1/assets/{row['id']}",
                "resolution": row["resolution"],
                "mime_type": row["mime_type"],
                "is_primary": bool(row["is_primary"]),
                "confidence": row["confidence"],
                "needs_review": bool(row["needs_review"]),
                "review_reason": row["review_reason"],
            }
            bucket = "videos" if row["media_type"] == "video" else "images"
            grouped[int(row["shoe_id"])][bucket].append(item)

        results = []
        for row in shoes:
            results.append({
                "id": row["id"],
                "sku": row["sku"],
                "model": row["model"],
                "colorway": row["colorway"],
                "brand": row["brand"],
                "name": row['name'] or row['model'],
                "release_date": row['release_date'],
                "msrp": row['msrp'],
                "msrp_currency": row['msrp_currency'],
                "catalog": json.loads(row['catalog_json']) if row['catalog_json'] else None,
                "media": grouped[int(row["id"])],
            })
        return {"total": int(total), "count": len(results), "limit": limit, "offset": offset, "results": results}

    def get_asset(self, asset_id: int) -> Optional[dict]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM media_assets WHERE id = ?", (asset_id,)).fetchone()
            return dict(row) if row else None

    def find_asset_by_path(self, path: str) -> Optional[dict]:
        with self.connection() as con:
            row = con.execute('SELECT * FROM media_assets WHERE file_path=?', (path,)).fetchone()
            return dict(row) if row else None

    def set_catalog(self, shoe_id: int, catalog: dict) -> None:
        with self.connection() as con:
            con.execute('''UPDATE shoes SET name=?, release_date=?, msrp=?, msrp_currency=?,
                           catalog_json=?, updated_at=datetime('now') WHERE id=?''',
                        (catalog.get('name'), catalog.get('release_date'), catalog.get('msrp'),
                         catalog.get('currency'), json.dumps(catalog), shoe_id))

    def flag_asset_for_review(self, asset_id: int, reason: str) -> None:
        with self.connection() as con:
            updated = con.execute(
                """
                UPDATE media_assets
                SET needs_review=1, review_reason=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (reason.strip(), asset_id),
            )
            if updated.rowcount != 1:
                raise ValueError(f"asset not found: {asset_id}")

    def save_ingest_job(self, job: dict) -> None:
        with self.connection() as con:
            con.execute(
                """
                INSERT INTO ingest_jobs(
                    id, status, request_json, events_json, result_json, error
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    request_json=excluded.request_json,
                    events_json=excluded.events_json,
                    result_json=excluded.result_json,
                    error=excluded.error,
                    updated_at=datetime('now')
                """,
                (
                    job["id"],
                    job["status"],
                    json.dumps(job.get("request", {})),
                    json.dumps(job.get("events", [])),
                    json.dumps(job["result"]) if job.get("result") is not None else None,
                    job.get("error", ""),
                ),
            )

    def get_ingest_job(self, job_id: str) -> Optional[dict]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM ingest_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "status": row["status"],
            "request": json.loads(row["request_json"]),
            "events": json.loads(row["events_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
        }

    def review_queue(self, limit: int = 100) -> list:
        with self.connection() as con:
            rows = con.execute(
                """
                SELECT ma.*, s.sku, s.model, s.colorway, s.brand
                FROM media_assets ma JOIN shoes s ON s.id=ma.shoe_id
                WHERE ma.needs_review=1
                ORDER BY ma.confidence ASC, ma.id ASC LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

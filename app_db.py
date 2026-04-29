"""
app_db.py — SACC Application State Database (V3.0)
====================================================
Replaces localStorage for Collections and user settings.
Stored in sacc_app.db alongside the repo — separate from the
pipeline sacc.db so the two concerns never collide.

Tables:
  collections    — named search shortcuts (id, name, query, color)
  user_settings  — arbitrary key/value store (replaces localStorage keys)
  error_history  — runtime error events from pipeline / API / renamer
"""

import sqlite3
import json
from datetime import datetime, timezone
from contextlib import contextmanager

_DDL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS collections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    query      TEXT NOT NULL DEFAULT '',
    color      TEXT NOT NULL DEFAULT '#888888',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS error_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL,
    message    TEXT NOT NULL,
    context    TEXT,
    resolved   INTEGER NOT NULL DEFAULT 0,
    timestamp  TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);
"""

_DEFAULT_COLLECTIONS = [
    ("Jordan Retros",    "Jordan Retro",   "#e63946"),
    ("adidas Originals", "adidas",         "#f4a261"),
    ("Nike Dunks",       "Dunk",           "#2a9d8f"),
    ("Collabs",          "collab",         "#9b5de5"),
]


class AppDB:
    """Thread-safe SQLite store for app-level state (collections, settings)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init(self):
        with self._conn() as con:
            con.executescript(_DDL)
            # Seed defaults on first run (only if table is empty)
            count = con.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
            if count == 0:
                con.executemany(
                    "INSERT INTO collections (name, query, color) VALUES (?,?,?)",
                    _DEFAULT_COLLECTIONS,
                )

    # ── Collections ─────────────────────────────────────────────────────────

    def get_collections(self) -> list:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM collections ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def add_collection(self, name: str, query: str, color: str = "#888888") -> dict:
        with self._conn() as con:
            cur = con.execute(
                "INSERT INTO collections (name, query, color) VALUES (?,?,?)",
                (name, query, color),
            )
            row = con.execute(
                "SELECT * FROM collections WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def delete_collection(self, col_id: int) -> bool:
        with self._conn() as con:
            cur = con.execute("DELETE FROM collections WHERE id = ?", (col_id,))
            return cur.rowcount > 0

    # ── Settings ─────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        """Return all settings as a flat dict with values JSON-decoded."""
        with self._conn() as con:
            rows = con.execute("SELECT key, value FROM user_settings").fetchall()
            result = {}
            for r in rows:
                try:
                    result[r["key"]] = json.loads(r["value"])
                except Exception:
                    result[r["key"]] = r["value"]
            return result

    def patch_settings(self, fields: dict) -> None:
        """Upsert arbitrary key/value pairs into user_settings."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as con:
            con.executemany(
                """INSERT INTO user_settings (key, value, updated_at) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                [(k, json.dumps(v), now) for k, v in fields.items()],
            )

    # ── Error history ─────────────────────────────────────────────────────────

    def log_error(self, code: str, message: str, context: str = "") -> dict:
        """Insert a new runtime error event. Returns the created row."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as con:
            cur = con.execute(
                "INSERT INTO error_history (code, message, context, timestamp) VALUES (?,?,?,?)",
                (code, message, context or None, now),
            )
            row = con.execute(
                "SELECT * FROM error_history WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def get_error_history(self, limit: int = 200) -> list:
        """Return most recent error events, newest last."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM error_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_error_resolved(self, error_id: int) -> bool:
        """Mark a single error event as resolved. Returns True if found."""
        with self._conn() as con:
            cur = con.execute(
                "UPDATE error_history SET resolved = 1 WHERE id = ?", (error_id,)
            )
            return cur.rowcount > 0

    def clear_error_history(self) -> int:
        """Delete all error history rows. Returns count deleted."""
        with self._conn() as con:
            cur = con.execute("DELETE FROM error_history")
            return cur.rowcount

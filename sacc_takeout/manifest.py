"""Versioned recovery database, deliberately separate from live SACC databases."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import re
import uuid

from . import SCHEMA_VERSION
from .common import canonical, child, token
from .review_policy import valid_screenshot_review


SCHEMA = """
CREATE TABLE recovery_schema(version INTEGER PRIMARY KEY, name TEXT NOT NULL);
INSERT INTO recovery_schema VALUES (1, 'sacc_takeout_recovery');
CREATE TABLE accounts(id TEXT PRIMARY KEY, label TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE batches(id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 export_key TEXT NOT NULL, config_json TEXT NOT NULL, inventory_hash TEXT NOT NULL,
 summary_json TEXT NOT NULL, UNIQUE(account_id, export_key));
CREATE TABLE archives(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
 path TEXT NOT NULL, fingerprint_json TEXT NOT NULL, UNIQUE(batch_id,path));
CREATE TABLE media(id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 sha256 TEXT NOT NULL, media_type TEXT NOT NULL CHECK(media_type IN ('image','video','unknown')),
 size_bytes INTEGER NOT NULL, privacy TEXT NOT NULL DEFAULT 'unknown',
 remote_eligible INTEGER NOT NULL DEFAULT 0 CHECK(remote_eligible=0), UNIQUE(account_id,sha256));
CREATE TABLE occurrences(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
 archive_id TEXT NOT NULL REFERENCES archives(id), member TEXT NOT NULL, member_index INTEGER NOT NULL,
 album_path TEXT NOT NULL, media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, crc INTEGER NOT NULL,
 match_json TEXT NOT NULL, media_id TEXT REFERENCES media(id),
 UNIQUE(archive_id,member_index));
CREATE INDEX occurrences_batch ON occurrences(batch_id);
CREATE INDEX occurrences_media ON occurrences(media_id);
CREATE TABLE sample_members(batch_id TEXT NOT NULL REFERENCES batches(id), ordinal INTEGER NOT NULL,
 occurrence_id TEXT NOT NULL UNIQUE REFERENCES occurrences(id), PRIMARY KEY(batch_id,ordinal));
CREATE TABLE recovery_results(occurrence_id TEXT PRIMARY KEY REFERENCES occurrences(id),
 state TEXT NOT NULL CHECK(state IN ('pending','staged','complete','error')),
 result_json TEXT NOT NULL DEFAULT '{}', error TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE events(id INTEGER PRIMARY KEY, occurrence_id TEXT REFERENCES occurrences(id),
 event TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE store_snapshots(id TEXT PRIMARY KEY, source TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE store_versions(id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES store_snapshots(id),
 store_id TEXT NOT NULL, venue_id TEXT, valid_from TEXT, valid_to TEXT, payload_json TEXT NOT NULL);
CREATE INDEX store_branch_dates ON store_versions(store_id, valid_from, valid_to);
CREATE TABLE visits(id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 status TEXT NOT NULL DEFAULT 'proposed', evidence_json TEXT NOT NULL);
CREATE TABLE visit_members(visit_id TEXT NOT NULL REFERENCES visits(id), media_id TEXT NOT NULL REFERENCES media(id),
 capture_utc TEXT, evidence_json TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(visit_id,media_id));
CREATE TABLE confirmations(id TEXT PRIMARY KEY, visit_id TEXT NOT NULL REFERENCES visits(id),
 store_version_id TEXT NOT NULL REFERENCES store_versions(id), reviewer TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE confirmation_dependencies(child_id TEXT REFERENCES confirmations(id),
 parent_id TEXT REFERENCES confirmations(id), PRIMARY KEY(child_id,parent_id));
CREATE TABLE revocations(confirmation_id TEXT PRIMARY KEY REFERENCES confirmations(id),
 reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE assignments(id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES media(id),
 visit_id TEXT NOT NULL REFERENCES visits(id), confirmation_id TEXT NOT NULL REFERENCES confirmations(id),
 store_version_id TEXT NOT NULL REFERENCES store_versions(id), method TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE TABLE media_links(id TEXT PRIMARY KEY, left_id TEXT NOT NULL REFERENCES media(id),
 right_id TEXT NOT NULL REFERENCES media(id), relationship TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE TABLE stage_results(id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES media(id),
 stage TEXT NOT NULL, version TEXT NOT NULL, payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE VIEW recovery_catalog AS
 SELECT o.id AS occurrence_id, o.media_id, b.account_id, b.export_key, o.batch_id,
 o.member AS original_path, o.album_path, o.media_type, o.size_bytes, a.path AS archive_path,
 r.state, json_extract(r.result_json,'$.capture.selected.utc') AS capture_utc,
 json_extract(r.result_json,'$.paths.staged') AS file_path,
 json_extract(r.result_json,'$.review_reasons') AS review_reasons
 FROM occurrences o JOIN batches b ON b.id=o.batch_id JOIN archives a ON a.id=o.archive_id
 LEFT JOIN recovery_results r ON r.occurrence_id=o.id;
"""


class Manifest:
    def __init__(self, root):
        self.root = Path(root)
        path = child(root, "recovery.sqlite3")
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        try:
            tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            if tables:
                rows = self.con.execute("SELECT version,name FROM recovery_schema").fetchall()
                if [tuple(r) for r in rows] != [(SCHEMA_VERSION, "sacc_takeout_recovery")]:
                    raise ValueError("Unsupported recovery schema; live databases cannot be used")
                required = set(re.findall(r'CREATE (?:TABLE|VIEW) (\w+)', SCHEMA))
                if not required <= tables:
                    raise ValueError('Incomplete recovery schema; no migration was performed')
            else:
                # executescript does not honor the connection context's implicit
                # transaction: include the transaction explicitly in the script.
                self.con.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')
                path.chmod(0o600)
        except Exception:
            self.con.rollback()
            self.con.close()
            raise

    def close(self):
        self.con.close()

    def event(self, occurrence_id, event, details):
        self.con.execute("INSERT INTO events(occurrence_id,event,details_json) VALUES (?,?,?)",
                         (occurrence_id, event, canonical(details)))

    def result(self, occurrence_id):
        row = self.con.execute("SELECT * FROM recovery_results WHERE occurrence_id=?", (occurrence_id,)).fetchone()
        return dict(row, result=json.loads(row["result_json"])) if row else None

    def save_result(self, occurrence_id, state, result, error=None):
        with self.con:
            self.con.execute("""INSERT INTO recovery_results(occurrence_id,state,result_json,error) VALUES (?,?,?,?)
                ON CONFLICT(occurrence_id) DO UPDATE SET state=excluded.state,result_json=excluded.result_json,
                error=excluded.error,updated_at=CURRENT_TIMESTAMP""",
                             (occurrence_id, state, canonical(result), error))
            self.event(occurrence_id, state, {"error": error, "result_sha256": token(result)})

    def link_media(self, occurrence_id, account_id, sha256, media_type, size):
        media_id = token("media", account_id, sha256)
        with self.con:
            self.con.execute("INSERT OR IGNORE INTO media(id,account_id,sha256,media_type,size_bytes) VALUES (?,?,?,?,?)",
                             (media_id, account_id, sha256, media_type, size))
            self.con.execute("UPDATE occurrences SET media_id=? WHERE id=?", (media_id, occurrence_id))
        return media_id

    def add_stage_result(self, media_id, stage, version, payload):
        if stage not in {"video_filter", "classification", "local_context"} or not version:
            raise ValueError("Unknown stage or empty version")
        if stage == "classification":
            if payload.get("privacy") not in {"personal", "mixed", "unknown", "non_personal"}:
                raise ValueError("Classification needs an explicit privacy axis")
            if payload.get("sneaker") not in {"present", "absent", "unknown"}:
                raise ValueError("Classification needs a separate sneaker axis")
        screenshot_review = stage == 'local_context' and payload.get('context_type') == 'screenshot_review'
        if screenshot_review and not valid_screenshot_review(payload):
            raise ValueError('Screenshot review requires a boolean decision and nonblank reviewer/evidence')
        # Reviews are events: identical re-confirmation after reversal is new evidence.
        ident = uuid.uuid4().hex if screenshot_review else token(media_id, stage, version, payload)
        with self.con:
            self.con.execute("INSERT OR IGNORE INTO stage_results(id,media_id,stage,version,payload_json) VALUES (?,?,?,?,?)",
                             (ident, media_id, stage, version, canonical(payload)))
        # Persisting local evidence never enables or triggers remote dispatch.
        return ident

    def link_components(self, left_id, right_id, relationship, evidence):
        if left_id == right_id or relationship not in {"live_photo", "motion_photo"}:
            raise ValueError("Invalid component relationship")
        if not evidence.get("component_identifier") or not evidence.get("source"):
            raise ValueError("Component links require an explicit identifier and source; not just a basename")
        ident = token(left_id, right_id, relationship, evidence)
        with self.con:
            self.con.execute("INSERT OR IGNORE INTO media_links VALUES (?,?,?,?,?)",
                             (ident, left_id, right_id, relationship, canonical(evidence)))
        return ident

    def lookup(self, query="", batch_id=None, limit=50):
        clauses, params = ["state='complete'"], []
        if query:
            clauses.append("original_path LIKE ?")
            params.append("%" + query + "%")
        if batch_id:
            clauses.append("batch_id=?")
            params.append(batch_id)
        rows = self.con.execute("SELECT * FROM recovery_catalog WHERE " + " AND ".join(clauses)
                                + " ORDER BY capture_utc,occurrence_id LIMIT ?", [*params, max(1, min(limit, 200))])
        return [dict(r) for r in rows]

    def compare_batches(self, old_id, new_id):
        for ident in (old_id,new_id):
            if not self.con.execute('SELECT 1 FROM batches WHERE id=?',(ident,)).fetchone():
                raise ValueError('Unknown manifest batch ID')
        def rows(batch):
            return self.con.execute("SELECT member,media_id FROM occurrences WHERE batch_id=?", (batch,)).fetchall()
        old, new = rows(old_id), rows(new_id)
        old_paths, new_paths = {r["member"] for r in old}, {r["member"] for r in new}
        old_ids, new_ids = {r["media_id"] for r in old if r["media_id"]}, {r["media_id"] for r in new if r["media_id"]}
        return {"added_paths": sorted(new_paths-old_paths), "missing_paths": sorted(old_paths-new_paths),
                "hash_proven_common_media": sorted(old_ids & new_ids),
                "old_unhashed_occurrences": sum(r["media_id"] is None for r in old),
                "new_unhashed_occurrences": sum(r["media_id"] is None for r in new),
                "warning": "Path differences do not prove added/missing content; only sampled members are hashed."}

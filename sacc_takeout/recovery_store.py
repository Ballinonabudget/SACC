"""Durable, isolated full-recovery ledger. Never opens a live SACC database."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .common import canonical, child, no_symlinks

SCHEMA = """
CREATE TABLE schema_version(version INTEGER PRIMARY KEY CHECK(version=1));
INSERT INTO schema_version VALUES(1);
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE items(id TEXT PRIMARY KEY,ordinal INTEGER NOT NULL UNIQUE,
 size_bytes INTEGER NOT NULL,media_type TEXT NOT NULL,source_json TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending',raw_sha256 TEXT,media_id TEXT,
 result_json TEXT,output_json TEXT,error TEXT,source_attempts INTEGER NOT NULL DEFAULT 0,
 metadata_attempts INTEGER NOT NULL DEFAULT 0);
CREATE INDEX items_state ON items(state);
CREATE INDEX items_media ON items(media_id);
CREATE TABLE reviews(version INTEGER NOT NULL,table_name TEXT NOT NULL,ordinal INTEGER NOT NULL,
 record_json TEXT NOT NULL,PRIMARY KEY(version,table_name,ordinal));
CREATE INDEX reviews_table ON reviews(version,table_name);
CREATE INDEX reviews_media ON reviews(version,table_name,json_extract(record_json,'$.media_id'),ordinal);
CREATE TABLE approvals(id INTEGER PRIMARY KEY,plan_id TEXT NOT NULL,scope TEXT NOT NULL,
 reviewer TEXT NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE events(id INTEGER PRIMARY KEY,event TEXT NOT NULL,occurrence_id TEXT,
 details_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE intents(id INTEGER PRIMARY KEY,occurrence_id TEXT NOT NULL REFERENCES items(id),
 phase TEXT NOT NULL,state TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE invalidations(media_id TEXT PRIMARY KEY,reason TEXT NOT NULL);
CREATE TABLE context_invalidations(confirmation_id TEXT PRIMARY KEY,reason TEXT NOT NULL);
CREATE TABLE counters(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
INSERT INTO counters VALUES('source_bytes_read',0);
CREATE TRIGGER immutable_source BEFORE UPDATE OF id,ordinal,size_bytes,media_type,source_json ON items
 BEGIN SELECT RAISE(ABORT,'Immutable planned selection'); END;
CREATE TRIGGER sealed_insert BEFORE INSERT ON items WHEN EXISTS(SELECT 1 FROM meta WHERE key='plan')
 BEGIN SELECT RAISE(ABORT,'Sealed selection'); END;
CREATE TRIGGER sealed_delete BEFORE DELETE ON items WHEN EXISTS(SELECT 1 FROM meta WHERE key='plan')
 BEGIN SELECT RAISE(ABORT,'Sealed selection'); END;
"""


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def bounded_json(value, maximum=16*1024**2):
    value = canonical(value)
    if len(value.encode()) > maximum:
        raise ValueError('Metadata record exceeds the bounded recovery-record limit')
    return value


class Ledger:
    def __init__(self, path, *, create=False, readonly=False):
        self.path = no_symlinks(Path(path).absolute())
        if not create and not self.path.is_file():
            raise ValueError('Existing recovery plan/ledger required')
        if create and self.path.exists():
            raise ValueError('Recovery ledger already exists')
        uri = self.path.as_uri() + ('?mode=ro' if readonly else '?mode=rw' if not create else '?mode=rwc')
        self.con = sqlite3.connect(uri, uri=True)
        self.con.row_factory = sqlite3.Row
        try:
            self.con.execute('PRAGMA foreign_keys=ON')
            if readonly:
                self.con.execute('PRAGMA query_only=ON')
            else:
                self.con.execute('PRAGMA synchronous=FULL')
                self.con.execute('PRAGMA journal_mode=DELETE')
            if create:
                self.con.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')
                self.path.chmod(0o600)
                sync_dir(self.path.parent)
            if [tuple(r) for r in self.con.execute('SELECT version FROM schema_version')] != [(1,)]:
                raise ValueError('Unsupported full-recovery ledger')
            required = {'items','reviews','approvals','events','intents','invalidations','context_invalidations','counters','meta'}
            tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= tables:
                raise ValueError('Incomplete full-recovery ledger')
            if readonly:
                self.con.execute('BEGIN')
        except BaseException:
            self.con.rollback()
            self.con.close()
            raise

    def close(self):
        self.con.close()

    def get(self, key, default=None):
        r = self.con.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, key, value):
        self.con.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                         (key, bounded_json(value)))

    def event(self, event, oid=None, **details):
        self.con.execute('INSERT INTO events(event,occurrence_id,details_json) VALUES(?,?,?)',
                         (event, oid, bounded_json(details)))

    def item(self, oid):
        r = self.con.execute('SELECT * FROM items WHERE id=?', (oid,)).fetchone()
        if not r:
            raise ValueError('Occurrence is outside the immutable selection')
        return dict(r)

    def update(self, oid, **fields):
        allowed = {'state','raw_sha256','media_id','result_json','output_json','error'}
        if not fields or not set(fields) <= allowed:
            raise ValueError('Invalid progress update')
        values = [bounded_json(v) if k.endswith('_json') and v is not None else v for k,v in fields.items()]
        self.con.execute('UPDATE items SET '+','.join(k+'=?' for k in fields)+' WHERE id=?', [*values, oid])

    def attempt(self, oid, phase, maximum):
        column = 'source_attempts' if phase == 'source' else 'metadata_attempts'
        with self.con:
            r = self.item(oid)
            if r[column] >= maximum:
                raise ValueError('Approved retry budget exhausted; inspect this occurrence')
            self.con.execute(f'UPDATE items SET {column}={column}+1 WHERE id=?', (oid,))
            self.event('attempt', oid, phase=phase, number=r[column]+1)

    def charge_bytes(self, amount, limit):
        if type(amount) is not int or amount < 0:
            raise ValueError('Invalid source-read accounting')
        with self.con:
            used = self.con.execute("SELECT value FROM counters WHERE key='source_bytes_read'").fetchone()[0]
            if used + amount > limit:
                raise ValueError('Approved cumulative source-read budget exhausted')
            self.con.execute("UPDATE counters SET value=value+? WHERE key='source_bytes_read'", (amount,))

    def add_intent(self, oid, phase, payload):
        with self.con:
            cursor = self.con.execute('INSERT INTO intents(occurrence_id,phase,state,payload_json) VALUES(?,?,?,?)',
                                      (oid, phase, 'started', bounded_json(payload)))
            return cursor.lastrowid

    def intent(self, ident, state, payload=None):
        with self.con:
            if payload is None:
                self.con.execute('UPDATE intents SET state=? WHERE id=?', (state, ident))
            else:
                self.con.execute('UPDATE intents SET state=?,payload_json=? WHERE id=?',
                                 (state, bounded_json(payload), ident))

    def verify_selection(self, plan):
        digest = hashlib.sha256()
        count = total = 0
        for r in self.con.execute('SELECT id,ordinal,size_bytes,media_type,source_json FROM items ORDER BY ordinal'):
            value = json.loads(r['source_json'])
            if (value['id'], value['size'], value['media_type']) != (r['id'], r['size_bytes'], r['media_type']):
                raise ValueError('Planned selection identity mismatch')
            digest.update((canonical(value)+'\n').encode())
            count += 1
            total += r['size_bytes']
        if (count,total,digest.hexdigest()) != (plan['files'],plan['source_bytes'],plan['selection_sha256']):
            raise ValueError('Immutable selection digest/count/byte mismatch')
        snapshot = hashlib.sha256()
        for r in self.con.execute('SELECT table_name,ordinal,record_json FROM reviews WHERE version=1 ORDER BY table_name,ordinal'):
            snapshot.update((canonical([r['table_name'],r['ordinal'],json.loads(r['record_json'])])+'\n').encode())
        if snapshot.hexdigest() != plan['review_snapshot_sha256']:
            raise ValueError('Immutable initial review snapshot mismatch')


@contextmanager
def open_ledger(root, readonly=False):
    db = Ledger(child(root, 'recovery-run.sqlite3'), readonly=readonly)
    try:
        yield db
    finally:
        db.close()

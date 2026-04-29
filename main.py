"""
main.py — SACC FastAPI Backend v3.0 (The Native Bridge)
=========================================================
Replaces api.py (Flask) with FastAPI.

New in v3.0:
  - GET  /api/pipeline/run-phase7  — SSE stream of phase7_renamer.py output
  - GET  /api/pipeline/run-phase8  — SSE stream of phase8_archival.py output
  - GET/POST/DELETE /api/collections — SQLite-backed (replaces localStorage)
  - GET/PATCH       /api/settings   — SQLite-backed (replaces localStorage)
  - FastAPI serves both the API (/api/*) and the SCAA static frontend (/)
    → one port (5174) replaces the old two-server setup

Run:
  uvicorn main:app --port 5174 --reload

  Or double-click start_sacc.command (will be updated to call uvicorn).
"""

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

sys.path.insert(0, os.path.dirname(__file__))

# ── Optional pipeline imports (graceful degradation) ─────────────────────────
try:
    from db import SACCDB
    _DB_OK = True
except ImportError:
    _DB_OK = False

try:
    from fcp_namer import LOCATION_DB, apply_confirmed_locations, get_loc_header, run_fcp_renamer
    _FCP_OK = True
except ImportError:
    LOCATION_DB: dict = {}
    _FCP_OK = False

try:
    from renamer_logic import LOCATION_DATA, run_vibe_renamer
    _RENAMER_OK = True
except ImportError:
    LOCATION_DATA: dict = {}
    _RENAMER_OK = False

try:
    from json_sync_validator import validate_folder
    _VALIDATOR_OK = True
except ImportError:
    _VALIDATOR_OK = False

from app_db import AppDB

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="SACC API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_APP_DB_PATH = os.path.join(os.path.dirname(__file__), "sacc_app.db")
_app_db = AppDB(_APP_DB_PATH)

_db_cache: dict = {}


def _get_db(folder: str) -> "SACCDB":
    db_path = os.path.join(folder, "sacc.db")
    if db_path not in _db_cache:
        _db_cache[db_path] = SACCDB(db_path)
    return _db_cache[db_path]


def _pipeline_db(db_param: str) -> sqlite3.Connection:
    if not db_param or not os.path.exists(db_param):
        raise HTTPException(404, f"DB not found: {db_param}")
    con = sqlite3.connect(db_param, timeout=10)
    con.row_factory = sqlite3.Row
    return con


VIDEO_EXTS = {".mov", ".mp4", ".MOV", ".MP4", ".mts", ".MTS"}

# ── NLP Location Aliases ──────────────────────────────────────────────────────
_LOC_ALIASES = {
    "florida mall": "FLM", "fl mall": "FLM",
    "millenia": "MAM", "mall at millenia": "MAM", "millennia": "MAM",
    "orlando fashion square": "OFS", "fashion square": "OFS",
    "west oaks": "WOM", "west oaks mall": "WOM",
    "vineland": "VLD", "premium outlets": "VLD", "vineland premium": "VLD",
    "international drive": "IDR", "i drive": "IDR", "idrive": "IDR",
    "lake buena vista": "LBV", "disney springs": "LBV",
    "waterford": "WFL", "waterford lakes": "WFL",
    "winter garden": "WGN", "winter garden village": "WGN",
    "marketplace": "OMP", "orlando marketplace": "OMP",
    "seminole": "SEM", "seminole towne": "SEM",
    "lakeland": "LKL", "lakeland square": "LKL",
    "paddock": "PDM", "paddock mall": "PDM", "ocala": "PDM",
    "tallahassee": "THL", "tally": "THL",
    "brandon": "BRN", "brandon exchange": "BRN",
    "international plaza": "INP", "int plaza": "INP",
    "university mall": "UNM", "university tampa": "UNM",
    "tampa premium": "TPA", "tampa outlets": "TPA",
    "hyde park": "HVP", "hyde park village": "HVP",
    "aventura": "AVE", "aventura mall": "AVE",
    "lincoln road": "LCN", "lincoln": "LCN",
    "dolphin": "DOL", "dolphin mall": "DOL",
    "gainesville": "GVA", "celebration pointe": "GVA",
    "celebration": "CEL-K", "kissimmee": "CEL-K",
    "osceola": "KSM", "kissimmee osceola": "KSM",
}


def resolve_nlp(text: str) -> dict:
    if not text:
        return {"code": "", "name": "", "confidence": "unresolved"}
    t = text.strip().lower()
    upper = t.upper()
    if upper in LOCATION_DB:
        return {"code": upper, "name": LOCATION_DB[upper].get("name", upper), "confidence": "exact"}
    if t in _LOC_ALIASES:
        code = _LOC_ALIASES[t]
        return {"code": code, "name": LOCATION_DB.get(code, {}).get("name", code), "confidence": "alias"}
    for alias, code in sorted(_LOC_ALIASES.items()):
        if alias in t or t in alias:
            return {"code": code, "name": LOCATION_DB.get(code, {}).get("name", code), "confidence": "fuzzy"}
    for code, entry in LOCATION_DB.items():
        name = entry.get("name", "").lower()
        if t in name or name in t:
            return {"code": code, "name": entry.get("name", code), "confidence": "fuzzy"}
    return {"code": "", "name": "", "confidence": "unresolved"}


def _load_json_db(folder: str) -> tuple:
    json_dir = os.path.join(folder, "json")
    records: list = []
    if not os.path.isdir(json_dir):
        return records, json_dir
    for f in sorted(os.listdir(json_dir)):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(json_dir, f)) as fh:
                data = json.load(fh)
            data["_json_file"] = f
            data["_json_path"] = os.path.join(json_dir, f)
            records.append(data)
        except Exception:
            pass
    return records, json_dir


def _preflight_scan(folder: str) -> list:
    if not folder or not os.path.isdir(folder):
        return []
    all_files = [f for f in Path(folder).iterdir()
                 if f.suffix.lower() in {".mp4", ".mov"} and not f.name.startswith(".")]
    by_size: dict = defaultdict(list)
    for f in all_files:
        try:
            by_size[f.stat().st_size].append(f)
        except Exception:
            pass
    confirmed = []
    chunk = 1024 * 1024
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        hashes: dict = defaultdict(list)
        for f in files:
            h = hashlib.md5()
            try:
                with open(f, "rb") as fh:
                    h.update(fh.read(chunk))
                    if size > chunk:
                        fh.seek(-min(chunk, size - chunk), 2)
                        h.update(fh.read(chunk))
                hashes[h.hexdigest()].append(f.name)
            except Exception:
                pass
        for digest, names in hashes.items():
            if len(names) > 1:
                confirmed.append({"size_mb": round(size / 1024 / 1024, 1), "files": names})
    return confirmed


# ── Pydantic request models ───────────────────────────────────────────────────

class LocationBody(BaseModel):
    text: str = ""

class ApplyLocationBody(BaseModel):
    path: str
    loc_code: str

class PreflightBody(BaseModel):
    path: str

class RenameBody(BaseModel):
    path: str
    loc: str = ""
    identifier: str = ""
    dry_run: bool = True

class PipelineRunBody(BaseModel):
    path: str
    loc: str = ""
    fcp_mode: bool = True

class DbSyncBody(BaseModel):
    path: str

class RevealBody(BaseModel):
    path: str
    file: str = ""

class PipelineOpenBody(BaseModel):
    db: str
    original_file_id: str

class MarkFCPBody(BaseModel):
    db: str
    ids: list[str]
    linked: bool = True

class CollectionBody(BaseModel):
    name: str
    query: str = ""
    color: str = "#888888"

class ArbitraryPatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    stem: str = ""

    def extra_fields(self) -> dict:
        return dict(self.model_extra or {})


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": "3.0",
        "fcp_ok": _FCP_OK,
        "renamer_ok": _RENAMER_OK,
        "validator_ok": _VALIDATOR_OK,
        "location_count": len(LOCATION_DB),
        "time": datetime.now(timezone.utc).isoformat(),
    }


# ── Locations ─────────────────────────────────────────────────────────────────

@app.get("/api/locations")
def locations():
    locs = []
    for code, entry in LOCATION_DB.items():
        locs.append({
            "code": code,
            "name": entry.get("name", code),
            "type": entry.get("type", ""),
            "region": entry.get("region", ""),
            "header": get_loc_header(code) if _FCP_OK else f"{code}-LOC",
        })
    for code, entry in LOCATION_DATA.items():
        if code not in LOCATION_DB:
            locs.append({
                "code": code,
                "name": entry.get("name", code),
                "type": entry.get("type", ""),
                "region": entry.get("region", ""),
                "header": f"{code}-{entry.get('type','LOC')}",
            })
    return {"locations": locs}


@app.post("/api/resolve-location")
def resolve_location(body: LocationBody):
    return resolve_nlp(body.text)


# ── Folder / JSON ─────────────────────────────────────────────────────────────

@app.get("/api/folder-status")
def folder_status(path: str = Query("")):
    if not path or not os.path.isdir(path):
        raise HTTPException(404, f"Folder not found: {path}")
    if not _VALIDATOR_OK:
        raise HTTPException(500, "json_sync_validator not available")
    report = validate_folder(path)
    report.pop("records", None)
    return report


@app.get("/api/json-db")
def json_db(path: str = Query("")):
    if not path or not os.path.isdir(path):
        raise HTTPException(404, f"Folder not found: {path}")
    records, json_dir = _load_json_db(path)
    clean = []
    for r in records:
        c = {k: v for k, v in r.items() if not k.startswith("_")}
        c["_stem"] = os.path.splitext(r["_json_file"])[0]
        clean.append(c)
    return {"folder": path, "json_dir": json_dir, "count": len(clean), "records": clean}


@app.patch("/api/json-db")
async def patch_json_db(request: Request):
    body = await request.json()
    folder = body.get("path", "")
    stem = body.get("stem", "")
    if not folder or not stem:
        raise HTTPException(400, "path and stem required")
    json_path = os.path.join(folder, "json", f"{stem}.json")
    if not os.path.exists(json_path):
        raise HTTPException(404, f"JSON not found: {json_path}")
    with open(json_path) as fh:
        payload = json.load(fh)
    for k, v in body.items():
        if k not in ("path", "stem") and not k.startswith("_"):
            payload[k] = v
    payload["_patched_at"] = datetime.now(timezone.utc).isoformat()
    with open(json_path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return {"ok": True, "stem": stem}


@app.post("/api/apply-location")
def apply_location(body: ApplyLocationBody):
    records, _ = _load_json_db(body.path)
    unknown = [r for r in records if not r.get("loc_code_confirmed")]
    updated = 0
    for r in unknown:
        jpath = r["_json_path"]
        try:
            with open(jpath) as fh:
                payload = json.load(fh)
            payload["loc_code_confirmed"] = body.loc_code
            payload["loc_source"] = "manual"
            payload["Location_Confidence"] = "manual"
            with open(jpath, "w") as fh:
                json.dump(payload, fh, indent=2)
            updated += 1
        except Exception:
            pass
    return {"ok": True, "updated": updated, "loc_code": body.loc_code}


@app.get("/api/whitelist")
def whitelist(path: str = Query("/Users/miniman/SACC/whitelist.json")):
    if not os.path.exists(path):
        raise HTTPException(404, f"Not found: {path}")
    with open(path) as fh:
        data = json.load(fh)
    items = data if isinstance(data, list) else [data]
    return {"count": len(items), "records": items}


@app.post("/api/preflight")
def preflight(body: PreflightBody):
    if not body.path:
        raise HTTPException(400, "path required")
    dupes = _preflight_scan(body.path)
    return {
        "folder": body.path,
        "duplicate_groups": len(dupes),
        "duplicates": dupes,
        "clean": len(dupes) == 0,
    }


@app.post("/api/rename")
def rename(body: RenameBody):
    if not body.path:
        raise HTTPException(400, "path required")
    if not os.path.isdir(body.path):
        raise HTTPException(404, f"Folder not found: {body.path}")

    results = []

    if _RENAMER_OK and body.identifier:
        try:
            for status in run_vibe_renamer(body.path, body.loc, body.identifier):
                if "error" in status:
                    raise HTTPException(500, status["error"])
                if status.get("done"):
                    return {
                        "ok": True, "mode": "vibe",
                        "processed": status.get("processed_count", 0),
                        "elapsed_s": status.get("elapsed_seconds", 0),
                        "results": status.get("results", []),
                    }
                results.append({
                    "original": status.get("original", ""),
                    "new":      status.get("new", ""),
                    "current":  status.get("current", 0),
                    "total":    status.get("total", 0),
                })
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, str(e))

    elif _FCP_OK:
        try:
            renamed = []
            for item in run_fcp_renamer(body.path, loc_override=body.loc, dry_run=body.dry_run):
                if "error" in item:
                    raise HTTPException(500, item["error"])
                renamed.append(item)
                results.append({"original": item.get("original", ""), "new": item.get("new_name", "")})
            return {"ok": True, "mode": "fcp", "dry_run": body.dry_run, "processed": len(renamed), "results": results}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, str(e))
    else:
        raise HTTPException(500, "No renamer available (fcp_namer or renamer_logic not loaded)")

    return {"ok": True, "results": results}


@app.post("/api/pipeline-run")
def pipeline_run(body: PipelineRunBody):
    """Legacy blocking pipeline run — use /api/pipeline/run-phase7 for live SSE."""
    if not body.path:
        raise HTTPException(400, "path required")
    script = os.path.join(os.path.dirname(__file__), "sacc_pipeline.py")
    if not os.path.exists(script):
        raise HTTPException(500, "sacc_pipeline.py not found")
    cmd = [sys.executable, script, "--src", body.path]
    if body.fcp_mode:
        cmd.append("--fcp")
    if body.loc:
        cmd += ["--loc", body.loc]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-2000:],
            "code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Pipeline timed out after 300s")
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Phase 7 — SSE streaming rename ───────────────────────────────────────────

PHASE7_SCRIPT = "/Volumes/Team Bank 12/Sneeaker Solo/phase7_renamer.py"
PHASE8_SCRIPT = "/Volumes/Team Bank 12/Sneeaker Solo/phase8_archival.py"


@app.get("/api/pipeline/run-phase7")
async def run_phase7(
    loc: str,
    apply: bool = False,
    all: bool = Query(False, alias="all"),
    file: Optional[str] = None,
):
    """
    SSE endpoint — streams phase7_renamer.py output line by line.

    Frontend usage:
        const es = new EventSource(
            `/api/pipeline/run-phase7?loc=FLM&apply=true`
        );
        es.onmessage = (e) => {
            const { line, done, exit_code } = JSON.parse(e.data);
            if (done) { es.close(); return; }
            appendToLog(line);   // update UI
        };

    Events emitted:
        { "line": "<output text>", "done": false }   — one per stdout line
        { "done": true, "exit_code": 0 }             — final event on completion
    """
    if not os.path.exists(PHASE7_SCRIPT):
        raise HTTPException(500, f"phase7_renamer.py not found at {PHASE7_SCRIPT}")

    cmd = [sys.executable, PHASE7_SCRIPT, "--loc", loc]
    if apply:
        cmd.append("--apply")
    if all:
        cmd.append("--all")
    if file:
        cmd += ["--file", file]

    async def event_stream():
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for raw in proc.stdout:
            line = raw.decode().rstrip()
            if line:
                yield f"data: {json.dumps({'line': line, 'done': False})}\n\n"
        await proc.wait()
        yield f"data: {json.dumps({'done': True, 'exit_code': proc.returncode})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",    # disable nginx buffering if proxied
        },
    )


# ── Phase 8 — SSE streaming archival ─────────────────────────────────────────

@app.get("/api/pipeline/run-phase8")
async def run_phase8(
    dry_run: bool = True,
    file: Optional[str] = None,
    root: Optional[str] = None,
):
    """
    SSE endpoint — streams phase8_archival.py output line by line.

    Frontend usage (same pattern as Phase 7):
        const es = new EventSource(`/api/pipeline/run-phase8?dry_run=false`);
        es.onmessage = (e) => {
            const { line, done, exit_code } = JSON.parse(e.data);
            if (done) { es.close(); updateStatus('archived'); return; }
            appendToLog(line);
        };
    """
    if not os.path.exists(PHASE8_SCRIPT):
        raise HTTPException(500, f"phase8_archival.py not found at {PHASE8_SCRIPT}")

    cmd = [sys.executable, PHASE8_SCRIPT]
    if dry_run:
        cmd.append("--dry-run")
    if file:
        cmd += ["--file", file]
    if root:
        cmd += ["--root", root]

    async def event_stream():
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for raw in proc.stdout:
            line = raw.decode().rstrip()
            if line:
                yield f"data: {json.dumps({'line': line, 'done': False})}\n\n"
        await proc.wait()
        yield f"data: {json.dumps({'done': True, 'exit_code': proc.returncode})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Collections (replaces localStorage `sacc_collections`) ───────────────────

@app.get("/api/collections")
def get_collections():
    return {"collections": _app_db.get_collections()}


@app.post("/api/collections", status_code=201)
def add_collection(body: CollectionBody):
    col = _app_db.add_collection(body.name, body.query, body.color)
    return col


@app.delete("/api/collections/{col_id}")
def delete_collection(col_id: int):
    deleted = _app_db.delete_collection(col_id)
    if not deleted:
        raise HTTPException(404, f"Collection {col_id} not found")
    return {"ok": True}


# ── Settings (replaces any other localStorage keys) ───────────────────────────

@app.get("/api/settings")
def get_settings():
    return _app_db.get_settings()


@app.patch("/api/settings")
async def patch_settings(request: Request):
    body = await request.json()
    _app_db.patch_settings(body)
    return {"ok": True}


# ── SQLite DB endpoints ───────────────────────────────────────────────────────

@app.post("/api/db/sync")
def db_sync(body: DbSyncBody):
    if not _DB_OK:
        raise HTTPException(500, "db.py not available")
    if not os.path.isdir(body.path):
        raise HTTPException(404, f"Folder not found: {body.path}")
    db = _get_db(body.path)
    result = db.sync_from_folder(body.path)
    summary = db.validation_summary()
    return {"ok": True, "folder": body.path, **result, "validation": summary}


@app.get("/api/db/search")
def db_search(
    path: str = Query(""),
    q: str = Query(""),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
):
    if not _DB_OK:
        raise HTTPException(500, "db.py not available")
    if not os.path.isdir(path):
        raise HTTPException(404, f"Folder not found: {path}")
    db = _get_db(path)
    results = db.search(q, limit=limit, offset=offset)
    total = db.stats().get("total", 0)
    return {"query": q, "total": total, "count": len(results), "offset": offset, "results": results}


@app.get("/api/db/stats")
def db_stats(path: str = Query("")):
    if not _DB_OK:
        raise HTTPException(500, "db.py not available")
    if not os.path.isdir(path):
        raise HTTPException(404, f"Folder not found: {path}")
    db = _get_db(path)
    return {"stats": db.stats(), "top_locations": db.top_locations(10)}


@app.get("/api/db/record")
def db_get_record(path: str = Query(""), stem: str = Query("")):
    if not _DB_OK:
        raise HTTPException(500, "db.py not available")
    if not path or not stem:
        raise HTTPException(400, "path and stem required")
    record = _get_db(path).get_by_stem(stem)
    if record is None:
        raise HTTPException(404, f"Record not found: {stem}")
    return record


@app.patch("/api/db/record")
async def db_patch_record(request: Request):
    if not _DB_OK:
        raise HTTPException(500, "db.py not available")
    body = await request.json()
    folder = body.pop("path", "")
    stem = body.pop("stem", "")
    if not folder or not stem:
        raise HTTPException(400, "path and stem required")
    ok = _get_db(folder).patch(stem, body)
    return {"ok": ok, "stem": stem}


@app.get("/api/db/validation-summary")
def db_validation_summary(path: str = Query("")):
    if not _DB_OK:
        raise HTTPException(500, "db.py not available")
    if not os.path.isdir(path):
        raise HTTPException(404, f"Folder not found: {path}")
    return _get_db(path).validation_summary()


@app.get("/api/db/validate")
def db_validate(path: str = Query("")):
    if not _DB_OK:
        raise HTTPException(500, "db.py not available")
    if not os.path.isdir(path):
        raise HTTPException(404, f"Folder not found: {path}")
    db = _get_db(path)
    rows = db.list_all(limit=10000)
    missing_json = [r["stem"] for r in rows if r.get("json_path") and not os.path.exists(r["json_path"])]
    no_model = [r["stem"] for r in rows if not r.get("model")]
    no_loc = [r["stem"] for r in rows if not r.get("loc_code")]
    return {
        "total": len(rows),
        "missing_json": missing_json,
        "no_model": no_model,
        "no_loc": no_loc,
        "clean": not (missing_json or no_model or no_loc),
    }


# ── Pipeline query endpoints ──────────────────────────────────────────────────

@app.get("/api/pipeline/search")
def pipeline_search(
    db: str = Query(""),
    q: str = Query(""),
    orientation: str = Query("all"),
    year: str = Query(""),
    shot_type: str = Query("all"),
    session_id: str = Query(""),
    loc_code: str = Query(""),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
):
    con = _pipeline_db(db)
    try:
        conditions, params = [], []
        if q:
            conditions.append(
                "(brand LIKE ? OR silhouette LIKE ? OR colorway_name LIKE ? OR style_code LIKE ?)"
            )
            like = f"%{q}%"
            params += [like, like, like, like]
        if orientation == "vertical":
            conditions.append("aspect_ratio = '9:16'")
        elif orientation == "horizontal":
            conditions.append("aspect_ratio = '16:9'")
        if year:
            conditions.append("shoot_year = ?"); params.append(year)
        if shot_type in ("broll", "vlog"):
            conditions.append("shot_type = ?"); params.append(shot_type)
        if session_id:
            conditions.append("session_id = ?"); params.append(session_id)
        if loc_code:
            conditions.append("loc_code = ?"); params.append(loc_code)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        total = con.execute(f"SELECT COUNT(*) FROM sneakers_broll {where}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM sneakers_broll {where} ORDER BY creation_time DESC, original_file_id LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return {"total": total, "count": len(rows), "offset": offset, "results": [dict(r) for r in rows]}
    finally:
        con.close()


@app.get("/api/pipeline/sessions")
def pipeline_sessions(db: str = Query("")):
    con = _pipeline_db(db)
    try:
        rows = con.execute("SELECT * FROM shoot_sessions ORDER BY shoot_date DESC, session_id").fetchall()
        return {"sessions": [dict(r) for r in rows]}
    finally:
        con.close()


@app.get("/api/pipeline/stats")
def pipeline_stats(db: str = Query("")):
    con = _pipeline_db(db)
    try:
        total      = con.execute("SELECT COUNT(*) FROM sneakers_broll").fetchone()[0]
        verified   = con.execute("SELECT COUNT(*) FROM sneakers_broll WHERE verification_status='VERIFIED'").fetchone()[0]
        broll      = con.execute("SELECT COUNT(*) FROM sneakers_broll WHERE shot_type='broll'").fetchone()[0]
        vlog       = con.execute("SELECT COUNT(*) FROM sneakers_broll WHERE shot_type='vlog'").fetchone()[0]
        vertical   = con.execute("SELECT COUNT(*) FROM sneakers_broll WHERE aspect_ratio='9:16'").fetchone()[0]
        horizontal = con.execute("SELECT COUNT(*) FROM sneakers_broll WHERE aspect_ratio='16:9'").fetchone()[0]
        archived   = con.execute("SELECT COUNT(*) FROM proxy_manifest WHERE processing_status='ARCHIVED'").fetchone()[0]
        sessions   = con.execute("SELECT COUNT(*) FROM shoot_sessions").fetchone()[0]
        years = [r[0] for r in con.execute(
            "SELECT DISTINCT shoot_year FROM sneakers_broll WHERE shoot_year IS NOT NULL ORDER BY shoot_year DESC"
        ).fetchall()]
        return {
            "total": total, "verified": verified,
            "shot_type": {"broll": broll, "vlog": vlog},
            "orientation": {"vertical": vertical, "horizontal": horizontal},
            "archived": archived, "sessions": sessions, "years": years,
        }
    finally:
        con.close()


@app.post("/api/pipeline/open")
def pipeline_open(body: PipelineOpenBody):
    con = _pipeline_db(body.db)
    try:
        row = con.execute(
            "SELECT asset_url FROM sneakers_broll WHERE original_file_id=?", (body.original_file_id,)
        ).fetchone()
        if not row or not row["asset_url"]:
            raise HTTPException(404, f"No asset_url for {body.original_file_id}")
        path = row["asset_url"]
        if not os.path.exists(path):
            raise HTTPException(404, f"File not found at {path}")
        subprocess.Popen(["open", "-R", path])
        return {"ok": True, "revealed": path}
    finally:
        con.close()


@app.post("/api/pipeline/mark-fcp")
def pipeline_mark_fcp(body: MarkFCPBody):
    _pipeline_db(body.db).close()  # validate path
    con = sqlite3.connect(body.db, timeout=10)
    try:
        linked = 1 if body.linked else 0
        con.executemany(
            "UPDATE sneakers_broll SET fcp_linked=? WHERE original_file_id=?",
            [(linked, fid) for fid in body.ids],
        )
        con.commit()
        return {"ok": True, "updated": len(body.ids), "fcp_linked": bool(linked)}
    finally:
        con.close()


# ── Media ─────────────────────────────────────────────────────────────────────

@app.post("/api/reveal")
def reveal_in_finder(body: RevealBody):
    if not body.path:
        raise HTTPException(400, "path required")
    safe_dir = Path(body.path).resolve()
    if not safe_dir.is_dir():
        raise HTTPException(404, f"Folder not found: {body.path}")
    if body.file:
        target = (safe_dir / Path(body.file).name).resolve()
        if target.parent == safe_dir and target.is_file():
            subprocess.Popen(["open", "-R", str(target)])
            return {"ok": True, "revealed": str(target)}
    subprocess.Popen(["open", str(safe_dir)])
    return {"ok": True, "opened": str(safe_dir)}


@app.get("/api/video")
def serve_video(path: str = Query(""), file: str = Query("")):
    if not path or not file:
        raise HTTPException(400, "path and file required")
    safe_dir = Path(path).resolve()
    safe_file = (safe_dir / Path(file).name).resolve()
    if safe_file.parent != safe_dir or not safe_file.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(str(safe_file))


# ── Static frontend — must be last so /api/* routes take precedence ───────────

_SCAA_DIR = os.path.join(os.path.dirname(__file__), "SCAA")
if os.path.isdir(_SCAA_DIR):
    app.mount("/", StaticFiles(directory=_SCAA_DIR, html=True), name="frontend")


# ── Dev entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("\n  ┌────────────────────────────────────────────────┐")
    print("  │   SACC v3.0  —  http://localhost:5174          │")
    print("  │   UI:  http://localhost:5174/SACC.html         │")
    print(f"  │   FCP engine:  {'✓' if _FCP_OK else '✗ fcp_namer.py missing'}                      │")
    print(f"  │   Renamer:     {'✓' if _RENAMER_OK else '✗ renamer_logic.py missing'}                      │")
    print("  └────────────────────────────────────────────────┘\n")
    uvicorn.run("main:app", host="127.0.0.1", port=5174, reload=False)

#!/usr/bin/env python3
"""
api.py — SACC Flask REST Backend
=================================
Exposes all pipeline operations as JSON endpoints so the SCAA
React frontend can call them without Streamlit.

Run:  python3 api.py
Port: 5174  (frontend static server runs on 5173)

Endpoints
---------
  GET  /api/health
  GET  /api/locations
  POST /api/resolve-location        { "text": "paddock mall" }
  GET  /api/folder-status?path=...
  GET  /api/json-db?path=...
  PATCH /api/json-db                { "path": ..., "stem": ..., <fields> }
  POST /api/apply-location          { "path": ..., "loc_code": ... }
  GET  /api/whitelist?path=...
  POST /api/preflight               { "path": ... }
  POST /api/rename                  { "path": ..., "loc": ..., "identifier": ..., "dry_run": bool }
  POST /api/pipeline-run            { "path": ..., "loc": ..., "fcp_mode": bool }

  -- SQLite database endpoints --
  POST /api/db/sync                 { "path": ... }
  GET  /api/db/search?path=...&q=...&limit=50&offset=0
  GET  /api/db/stats?path=...
  GET  /api/db/record?path=...&stem=...
  PATCH /api/db/record              { "path": ..., "stem": ..., <fields> }
  GET  /api/db/validate?path=...
"""

import os, sys, json, time, re, hashlib, subprocess
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

from flask import Flask, request, jsonify, send_file, abort
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

app = Flask(__name__)
CORS(app)  # allow SCAA frontend on :5173 to call this API on :5174

# ── SACC Error Code Ledger ────────────────────────────────────────────────────
#
# Codes
#   E001–E009  Configuration errors  (user must fix a setting or path)
#   E010–E019  Pipeline errors       (failure inside the pipeline stages)
#   E020–E029  Validation warnings   (data-integrity issues, not blockers)
#   E030–E039  Validation errors     (blocking integrity failures)
#
# Each error response carries: code, category, message, hint
#
_ERROR_REGISTRY = {
    "E001": ("config",     "Path argument missing",
             "Provide a 'path' field in the request body."),
    "E002": ("system",     "sacc_pipeline.py not found",
             "Reinstall SACC or check that /Users/miniman/SACC/ is intact."),
    "E003": ("config",     "Source folder not found",
             "Check that the NAS is mounted: ls '/Volumes/Team Bank 12'"),
    "E010": ("pipeline",   "Pipeline exited with a non-zero code",
             "Expand the log below — look for the first [ERROR] line."),
    "E011": ("system",     "Pipeline timed out (300 s)",
             "Split the batch into smaller folders, or run sacc_pipeline.py from terminal."),
    "E012": ("system",     "Pipeline subprocess crashed",
             "Run sacc_pipeline.py directly from terminal to see the full traceback."),
    "E020": ("validation", "Video has no companion JSON",
             "Stage 8 (Vertex AI) has not yet run on this file."),
    "E021": ("validation", "Orphaned JSON — no matching video",
             "The source video may have been moved or deleted."),
    "E030": ("validation", "Required JSON field missing",
             "Re-run Stage 8 on this file to regenerate the JSON record."),
}

class _ErrHelper:
    """Attach a SACC error code to any response dict."""
    def _build(self, code, override_msg=None):
        entry = _ERROR_REGISTRY.get(code, ("unknown", code, "No details available."))
        category, default_msg, hint = entry
        return {
            "error_code": code,
            "error_category": category,
            "error": override_msg or default_msg,
            "hint": hint,
        }
    def config(self, code, msg=None):   return self._build(code, msg)
    def system(self, code, msg=None):   return self._build(code, msg)
    def pipeline(self, code, msg=None): return self._build(code, msg)

SACC_ERRORS = _ErrHelper()

# ── Optional imports (graceful degradation) ───────────────────────────────────
try:
    from db import SACCDB
    _DB_OK = True
except ImportError:
    _DB_OK = False

# Per-folder DB instance cache (keyed by db_path)
_db_cache: dict = {}

def _get_db(folder: str) -> "SACCDB":
    db_path = os.path.join(folder, "sacc.db")
    if db_path not in _db_cache:
        _db_cache[db_path] = SACCDB(db_path)
    return _db_cache[db_path]

try:
    from fcp_namer import (
        LOCATION_DB, run_fcp_renamer, apply_confirmed_locations,
        get_loc_header
    )
    _FCP_OK = True
except ImportError:
    LOCATION_DB = {}
    _FCP_OK = False

try:
    from renamer_logic import LOCATION_DATA, run_vibe_renamer
    _RENAMER_OK = True
except ImportError:
    LOCATION_DATA = {}
    _RENAMER_OK = False

try:
    from json_sync_validator import validate_folder
    _VALIDATOR_OK = True
except ImportError:
    _VALIDATOR_OK = False

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
    "brandon": "BTC", "brandon exchange": "BTC", "brandon town center": "BTC", "brandon mall": "BTC",
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
    "nike clearance 192": "NC192", "clearance 192": "NC192",
    "store 192": "NC192", "us 192": "NC192", "ncs 192": "NC192",
    "the loop": "NCLP", "loop": "NCLP", "nike clearance loop": "NCLP",
    "clearance loop": "NCLP", "loop clearance": "NCLP",
}

def resolve_nlp(text):
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


# ── Helpers ───────────────────────────────────────────────────────────────────

VIDEO_EXTS = {".mov", ".mp4", ".MOV", ".MP4", ".mts", ".MTS"}

def _load_json_db(folder):
    """Load all SACC pipeline JSON files from <folder>/json/."""
    json_dir = os.path.join(folder, "json")
    records = []
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

def _preflight_scan(folder):
    """Fast partial-hash dedup scan."""
    if not folder or not os.path.isdir(folder):
        return []
    all_files = [f for f in Path(folder).iterdir()
                 if f.suffix.lower() in {'.mp4', '.mov'} and not f.name.startswith('.')]
    by_size = defaultdict(list)
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
        hashes = defaultdict(list)
        for f in files:
            h = hashlib.md5()
            try:
                with open(f, 'rb') as fh:
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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "fcp_ok": _FCP_OK,
        "renamer_ok": _RENAMER_OK,
        "validator_ok": _VALIDATOR_OK,
        "location_count": len(LOCATION_DB),
        "time": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/locations")
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
    # Also include renamer_logic locations if different
    for code, entry in LOCATION_DATA.items():
        if code not in LOCATION_DB:
            locs.append({
                "code": code,
                "name": entry.get("name", code),
                "type": entry.get("type", ""),
                "region": entry.get("region", ""),
                "header": f"{code}-{entry.get('type','LOC')}",
            })
    return jsonify({"locations": locs})


@app.route("/api/resolve-location", methods=["POST"])
def resolve_location():
    body = request.get_json(silent=True) or {}
    return jsonify(resolve_nlp(body.get("text", "")))


@app.route("/api/folder-status")
def folder_status():
    folder = request.args.get("path", "")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    if not _VALIDATOR_OK:
        return jsonify({"error": "json_sync_validator not available"}), 500
    report = validate_folder(folder)
    report.pop("records", None)  # strip verbose per-file data for summary call
    return jsonify(report)


@app.route("/api/json-db")
def json_db():
    folder = request.args.get("path", "")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    records, json_dir = _load_json_db(folder)
    # Strip internal path fields before sending to frontend
    clean = []
    for r in records:
        c = {k: v for k, v in r.items() if not k.startswith("_")}
        c["_stem"] = os.path.splitext(r["_json_file"])[0]
        clean.append(c)
    return jsonify({
        "folder": folder,
        "json_dir": json_dir,
        "count": len(clean),
        "records": clean,
    })


@app.route("/api/json-db", methods=["PATCH"])
def patch_json_db():
    body = request.get_json(silent=True) or {}
    folder = body.get("path", "")
    stem   = body.get("stem", "")
    if not folder or not stem:
        return jsonify({"error": "path and stem required"}), 400
    json_path = os.path.join(folder, "json", f"{stem}.json")
    if not os.path.exists(json_path):
        return jsonify({"error": f"JSON not found: {json_path}"}), 404
    try:
        with open(json_path) as fh:
            payload = json.load(fh)
        # Apply all non-underscore, non-reserved fields from body
        for k, v in body.items():
            if k not in ("path", "stem") and not k.startswith("_"):
                payload[k] = v
        payload["_patched_at"] = datetime.now(timezone.utc).isoformat()
        with open(json_path, "w") as fh:
            json.dump(payload, fh, indent=2)
        return jsonify({"ok": True, "stem": stem})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/apply-location", methods=["POST"])
def apply_location():
    body    = request.get_json(silent=True) or {}
    folder  = body.get("path", "")
    code    = body.get("loc_code", "")
    if not folder or not code:
        return jsonify({"error": "path and loc_code required"}), 400
    records, json_dir = _load_json_db(folder)
    unknown = [r for r in records if not r.get("loc_code_confirmed")]
    updated = 0
    for r in unknown:
        jpath = r["_json_path"]
        try:
            with open(jpath) as fh:
                payload = json.load(fh)
            payload["loc_code_confirmed"]  = code
            payload["loc_source"]          = "manual"
            payload["Location_Confidence"] = "manual"
            with open(jpath, "w") as fh:
                json.dump(payload, fh, indent=2)
            updated += 1
        except Exception:
            pass
    return jsonify({"ok": True, "updated": updated, "loc_code": code})


@app.route("/api/whitelist")
def whitelist():
    path = request.args.get("path", "/Users/miniman/SACC/whitelist.json")
    if not os.path.exists(path):
        return jsonify({"error": f"Not found: {path}", "records": []}), 404
    try:
        with open(path) as fh:
            data = json.load(fh)
        items = data if isinstance(data, list) else [data]
        return jsonify({"count": len(items), "records": items})
    except Exception as e:
        return jsonify({"error": str(e), "records": []}), 500


@app.route("/api/preflight", methods=["POST"])
def preflight():
    body   = request.get_json(silent=True) or {}
    folder = body.get("path", "")
    if not folder:
        return jsonify({"error": "path required"}), 400
    dupes = _preflight_scan(folder)
    return jsonify({
        "folder": folder,
        "duplicate_groups": len(dupes),
        "duplicates": dupes,
        "clean": len(dupes) == 0,
    })


@app.route("/api/rename", methods=["POST"])
def rename():
    body       = request.get_json(silent=True) or {}
    folder     = body.get("path", "")
    loc        = body.get("loc", "")
    identifier = body.get("identifier", "")
    dry_run    = body.get("dry_run", True)

    if not folder:
        return jsonify({"error": "path required"}), 400
    if not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 404

    results = []

    if _RENAMER_OK and identifier:
        # Vibe renamer — classic mode with identifier
        try:
            for status in run_vibe_renamer(folder, loc, identifier, dry_run=dry_run):
                if "error" in status:
                    return jsonify({"error": status["error"]}), 500
                if status.get("done"):
                    return jsonify({
                        "ok": True,
                        "mode": "vibe",
                        "processed": status.get("processed_count", 0),
                        "elapsed_s": status.get("elapsed_seconds", 0),
                        "results": status.get("results", []),
                    })
                results.append({
                    "original": status.get("original", ""),
                    "new":      status.get("new", ""),
                    "current":  status.get("current", 0),
                    "total":    status.get("total", 0),
                })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif _FCP_OK:
        # FCP renamer — no identifier needed
        try:
            renamed = []
            for item in run_fcp_renamer(folder, loc_override=loc, dry_run=dry_run):
                if "error" in item:
                    return jsonify({"error": item["error"]}), 500
                renamed.append(item)
                results.append({
                    "original": item.get("original", ""),
                    "new":      item.get("new", ""),
                })
            return jsonify({
                "ok": True,
                "mode": "fcp",
                "dry_run": dry_run,
                "processed": len(renamed),
                "results": results,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify({"error": "No renamer available (fcp_namer or renamer_logic not loaded)"}), 500

    return jsonify({"ok": True, "results": results})


@app.route("/api/pipeline-run", methods=["POST"])
def pipeline_run():
    """Kick off sacc_pipeline.py as a subprocess."""
    import subprocess
    body     = request.get_json(silent=True) or {}
    folder   = body.get("path", "")
    loc      = body.get("loc", "")
    fcp_mode = body.get("fcp_mode", True)
    root     = body.get("root", "/Volumes/Team Bank 12/SACC")

    if not folder:
        return jsonify(SACC_ERRORS.config("E001", "path required")), 400

    script = os.path.join(os.path.dirname(__file__), "sacc_pipeline.py")
    if not os.path.exists(script):
        return jsonify(SACC_ERRORS.system("E002", "sacc_pipeline.py not found")), 500

    if not os.path.isdir(folder):
        return jsonify(SACC_ERRORS.config("E003", f"Folder not found: {folder}")), 404

    cmd = [sys.executable, script, "--inbox", folder, "--root", root]
    if fcp_mode:
        cmd.append("--fcp")
    if loc:
        cmd += ["--loc", loc.strip().upper()]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        ok = result.returncode == 0
        combined = result.stdout[-4000:]
        if result.stderr:
            combined += "\n--- STDERR ---\n" + result.stderr[-1000:]
        resp = {
            "ok":     ok,
            "stdout": combined,
            "code":   result.returncode,
        }
        if not ok:
            resp.update(SACC_ERRORS.pipeline("E010",
                f"Pipeline exited with code {result.returncode}. "
                "Check stdout for details."))
        return jsonify(resp)
    except subprocess.TimeoutExpired:
        return jsonify(SACC_ERRORS.system("E011", "Pipeline timed out after 300 s — "
            "reduce batch size or increase timeout")), 504
    except Exception as e:
        return jsonify(SACC_ERRORS.system("E012", str(e))), 500


# ── SQLite database endpoints ─────────────────────────────────────────────────

@app.route("/api/db/sync", methods=["POST"])
def db_sync():
    """Ingest all JSON files in <folder>/json/ into sacc.db."""
    if not _DB_OK:
        return jsonify({"error": "db.py not available"}), 500
    body   = request.get_json(silent=True) or {}
    folder = body.get("path", "")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    try:
        db     = _get_db(folder)
        result = db.sync_from_folder(folder)
        summary = db.validation_summary()
        return jsonify({"ok": True, "folder": folder, **result, "validation": summary})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/search")
def db_search():
    """Full-text search across the SQLite database for a folder."""
    if not _DB_OK:
        return jsonify({"error": "db.py not available"}), 500
    folder = request.args.get("path", "")
    query  = request.args.get("q", "")
    limit  = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    try:
        db      = _get_db(folder)
        results = db.search(query, limit=limit, offset=offset)
        total   = db.stats().get("total", 0)
        return jsonify({
            "query":   query,
            "total":   total,
            "count":   len(results),
            "offset":  offset,
            "results": results,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/stats")
def db_stats():
    if not _DB_OK:
        return jsonify({"error": "db.py not available"}), 500
    folder = request.args.get("path", "")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    try:
        db = _get_db(folder)
        return jsonify({
            "stats":         db.stats(),
            "top_locations": db.top_locations(10),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/record")
def db_get_record():
    if not _DB_OK:
        return jsonify({"error": "db.py not available"}), 500
    folder = request.args.get("path", "")
    stem   = request.args.get("stem", "")
    if not folder or not stem:
        return jsonify({"error": "path and stem required"}), 400
    try:
        record = _get_db(folder).get_by_stem(stem)
        if record is None:
            return jsonify({"error": f"Record not found: {stem}"}), 404
        return jsonify(record)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/record", methods=["PATCH"])
def db_patch_record():
    if not _DB_OK:
        return jsonify({"error": "db.py not available"}), 500
    body   = request.get_json(silent=True) or {}
    folder = body.pop("path", "")
    stem   = body.pop("stem", "")
    if not folder or not stem:
        return jsonify({"error": "path and stem required"}), 400
    try:
        ok = _get_db(folder).patch(stem, body)
        return jsonify({"ok": ok, "stem": stem})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/validation-summary")
def db_validation_summary():
    if not _DB_OK:
        return jsonify({"error": "db.py not available"}), 500
    folder = request.args.get("path", "")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    try:
        return jsonify(_get_db(folder).validation_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/validate")
def db_validate():
    if not _DB_OK:
        return jsonify({"error": "db.py not available"}), 500
    folder = request.args.get("path", "")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    try:
        db   = _get_db(folder)
        rows = db.list_all(limit=10000)
        missing_json = [r["stem"] for r in rows if r.get("json_path") and not os.path.exists(r["json_path"])]
        no_model     = [r["stem"] for r in rows if not r.get("model")]
        no_loc       = [r["stem"] for r in rows if not r.get("loc_code")]
        return jsonify({
            "total":        len(rows),
            "missing_json": missing_json,
            "no_model":     no_model,
            "no_loc":       no_loc,
            "clean":        not (missing_json or no_model or no_loc),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reveal", methods=["POST"])
def reveal_in_finder():
    """Open the enclosing folder in Finder and select the file (macOS only).
    Body: { "path": "<folder>", "file": "<filename>" }
    """
    body     = request.get_json(silent=True) or {}
    folder   = body.get("path", "")
    filename = body.get("file", "")
    if not folder:
        return jsonify({"error": "path required"}), 400
    safe_dir = Path(folder).resolve()
    if not safe_dir.is_dir():
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    if filename:
        target = (safe_dir / Path(filename).name).resolve()
        if target.parent == safe_dir and target.is_file():
            subprocess.Popen(["open", "-R", str(target)])
            return jsonify({"ok": True, "revealed": str(target)})
    subprocess.Popen(["open", str(safe_dir)])
    return jsonify({"ok": True, "opened": str(safe_dir)})


@app.route("/api/video")
def serve_video():
    """Stream a video file from the NAS for in-browser preview.
    Query params: path=<folder>  file=<filename>
    """
    folder   = request.args.get("path", "")
    filename = request.args.get("file", "")
    if not folder or not filename:
        abort(400)
    # Resolve and validate — prevent path traversal
    safe_dir  = Path(folder).resolve()
    safe_file = (safe_dir / Path(filename).name).resolve()
    if safe_file.parent != safe_dir or not safe_file.is_file():
        abort(404)
    return send_file(str(safe_file), conditional=True)


# ── Pipeline database endpoints (/api/pipeline/*) ────────────────────────────
# These work directly against sneakers_broll / shoot_sessions in any sacc.db
# pointed to by the `db` query param. Independent of the legacy SACCDB/clips layer.

def _pipeline_db(db_param: str):
    """Return (con, error_response) for a pipeline DB path param."""
    if not db_param or not os.path.exists(db_param):
        return None, (jsonify({"error": f"DB not found: {db_param}"}), 404)
    try:
        import sqlite3 as _sql
        con = _sql.connect(db_param)
        con.row_factory = _sql.Row
        return con, None
    except Exception as e:
        return None, (jsonify({"error": str(e)}), 500)


@app.route("/api/pipeline/search")
def pipeline_search():
    """
    Compound search across sneakers_broll.

    Query params (all optional):
      db          — path to sacc.db
      q           — full-text query (brand, silhouette, colorway, style_code)
      orientation — vertical | horizontal | all (default all)
      year        — 4-digit shoot year (e.g. 2025)
      shot_type   — broll | vlog | all (default all)
      session_id  — exact session ID
      loc_code    — exact location code (e.g. FLM)
      limit       — default 50
      offset      — default 0
    """
    db_param = request.args.get("db", "")
    con, err = _pipeline_db(db_param)
    if err:
        return err

    q           = request.args.get("q", "").strip()
    orientation = request.args.get("orientation", "all").lower()
    year        = request.args.get("year", "").strip()
    shot_type   = request.args.get("shot_type", "all").lower()
    session_id  = request.args.get("session_id", "").strip()
    loc_code    = request.args.get("loc_code", "").strip()
    limit       = min(int(request.args.get("limit", 50)), 500)
    offset      = int(request.args.get("offset", 0))

    try:
        conditions = []
        params     = []

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
            conditions.append("shoot_year = ?")
            params.append(year)

        if shot_type in ("broll", "vlog"):
            conditions.append("shot_type = ?")
            params.append(shot_type)

        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        if loc_code:
            conditions.append("loc_code = ?")
            params.append(loc_code)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        total_row = con.execute(
            f"SELECT COUNT(*) FROM sneakers_broll {where}", params
        ).fetchone()[0]

        rows = con.execute(
            f"SELECT * FROM sneakers_broll {where} ORDER BY creation_time DESC, original_file_id LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        return jsonify({
            "total":  total_row,
            "count":  len(rows),
            "offset": offset,
            "results": [dict(r) for r in rows],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        con.close()


@app.route("/api/pipeline/sessions")
def pipeline_sessions():
    """List all shoot sessions. Query param: db=<path to sacc.db>"""
    db_param = request.args.get("db", "")
    con, err = _pipeline_db(db_param)
    if err:
        return err
    try:
        rows = con.execute(
            "SELECT * FROM shoot_sessions ORDER BY shoot_date DESC, session_id"
        ).fetchall()
        return jsonify({"sessions": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        con.close()


@app.route("/api/pipeline/stats")
def pipeline_stats():
    """Aggregate stats for the pipeline DB. Query param: db=<path to sacc.db>"""
    db_param = request.args.get("db", "")
    con, err = _pipeline_db(db_param)
    if err:
        return err
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

        return jsonify({
            "total": total, "verified": verified,
            "shot_type": {"broll": broll, "vlog": vlog},
            "orientation": {"vertical": vertical, "horizontal": horizontal},
            "archived": archived, "sessions": sessions,
            "years": years,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        con.close()


@app.route("/api/pipeline/open", methods=["POST"])
def pipeline_open():
    """
    Open a clip's asset in Finder (macOS).
    Body: { "db": "<db_path>", "original_file_id": "<id>" }
    """
    body    = request.get_json(silent=True) or {}
    db_path = body.get("db", "")
    fid     = body.get("original_file_id", "")
    if not db_path or not fid:
        return jsonify({"error": "db and original_file_id required"}), 400

    con, err = _pipeline_db(db_path)
    if err:
        return err
    try:
        row = con.execute(
            "SELECT asset_url FROM sneakers_broll WHERE original_file_id=?", (fid,)
        ).fetchone()
        if not row or not row["asset_url"]:
            return jsonify({"error": f"No asset_url for {fid}"}), 404
        path = row["asset_url"]
        if not os.path.exists(path):
            return jsonify({"error": f"File not found at {path}"}), 404
        subprocess.Popen(["open", "-R", path])
        return jsonify({"ok": True, "revealed": path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        con.close()


@app.route("/api/pipeline/mark-fcp", methods=["POST"])
def pipeline_mark_fcp():
    """
    Mark clip(s) as FCP-linked (frozen — phase7/phase8 will not touch them).
    Body: { "db": "<db_path>", "ids": ["C0015", ...], "linked": true }
    """
    body    = request.get_json(silent=True) or {}
    db_path = body.get("db", "")
    ids     = body.get("ids", [])
    linked  = 1 if body.get("linked", True) else 0
    if not db_path or not ids:
        return jsonify({"error": "db and ids required"}), 400

    con, err = _pipeline_db(db_path)
    if err:
        return err
    try:
        import sqlite3 as _sql
        con2 = _sql.connect(db_path)
        con2.executemany(
            "UPDATE sneakers_broll SET fcp_linked=? WHERE original_file_id=?",
            [(linked, fid) for fid in ids],
        )
        con2.commit()
        con2.close()
        return jsonify({"ok": True, "updated": len(ids), "fcp_linked": bool(linked)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        con.close()


# ── Error Repository ─────────────────────────────────────────────────────────
#
# Persists to SACC/error_log.json. Two collections:
#   "history"  — timestamped runtime events (auto-appended by the app)
#   "known"    — pre-documented errors with resolution steps (seeded on first run)
#
_ERROR_LOG_PATH = os.path.join(os.path.dirname(__file__), "error_log.json")

_KNOWN_ERRORS = [
    {
        "code": "E001", "category": "config",
        "title": "Path argument missing",
        "description": "A required 'path' field was not included in the API request body.",
        "resolution": "Provide a 'path' field pointing to a valid folder on the NAS.",
        "example": '{"path": "/Volumes/Team Bank 12/Sneeaker Solo"}',
    },
    {
        "code": "E002", "category": "system",
        "title": "sacc_pipeline.py not found",
        "description": "The pipeline orchestrator script is missing from the SACC root directory.",
        "resolution": "Verify /Users/miniman/SACC/sacc_pipeline.py exists. Re-clone the repo if missing.",
        "example": "",
    },
    {
        "code": "E003", "category": "config",
        "title": "Source folder not found",
        "description": "The specified path does not exist on disk — usually the NAS is not mounted.",
        "resolution": "Open Finder and verify /Volumes/Team Bank 12 is visible. "
                      "If not, reconnect to the NAS via Network → Connect to Server.",
        "example": "",
    },
    {
        "code": "E010", "category": "pipeline",
        "title": "Pipeline exited with non-zero code",
        "description": "sacc_pipeline.py crashed or encountered an unhandled exception.",
        "resolution": "Expand the log panel in the Dashboard for the first [ERROR] line. "
                      "Run sacc_pipeline.py directly from Terminal for the full traceback.",
        "example": "python3 /Users/miniman/SACC/sacc_pipeline.py --inbox <path> --fcp",
    },
    {
        "code": "E011", "category": "system",
        "title": "Pipeline timeout (300 s)",
        "description": "The pipeline took more than 5 minutes — usually a very large batch "
                       "or a hung Apple Compressor job.",
        "resolution": "Split the batch into smaller date folders (≤20 files each). "
                      "Check that Apple Compressor is not already running a job.",
        "example": "",
    },
    {
        "code": "E012", "category": "system",
        "title": "Pipeline subprocess crashed",
        "description": "subprocess.run() raised an unexpected exception before the script could start.",
        "resolution": "Run python3 /Users/miniman/SACC/sacc_pipeline.py directly to see the full error. "
                      "Check that Python 3 and all dependencies are installed.",
        "example": "pip3 install -r /Users/miniman/SACC/requirements.txt",
    },
    {
        "code": "E020", "category": "validation",
        "title": "No companion JSON (Stage 8 queue)",
        "description": "A video file exists in the folder but has no matching JSON in the json/ subfolder. "
                       "This is the expected state for unprocessed footage — not a failure.",
        "resolution": "Run the Batch Pipeline (Dashboard → Start Batch Pipeline) to send the file "
                      "through Vertex AI and generate the JSON record.",
        "example": "",
    },
    {
        "code": "E021", "category": "validation",
        "title": "Orphaned JSON",
        "description": "A JSON file exists in json/ but has no matching video file in the folder.",
        "resolution": "The source video may have been moved or deleted. Either restore the video "
                      "or delete the orphaned JSON. Use Verify view to inspect.",
        "example": "",
    },
    {
        "code": "E030", "category": "validation",
        "title": "Required JSON field missing",
        "description": "A JSON record is missing one of: original_file, analysed_at, proxy_deleted, Model, SKU.",
        "resolution": "Re-run Stage 8 (Vertex AI) on the file to regenerate a complete JSON record. "
                      "If the issue persists, check that gemini_pipeline.py is writing all required fields.",
        "example": "",
    },
    {
        "code": "E040", "category": "renamer",
        "title": "Invalid location code",
        "description": "A location code entered in the Renamer or Pipeline location override field "
                       "is not in the SACC location database.",
        "resolution": "Use a valid SACC code: PDM, FLM, MAM, OFS, WOM, VLD, IDR, LBV, WFL, WGN, "
                      "OMP, SEM, LKL, THL, BTC, INP, UNM, TPA, HVP, AVE, LCN, DOL, GVA, CEL-K, KSM, NC192, NCLP.",
        "example": "",
    },
    {
        "code": "E041", "category": "renamer",
        "title": "No video files found in folder",
        "description": "The Renamer or FCP namer could not find any .mov/.mp4/.m4v files at the "
                       "specified path.",
        "resolution": "Check that the path points to a folder containing video files directly "
                      "(not a parent folder). For FCP libraries, the pipeline now auto-detects "
                      "'Final Cut Original Media/<date>/' subfolders.",
        "example": "",
    },
    {
        "code": "E050", "category": "preflight",
        "title": "Duplicate footage detected",
        "description": "The Duplicate Scan found two or more files with identical size and checksum.",
        "resolution": "Review the duplicates listed in the Duplicate Scan panel. Delete the extra "
                      "copies before running the pipeline to avoid wasting Compressor and Vertex AI quota.",
        "example": "",
    },
    {
        "code": "E060", "category": "api",
        "title": "API server offline",
        "description": "The Flask API on port 5174 is not responding.",
        "resolution": "Open Terminal and run: bash /Users/miniman/SACC/start_sacc.command\n"
                      "Or run the API directly: python3 /Users/miniman/SACC/api.py",
        "example": "bash /Users/miniman/SACC/start_sacc.command",
    },
]

def _load_error_log():
    if not os.path.exists(_ERROR_LOG_PATH):
        return {"history": [], "known": _KNOWN_ERRORS}
    try:
        with open(_ERROR_LOG_PATH) as f:
            data = json.load(f)
        # Always refresh known errors from source of truth
        data["known"] = _KNOWN_ERRORS
        return data
    except Exception:
        return {"history": [], "known": _KNOWN_ERRORS}

def _save_error_log(data):
    try:
        with open(_ERROR_LOG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _append_error_event(code, message, context=""):
    data = _load_error_log()
    data["history"].append({
        "id":        len(data["history"]) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "code":      code,
        "message":   message,
        "context":   context,
        "resolved":  False,
    })
    # Cap history at 500 entries
    if len(data["history"]) > 500:
        data["history"] = data["history"][-500:]
    _save_error_log(data)


@app.route("/api/errors")
def get_errors():
    return jsonify(_load_error_log())


@app.route("/api/errors", methods=["POST"])
def post_error():
    body = request.get_json(silent=True) or {}
    code    = body.get("code", "E000")
    message = body.get("message", "")
    context = body.get("context", "")
    if not message:
        return jsonify({"error": "message required"}), 400
    _append_error_event(code, message, context)
    return jsonify({"ok": True})


@app.route("/api/errors/<int:entry_id>", methods=["PATCH"])
def patch_error(entry_id):
    """Mark a history entry resolved."""
    data = _load_error_log()
    for entry in data["history"]:
        if entry["id"] == entry_id:
            entry["resolved"] = True
            _save_error_log(data)
            return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@app.route("/api/errors/history", methods=["DELETE"])
def clear_error_history():
    data = _load_error_log()
    data["history"] = []
    _save_error_log(data)
    return jsonify({"ok": True, "cleared": True})


# ── Dev server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  ┌─────────────────────────────────────────┐")
    print("  │   SACC API  —  http://localhost:5174    │")
    print("  │   FCP engine:", "✓" if _FCP_OK else "✗ (fcp_namer.py missing)",
          "             │")
    print("  │   Renamer:  ", "✓" if _RENAMER_OK else "✗ (renamer_logic.py missing)",
          "             │")
    print("  └─────────────────────────────────────────┘\n")
    app.run(port=5174, debug=False)

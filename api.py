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
            for status in run_vibe_renamer(folder, loc, identifier):
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
                    "new":      item.get("new_name", ""),
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

    if not folder:
        return jsonify({"error": "path required"}), 400

    script = os.path.join(os.path.dirname(__file__), "sacc_pipeline.py")
    if not os.path.exists(script):
        return jsonify({"error": "sacc_pipeline.py not found"}), 500

    cmd = [sys.executable, script, "--src", folder]
    if fcp_mode:
        cmd.append("--fcp")
    if loc:
        cmd += ["--loc", loc]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return jsonify({
            "ok":      result.returncode == 0,
            "stdout":  result.stdout[-4000:],   # last 4k chars
            "stderr":  result.stderr[-2000:],
            "code":    result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Pipeline timed out after 300s"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

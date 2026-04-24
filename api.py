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
"""

import os, sys, json, time, re, hashlib
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

from flask import Flask, request, jsonify
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

app = Flask(__name__)
CORS(app)  # allow SCAA frontend on :5173 to call this API on :5174

# ── Optional imports (graceful degradation) ───────────────────────────────────
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

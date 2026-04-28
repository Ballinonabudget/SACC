# SACC — Sneaker Archive Command Center
## Claude Code Project Brief — read this fully before writing any code

---

## What this project is

SACC is a local pipeline + web app for cataloging sneaker B-roll video footage.
It identifies shoes via AI (Gemini/Vertex), stores metadata in SQLite, and
presents everything through a web UI with search, gallery, timeline, and pipeline views.

---

## How to run the app (no terminal needed for the user)

```bash
# Double-click in Finder:
/Users/miniman/SACC/start_sacc.command

# Or from terminal:
bash /Users/miniman/SACC/start_sacc.command
```

This starts:
- **Flask API** on `http://localhost:5174` (api.py)
- **Static file server** on `http://localhost:5173` (serves SCAA/ folder)
- Opens browser to `http://localhost:5173/SACC.html` automatically

There is also a legacy **Streamlit** dashboard (`app.py`) — run with `streamlit run app.py`.
The current focus is the SCAA frontend + Flask API stack, not Streamlit.

---

## Repo layout

```
/Users/miniman/SACC/
├── start_sacc.command     ← double-click launcher (Finder-friendly)
├── api.py                 ← Flask REST API (port 5174)
├── app.py                 ← Streamlit dashboard (legacy, port 8501)
├── db.py                  ← SQLite layer with FTS5 full-text search
├── sacc_pipeline.py       ← 10-stage pipeline orchestrator
├── gemini_pipeline.py     ← Gemini/Vertex AI video analysis
├── sacc_watcher.py        ← Folder watcher (watches Inbox/, fires pipeline)
├── sacc_test.py           ← CLI test tool: inspect / search / rename
├── compress_jordans.py    ← Apple Compressor proxy generation
├── renamer_logic.py       ← SACC filename builder + metadata extraction
├── fcp_namer.py           ← FCP GPS-aware naming engine
├── json_sync_validator.py ← Validates JSON ↔ file consistency
├── forensic_match.py      ← Fuzzy match JSONs to videos
├── .env                   ← API keys (GEMINI_API_KEY set, do NOT commit)
├── whitelist.json         ← Approved shoe models whitelist
├── SCAA/                  ← Frontend (React + HTML, served by static server)
│   └── SACC.html          ← Entry point → http://localhost:5173/SACC.html
├── frontend/              ← Older React component files (may be merged into SCAA)
├── ingestion_zone/        ← Test input folder for sacc_test.py rename mode
└── test_data/             ← Test fixture files
```

---

## Architecture

```
Inbox/ (NAS)
  └─[sacc_watcher.py]─→ detects new files (30s settle)
       └─[sacc_pipeline.py]─→ 10 stages:
            1. FCP Inspector rename (manual, pre-consolidation)
            2. FCP consolidation
            3. Batch rename → permanent SACC filename (relational key)
            4. Organise → /SACC/YYYY/YYYYMMDD/
            5. Pre-Flight gate (ffprobe: duration + motion)
            6. Apple Compressor → _proxy/<same_name>.mp4
            7. Wait for proxies
            8. Gemini/Vertex AI → JSON per file
            9. Delete proxies (transient)
           10. Apply AI-confirmed location to UNKNOWN filenames

JSON written → db.py (SQLite) ← api.py (Flask) ← SCAA frontend (search/gallery/timeline)
```

---

## Key file paths

| What | Path |
|------|------|
| Repo | `/Users/miniman/SACC/` |
| Branch | `v2.0-path-integration` |
| NAS root | `/Volumes/Team Bank 12/SACC/` |
| NAS Inbox | `/Volumes/Team Bank 12/SACC/Inbox/` |
| Sneeaker Solo folder | `/Volumes/Team Bank 12/Sneeaker Solo/` (existing JSON + videos, test target) |
| SQLite DB | `/Volumes/Team Bank 12/Sneeaker Solo/sacc.db` (or per-folder) |
| .env | `/Users/miniman/SACC/.env` |
| API log | `/tmp/sacc_api.log` |
| UI log | `/tmp/sacc_ui.log` |

---

## Environment (.env already set up)

```
GEMINI_API_KEY=<already set in .env>
VERTEX_PROJECT_ID=<set this to switch to Vertex AI — preferred for production>
VERTEX_LOCATION=us-central1
VERTEX_MODEL=gemini-2.5-pro
```

`gemini_pipeline.py` loads `.env` automatically via `python-dotenv`.
When `VERTEX_PROJECT_ID` is set, it switches to Vertex AI. Otherwise it uses
the Gemini API via `google.generativeai`.

---

## Gemini pipeline — current state (already correct)

`gemini_pipeline.py` already has:
- ✅ Gemini File API (upload via `genai.upload_file()`, not base64)
- ✅ Upload-once pattern (upload → wait for ACTIVE → infer separately)
- ✅ Exponential backoff retry (`_retry()` helper: 5s → 10s → 20s)
- ✅ Auto-delete uploaded file after inference
- ✅ `.env` loading
- ✅ Vertex AI fallback path built in
- ✅ Model: `gemini-2.5-pro` (not flash — pro handles video better)
- ✅ Location detection: visual signage + audio transcript → SACC location code

**The 429 rate limit issue from earlier sessions is largely addressed.**
If 429s return, increase `delay` in `_retry()` from 5 to 30 and `attempts` from 3 to 5.

---

## SACC filename convention

**FCP mode (recommended — GPS auto-detect):**
```
[LOC-TYPE]_[YYYYMMDD]_[CameraModel]_[OriginalStem]
PDM-MALL_20241221_iPhone15ProMax_IMG_3439.mov
```

**Classic mode (manual --loc --id):**
```
[LOC-TYPE]_[YYMMDD]_[ShoeIdentifier]_[CameraModel]_[OriginalStem]
FLM-MALL_260423_Air-Jordan-1-Chicago_iPhone15ProMax_IMG_3439.mov
```

**Proxy (always):** same stem as source, forced .mp4, lives in `_proxy/` subfolder.
**JSON (always):** same stem as source, lives in `json/` subfolder.

The filename stem is the **permanent relational key** — JSON ↔ proxy ↔ hi-res master
are all linked by matching stems.

---

## SACC location codes (Florida retail network)

```
FLM=Florida Mall          MAM=Mall at Millenia      OFS=Orlando Fashion Square
WOM=West Oaks Mall        VLD=Vineland Premium       IDR=International Drive
LBV=Lake Buena Vista      WFL=Waterford Lakes        WGN=Winter Garden Village
OMP=Orlando Marketplace   SEM=Seminole Towne Ctr     LKL=Lakeland Square
PDM=Paddock Mall (Ocala)  THL=Tallahassee Mall       BRN=Brandon Exchange
INP=International Plaza   UNM=University Mall Tampa  TPA=Tampa Premium Outlets
HVP=Hyde Park Village     AVE=Aventura Mall          LCN=Lincoln Road
DOL=Dolphin Mall          GVA=Gainesville Celebration CEL-K=Celebration Kissimmee
KSM=Kissimmee Osceola
```

---

## SQLite schema (db.py → SACCDB class)

Table: `clips` — one row per renamed video file
```
id, original_file, fcp_filename, shoot_date, cam_make, cam_model,
loc_code, loc_name, loc_source, loc_confidence, loc_visual, loc_audio,
model, sku, size, price,
proxy_file, proxy_deleted, analysed_at,
json_path, folder_path, created_at, updated_at
```

Table: `clips_fts` — FTS5 full-text search over:
`model, sku, fcp_filename, original_file, loc_code, loc_name, loc_visual, loc_audio`

Key methods:
```python
db = SACCDB("/path/to/sacc.db")
db.sync_from_folder("/path/to/folder")   # imports all JSONs in folder
results = db.search("chicago")            # full-text search
record  = db.get_by_stem("FLM-MALL_...")
db.patch(stem, {"loc_code": "PDM"})
```

---

## sacc_test.py — 3 CLI modes

```bash
# Inspect folder (no changes)
python sacc_test.py inspect --folder "/Volumes/Team Bank 12/Sneeaker Solo"

# Search existing JSON records
python sacc_test.py search --folder "/Volumes/Team Bank 12/Sneeaker Solo" --query "Jordan 1"
python sacc_test.py search --folder "/Volumes/Team Bank 12/Sneeaker Solo" --query "555088-101"

# Rename videos from JSON (no Gemini call)
python sacc_test.py rename --folder "/Volumes/Team Bank 12/Sneeaker Solo" --loc FLM
python sacc_test.py rename --folder "/Volumes/Team Bank 12/Sneeaker Solo" --loc FLM --apply

# Rename with manual identifier (no JSON needed)
python sacc_test.py rename --folder "/Users/miniman/SACC/ingestion_zone" --loc PDM --id "Air Jordan 1 Chicago" --dry-run
python sacc_test.py rename --folder "/Users/miniman/SACC/ingestion_zone" --loc PDM --id "Air Jordan 1 Chicago" --apply
```

---

## sacc_pipeline.py — full run

```bash
# FCP mode (recommended — GPS auto-detect)
python sacc_pipeline.py --fcp \
  --inbox "/Volumes/Team Bank 12/SACC/Inbox" \
  --root  "/Volumes/Team Bank 12/SACC"

# FCP dry-run (preview only)
python sacc_pipeline.py --fcp --dry-run

# Classic mode (manual shoe ID)
python sacc_pipeline.py \
  --inbox "/Volumes/Team Bank 12/SACC/Inbox" \
  --root  "/Volumes/Team Bank 12/SACC" \
  --loc FLM --id "Air Jordan 1 Chicago"
```

---

## Git state

```bash
git -C /Users/miniman/SACC log --oneline -10
git -C /Users/miniman/SACC status
```

Recent commits (most recent first):
- `529695b` feat: add Duplicates KPI card — 6th card fed from preflight scan
- `9847742` fix: Refresh button unresponsive — event object crashing loadStats
- `49de90d` feat: auto preflight scan on folder load, remove Proxy Cleaned KPI
- `8182271` fix: absolute path resolution in start_sacc.command
- `374ec5b` feat: SQLite layer, live search API, ADR, search-view live wiring
- `b9da499` feat: full SCAA migration — Flask API, Dashboard, Renamer, Verify views

Branch: `v2.0-path-integration`

---

## What to work on next — in priority order

### 1. Verify start_sacc.command works end-to-end
```bash
bash /Users/miniman/SACC/start_sacc.command
# Check: http://localhost:5174/api/health → should return {"status":"ok"}
# Check: http://localhost:5173/SACC.html  → should open UI
```

### 2. Sync the Sneeaker Solo folder into SQLite
The Sneeaker Solo folder has existing JSON outputs from a previous Gemini run.
Sync them into the database so the search view has live data:
```python
from db import SACCDB
db = SACCDB("/Volumes/Team Bank 12/Sneeaker Solo/sacc.db")
db.sync_from_folder("/Volumes/Team Bank 12/Sneeaker Solo")
```

### 3. Wire search API to the Sneeaker Solo database
`api.py` needs to know which `sacc.db` to query. Check if there's a
`DB_PATH` env var or if it's hardcoded. Update so it points to the
correct database for the current folder.

### 4. Test the full pipeline on a small batch (3–5 files)
Put 3–5 video files in Inbox and run with `--dry-run` first, then for real.
Watch for any remaining 429s — if they appear, increase `delay` in `_retry()`.

### 5. Streamlit deprecation warnings
`app.py` uses `use_container_width` which is deprecated. Replace with `width='stretch'`
or `width='content'` throughout. Low priority — Streamlit is the legacy UI.

---

## DO NOT

- Do NOT re-run Gemini on files that already have JSON output — check for existing JSON first
- Do NOT commit `.env` to git
- Do NOT merge to main until `start_sacc.command` → UI → search → results works end-to-end
- Do NOT rename files before running `inspect` to verify JSON ↔ video matching
- Do NOT touch `Master_Whitelist_v1/` or `Renamer Logic/` without asking — legacy reference files

---

## Cowork session context

Previous sessions in Cowork (Claude's chat interface) built the pipeline, fixed 429 errors,
and created a browser-based search GUI. The search GUI built in Cowork is a separate
standalone HTML tool — not part of the SCAA frontend. The project tracker is at:
`/Users/miniman/Library/Application Support/Claude/.../outputs/SACC_Project_Tracker.html`

Going forward: Claude Code handles all pipeline/Python/API/git work.
Cowork handles reports, the project tracker, and GUI prototyping.

---

## Script Consolidation — April 2026

SACC (`/Users/miniman/SACC/`) is now the **single central hub for all Python scripts**.
The `Sneaker_Scripts` folder (`/Users/miniman/Documents/Sneaker_Scripts/`) is now legacy — do NOT look for scripts there.

### Scripts added from Sneaker_Scripts

| File | Description |
|------|-------------|
| `Beta Halloween Edition.py` | Apple Compressor batch script for Halloween b-roll footage |
| `sneaker_pipeline.py` | Earlier standalone pipeline (kept for reference) |
| `sneaker_schema.py` | Sneaker metadata schema definitions |
| `API_Ready_HEVC.compressorsetting` | Apple Compressor HEVC preset — used by `compress_jordans.py` |

### Duplicate resolved
Both folders had `compress_jordans.py`. The SACC version (Apr 23, 2026) is newer and was kept.

### Path fix applied
`compress_jordans.py` previously referenced `SETTING_PATH` pointing to `Sneaker_Scripts/`.
This has been updated to `/Users/miniman/SACC/API_Ready_HEVC.compressorsetting`.

### Updated repo layout additions
```
/Users/miniman/SACC/
├── API_Ready_HEVC.compressorsetting  ← Apple Compressor HEVC preset
├── Beta Halloween Edition.py         ← Compressor batch for Halloween b-roll
├── sneaker_pipeline.py               ← Standalone pipeline (legacy reference)
└── sneaker_schema.py                 ← Metadata schema definitions
```


### Additional recovery — sneaker_schema.py (April 2026)
`sneaker_schema.py` was found in `/Users/miniman/Downloads/` (not in Sneaker_Scripts as expected).
It has been copied to `/Users/miniman/SACC/sneaker_schema.py`.
The Downloads copies at `/Users/miniman/Downloads/sneaker_schema.py` and
`/Users/miniman/Downloads/Claude Code/sneaker_schema.py` are now redundant.

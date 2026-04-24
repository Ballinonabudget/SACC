# SACC Codebase Audit Report
**Date:** 2026-04-23  
**Scope:** `/Users/miniman/SACC/` — full directory, analysis-only (no deletions)  
**Status:** Alpha — GUI functional, backend pipeline wired, Vertex AI pending

---

## 1. Security Findings

### CRITICAL — Third-Party API Keys in Committed JSON Files

| File | Key Found | Action Required |
|---|---|---|
| `dump.json` | StockX `STACK_API_KEY: blt818b0c67cf450811` | Add to `.gitignore` |
| `dump.json` | DataDog RUM token `pube74e41f9775d0c47e40393c3a40d1d8c` | Add to `.gitignore` |
| `dump.json` | Segment write key `t2qh429p5qub` | Add to `.gitignore` |
| `test_data/jordan/dump.json` | Same keys (exact duplicate) | Add to `.gitignore` |

These are StockX's infrastructure keys harvested during the scrape — not your own — but they expose a scraped raw page dump that should never be committed. These files have no pipeline utility; the useful data was zero-records anyway (both were malformed).

**Your own keys are handled correctly:** `gemini_pipeline.py` reads `GEMINI_API_KEY` from `.env` via `python-dotenv`. No hardcoded secrets found in any `.py` file.

### MISSING — `.gitignore` does not exist

There is no `.gitignore` in the repo root. Without it, the following will be committed on the next `git add`:
- `dump.json`, `test_data/jordan/dump.json` (scraped data + 3rd-party keys)
- `sacc_launchd.err`, `sacc_launchd.log` (runtime logs)
- `.env` (if created)
- `__pycache__/`, `.DS_Store`

### MISSING — `.env.example`

No documentation of required environment variables. Needed for onboarding and GitHub.

**Required vars:**
```
GEMINI_API_KEY=          # Current: Gemini 2.5 Pro (to be replaced by Vertex AI)
# VERTEX_PROJECT_ID=     # Future: GCP project for Vertex AI
# VERTEX_LOCATION=       # Future: e.g. us-central1
```

---

## 2. Redundancy & Obsolete Files

| File | Status | Reason |
|---|---|---|
| `app.py` | **Obsolete** | Streamlit UI — replaced by SCAA React GUI |
| `my_dashboard.py` | **Obsolete** | Another Streamlit dashboard — replaced |
| `dump.json` | **Obsolete** | Raw StockX page scrape, no pipeline utility, contains 3rd-party keys |
| `test_data/jordan/dump.json` | **Obsolete** | Exact duplicate of `dump.json` |
| `vibe_ghost_component/__init__.py` | **Orphan** | Empty module, not imported anywhere |
| `whitelist.json` | **Stale** | Only 2 records, both with empty `style_code` and `colorway_name`. The real whitelist lives in `SCAA/sacc/data.js` `SACC_WHITELIST` (12 entries). Needs to be populated. |
| `SCAA/find_path.py` | **Duplicate** | Identical to root `find_path.py` |
| `SCAA/renamer_logic.py` | **Duplicate** | Identical to root `renamer_logic.py` — single source of truth should be root |

---

## 3. Broken References & Import Issues

### `compress_jordans.py` — Setting File Path

```python
_SCRIPT_DIR  = "/Users/miniman/Documents/Sneaker_Scripts"
SETTING_PATH = (
    os.path.join(_THIS_DIR, SETTING_NAME)           # ← check here first
    if os.path.exists(os.path.join(_THIS_DIR, SETTING_NAME))
    else os.path.join(_SCRIPT_DIR, SETTING_NAME)    # ← hardcoded fallback
)
```

**Status:** `API_Ready_HEVC.compressorsetting` not found at either path.  
**Fix:** Copy `.compressorsetting` file into `SACC/` repo root. The lookup order is correct; the file just needs to be there.

### `compress_jordans.py` — Test Block Uses Typo Path

```python
test_folder = "/Volumes/Team Bank 12/Sneeaker Solo"   # ← "Sneeaker" typo
```

This only runs under `if __name__ == "__main__"` so it doesn't affect pipeline runs, but it will error if someone runs the file directly for testing.

### `jordan1_og_stockx.json` / `test_data/jordan/jordan1_og_stockx.json`

Both files are JSON arrays (`[{...}, {...}]`) but `sacc_test.py` tries to read them as dicts, calling `data["_source_json"]`. This produces:
```
[WARN] Could not parse jordan1_og_stockx.json: list indices must be integers or slices, not str
```
The search engine returns zero results when pointed at these files. These are not Gemini JSON outputs — they are scraper outputs. Either exclude them from `sacc_test.py` scanning or convert them to the Gemini output format.

### `renamer_logic.py` — `import re` Inside Loop

```python
for i, filename in enumerate(files):
    ...
    import re   # ← line 120, inside the for loop
```
This works because Python caches imports, but it's a code smell. Move `import re` to the top of the file.

### `sacc_test.py rename` — Circular Dependency

`mode_rename` requires pre-existing Gemini JSON outputs to extract shoe identifiers. On a first run with unprocessed footage there are no JSON files, so the rename stage errors out:
```
[ERROR] No JSON records found — cannot determine shoe identifiers.
```
The full pipeline (`sacc_pipeline.py`) handles this correctly by accepting `--id` as a CLI argument. The test tool's rename mode should add `--id` as a fallback parameter.

---

## 4. Rename Tool — Test Results ✓

**Test:** Dry-run against 44 real `.mov` files in `ingestion_zone/`  
**Result: PASS — naming convention is correct**

```
IN  : IMG_3439.mov (76.0 MB)
OUT : FLM-MALL_260423_Air-Jordan-1-Chicago_Cam_IMG_3439.mov

IN  : IMG_3438.mov (73.2 MB)
OUT : FLM-MALL_260423_Air-Jordan-1-Chicago_Cam_IMG_3438.mov
```

**Notes:**
- `date=260423` — defaults to today because ffprobe metadata extraction requires the binary to be running on the actual Mac. The bundled `ffprobe` binary is present at `/Users/miniman/SACC/ffprobe` and will extract real `creation_time` on hardware.
- `cam=Cam` — same reason; will extract `iPhone15ProMax` etc. from QuickTime tags on real footage.
- Prefix de-duplication regex works correctly — re-renaming an already-named file strips the old prefix cleanly.
- **One file already partially renamed:** `PDM-MALL_IMG_3422.mov` — missing the full `YYMMDD_identifier_cam_` segment. This file needs a full rename pass.

**Location data is 100% in sync** between `renamer_logic.py` (backend) and `SCAA/sacc/data.js` (frontend): all 25 locations match exactly.

---

## 5. Compression Tool — Test Results ⚠ BLOCKED (Expected)

**Status:** Apple Compressor binary not found at `/Applications/Compressor.app/Contents/MacOS/Compressor`

This is expected in the analysis environment. On your Mac with Compressor installed:
- The 3-guard duplicate-skip logic (G1/G2/G3) is correct and will prevent re-processing.
- The `wait_for_compression` polling loop and 3600s timeout are appropriate.
- The `_Gemini_API.mp4` output naming convention is consistent with what `gemini_pipeline.py` expects.

**Blocker to resolve before Vertex AI integration:**  
Copy `API_Ready_HEVC.compressorsetting` into the `SACC/` repo root so `SETTING_PATH` resolves locally.

---

## 6. Search Accuracy — Alpha Prototype Status

**Current state of `whitelist.json`:** 2 records, both empty (no SKU, no colorway).  
**Current state of `SCAA/sacc/data.js` SACC_WHITELIST:** 12 valid entries with correct SKUs, colorways, retail prices, and target filenames.

**Search engine logic in `sacc_test.py`:** Correct — scored full-text search across Model, SKU, Size, Price, source_file, and all raw JSON values. Returns ranked results.

**To establish a functional Alpha:**
1. Populate `whitelist.json` from the Master Whitelist (located at `SACC/Master_Whitelist_v1`).
2. Run `sacc_test.py inspect` against a folder with real Gemini JSON outputs to confirm search scoring.
3. The SCAA Search view (`SCAA/sacc/search-view.jsx`) is live and searches both archive entries and whitelist simultaneously.

---

## 7. Architecture — Missing Features

| Gap | Impact | Priority |
|---|---|---|
| No `.gitignore` | Keys committed to GitHub | Critical |
| `whitelist.json` not populated | Search returns no verified matches | High |
| `API_Ready_HEVC.compressorsetting` missing from repo | Compression stage always fails | High |
| No `requirements.txt` or `pyproject.toml` | No reproducible installs | High |
| `gemini_pipeline.py` uses `google.generativeai` | Must migrate to `vertexai` SDK for Vertex AI | Medium |
| No retry logic in `gemini_pipeline.py` | Single API failure kills the whole file | Medium |
| No batch-size limiter for Vertex AI | Could exhaust quota on large ingestion_zone runs | Medium |
| `sacc_test.py rename` requires pre-existing JSON | Can't rename-test cold | Low |
| `import re` inside loop in `renamer_logic.py` | Code smell, minor perf | Low |
| `vibe_ghost_component` empty/unused | Dead code | Low |
| Duplicate files in `SCAA/` vs root | Drift risk | Low |

---

## 8. Iterative Roadmap

### Phase 0 — Housekeeping (Do first, ~1 hour)
1. Create `.gitignore` (dump.json, *.log, .env, __pycache__, .DS_Store)
2. Create `.env.example` documenting required vars
3. Copy `API_Ready_HEVC.compressorsetting` into repo root
4. Move `import re` to top of `renamer_logic.py`
5. Fix typo: `"Sneeaker Solo"` → `"Sneaker Solo"` in compress_jordans test block
6. Populate `whitelist.json` from `Master_Whitelist_v1`

### Phase 1 — Alpha Prototype Validation (This sprint)
1. Run `sacc_test.py rename --apply` on `ingestion_zone/` with loc `PDM` (matches the partially-named file already there)
2. Run `sacc_test.py inspect` on a dated folder with real Gemini JSON outputs
3. Confirm search scoring against real outputs
4. Verify SCAA GUI search tab returns correct results from live data

### Phase 2 — Compression Integration Test
1. Confirm `API_Ready_HEVC.compressorsetting` resolves on Mac
2. Run `run_compression()` against a small batch (3-5 files from `ingestion_zone/`)
3. Verify `_Gemini_API.mp4` outputs land in `Compressed_Files/`
4. Validate the 3 duplicate guards (G1/G2/G3) with a re-run
5. Confirm `wait_for_compression()` exits cleanly

### Phase 3 — Vertex AI Migration
1. Create GCP project, enable Vertex AI API
2. Add `VERTEX_PROJECT_ID` and `VERTEX_LOCATION` to `.env`
3. Replace `google.generativeai` with `vertexai` SDK in `gemini_pipeline.py`
4. Update model name: `"models/gemini-2.5-pro"` → Vertex AI endpoint
5. Add retry logic with exponential backoff (3 attempts)
6. Add batch-size limiter (max N concurrent video uploads)
7. Test end-to-end: `ingestion_zone/` → rename → compress → Vertex AI → JSON

### Phase 4 — SCAA GUI Completion
1. Wire SCAA Import view to real `run_vibe_renamer` via a local API server or Electron IPC
2. Add Vertex AI status/progress stream to Import view log panel
3. Populate SCAA Archive with real Gemini JSON outputs (not just seed data)
4. Add `.env` configuration panel to SCAA Tweaks

### Phase 5 — Production Hardening
1. Full Synology integration — verify `/Volumes/Team Bank 12/SACC/` mount and folder structure
2. `sacc_watcher.py` launchd daemon — test auto-trigger on FCP drop
3. Add `sacc_rename_log.json` audit trail viewer to SCAA Timeline view
4. Pre-Flight gate UI — surface skipped clips in Import view
5. GitHub Actions CI: lint (ruff/eslint), import check, `sacc_test.py inspect` dry-run

---

## 9. Immediate Next Commands

```bash
# 1. Run rename on ingestion_zone (dry-run first)
python sacc_test.py rename --folder "/Users/miniman/SACC/ingestion_zone" --loc PDM

# 2. Apply rename (after confirming dry-run looks correct)
python sacc_test.py rename --folder "/Users/miniman/SACC/ingestion_zone" --loc PDM --apply

# 3. Full pipeline dry-run (Synology must be mounted)
python sacc_pipeline.py \
  --inbox "/Volumes/Team Bank 12/SACC/Inbox" \
  --root  "/Volumes/Team Bank 12/SACC" \
  --loc   FLM \
  --id    "Air Jordan 1 Chicago" \
  --dry-run

# 4. Install missing dependencies
pip install google-generativeai python-dotenv watchdog --break-system-packages
```

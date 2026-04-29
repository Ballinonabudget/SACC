# SACC — OpenAI Codex Handover
**Date:** 2026-04-29  
**Handed over from:** Claude (Cowork session)  
**Picking up:** OpenAI Codex  
**Branch:** `v2.0-path-integration`

---

## What this project is

**SACC** (Sneaker Archive Command Center) is a local pipeline + web app for cataloging sneaker B-roll video footage.

- **Pipeline**: ingests raw video from a NAS, runs it through Apple Compressor (proxy), sends proxies to Vertex AI (Gemini 2.5 Pro) for shoe identification, writes JSON metadata, and archives files into a dated folder structure.
- **Web app (SCAA)**: a single-page React app served by a FastAPI server that provides search, gallery, timeline, renamer, and dashboard views for the archive.
- **F+G Prototype**: a separate editorial/blog-style HTML prototype (checkerboard grid homepage → story scroll post page) that can be wired to the same data layer.

---

## Repo layout

```
/Users/miniman/SACC/
├── start_sacc.command          ← double-click to launch (kills port 5174, starts uvicorn)
├── main.py                     ← FastAPI backend (port 5174) — serves API + SCAA static
├── app_db.py                   ← SQLite helper: collections, settings, error_history
├── db.py                       ← Pipeline SQLite layer (clips table, FTS5 search)
├── sacc_pipeline.py            ← 10-stage pipeline orchestrator
├── gemini_pipeline.py          ← Vertex AI / Gemini video analysis
├── fcp_namer.py                ← FCP GPS-aware naming engine
├── renamer_logic.py            ← Classic/Vibe filename builder
├── sacc_watcher.py             ← Folder watcher → fires pipeline
├── sacc_test.py                ← CLI: inspect / search / rename
├── json_sync_validator.py      ← JSON ↔ video file consistency validator
├── compress_jordans.py         ← Apple Compressor batch proxy generation
├── .env                        ← GEMINI_API_KEY, VERTEX_PROJECT_ID (DO NOT COMMIT)
├── sacc_app.db                 ← SQLite: collections, settings, error_history
├── SCAA/
│   ├── SACC.html               ← Main app entry point → http://localhost:5174/SACC.html
│   ├── sacc-data.json          ← RSV editorial data schema (F+G prototype)
│   ├── fg-prototype.html       ← F+G prototype (checkerboard grid + story scroll)
│   └── sacc/
│       ├── components.jsx      ← Shared UI components (Btn, Card, etc.)
│       ├── dashboard-view.jsx  ← Pipeline dashboard + KPI cards
│       ├── gallery-view.jsx    ← Media gallery
│       ├── search-view.jsx     ← Live search (FTS5)
│       ├── timeline-view.jsx   ← Chronological timeline
│       ├── renamer-view.jsx    ← Vibe renamer + FCP pipeline tab
│       ├── import-view.jsx     ← Import/ingest view
│       ├── verify-view.jsx     ← Verification view
│       ├── error-log-view.jsx  ← Error Repository (known codes + runtime history)
│       ├── docs-view.jsx       ← Feature Dictionary (in-app reference)
│       └── data.js             ← Static seed data
└── Downloads/Blog _/           ← Design reference folder (NOT in repo)
    ├── Sneaker Archive Prototype.html   ← React-based prototype (reference)
    ├── Sneaker Archive Full Pages.html  ← Full page mockup (reference)
    ├── Sneaker Archive Wireframes.html  ← Wireframes (reference)
    ├── SACC Archive - Standalone.html   ← Standalone bundle (reference)
    └── sacc-data.json                   ← RSV schema source of truth (copied to SCAA/)
```

---

## How to run

```bash
# Start everything (FastAPI on 5174 + opens browser)
bash /Users/miniman/SACC/start_sacc.command

# Health check
curl http://localhost:5174/api/health

# Main app
open http://localhost:5174/SACC.html

# F+G Prototype
open http://localhost:5174/fg-prototype.html
```

---

## API endpoints

All routes served by `main.py` on port 5174. The static `SCAA/` dir is mounted at `/`.

### Core
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Server status + feature flags |
| GET | `/api/locations` | All SACC location codes |
| POST | `/api/resolve-location` | NLP → location code (fuzzy match) |

### Folder / Pipeline
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/folder-status` | Scan folder: video count, JSON pairing, validation |
| POST | `/api/preflight` | Duplicate detection (size + MD5 checksum) |
| POST | `/api/rename` | Run Vibe or FCP batch renamer |
| GET | `/api/pipeline/run-phase7` | SSE stream: rename stage |
| GET | `/api/pipeline/run-phase8` | SSE stream: archive stage |
| POST | `/api/pipeline-run` | Full 10-stage batch pipeline |

### Database
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/db/sync` | Sync JSON folder → SQLite |
| GET | `/api/db/search` | FTS5 full-text search |
| GET | `/api/db/list` | List all clips (paginated) |
| PATCH | `/api/db/patch` | Update a clip record by stem |
| GET | `/api/db/validate` | Validate all records |

### Collections & Settings
| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/api/collections` | Named search shortcuts |
| DELETE | `/api/collections/{id}` | Delete a collection |
| GET/PATCH | `/api/settings` | User settings (key-value store) |

### Error Repository *(new — wired in this session)*
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/errors` | `{ known: [...], history: [...] }` |
| POST | `/api/errors` | Log a runtime error event |
| PATCH | `/api/errors/{id}` | Mark history event as resolved |
| DELETE | `/api/errors/history` | Clear all history |

### Pipeline search (sneaker_schema DB)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipeline/search` | Search sneakers_broll table |
| GET | `/api/pipeline/sessions` | List shoot sessions |
| GET | `/api/pipeline/stats` | Aggregate stats |
| POST | `/api/pipeline/open` | Reveal file in Finder |
| POST | `/api/pipeline/mark-fcp` | Mark clips as FCP-linked |

### Media
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/reveal` | Open folder in Finder |
| GET | `/api/video` | Stream a video file |

---

## SQLite databases

### `sacc_app.db` — App state (`app_db.py → AppDB`)
```sql
collections    (id, name, query, color, created_at)
user_settings  (key, value, updated_at)
error_history  (id, code, message, context, resolved, timestamp)
```

### `sacc.db` (per-folder) — Pipeline clips (`db.py → SACCDB`)
```sql
clips (
  id, original_file, fcp_filename, shoot_date, cam_make, cam_model,
  loc_code, loc_name, loc_source, loc_confidence, loc_visual, loc_audio,
  model, sku, size, price,
  proxy_file, proxy_deleted, analysed_at,
  json_path, folder_path, created_at, updated_at
)
clips_fts  -- FTS5 over model, sku, fcp_filename, loc_code, loc_name, loc_visual, loc_audio
```

### `sneakers_broll` table (pipeline import — `import_sneaker_db.py`)
Full schema in `sneaker_schema.py`. Key columns:
```
original_file_id, brand, silhouette, colorway_name, style_code,
shoot_date, shoot_year, loc_code, session_id,
shot_type (broll|vlog), aspect_ratio (9:16|16:9),
verification_status, fcp_linked, asset_url
```

---

## Data schemas

### RSV Editorial Schema (`sacc-data.json` / F+G prototype)
```json
{
  "id": "RSV-001_",
  "storeType": "RSV",
  "code": "001",
  "name": "Air Max 95",
  "subtitle": "Original",
  "brand": "Nike",
  "year": 1995,
  "colorway": "Neutral Grey",
  "material": "Mesh / N.P.R.",
  "designer": "Sergio Lozano",
  "sku": "609048-059",
  "retail": "$110",
  "tag": "THE SILHOUETTE",
  "isDark": true,
  "images": {
    "hero": "RSV-001_/hero.webp",
    "threequarter": "RSV-001_/3q.webp",
    "material": "RSV-001_/material.webp",
    "sole": "RSV-001_/sole.webp",
    "detail": "RSV-001_/detail.webp"
  },
  "sections": [
    { "label": "THE SILHOUETTE", "heading": "...", "body": "...", "type": "story", "imageKey": "threequarter" },
    { "label": "MATERIAL",       "heading": "...", "body": "...", "type": "material", "imageKey": "material" },
    { "label": "ARCHIVE SPECS",  "type": "specs", "imageKey": "sole" }
  ]
}
```
`section.type`: `"story"` | `"material"` | `"specs"` — the prototype renders each differently.

### SACC Pipeline Filename Convention
```
FCP mode:     [LOC-TYPE]_[YYYYMMDD]_[CamModel]_[OriginalStem].[ext]
Classic mode: [LOC-TYPE]_[YYMMDD]_[Identifier]_[CamModel]_[OriginalStem].[ext]

Example: PDM-MALL_20241221_iPhone15ProMax_IMG_3423.mov
```
The filename stem is the **relational key** — JSON, proxy, and hi-res master share the same stem.

---

## Environment

```bash
# /Users/miniman/SACC/.env
GEMINI_API_KEY=<set>
VERTEX_PROJECT_ID=<set this for Vertex AI mode>
VERTEX_LOCATION=us-central1
VERTEX_MODEL=gemini-2.5-pro
```

NAS paths:
```
/Volumes/Team Bank 12/SACC/          ← archive root
/Volumes/Team Bank 12/SACC/Inbox/    ← drop new footage here
/Volumes/Team Bank 12/Sneeaker Solo/ ← legacy footage + test target
```

---

## What was completed in this Claude session

1. **`/api/errors` endpoint** — fully wired in `main.py` with 20 pre-documented known error codes across 7 categories (config, system, pipeline, validation, renamer, preflight, api). `app_db.py` extended with `error_history` table and CRUD methods.

2. **`error-log-view.jsx`** — already built. Calls `GET /api/errors` → renders Known Errors tab (accordion cards with description, resolution, example) + History tab (runtime events with resolve/clear). Now has a live backend.

3. **`docs-view.jsx`** — already built. Full in-app Feature Dictionary with 5 sections: Pipeline Dashboard, Vibe Renamer + FCP Pipeline, Pipeline Stage Reference, SACC Filename Format, Location Code Reference (all 25 Florida locations). No API dependency — static.

4. **`fg-prototype.html`** — complete standalone F+G prototype:
   - **F (Grid)**: checkerboard homepage — featured hero tile, 2–5 column alternating dark/light/ghost tile grid, stagger entrance animations
   - **G (Post)**: story scroll — GSAP color-matched transition (dark→dark, light→light), parallax hero, spec strip, alternating story/material/specs sections with ScrollTrigger reveals, archive specs table, chained next-entry CTA
   - Data-driven from `sacc-data.json` (RSV schema), inline fallback if fetch fails

5. **`sacc-data.json`** — RSV editorial schema with 6 entries (Air Max 95, Jordan 1 Bred, Dunk Low Pro B, Samba OG, Gel-Lyte III, Air Force 1). Placed at `SCAA/sacc-data.json` — served at `/sacc-data.json` by the FastAPI static mount.

---

## What Codex picks up next

### Priority 1 — NAS image bridge
The F+G prototype fetches images from `config.baseImageUrl` (`/nas/sneakers/`). This path isn't served yet.

**Task**: Add a FastAPI route to stream files from the NAS:
```python
@app.get("/nas/sneakers/{path:path}")
def serve_nas_media(path: str):
    full = Path("/Volumes/Team Bank 12/SACC/nas-media") / path
    if not full.is_file():
        raise HTTPException(404)
    return FileResponse(str(full))
```
Then populate `/Volumes/Team Bank 12/SACC/nas-media/RSV-001_/hero.webp` etc.

### Priority 2 — Wire F+G prototype to the SACC pipeline DB
Currently `sacc-data.json` is static. The real data lives in `sacc.db` (clips table) and the `sneakers_broll` pipeline table.

**Task**: Add a GET `/api/fg/entries` endpoint that:
1. Queries `sneakers_broll` (or `clips`) with pagination
2. Maps each row to the RSV schema (or a merged schema)
3. Returns `{ config: {...}, entries: [...] }`

Then update `fg-prototype.html` to fetch from `/api/fg/entries` instead of `./sacc-data.json`.

Schema mapping reference:
```
clips.model          → name
clips.loc_code       → storeType / code
clips.shoot_date     → year
clips.sku            → sku
clips.fcp_filename   → id
clips.proxy_file     → images.hero (if proxy exists)
```

### Priority 3 — GSAP TimelineMax seamless continuity button
The original brief requested a `TimelineMax`-based seamless transition between the last frame of the current post and the first frame of the next. Currently it's a simple opacity fade.

**Task**: In `fg-prototype.html`, when Next Entry is clicked:
1. Capture the current scroll position + hero image
2. Create a GSAP `gsap.timeline()` that:
   - Scales the current hero image UP to fill the viewport
   - Cross-dissolves to the next entry's hero gradient/image
   - Slides the new post content up from beneath
3. Use `ScrollTrigger.saveStyles` to preserve positions across the transition

### Priority 4 — Sync Sneeaker Solo folder to SQLite
The folder at `/Volumes/Team Bank 12/Sneeaker Solo/` has existing JSON outputs from a previous Gemini run. Sync them in:

```python
from db import SACCDB
db = SACCDB("/Volumes/Team Bank 12/Sneeaker Solo/sacc.db")
db.sync_from_folder("/Volumes/Team Bank 12/Sneeaker Solo")
```

Then point the API's `DB_PATH` to this database so the search view has live data.

### Priority 5 — Error logging in pipeline
The pipeline and renamer don't yet call `POST /api/errors` when they encounter issues. Add a helper:

```python
import requests

def log_sacc_error(code: str, message: str, context: str = ""):
    try:
        requests.post("http://127.0.0.1:5174/api/errors",
                      json={"code": code, "message": message, "context": context},
                      timeout=2)
    except Exception:
        pass  # Never block the pipeline for logging
```

Call this from `sacc_pipeline.py`, `gemini_pipeline.py`, and `renamer_logic.py` at the right failure points. Use the documented error codes (CFG-001 through API-003).

### Priority 6 — Tweaks panel for F+G prototype
Add a floating panel (bottom-right corner) with toggles:
- Font: sans / mono / serif
- Grid columns: 2 / 3 / 4 / 5
- Color mode: auto (follow isDark) / force dark / force light
- Tile aspect ratio: 3:4 / 1:1 / 4:5

---

## Known issues / watch-outs

| Issue | File | Notes |
|-------|------|-------|
| `VERTEX_PROJECT_ID` not set | `.env` | Falls back to Gemini API key — set for production |
| Sneeaker Solo folder name has typo | NAS | Two `e`s in `Sneeaker` — this is correct, don't rename |
| Streamlit `use_container_width` deprecation | `app.py` | Low priority — Streamlit is legacy UI |
| `fg-prototype.html` images 404 until NAS route added | `main.py` | Expected — falls back to gradient backgrounds |
| `activeFolder` default cleared | `SACC.html` line 153 | Session-only — intentional, not persisted |
| `sacc.db` WAL lock under parallel sessions | `app_db.py` | Use `pkill -f uvicorn && start_sacc.command` to resolve |

---

## Git state

```bash
git -C /Users/miniman/SACC log --oneline -5
git -C /Users/miniman/SACC status
git -C /Users/miniman/SACC diff HEAD
```

Branch: `v2.0-path-integration`  
Do not merge to `main` until: `start_sacc.command` → UI → search → results works end-to-end with Sneeaker Solo data.

---

## Files changed this session

```
modified:  /Users/miniman/SACC/app_db.py       ← added error_history table + 4 methods
modified:  /Users/miniman/SACC/main.py          ← added _KNOWN_ERRORS + 4 /api/errors routes
created:   /Users/miniman/SACC/SCAA/fg-prototype.html   ← F+G prototype (complete)
created:   /Users/miniman/SACC/SCAA/sacc-data.json      ← RSV editorial schema (6 entries)
```

These files are ready to commit:
```bash
git -C /Users/miniman/SACC add app_db.py main.py SCAA/fg-prototype.html SCAA/sacc-data.json
git -C /Users/miniman/SACC commit -m "feat: errors API, F+G prototype, RSV data schema"
```

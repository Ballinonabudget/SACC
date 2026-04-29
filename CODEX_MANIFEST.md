# SACC — CODEX HANDOFF MANIFEST
**Generated:** 2026-04-29  
**Platform:** Mac Mini (miniman) → Synology NAS  
**Server:** FastAPI/uvicorn · port 5174 · `python3.10.12`  
**Branch:** `v2.0-path-integration`  
**Entrypoint:** `bash /Users/miniman/SACC/start_sacc.command`

---

## 1. STATE AUDIT — EXACT COMPLETION STATUS

### 1.1 Backend (`main.py` · 1005 lines · syntax-verified)

| Line | Route | Status |
|------|-------|--------|
| 263 | `GET /api/health` | ✅ LIVE |
| 278 | `GET /api/locations` | ✅ LIVE |
| 301 | `POST /api/resolve-location` | ✅ LIVE |
| 308 | `GET /api/folder-status` | ✅ LIVE |
| 319 | `GET /api/json-db` | ✅ LIVE |
| 332 | `PATCH /api/json-db` | ✅ LIVE |
| 353 | `POST /api/apply-location` | ✅ LIVE |
| 374 | `GET /api/whitelist` | ✅ LIVE |
| 384 | `POST /api/preflight` | ✅ LIVE |
| 397 | `POST /api/rename` | ✅ LIVE |
| 448 | `POST /api/pipeline-run` | ✅ LIVE |
| 485 | `GET /api/pipeline/run-phase7` | ✅ LIVE · SSE · streams `PHASE7_SCRIPT` |
| 545 | `GET /api/pipeline/run-phase8` | ✅ LIVE · SSE · streams `PHASE8_SCRIPT` |
| 595 | `GET/POST /api/collections` | ✅ LIVE · SQLite-backed |
| 606 | `DELETE /api/collections/{id}` | ✅ LIVE |
| 616 | `GET/PATCH /api/settings` | ✅ LIVE · SQLite-backed |
| 630 | `POST /api/db/sync` | ✅ LIVE |
| 642 | `GET /api/db/search` | ✅ LIVE · FTS5 |
| 659 | `GET /api/db/stats` | ✅ LIVE |
| 669 | `GET /api/db/record` | ✅ LIVE |
| 681 | `PATCH /api/db/record` | ✅ LIVE |
| 694 | `GET /api/db/validation-summary` | ✅ LIVE |
| 703 | `GET /api/db/validate` | ✅ LIVE |
| 725 | `GET /api/pipeline/search` | ✅ LIVE · `sneakers_broll` table |
| 769 | `GET /api/pipeline/sessions` | ✅ LIVE |
| 779 | `GET /api/pipeline/stats` | ✅ LIVE |
| 804 | `POST /api/pipeline/open` | ✅ LIVE · `open -R` |
| 822 | `POST /api/pipeline/mark-fcp` | ✅ LIVE |
| 840 | `POST /api/reveal` | ✅ LIVE |
| 856 | `GET /api/video` | ✅ LIVE · FileResponse |
| 971 | `GET /api/errors` | ✅ LIVE · **added this session** |
| 981 | `POST /api/errors` | ✅ LIVE · **added this session** |
| 989 | `PATCH /api/errors/{error_id}` | ✅ LIVE · **added this session** |
| 999 | `DELETE /api/errors/history` | ✅ LIVE · **added this session** |
| — | `GET /nas/sneakers/{path:path}` | ❌ NOT IMPLEMENTED · **Priority 1** |
| — | `GET /api/fg/entries` | ❌ NOT IMPLEMENTED · **Priority 2** |

**MISSING HARDCODED PATHS (main.py):**
```python
# line 481
PHASE7_SCRIPT = "/Volumes/Team Bank 12/Sneeaker Solo/phase7_renamer.py"
PHASE8_SCRIPT = "/Volumes/Team Bank 12/Sneeaker Solo/phase8_archival.py"
# These scripts do NOT exist at that path. Phase 7/8 SSE endpoints will raise HTTP 500.
# Codex action: verify existence or remap to sacc_pipeline.py stages
```

### 1.2 App Database (`app_db.py` · AppDB class)

```sql
-- sacc_app.db (path: /Users/miniman/SACC/sacc_app.db)
collections   (id INT PK, name TEXT, query TEXT, color TEXT, created_at TEXT)
user_settings (key TEXT PK, value TEXT, updated_at TEXT)
error_history (id INT PK, code TEXT, message TEXT, context TEXT, resolved INT, timestamp TEXT)
-- error_history added this session. 4 methods: log_error, get_error_history,
-- mark_error_resolved, clear_error_history
```

### 1.3 Pipeline Database (`db.py` · SACCDB class)

```sql
-- sacc.db (one per NAS folder — path passed at runtime)
clips (
  id, stem TEXT UNIQUE,       -- relational key: filename without extension
  original_file, fcp_filename, folder_path, json_path,
  shoot_date, cam_make, cam_model,
  loc_code, loc_name, loc_source, loc_confidence, loc_visual, loc_audio,
  model, colorway, dominant_color, secondary_color, sku, size, price,
  release_date, shot_context TEXT DEFAULT 'unknown',
  proxy_file, proxy_deleted INT DEFAULT 0,
  analysed_at, created_at, updated_at
)
clips_fts USING fts5(
  stem, original_file, fcp_filename, model, colorway, sku,
  loc_code, loc_name, loc_visual, loc_audio,
  content='clips', content_rowid='id', tokenize='unicode61'
)
```

### 1.4 Pipeline Import DB (`sneaker_schema.py` / `import_sneaker_db.py`)

```sql
-- Separate DB (path passed at runtime)
-- Primary table: sneakers_broll
-- Key columns verified from main.py /api/pipeline/search:
  brand, silhouette, colorway_name, style_code,
  shoot_year, loc_code, session_id,
  aspect_ratio ('9:16'|'16:9'),
  shot_type ('broll'|'vlog'),
  verification_status, fcp_linked INT, asset_url,
  original_file_id, creation_time

-- Secondary tables:
  proxy_manifest  (processing_status: 'ARCHIVED')
  shoot_sessions  (shoot_date, session_id)
```

### 1.5 Frontend (SCAA — `SACC.html` + Babel JSX components)

| Component | File | Status |
|-----------|------|--------|
| App shell + sidebar | `SACC.html` | ✅ LIVE |
| Error Repository | `sacc/error-log-view.jsx` | ✅ LIVE · calls `http://localhost:5174/api/errors` |
| Feature Dictionary | `sacc/docs-view.jsx` | ✅ LIVE · static data, no API |
| Pipeline Dashboard | `sacc/dashboard-view.jsx` | ✅ LIVE |
| Gallery | `sacc/gallery-view.jsx` | ✅ LIVE |
| Search | `sacc/search-view.jsx` | ✅ LIVE · FTS5 |
| Timeline | `sacc/timeline-view.jsx` | ✅ LIVE |
| Renamer | `sacc/renamer-view.jsx` | ✅ LIVE |
| Verify | `sacc/verify-view.jsx` | ✅ LIVE |
| Import | `sacc/import-view.jsx` | ✅ LIVE |

**Sidebar view IDs wired in `SACC.html` lines 341–354:**
```js
// Lite mode: gallery, timeline, search
// Pro mode: gallery, timeline, search, dashboard, renamer, verify, import, errorlog, docs
{ id: 'errorlog', icon: '⚠', label: 'Errors' }   // → ErrorLogView
{ id: 'docs',     icon: '?', label: 'Docs' }       // → DocsView
```
**`activeFolder` state (line 153):** `useState('')` — session-only, not persisted. Was previously `useState('/Volumes/Team Bank 12/Sneaker Solo')`. Change is intentional.

### 1.6 F+G Prototype (`SCAA/fg-prototype.html` · 36KB)

**STATUS: COMPLETE — data-driven, ready for NAS bridge.**

Scrollytelling components implemented:

| Component | Trigger | Implementation |
|-----------|---------|----------------|
| Grid tile entrance | `IntersectionObserver` threshold 0.04 | `gsap.to(tile, {opacity:1, y:0, delay: (i%5)*0.055})` |
| View transition (grid→post) | click on tile | GSAP opacity overlay, color-matched to `isDark` — dark:`#0d0d0f`, light:`#eae7e0` |
| Hero content entrance | post render | `gsap.from` stagger: title(+0.1s), eyebrow(0), subtitle(+0.14s), spec-strip(+0.22s) |
| Hero parallax | ScrollTrigger scrub | `gsap.to('#post-hero-bg', {y:'20%', scrub:1.2})` |
| Nav title fade | ScrollTrigger `start:'bottom 60%'` | `opacity: 0 → 1` when hero exits viewport |
| Story section reveals | ScrollTrigger `start:'top 88%', once:true` | `gsap.to(el, {opacity:1, y:0, delay: i*0.04})` |
| Next-entry reveal | ScrollTrigger `start:'top 90%', once:true` | `gsap.from('#next-entry', ...)` |
| Section media hover | CSS transition | `transform: scale(1.04)` on `.story-section:hover .media-fill` |
| View transition (post→grid) | back button | GSAP overlay + `ScrollTrigger.getAll().forEach(t=>t.kill())` |

**Progressive disclosure triggers (post page, per section type):**
```
section.type === 'story'    → alternating grid layout (even: media-left, odd: media-right via .flip)
section.type === 'material' → same alternating grid, alt-bg class on text panel
section.type === 'specs'    → full spec table rendered from all entry fields
```

**NOT YET IMPLEMENTED in prototype:**
- `TimelineMax` seamless video continuity (next entry cross-dissolve from last hero frame)
- Tweaks panel (font/grid/color toggles)
- `/nas/sneakers/` image serving (all images render as gradient fallback until route exists)

---

## 2. DEPENDENCY MAPPING

### 2.1 Synology NAS → SQLite mapping

```
NAS PATH                                    → SQLITE DB                      → PYTHON CLASS
─────────────────────────────────────────── ──────────────────────────────── ────────────────
/Volumes/Team Bank 12/SACC/                 → (no top-level DB)              → —
/Volumes/Team Bank 12/SACC/Inbox/           → pipeline staging area          → sacc_pipeline.py
/Volumes/Team Bank 12/SACC/YYYY/YYYYMMDD/   → clips in per-folder sacc.db    → db.py:SACCDB
/Volumes/Team Bank 12/Sneeaker Solo/        → sacc.db (NOT YET SYNCED)       → db.py:SACCDB
/Volumes/Team Bank 12/Sneeaker Solo/json/   → companion JSONs (per clip)     → gemini_pipeline.py
/Volumes/Team Bank 12/Sneeaker Solo/_proxy/ → transient proxies (Stage 6-7)  → compress_jordans.py
/Users/miniman/SACC/sacc_app.db            → collections/settings/errors     → app_db.py:AppDB
```

**CRITICAL — NOT SYNCED:**
```
/Volumes/Team Bank 12/Sneeaker Solo/ has existing JSON outputs from a prior
Gemini run. sacc.db DOES NOT EXIST there yet. Run before any search-view testing:

  python3 -c "
  from db import SACCDB
  db = SACCDB('/Volumes/Team Bank 12/Sneeaker Solo/sacc.db')
  db.sync_from_folder('/Volumes/Team Bank 12/Sneeaker Solo')
  print('done')
  "
```

**CRITICAL — PHASE 7/8 SCRIPTS MISSING:**
```
main.py lines 481-482 reference:
  /Volumes/Team Bank 12/Sneeaker Solo/phase7_renamer.py  ← does not exist
  /Volumes/Team Bank 12/Sneeaker Solo/phase8_archival.py ← does not exist
Both SSE endpoints will HTTP 500 until resolved.
```

### 2.2 NAS media serving (unimplemented gap)

```
fg-prototype.html config.baseImageUrl = "/nas/sneakers/"
Fetches: /nas/sneakers/RSV-001_/hero.webp
Route does not exist in main.py.
Expected NAS path: /Volumes/Team Bank 12/SACC/nas-media/RSV-001_/hero.webp
```

### 2.3 Python version + key dependencies

```
Runtime: Python 3.10.12 (macOS system python3)
Required: fastapi, uvicorn[standard], google-generativeai, vertexai (google-cloud-aiplatform)
ffprobe:  /Users/miniman/SACC/ffprobe (binary, chmod +x required)
.env:     GEMINI_API_KEY=<set>, VERTEX_PROJECT_ID=<set if Vertex mode>
          VERTEX_LOCATION=us-central1, VERTEX_MODEL=gemini-2.5-pro
```

### 2.4 Gemini / Vertex pipeline constants

```python
# gemini_pipeline.py
_retry(fn, attempts=3, delay=5)   # backoff: 5s → 10s → 20s
# If 429s recur: set attempts=5, delay=30

# Mode selection (runtime):
VERTEX_PROJECT_ID set → vertexai SDK, GenerativeModel("gemini-2.5-pro")
VERTEX_PROJECT_ID not set → google.generativeai, upload_file() File API
# Both paths write identical JSON schema to json/<stem>.json
```

---

## 3. LOGIC EXTRACTION — SCROLLYTELLING + PROGRESSIVE DISCLOSURE

### 3.1 Implemented (fg-prototype.html)

**Color-state machine:**
```js
// Entry point: openPost(idx)
entry.isDark → overlay.background = '#0d0d0f'  (black fade)
!entry.isDark → overlay.background = '#eae7e0' (cream fade)
// GSAP: opacity 0→1 (0.3s power2.in) → swap DOM → opacity 1→0 (0.5s power2.out)
// ScrollTrigger.getAll().forEach(t=>t.kill()) on every view swap
```

**Checkerboard palette logic:**
```js
function tileClass(entry, idx) {
  if (entry.isDark) return 'tile-dark';           // CSS: bg var(--mid) #161618
  return idx % 3 === 0 ? 'tile-light' : 'tile-ghost';
  // tile-light: bg var(--light) #f5f3ef
  // tile-ghost: bg var(--ghost) #eae7e0
}
```

**Section-type renderer (post page):**
```js
// Iterates entry.sections array. Three render paths:
sec.type === 'specs'    → <div class="specs-section story-section"> + full spec table
sec.type === 'story'    → <div class="story-section[.flip]"> alternating i%2
sec.type === 'material' → same as story + .alt-bg on section-text panel
// .flip = direction:rtl trick (reverses column order without changing DOM)
```

**ScrollTrigger wiring (wirePostScroll function):**
```js
// Kills all existing triggers before re-registering (critical for view swap)
ScrollTrigger.getAll().forEach(t => t.kill());

// 1. Nav title (post hero exit)
ScrollTrigger.create({ trigger:'.post-hero', start:'bottom 60%',
  onEnter: () => navTitle.style.opacity='1',
  onLeaveBack: () => navTitle.style.opacity='0' });

// 2. Section stagger reveals
querySelectorAll('.story-section, .specs-section').forEach((el, i) => {
  ScrollTrigger.create({ trigger:el, start:'top 88%', once:true,
    onEnter() { gsap.to(el, {opacity:1, y:0, duration:0.75, delay:i*0.04}) } });

// 3. Hero parallax (scrub)
gsap.to('#post-hero-bg', { y:'20%',
  scrollTrigger: { trigger:'.post-hero', start:'top top', end:'bottom top', scrub:1.2 } });
```

### 3.2 Conceptualized but NOT implemented

**TimelineMax seamless continuity (original brief requirement):**
```
Trigger: next-entry button click
Intent:
  1. Freeze current scroll position
  2. gsap.timeline():
     a. Scale #post-hero-bg from current size → 100vw/100vh (cover)
     b. Cross-dissolve to next entry's hero gradient/image (opacity 0→1)
     c. Slide new post content up from y:100vh → y:0
  3. Use ScrollTrigger.saveStyles() before transition,
     ScrollTrigger.revert() after to reset scroll context
Implementation location: replace current openPost() call in next-btn.onclick
```

**Tweaks panel (requested but not built):**
```
UI: fixed bottom-right, 32px toggle button, slide-up panel
Controls:
  font-mode: CSS var(--sans) | var(--mono) | serif swap on :root
  grid-cols: .tile-grid CSS grid-template-columns 2|3|4|5
  color-mode: auto (follow isDark per tile) | force-dark | force-light
  tile-ratio: aspect-ratio 3/4 | 1/1 | 4/5 on .tile
State: localStorage key 'fg_tweaks'
```

---

## 4. CODEX COMMAND — IMMEDIATE EXECUTION DIRECTIVE

```
SYSTEM: You are executing against an existing FastAPI codebase.
Runtime: Python 3.10.12. Server: uvicorn on port 5174. File: /Users/miniman/SACC/main.py.

You have the following established modules — DO NOT rewrite them:
  main.py (1005 lines)         — FastAPI app, all routes except /nas/sneakers/ and /api/fg/entries
  app_db.py (AppDB class)      — SQLite: collections, settings, error_history
  db.py (SACCDB class)         — SQLite: clips, clips_fts (FTS5)
  SCAA/fg-prototype.html       — complete F+G prototype, data-driven from sacc-data.json
  SCAA/sacc-data.json          — RSV editorial schema, 6 entries, baseImageUrl="/nas/sneakers/"
  SCAA/SACC.html               — main app (React/Babel), errorlog+docs tabs wired at lines 506-511

EXECUTE IN ORDER:

─── MILESTONE 1: NAS media bridge ────────────────────────────────────────────

File: /Users/miniman/SACC/main.py
Insert BEFORE the static mount line:
  # ── Static frontend — must be last so /api/* routes take precedence ─────

Code to insert:
```python
@app.get("/nas/sneakers/{media_path:path}")
def serve_nas_media(media_path: str):
    """Serve images from NAS media store for F+G prototype."""
    NAS_MEDIA_ROOT = Path("/Volumes/Team Bank 12/SACC/nas-media")
    safe = (NAS_MEDIA_ROOT / media_path).resolve()
    if not str(safe).startswith(str(NAS_MEDIA_ROOT)):
        raise HTTPException(403, "Path traversal denied")
    if not safe.is_file():
        raise HTTPException(404, f"Media not found: {media_path}")
    return FileResponse(str(safe))
```

Verification: `curl http://localhost:5174/nas/sneakers/RSV-001_/hero.webp` → 200 or 404 (not 500)

─── MILESTONE 2: /api/fg/entries — live data bridge ──────────────────────────

File: /Users/miniman/SACC/main.py
Insert after the /nas/sneakers/ route. This endpoint replaces the static
sacc-data.json fetch in fg-prototype.html for production.

Code:
```python
@app.get("/api/fg/entries")
def fg_entries(
    db_path: str = Query(""),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """
    Map pipeline clips table → RSV editorial schema for fg-prototype.html.
    Falls back to sacc-data.json if no db_path provided.
    """
    if not db_path or not os.path.isfile(db_path):
        # Return static JSON as fallback
        static_path = os.path.join(os.path.dirname(__file__), "SCAA", "sacc-data.json")
        if os.path.isfile(static_path):
            with open(static_path) as f:
                return json.load(f)
        raise HTTPException(404, "No db_path and no static sacc-data.json fallback")

    if not _DB_OK:
        raise HTTPException(500, "db.py not available")

    sdb = _get_db(db_path)
    rows = sdb.list_all(limit=limit, offset=offset)

    def to_rsv(row, idx):
        loc = row.get("loc_code") or "RSV"
        code_str = str(idx + 1).zfill(3)
        stem = row.get("stem", "")
        return {
            "id": stem,
            "storeType": loc,
            "code": code_str,
            "name": row.get("model") or row.get("fcp_filename") or stem,
            "subtitle": row.get("colorway") or "",
            "brand": "",          # not in clips table — enrich from whitelist if needed
            "year": int(row.get("shoot_date", "20000101")[:4]) if row.get("shoot_date") else 0,
            "colorway": row.get("colorway") or "",
            "material": "",
            "designer": "",
            "sku": row.get("sku") or "",
            "retail": f"${row.get('price')}" if row.get("price") else "",
            "tag": (row.get("model") or "").upper()[:24],
            "isDark": idx % 2 == 0,
            "images": {
                "hero":         f"/api/video?path={row.get('folder_path','')}&file={stem}.mov",
                "threequarter": "",
                "material":     "",
                "sole":         "",
                "detail":       "",
            },
            "sections": [
                {"label": "LOCATION",      "heading": row.get("loc_name") or loc,
                 "body": row.get("loc_visual") or row.get("loc_audio") or "",
                 "type": "story", "imageKey": "hero"},
                {"label": "ARCHIVE SPECS", "type": "specs", "imageKey": "sole"},
            ],
        }

    entries = [to_rsv(r, i) for i, r in enumerate(rows)]
    return {
        "config": {
            "title": "SACC Archive",
            "baseImageUrl": "/nas/sneakers/",
            "imageFormat": "webp",
            "entriesPerPage": 12,
        },
        "entries": entries,
    }
```

─── MILESTONE 3: Sync Sneeaker Solo → sacc.db ────────────────────────────────

File: NEW script at /Users/miniman/SACC/sync_sneeaker_solo.py
Purpose: one-shot sync of legacy Sneeaker Solo folder into SQLite

```python
#!/usr/bin/env python3
"""One-shot sync: /Volumes/Team Bank 12/Sneeaker Solo/ → sacc.db"""
import sys
sys.path.insert(0, "/Users/miniman/SACC")
from db import SACCDB

FOLDER = "/Volumes/Team Bank 12/Sneeaker Solo"
DB_PATH = f"{FOLDER}/sacc.db"

db = SACCDB(DB_PATH)
result = db.sync_from_folder(FOLDER)
stats = db.validation_summary()
print(f"Synced. DB: {DB_PATH}")
print(f"Stats: {stats}")
```

Run: `python3 /Users/miniman/SACC/sync_sneeaker_solo.py`
Verify: `curl "http://localhost:5174/api/db/stats?path=/Volumes/Team%20Bank%2012/Sneeaker%20Solo"`

─── MILESTONE 4: Error logging in pipeline ────────────────────────────────────

File: /Users/miniman/SACC/sacc_pipeline.py  (and gemini_pipeline.py, renamer_logic.py)
Add this helper near the top of each file, after imports:

```python
def _log_error(code: str, message: str, context: str = "") -> None:
    """Non-blocking: POST runtime error to /api/errors for the Error Repository tab."""
    try:
        import requests
        requests.post(
            "http://127.0.0.1:5174/api/errors",
            json={"code": code, "message": message, "context": context},
            timeout=1.5,
        )
    except Exception:
        pass  # Never block the pipeline for logging
```

Call sites:
```python
# sacc_pipeline.py — stage failures:
except Exception as e:
    _log_error("PIPE-001", f"Inbox not found: {inbox}", str(e))

# gemini_pipeline.py — 429:
_log_error("API-001", f"Gemini 429 on {proxy_path}", f"attempt {i+1}/{attempts}")

# renamer_logic.py — bad loc_code:
_log_error("RNM-001", f"Unrecognised location code: {loc_code}", "")
```

─── MILESTONE 5: Phase 7/8 script path resolution ────────────────────────────

File: /Users/miniman/SACC/main.py lines 481-482
Current (broken):
  PHASE7_SCRIPT = "/Volumes/Team Bank 12/Sneeaker Solo/phase7_renamer.py"
  PHASE8_SCRIPT = "/Volumes/Team Bank 12/Sneeaker Solo/phase8_archival.py"

Action — verify which of these is true:
  A) Scripts exist on NAS at that path → no change needed
  B) Scripts don't exist → remap to sacc_pipeline.py stage functions:

```python
# If B: replace lines 481-482 with:
PHASE7_SCRIPT = os.path.join(os.path.dirname(__file__), "sacc_pipeline.py")
PHASE8_SCRIPT = os.path.join(os.path.dirname(__file__), "sacc_pipeline.py")
# And update the cmd construction in run_phase7/run_phase8 to pass --fcp --dry-run etc.
```

─── MILESTONE 6: TimelineMax view transition ──────────────────────────────────

File: /Users/miniman/SACC/SCAA/fg-prototype.html
Target function: openPost(idx) — currently a plain opacity overlay

Replace with:
```js
function openPost(idx) {
  curIdx = idx;
  const entry = DATA.entries[idx];
  const ov = document.getElementById('transition-overlay');
  ov.style.background = entry.isDark ? '#0d0d0f' : '#eae7e0';

  // Freeze current hero if visible
  const currentHero = document.getElementById('post-hero-bg');
  const isOnPost = document.getElementById('view-post').style.display !== 'none';

  const tl = gsap.timeline({
    onComplete() {
      renderPost(entry, idx);
      document.getElementById('view-grid').style.display = 'none';
      document.getElementById('view-post').style.display = 'block';
      window.scrollTo(0, 0);
      animatePostEntrance();
      wirePostScroll();
      gsap.to(ov, { opacity: 0, duration: 0.55, ease: 'power2.out' });
    }
  });

  if (isOnPost && currentHero) {
    // Seamless: scale current hero to fill viewport, then fade overlay
    tl.to(currentHero, { scale: 1.12, duration: 0.45, ease: 'power2.in' }, 0)
      .to(ov, { opacity: 1, duration: 0.3, ease: 'power2.in' }, 0.2);
  } else {
    tl.to(ov, { opacity: 1, duration: 0.3, ease: 'power2.in' });
  }

  // Reset hero scale after swap
  tl.call(() => { if (currentHero) gsap.set(currentHero, { scale: 1 }); });
}
```

─── COMMIT ────────────────────────────────────────────────────────────────────

After milestones 1-6:
```bash
cd /Users/miniman/SACC
git add main.py app_db.py SCAA/fg-prototype.html SCAA/sacc-data.json \
        sync_sneeaker_solo.py CODEX_MANIFEST.md CODEX_HANDOVER.md
git commit -m "feat: NAS bridge, fg/entries API, errors backend, F+G prototype complete"
git push origin v2.0-path-integration
```

DO NOT merge to main until:
  curl http://localhost:5174/api/health → {"status":"ok"}
  curl http://localhost:5174/api/errors → {"known":[...20 entries...],"history":[...]}
  open http://localhost:5174/fg-prototype.html → grid loads, tile click transitions to post
  open http://localhost:5174/SACC.html → Errors + Docs tabs render without console errors
```

---

## 5. FILE INVENTORY — EXACT PATHS

```
MODIFIED THIS SESSION:
  /Users/miniman/SACC/main.py          (lines 862–1003 added: _KNOWN_ERRORS + 4 routes)
  /Users/miniman/SACC/app_db.py        (lines 36–44, 131–166 added: error_history table + methods)

CREATED THIS SESSION:
  /Users/miniman/SACC/SCAA/fg-prototype.html   (36KB — complete F+G prototype)
  /Users/miniman/SACC/SCAA/sacc-data.json      (RSV schema, 6 entries — copied from Blog _)
  /Users/miniman/SACC/CODEX_HANDOVER.md        (prose handover)
  /Users/miniman/SACC/CODEX_MANIFEST.md        (this file)

REFERENCE (DO NOT MODIFY):
  /Users/miniman/Downloads/Blog _/Sneaker Archive Prototype.html
  /Users/miniman/Downloads/Blog _/Sneaker Archive Full Pages.html
  /Users/miniman/Downloads/Blog _/Sneaker Archive Wireframes.html
  /Users/miniman/Downloads/Blog _/SACC Archive - Standalone.html
```

---

*End of manifest. Codex begins at Milestone 1.*

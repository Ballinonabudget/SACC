#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SACC Legacy Cleanup — cleanup_legacy.sh
# Run once from Terminal: bash /Users/miniman/SACC/cleanup_legacy.sh
# Creates a dated archive first, then removes all decommissioned files.
# ─────────────────────────────────────────────────────────────────────────────

SACC="/Users/miniman/SACC"
ARCHIVE="$SACC/_decommissioned_$(date +%Y%m%d)"

echo ""
echo "  SACC Legacy Cleanup"
echo "  ───────────────────"
echo "  Archive → $ARCHIVE"
echo ""

# Safety check — never run against wrong directory
if [ ! -f "$SACC/sacc_pipeline.py" ]; then
  echo "  ✗ ERROR: sacc_pipeline.py not found. Wrong directory?"
  exit 1
fi

mkdir -p "$ARCHIVE"

# ── Helper: archive then delete ───────────────────────────────────────────────
archive_rm() {
  local TARGET="$1"
  local LABEL="$2"
  if [ -e "$TARGET" ] || [ -d "$TARGET" ]; then
    cp -r "$TARGET" "$ARCHIVE/" 2>/dev/null
    rm -rf "$TARGET"
    echo "  ✓  [REMOVED]  $LABEL"
  else
    echo "  –  [SKIP]     $LABEL (not found)"
  fi
}

echo "── Category 1: StockX / GOAT scrapers and data artifacts ──────────────"
archive_rm "$SACC/scraper.py"               "scraper.py             (StockX scraper)"
archive_rm "$SACC/test_scrape.py"           "test_scrape.py         (StockX scraper test)"
archive_rm "$SACC/jordan1_og_stockx.json"   "jordan1_og_stockx.json (StockX raw data)"
archive_rm "$SACC/dump.json"                "dump.json              (StockX 1.3MB raw dump)"
archive_rm "$SACC/find_path.py"             "find_path.py           (dump.json parser, no other use)"
archive_rm "$SACC/test_data"                "test_data/             (StockX test fixtures)"
echo ""

echo "── Category 2: Anti-Gravity / superseded Streamlit prototypes ──────────"
archive_rm "$SACC/my_dashboard.py"          "my_dashboard.py        (3-button mock, superseded by SCAA)"
archive_rm "$SACC/Renamer Logic"            "'Renamer Logic'        (no-ext prototype, superseded by renamer_logic.py)"
archive_rm "$SACC/vibe_ghost_component"     "vibe_ghost_component/  (Streamlit custom component, superseded by renamer-view.jsx)"
archive_rm "$SACC/run_sacc.sh"              "run_sacc.sh            (old Streamlit launcher, superseded by start_sacc.command)"
echo ""

echo "── Category 3: Legacy frontend/ (superseded by SCAA/) ─────────────────"
archive_rm "$SACC/frontend"                 "frontend/              (old SCAA v1, missing 5 views, superseded by SCAA/)"
echo ""

echo "── Category 4: SCAA/ internal duplicates and design-tool artifacts ─────"
archive_rm "$SACC/SCAA/find_path.py"                    "SCAA/find_path.py            (duplicate of deleted root file)"
archive_rm "$SACC/SCAA/renamer_logic.py"                "SCAA/renamer_logic.py        (duplicate of root renamer_logic.py)"
archive_rm "$SACC/SCAA/SACC Wireframes.html"            "SCAA/SACC Wireframes.html    (pre-SACC.html wireframe doc)"
archive_rm "$SACC/SCAA/design-canvas.jsx"               "SCAA/design-canvas.jsx       (Figma-style design tool, not app code)"
archive_rm "$SACC/SCAA/.design-canvas.state.json"       "SCAA/.design-canvas.state.json (design tool state file)"
archive_rm "$SACC/SCAA/Master_Whitelist_v1"             "SCAA/Master_Whitelist_v1     (duplicate of root Master_Whitelist_v1)"
echo ""

echo "── Category 5: Mock / test data ────────────────────────────────────────"
archive_rm "$SACC/mock_m4_drive"            "mock_m4_drive/         (fake test images/video, not real footage)"
echo ""

echo "── Category 6: Stale logs and build artifacts ──────────────────────────"
archive_rm "$SACC/sacc_launchd.log"         "sacc_launchd.log       (8,000+ stale watcher log lines)"
archive_rm "$SACC/sacc_launchd.err"         "sacc_launchd.err       (watcher error log)"
archive_rm "$SACC/ffprobe.zip"              "ffprobe.zip            (source archive for binary, binary already extracted)"
echo ""

# ── Commit cleanup to git ─────────────────────────────────────────────────────
echo "── Committing cleanup to git ───────────────────────────────────────────"
cd "$SACC"
# Remove lock files from sandbox session if still present
rm -f .git/index.lock .git/HEAD.lock .git/objects/maintenance.lock 2>/dev/null
git add -A
git commit -m "chore: decommission legacy scrapers, prototypes, and noise scripts

Removed (archived to _decommissioned_$(date +%Y%m%d)/):
  - scraper.py, test_scrape.py          — StockX/GOAT scrapers
  - jordan1_og_stockx.json, dump.json   — StockX data artifacts
  - find_path.py, test_data/            — StockX-dependent utilities
  - my_dashboard.py, 'Renamer Logic'    — superseded Streamlit prototypes
  - vibe_ghost_component/               — Streamlit custom component
  - run_sacc.sh                         — old Streamlit launcher
  - frontend/                           — SCAA v1 (5 views missing)
  - SCAA/find_path.py, SCAA/renamer_logic.py — SCAA/ duplicates
  - SCAA/SACC Wireframes.html           — pre-SACC.html wireframe doc
  - SCAA/design-canvas.jsx, .state.json — design tool artifacts
  - SCAA/Master_Whitelist_v1            — duplicate whitelist
  - mock_m4_drive/                      — fake test fixtures
  - sacc_launchd.log, sacc_launchd.err  — stale daemon logs
  - ffprobe.zip                         — binary source archive

Retained operational core:
  sacc_pipeline.py, fcp_namer.py, gemini_pipeline.py,
  renamer_logic.py, sacc_test.py, compress_jordans.py,
  json_sync_validator.py, api.py, sacc_watcher.py,
  forensic_match.py, whitelist.json, ffprobe, start_sacc.command,
  SCAA/ (SACC.html + 7 views), ingestion_zone/"
echo "  ✓ Committed"
git push origin v2.0-path-integration && echo "  ✓ Pushed" || echo "  ⚠ Push failed — run: git push origin v2.0-path-integration"

echo ""
echo "  ─────────────────────────────────────────────────────"
echo "  Cleanup complete."
echo "  Archive preserved at: $ARCHIVE"
echo "  Delete the archive after 30 days if no issues surface."
echo "  ─────────────────────────────────────────────────────"
echo ""

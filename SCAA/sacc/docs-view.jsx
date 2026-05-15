// SACC — Feature Dictionary
// Comprehensive in-app reference for every UI element, data field, and pipeline concept.

const DOCS_SECTIONS = [
  // ── DASHBOARD ─────────────────────────────────────────────────────────────
  {
    id: 'dashboard',
    title: 'Pipeline Dashboard',
    icon: '◈',
    entries: [
      {
        name: 'Source Folder',
        type: 'Input · Text field',
        purpose: 'Sets the working directory for all Dashboard operations. All KPI cards, the Duplicate Scan, and the Batch Pipeline target this path.',
        behavior: 'Type or paste a folder path. Press Enter or click Refresh to scan. Session-only — clears when the app closes. Has no effect on files until you explicitly click Refresh or Start Batch Pipeline.',
        notes: 'Accepts flat folders and FCP library layouts (Final Cut Original Media/YYYY-MM-DD/). The pipeline auto-detects subdirectory structure.',
      },
      {
        name: '↺ Refresh',
        type: 'Button',
        purpose: 'Triggers a full folder scan: counts video files, checks JSON pairing status, and auto-starts the Duplicate Scan.',
        behavior: 'Calls /api/folder-status → json_sync_validator → populates all 6 KPI cards. Then calls /api/preflight → duplicate scan → Duplicates card. Also fires automatically when the API first comes online if a path is in the field.',
        notes: 'Does not modify any files. Safe to run at any time.',
      },
      {
        name: '✕ Clear',
        type: 'Button',
        purpose: 'Resets the Source Folder field and clears all KPI cards and scan results.',
        behavior: 'Empties the path input and sets all stats to null. Does not affect any files on disk.',
        notes: 'Use this before switching to a different folder to avoid accidentally running the pipeline on the wrong path.',
      },
      {
        name: 'Total Videos',
        type: 'KPI Card · Integer',
        purpose: 'Count of all video files (.mov, .mp4, .MP4, .MOV, .mts) found in the source folder.',
        behavior: 'Scanned by the validator on Refresh. Looks one level deep into subdirectories if no videos are found at the top level.',
        notes: 'Does not require JSON files to be present. A count of 0 after scanning a NAS folder usually means the NAS is not mounted.',
      },
      {
        name: 'JSON Paired',
        type: 'KPI Card · Integer · Green',
        purpose: 'Count of video files that have a matching companion JSON in the json/ subfolder.',
        behavior: 'Matched by filename stem. A file named PDM-MALL_20241221_iPhone15ProMax_IMG_3423.mov is paired if json/PDM-MALL_20241221_iPhone15ProMax_IMG_3423.json exists.',
        notes: 'JSON files are the output of Stage 8 (Vertex AI). A paired file has been through full AI analysis.',
      },
      {
        name: 'Needs Stage 8',
        type: 'KPI Card · Integer · Amber when > 0',
        purpose: 'Count of video files with no companion JSON — they are in the Stage 8 processing queue.',
        behavior: 'Calculated as Total Videos − JSON Paired. An amber colour indicates unprocessed footage; this is the expected state before running the pipeline.',
        notes: 'Not an error. Resolve by running the Batch Pipeline.',
      },
      {
        name: 'Loc Confirmed',
        type: 'KPI Card · Integer · Green',
        purpose: 'Count of JSON records where loc_code_confirmed is set (location was confirmed by either manual override or AI visual/audio analysis).',
        behavior: 'Read from each JSON file\'s loc_code_confirmed field. Populated after Stage 8 (Vertex AI) or Stage 10 (apply confirmed location).',
        notes: 'Only counts files that have JSON. A file in the Stage 8 queue contributes 0 to this card.',
      },
      {
        name: 'Loc Unknown',
        type: 'KPI Card · Integer · Amber when > 0',
        purpose: 'Count of JSON records where the SACC filename starts with UNKNOWN_ — location was not confirmed by AI at Stage 8.',
        behavior: 'The pipeline uses UNKNOWN_ as a placeholder when no location override was provided and Vertex AI could not confidently identify the retail location from video content.',
        notes: 'Resolve by running Stage 10 (apply-loc) after providing a location code, or by re-running Stage 8 with a clearer video clip.',
      },
      {
        name: 'Duplicates',
        type: 'KPI Card · Integer · Amber when > 0',
        purpose: 'Count of duplicate groups found by the pre-flight checksum scan.',
        behavior: 'Populated by the Duplicate Scan (runs automatically after Refresh). Uses file size + partial MD5 checksum — not filename — to detect exact copies.',
        notes: 'Duplicates waste Compressor quota and Vertex AI credits. Resolve before running the pipeline.',
      },
      {
        name: 'Stage 8 Queue Panel',
        type: 'Status panel · Amber',
        purpose: 'Lists files that are awaiting Stage 8 (Vertex AI). Shown in amber to distinguish from actual errors.',
        behavior: 'Appears when Needs Stage 8 > 0. Shows the first 4 filenames and a count of remaining files.',
        notes: 'This is normal for unprocessed footage. Not a system error.',
      },
      {
        name: 'Errors Panel',
        type: 'Status panel · Red',
        purpose: 'Lists actual validation failures: JSON parse errors, missing required fields, relational key mismatches.',
        behavior: 'Appears only when the validator encounters broken or incomplete JSON records — not for missing JSON (that is the amber Stage 8 Queue).',
        notes: 'A red Errors panel requires investigation. Check the specific error message and refer to the Error Repository for resolution steps.',
      },
      {
        name: 'Duplicate Scan',
        type: 'Panel · Standalone pre-flight tool',
        purpose: 'Detects exact-match duplicate video files before pipeline processing.',
        behavior: 'Auto-runs after every Refresh. Uses file size + 64 KB partial MD5 checksum to find identical files regardless of filename. Groups duplicates and shows file size.',
        notes: 'Re-scan button re-runs the checksum scan without reloading the KPI cards. Safe to run any time.',
      },
      {
        name: 'Batch Pipeline (FCP Mode)',
        type: 'Panel · Pro only',
        purpose: 'Runs all 10 pipeline stages on the source folder: rename → compress → Vertex AI → JSON index → Stage 10 location confirm.',
        behavior: 'Calls /api/pipeline-run → sacc_pipeline.py --fcp. Detects FCP library folder structures automatically. Returns stdout/stderr log on completion.',
        notes: 'This is a destructive operation — it renames and moves files. Run the Renamer\'s Dry Run first if unsure.',
      },
      {
        name: 'Location Override',
        type: 'Input · SACC location code',
        purpose: 'Sets the [Custom Name] token in the FCP filename for the entire batch.',
        behavior: 'Must be a valid SACC code (PDM, FLM, MAM, etc.). Forces uppercase automatically. When set, all files in the batch are named with this location header (e.g. PDM-MALL_). When left blank, Vertex AI detects location from video content and files are initially named UNKNOWN_ until Stage 10 confirms.',
        notes: 'This is NOT a free-text label. Entering "b-roll" or any string not in the location database will fail pipeline validation at Stage 3.',
      },
    ],
  },

  // ── RENAMER ───────────────────────────────────────────────────────────────
  {
    id: 'renamer',
    title: 'Vibe Renamer + FCP Pipeline',
    icon: '✎',
    entries: [
      {
        name: 'Target Folder',
        type: 'Input · Text field',
        purpose: 'The folder containing video files to rename. Separate from the Dashboard Source Folder.',
        behavior: 'Does not auto-scan on entry. Scanning happens when Run Batch Renamer is clicked.',
        notes: 'Can point to a flat folder or a specific date folder inside an FCP library.',
      },
      {
        name: 'Search Location (NLP)',
        type: 'Input · Natural language',
        purpose: 'Resolves a free-text location description to a SACC location code using fuzzy matching.',
        behavior: 'Debounced 300ms — calls /api/resolve-location as you type. Matches against full names ("Paddock Mall" → PDM), aliases ("paddock", "ocala" → PDM), and partial strings. A green dot and code appear when a match is found.',
        notes: 'Accepted inputs: full mall name, city name, SACC code directly, or common aliases. Case-insensitive.',
      },
      {
        name: 'Browse All Locations',
        type: 'Dropdown list · Filterable',
        purpose: 'Lets you select a location by clicking rather than typing.',
        behavior: 'Clicking a row sets both the NLP input and the resolved location code. Filterable by name, code, or region.',
        notes: 'Populated from the SACC location database (25 Florida retail locations).',
      },
      {
        name: 'Identifier',
        type: 'Input · Text · Classic mode only',
        purpose: 'The shoe or event identifier embedded in the filename between the location header and the camera model.',
        behavior: 'Used only in Classic (Vibe) mode. Results in: PDM-MALL_241221_Air-Jordan-1_iPhone15ProMax_IMG_3423.mov. Spaces are replaced with hyphens automatically.',
        notes: 'Leave blank to use FCP mode (no identifier — cleaner for archival). FCP mode is recommended for all new footage.',
      },
      {
        name: 'FCP Filename Preview',
        type: 'Display · Read-only',
        purpose: 'Shows the output filename format based on current settings.',
        behavior: 'Computed client-side from the resolved location code, today\'s date, and the identifier. Shows [CamModel] as a placeholder — the real camera model is extracted from file metadata (ffprobe) when the rename actually runs.',
        notes: 'The date in the preview is today\'s date, not the shoot date. The actual rename uses the shoot date from file metadata.',
      },
      {
        name: 'Dry Run',
        type: 'Checkbox · Default on',
        purpose: 'When checked, the renamer shows what it would do without changing any files.',
        behavior: 'Checked: runs through all logic, returns preview results, no os.rename() calls. Unchecked: physically renames files. Both modes return the same response structure.',
        notes: 'Always run with Dry Run on first to verify the output names look correct before committing.',
      },
      {
        name: 'Run Batch Renamer',
        type: 'Button · Green',
        purpose: 'Executes the rename operation on all video files in the target folder.',
        behavior: 'With identifier set → Vibe/Classic mode (run_vibe_renamer). Without identifier → FCP mode (run_fcp_renamer). Results are listed below with original → new filename pairs.',
        notes: 'Reads actual file metadata (date, camera model) at rename time — the FCP Preview is an approximation only.',
      },
      {
        name: 'Renamer Tab',
        type: 'View tab',
        purpose: 'The main rename workflow: NLP location resolver + identifier + dry run preview.',
        behavior: 'Default tab when the Renamer view opens.',
        notes: '',
      },
      {
        name: 'Database Tab',
        type: 'View tab',
        purpose: 'Shows all JSON records in the json/ subfolder of the target folder as a table.',
        behavior: 'Loads on tab click. Columns: FCP Filename, Model, SKU, Location, Proxy. Also exposes the "Apply loc → UNKNOWN records" action to bulk-set location on unresolved files.',
        notes: 'Data comes from JSON files on disk, not SQLite. Reflects the state of the json/ folder.',
      },
      {
        name: 'Pipeline Tab',
        type: 'View tab',
        purpose: 'Direct access to Phase 7 (rename) and Phase 8 (archive to Synology) with live streaming log.',
        behavior: 'Phase 7 runs sacc_pipeline.py rename stage via SSE stream. Phase 8 runs the archival stage. Both show live output line by line.',
        notes: 'These are lower-level controls than the Dashboard Batch Pipeline. Use when you need to run individual stages separately.',
      },
    ],
  },

  // ── PIPELINE STAGES ───────────────────────────────────────────────────────
  {
    id: 'pipeline',
    title: 'Pipeline Stage Reference',
    icon: '⟳',
    entries: [
      {
        name: 'Stage 3 — FCP Rename',
        type: 'Pipeline stage',
        purpose: 'Establishes the permanent SACC filename (the relational key) for every video file.',
        behavior: 'FCP mode: [LOC-TYPE]_[YYYYMMDD]_[CamModel]_[OriginalStem]. Classic mode: [LOC-TYPE]_[YYMMDD]_[Identifier]_[CamModel]_[OriginalStem]. Strips any existing SACC prefix to prevent double-naming.',
        notes: 'This filename is the relational key. All downstream assets (JSON, proxy) use the same stem. Do not rename files outside SACC after this stage.',
      },
      {
        name: 'Stage 4 — Organise',
        type: 'Pipeline stage',
        purpose: 'Moves renamed files from Inbox into the dated archive structure: /SACC/YYYY/YYYYMMDD/.',
        behavior: 'Date is read from file metadata (ffprobe), not today\'s date. Groups clips by shoot date automatically.',
        notes: 'Files that already exist at the destination are skipped (not overwritten).',
      },
      {
        name: 'Stage 5 — Pre-Flight',
        type: 'Pipeline stage',
        purpose: 'Filters clips that would waste Compressor quota — too short or no detectable motion.',
        behavior: 'Minimum duration: 3 seconds. Minimum motion score: 1 frame per second. Files that fail are logged to preflight_skipped.json and excluded from compression.',
        notes: 'ffprobe failures are non-blocking — a clip that cannot be probed is passed through.',
      },
      {
        name: 'Stage 6+7 — Compress (Proxy)',
        type: 'Pipeline stage',
        purpose: 'Generates a compressed proxy copy of each file for Vertex AI upload (reduces API costs).',
        behavior: 'Calls Apple Compressor with the HEVC preset. Proxy inherits the exact same filename stem as the source and is placed in a _proxy/ subfolder.',
        notes: 'Proxy files are transient — deleted at Stage 9. The source hi-res file is never modified.',
      },
      {
        name: 'Stage 8 — Vertex AI (Gemini)',
        type: 'Pipeline stage',
        purpose: 'The core AI analysis stage. Sends each proxy to Gemini/Vertex AI and extracts: shoe model, SKU, location (visual + audio), confidence scores.',
        behavior: 'Uploads proxy via Gemini File API, waits for ACTIVE status, runs inference, writes JSON to json/<stem>.json, deletes the uploaded file. Retries with exponential backoff on 429 rate limits.',
        notes: 'Uses gemini-2.5-pro (not flash) for better video understanding. JSON output is the permanent record.',
      },
      {
        name: 'Stage 9 — Delete Proxies',
        type: 'Pipeline stage',
        purpose: 'Removes the _proxy/ folder after Stage 8 completes successfully.',
        behavior: 'Only runs if Stage 8 produced JSON output. If Stage 8 failed, proxies are kept so Stage 8 can be retried without re-running Compressor.',
        notes: 'proxy_deleted: true is written into the JSON record when this stage completes.',
      },
      {
        name: 'Stage 10 — Apply Confirmed Locations',
        type: 'Pipeline stage',
        purpose: 'Renames UNKNOWN_ files to their confirmed location codes after AI analysis.',
        behavior: 'Reads loc_code_confirmed from each JSON, replaces UNKNOWN in the filename with the correct LOC-TYPE header. Also renames the companion JSON to keep stems in sync.',
        notes: 'Only runs in FCP mode. Triggered automatically at the end of the pipeline, or manually via: python3 fcp_namer.py --apply-loc --folder <dest_dir>.',
      },
    ],
  },

  // ── FILENAME FORMAT ───────────────────────────────────────────────────────
  {
    id: 'filenames',
    title: 'SACC Filename Format',
    icon: '⊟',
    entries: [
      {
        name: 'FCP Format (recommended)',
        type: 'Filename convention',
        purpose: 'The current standard filename format for all new footage processed through the FCP pipeline.',
        behavior: '[LOC-TYPE]_[YYYYMMDD]_[CamModel]_[OriginalStem].[ext]\n\nExample: PDM-MALL_20241221_iPhone15ProMax_IMG_3423.mov',
        notes: 'No shoe identifier in the filename — the AI captures that in the JSON. Cleaner for archival and easier to parse programmatically.',
      },
      {
        name: 'Classic / Vibe Format (legacy)',
        type: 'Filename convention',
        purpose: 'The original SACC naming format that includes a manual shoe identifier.',
        behavior: '[LOC-TYPE]_[YYMMDD]_[Identifier]_[CamModel]_[OriginalStem].[ext]\n\nExample: PDM-MALL_241221_Before-X-Mas-2024_iPhone15ProMax_IMG_3423.mov',
        notes: 'Still supported by the Renamer. 6-digit date (YYMMDD vs YYYYMMDD). The Renamer\'s Dry Run shows the exact output before committing.',
      },
      {
        name: 'LOC-TYPE token',
        type: 'Filename segment',
        purpose: 'The location code + store type prefix. Identifies where the footage was shot.',
        behavior: 'Built from LOCATION_DB: code + "-" + type. Examples: PDM-MALL, FLM-MALL, VLD-NFS, HVP-NIKE.',
        notes: 'This is the [Custom Name] token in Final Cut Pro naming preset terminology.',
      },
      {
        name: 'CamModel token',
        type: 'Filename segment',
        purpose: 'The camera device that recorded the clip, extracted from file metadata.',
        behavior: 'Read by ffprobe from com.apple.quicktime.model (iPhone) or com.apple.proapps.modelname tags. Spaces stripped: "iPhone 15 Pro Max" → "iPhone15ProMax".',
        notes: 'Falls back to "Cam" if no model tag is found in metadata (common for Sony/DJI footage without QuickTime metadata).',
      },
      {
        name: 'UNKNOWN prefix',
        type: 'Filename segment',
        purpose: 'Placeholder used when no location code is available at Stage 3 rename time.',
        behavior: 'Files named UNKNOWN_20241221_iPhone15ProMax_IMG_3423.mov are renamed to the confirmed location header at Stage 10 once Vertex AI identifies the location.',
        notes: 'A count of UNKNOWN files is shown in the "Loc Unknown" KPI card on the Dashboard.',
      },
    ],
  },

  // ── LOCATION CODES ────────────────────────────────────────────────────────
  {
    id: 'locations',
    title: 'SACC Location Code Reference',
    icon: '◉',
    entries: [
      { name: 'PDM', type: 'MALL · Ocala',         purpose: 'Paddock Mall',                    behavior: '', notes: '' },
      { name: 'FLM', type: 'MALL · Orlando',        purpose: 'The Florida Mall',                behavior: '', notes: '' },
      { name: 'MAM', type: 'MALL · Orlando',        purpose: 'Mall at Millenia',                behavior: '', notes: '' },
      { name: 'OFS', type: 'MALL · Orlando',        purpose: 'Orlando Fashion Square',          behavior: '', notes: '' },
      { name: 'WOM', type: 'MALL · Orlando',        purpose: 'West Oaks Mall',                  behavior: '', notes: '' },
      { name: 'WFL', type: 'MALL · Orlando',        purpose: 'Waterford Lakes',                 behavior: '', notes: '' },
      { name: 'WGN', type: 'MALL · Orlando',        purpose: 'Winter Garden Village',           behavior: '', notes: '' },
      { name: 'SEM', type: 'MALL · Sanford',        purpose: 'Seminole Towne Center',           behavior: '', notes: '' },
      { name: 'LKL', type: 'MALL · Lakeland',       purpose: 'Lakeland Square Mall',            behavior: '', notes: '' },
      { name: 'THL', type: 'MALL · Tallahassee',    purpose: 'Tallahassee Mall',                behavior: '', notes: '' },
      { name: 'BTC', type: 'MALL · Tampa',          purpose: 'Brandon Exchange (Brandon Town Center)', behavior: '', notes: '' },
      { name: 'INP', type: 'MALL · Tampa',          purpose: 'International Plaza',             behavior: '', notes: '' },
      { name: 'UNM', type: 'MALL · Tampa',          purpose: 'University Mall',                 behavior: '', notes: '' },
      { name: 'VLD', type: 'NFS · Orlando',         purpose: 'Vineland Premium Outlets',        behavior: '', notes: '' },
      { name: 'IDR', type: 'NFS · Orlando',         purpose: 'International Drive',             behavior: '', notes: '' },
      { name: 'LBV', type: 'NFS · Orlando',         purpose: 'Lake Buena Vista',                behavior: '', notes: '' },
      { name: 'OMP', type: 'NCS · Orlando',         purpose: 'Orlando Marketplace (I-Drive)',   behavior: '', notes: '' },
      { name: 'TPA', type: 'NFS · Tampa',           purpose: 'Tampa Premium Outlets',           behavior: '', notes: '' },
      { name: 'HVP', type: 'NIKE · Tampa',          purpose: 'Hyde Park Village',               behavior: '', notes: '' },
      { name: 'AVE', type: 'NIKE · Miami',          purpose: 'Aventura Mall',                   behavior: '', notes: '' },
      { name: 'LCN', type: 'NIKE · Miami',          purpose: 'Lincoln Road',                    behavior: '', notes: '' },
      { name: 'DOL', type: 'NFS · Miami',           purpose: 'Dolphin Mall',                    behavior: '', notes: '' },
      { name: 'GVA', type: 'NFS · Gainesville',     purpose: 'Gainesville (Celebration Pointe)',behavior: '', notes: '' },
      { name: 'CEL-K', type: 'NFS · Kissimmee',    purpose: 'Celebration (Kissimmee)',          behavior: '', notes: '' },
      { name: 'KSM', type: 'NCS · Kissimmee',       purpose: 'Kissimmee (Osceola Pkwy)',        behavior: '', notes: '' },
      { name: 'NC192', type: 'NCS · Kissimmee',     purpose: 'Nike Clearance Store 192 (US-192, defunct, pre-Loop)', behavior: 'archive-only', notes: 'Defunct predecessor of NCLP. Covers pre-2019 / early-2019 footage.' },
      { name: 'NCLP',  type: 'NCS · Kissimmee',     purpose: 'Nike Clearance Store at the Loop',                    behavior: '', notes: 'Active successor to NC192 on the US-192 / Loop corridor.' },
    ],
  },
];

function DocsView({ mode }) {
  const P = SACC_PALETTE;
  const [activeSection, setActiveSection] = React.useState('dashboard');
  const [search, setSearch] = React.useState('');
  const [expanded, setExpanded] = React.useState(null);

  const section = DOCS_SECTIONS.find(s => s.id === activeSection);

  const entries = React.useMemo(() => {
    if (!section) return [];
    if (!search.trim()) return section.entries;
    const q = search.toLowerCase();
    return section.entries.filter(e =>
      e.name.toLowerCase().includes(q) ||
      e.purpose.toLowerCase().includes(q) ||
      e.behavior.toLowerCase().includes(q) ||
      e.type.toLowerCase().includes(q)
    );
  }, [section, search]);

  // For location codes: compact table layout
  const isLocations = activeSection === 'locations';

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', background: P.bg,
      fontFamily: '-apple-system, sans-serif' }}>

      {/* Left nav */}
      <div style={{ width: 180, flexShrink: 0, borderRight: `1px solid ${P.border}`,
        padding: '20px 0', display: 'flex', flexDirection: 'column', gap: 2, overflowY: 'auto' }}>
        <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace',
          letterSpacing: '0.06em', padding: '0 16px', marginBottom: 8 }}>
          FEATURE DICTIONARY
        </div>
        {DOCS_SECTIONS.map(s => (
          <div key={s.id} onClick={() => { setActiveSection(s.id); setSearch(''); setExpanded(null); }}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 16px',
              cursor: 'pointer', borderRadius: 0,
              background: activeSection === s.id ? P.accentLight : 'transparent',
              color: activeSection === s.id ? P.accent : P.text,
              transition: 'background 0.1s' }}>
            <span style={{ fontSize: 13, minWidth: 18 }}>{s.icon}</span>
            <span style={{ fontSize: 12, fontWeight: activeSection === s.id ? 700 : 400,
              lineHeight: 1.3 }}>
              {s.title}
            </span>
          </div>
        ))}
      </div>

      {/* Main content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 24, display: 'flex',
        flexDirection: 'column', gap: 14 }}>

        {/* Section header */}
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: P.text, marginBottom: 4 }}>
            {section?.icon} {section?.title}
          </div>
          <div style={{ fontSize: 11, color: P.muted, fontFamily: 'Space Mono, monospace' }}>
            {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
            {search && ` matching "${search}"`}
          </div>
        </div>

        {/* Search */}
        {!isLocations && (
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={`Search ${section?.title}…`}
            style={{ border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
              fontSize: 12, color: P.text, background: P.bg, outline: 'none',
              fontFamily: '-apple-system, sans-serif' }}
          />
        )}

        {/* Location code table */}
        {isLocations && (
          <div style={{ background: P.panel, border: `1px solid ${P.border}`,
            borderRadius: 10, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '60px 140px 1fr',
              padding: '8px 14px', background: P.bg, borderBottom: `1px solid ${P.border}`,
              fontSize: 9, fontFamily: 'Space Mono, monospace', color: P.muted,
              letterSpacing: '0.06em' }}>
              {['CODE', 'TYPE · REGION', 'LOCATION NAME'].map(h => <div key={h}>{h}</div>)}
            </div>
            {entries.map((e, i) => (
              <div key={e.name} style={{ display: 'grid',
                gridTemplateColumns: '60px 140px 1fr',
                padding: '8px 14px',
                borderBottom: i < entries.length - 1 ? `1px solid ${P.border}` : 'none',
                background: i % 2 === 0 ? 'transparent' : P.bg + '80',
                alignItems: 'center' }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: P.accent,
                  fontFamily: 'Space Mono, monospace' }}>{e.name}</span>
                <span style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace' }}>{e.type}</span>
                <span style={{ fontSize: 12, color: P.text }}>{e.purpose}</span>
              </div>
            ))}
          </div>
        )}

        {/* Entry cards */}
        {!isLocations && entries.map(e => {
          const isOpen = expanded === e.name;
          return (
            <div key={e.name}
              style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10,
                overflow: 'hidden' }}>
              {/* Always-visible row */}
              <div onClick={() => setExpanded(isOpen ? null : e.name)}
                style={{ display: 'flex', alignItems: 'center', gap: 10,
                  padding: '11px 14px', cursor: 'pointer' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: P.text }}>{e.name}</span>
                    <span style={{ fontSize: 9, fontFamily: 'Space Mono, monospace',
                      color: P.accent, background: P.accentLight,
                      padding: '2px 6px', borderRadius: 3 }}>
                      {e.type}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: P.muted, lineHeight: 1.4 }}>
                    {e.purpose}
                  </div>
                </div>
                <span style={{ fontSize: 12, color: P.muted, flexShrink: 0 }}>
                  {isOpen ? '▲' : '▼'}
                </span>
              </div>

              {/* Expanded detail */}
              {isOpen && (
                <div style={{ borderTop: `1px solid ${P.border}`, padding: '14px',
                  display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {e.behavior && (
                    <div>
                      <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace',
                        letterSpacing: '0.06em', marginBottom: 5 }}>HOW IT WORKS</div>
                      <div style={{ fontSize: 12, color: P.text, lineHeight: 1.7,
                        whiteSpace: 'pre-wrap' }}>
                        {e.behavior}
                      </div>
                    </div>
                  )}
                  {e.notes && (
                    <div style={{ background: P.accent + '10', border: `1px solid ${P.accent}30`,
                      borderRadius: 6, padding: '10px 12px' }}>
                      <div style={{ fontSize: 9, color: P.accent, fontFamily: 'Space Mono, monospace',
                        letterSpacing: '0.06em', marginBottom: 4 }}>NOTE</div>
                      <div style={{ fontSize: 12, color: P.text, lineHeight: 1.6 }}>
                        {e.notes}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

window.DocsView = DocsView;

// SACC — Dashboard View (v2)
// Auto-runs duplicate scan on folder load. Proxy Cleaned removed from preflight.

const API = 'http://localhost:5174';
const DEFAULT_FOLDER = '/Volumes/Team Bank 12/Sneeaker Solo/Sneaker solo Originals';

function DashboardView({ mode, accent, folder, setFolder }) {
  const P = SACC_PALETTE;
  const [dbStats, setDbStats]       = React.useState(null);
  const [statsError, setStatsError] = React.useState('');
  const [loading, setLoading]       = React.useState(false);
  const [preflightRes, setPreflight]       = React.useState(null);
  const [preflightRunning, setPreflightRunning] = React.useState(false);
  const [pipelineRes, setPipelineRes]   = React.useState(null);
  const [pipelineRunning, setPipelineRunning] = React.useState(false);
  const [pipelineLoc, setPipelineLoc]   = React.useState('');
  // Folder is session-only — not persisted to localStorage.
  // Starts blank so user consciously chooses a path each session.
  const [folderInput, setFolderInput]   = React.useState('');
  const [apiOnline, setApiOnline]       = React.useState(null);

  // Check API health on mount
  React.useEffect(() => {
    fetch(`${API}/api/health`)
      .then(r => r.json())
      .then(d => setApiOnline(d.status === 'ok'))
      .catch(() => setApiOnline(false));
  }, []);

  // Auto-run preflight duplicate scan for a given folder path
  const runPreflightFor = React.useCallback((path) => {
    if (!path) return;
    setPreflightRunning(true);
    setPreflight(null);
    fetch(`${API}/api/preflight`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
      .then(r => r.json())
      .then(d => { setPreflight(d); setPreflightRunning(false); })
      .catch(e => { setPreflight({ error: String(e) }); setPreflightRunning(false); });
  }, []);

  // Load folder stats — auto-triggers preflight on success
  const loadStats = React.useCallback(() => {
    const f = folderInput.trim();
    if (!f) return;
    setLoading(true);
    setStatsError('');
    setPreflight(null);
    fetch(`${API}/api/folder-status?path=${encodeURIComponent(f)}`)
      .then(r => r.json())
      .then(d => {
        if (d.error || d.fatal) {
          setStatsError(d.error || d.fatal);
          setDbStats(null);
        } else {
          setDbStats(d);
          // ── Auto-trigger duplicate scan immediately on folder load ──
          runPreflightFor(f);
        }
        setLoading(false);
      })
      .catch(err => {
        setStatsError(`Could not reach API at ${API} — is the server running? (${err.message})`);
        setLoading(false);
      });
  }, [folderInput, runPreflightFor]);

  // Only auto-load if a folder is already set (it won't be on fresh session)
  React.useEffect(() => { if (apiOnline && folderInput.trim()) loadStats(); }, [apiOnline]);

  // Keep manual button as a re-run option
  const runPreflight = () => runPreflightFor(folderInput);

  const clearFolder = () => {
    setFolderInput('');
    setDbStats(null);
    setStatsError('');
    setPreflight(null);
    setPipelineRes(null);
  };

  const runPipeline = () => {
    setPipelineRunning(true);
    setPipelineRes(null);
    fetch(`${API}/api/pipeline-run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: folderInput, loc: pipelineLoc, fcp_mode: true }),
    })
      .then(r => r.json())
      .then(d => { setPipelineRes(d); setPipelineRunning(false); loadStats(); })
      .catch(e => { setPipelineRes({ error: String(e) }); setPipelineRunning(false); });
  };

  // KPI data derived from dbStats
  const s = dbStats?.summary || {};
  const dupCount = preflightRunning
    ? '…'
    : preflightRes && !preflightRes.error
      ? (preflightRes.duplicate_groups ?? 0)
      : '—';
  const dupWarn = typeof dupCount === 'number' && dupCount > 0;

  const kpis = [
    { val: s.total_videos  ?? '—', label: 'Total Videos',  accent: false },
    { val: s.paired        ?? '—', label: 'JSON Paired',    accent: true  },
    { val: s.unpaired      ?? '—', label: 'Needs Stage 8',  warn: (s.unpaired > 0) },
    { val: s.loc_confirmed ?? '—', label: 'Loc Confirmed',  success: true },
    { val: s.unknown_loc   ?? '—', label: 'Loc Unknown',    warn: (s.unknown_loc > 0) },
    { val: dupCount,               label: 'Duplicates',     warn: dupWarn, clean: (!dupWarn && dupCount !== '—') },
  ];

  const cardColor = (k) => {
    if (k.accent)              return P.accent;
    if (k.success || k.clean)  return P.success;
    if (k.warn && k.val > 0)   return P.warning;
    return P.text;
  };

  return (
    <div style={{ flex: 1, overflowY: 'auto', background: P.bg, padding: 20,
      display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif' }}>
            Pipeline Dashboard
          </div>
          <div style={{ fontSize: 11, color: P.muted, fontFamily: 'Space Mono, monospace', marginTop: 2 }}>
            Real-time sync status · Batch operations · Pre-flight checks
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%',
            background: apiOnline === null ? P.muted : apiOnline ? P.success : P.error }} />
          <span style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace' }}>
            {apiOnline === null ? 'CONNECTING' : apiOnline ? 'API ONLINE' : 'API OFFLINE'}
          </span>
        </div>
      </div>

      {/* Folder input */}
      <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '12px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace', letterSpacing: '0.06em' }}>
            SOURCE FOLDER
          </span>
          <span style={{ fontSize: 9, color: P.muted, fontFamily: '-apple-system, sans-serif' }}>
            Session-only — cleared on close · press Enter or Refresh to scan
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            value={folderInput}
            onChange={e => setFolderInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && loadStats()}
            style={{ flex: 1, border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
              fontSize: 12, fontFamily: 'Space Mono, monospace', color: P.text,
              background: P.bg, outline: 'none' }}
            placeholder="Paste a folder path, e.g. /Volumes/Team Bank 12/…"
          />
          {/* Refresh — scans the folder and re-runs the duplicate check */}
          <Btn onClick={() => loadStats()} disabled={loading || !folderInput.trim()}
            title="Scan folder: counts videos, checks JSON pairing, triggers duplicate scan">
            {loading ? '…' : '↺ Refresh'}
          </Btn>
          {/* Clear — resets all metrics; does NOT affect files on disk */}
          <Btn onClick={clearFolder} disabled={!folderInput && !dbStats}
            title="Clear path and reset all metrics (no files are changed)">
            ✕ Clear
          </Btn>
        </div>
      </div>

      {/* Folder / API error */}
      {statsError && (
        <div style={{ background: P.error + '15', border: `1px solid ${P.error}44`,
          borderRadius: 8, padding: '10px 14px', fontSize: 12,
          color: P.error, fontFamily: '-apple-system, sans-serif' }}>
          <strong>✗ Error:</strong> {statsError}
          {statsError.includes('Folder not found') && (
            <div style={{ marginTop: 6, fontSize: 11, color: P.muted }}>
              Check that the NAS volume is mounted: <code style={{ fontFamily: 'Space Mono, monospace' }}>ls "/Volumes/Team Bank 12"</code>
            </div>
          )}
        </div>
      )}

      {/* API offline warning */}
      {apiOnline === false && (
        <div style={{ background: P.error + '15', border: `1px solid ${P.error}44`,
          borderRadius: 8, padding: '10px 14px', fontSize: 12,
          color: P.error, fontFamily: '-apple-system, sans-serif' }}>
          ✗ API server offline — start it with: <code style={{ fontFamily: 'Space Mono, monospace', fontSize: 11 }}>python3 /Users/miniman/SACC/api.py</code>
        </div>
      )}

      {/* KPI cards — 3×2 grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
        {kpis.map((k, i) => (
          <div key={i} style={{ background: P.panel, border: `1px solid ${P.border}`,
            borderRadius: 10, padding: '14px 16px' }}>
            <div style={{ fontSize: 26, fontWeight: 700, color: cardColor(k),
              fontFamily: '-apple-system, sans-serif', lineHeight: 1 }}>
              {k.val}
            </div>
            <div style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace', marginTop: 4 }}>
              {k.label}
            </div>
          </div>
        ))}
      </div>

      {/* KPI legend — always visible, explains what each card means */}
      <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 8,
        padding: '10px 14px', display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: '6px 16px' }}>
        {[
          ['Total Videos',  'All .mov/.mp4 files in the source folder'],
          ['JSON Paired',   'Videos that have a Stage 8 AI JSON file'],
          ['Needs Stage 8', 'Videos with no JSON — Vertex AI not yet run'],
          ['Loc Confirmed', 'JSON records with a confirmed retail location'],
          ['Loc Unknown',   'JSON records where location = UNKNOWN (Stage 10 pending)'],
          ['Duplicates',    'Exact-match duplicate clips (pre-flight scan)'],
        ].map(([label, desc]) => (
          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: P.muted, fontFamily: 'Space Mono, monospace', letterSpacing: '0.05em' }}>
              {label}
            </span>
            <span style={{ fontSize: 10, color: P.muted, fontFamily: '-apple-system, sans-serif', lineHeight: 1.4 }}>
              {desc}
            </span>
          </div>
        ))}
      </div>

      {/* Stage 8 queue — amber/info, not errors */}
      {dbStats?.queue?.length > 0 && (
        <div style={{ background: P.warning + '10', border: `1px solid ${P.warning}33`,
          borderRadius: 8, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 10, color: P.warning, fontFamily: 'Space Mono, monospace', fontWeight: 700 }}>
                STAGE 8 QUEUE — {dbStats.queue.length} file{dbStats.queue.length !== 1 ? 's' : ''}
              </span>
            </div>
            <span style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace' }}>
              [E020] expected · not an error
            </span>
          </div>
          <div style={{ fontSize: 11, color: P.muted, fontFamily: '-apple-system, sans-serif', lineHeight: 1.5 }}>
            These files have no companion JSON because Vertex AI (Stage 8) has not yet run on them.
            This is the normal state for unprocessed footage — run the Batch Pipeline to generate JSON for each file.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {dbStats.queue.slice(0, 4).map((f, i) => (
              <div key={i} style={{ fontSize: 10, color: P.warning, fontFamily: 'Space Mono, monospace' }}>
                ⏳ {f}
              </div>
            ))}
            {dbStats.queue.length > 4 && (
              <div style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace' }}>
                … and {dbStats.queue.length - 4} more awaiting Stage 8
              </div>
            )}
          </div>
        </div>
      )}

      {/* Real errors — parse failures, missing required fields */}
      {dbStats?.errors?.length > 0 && (
        <div style={{ background: P.error + '10', border: `1px solid ${P.error}33`,
          borderRadius: 8, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 2 }}>
            <span style={{ fontSize: 10, color: P.error, fontFamily: 'Space Mono, monospace', fontWeight: 700 }}>
              ERRORS ({dbStats.errors.length})
            </span>
            <span style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace' }}>
              JSON parse failures or missing required fields — action required
            </span>
          </div>
          {dbStats.errors.slice(0, 5).map((e, i) => (
            <div key={i} style={{ fontSize: 11, color: P.error, fontFamily: '-apple-system, sans-serif' }}>✗ {e}</div>
          ))}
          {dbStats.errors.length > 5 && (
            <div style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace' }}>
              … and {dbStats.errors.length - 5} more
            </div>
          )}
        </div>
      )}

      {/* Warnings — soft issues like orphan JSONs */}
      {dbStats?.warnings?.length > 0 && (
        <div style={{ background: P.warning + '10', border: `1px solid ${P.warning}33`,
          borderRadius: 8, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 10, color: P.warning, fontFamily: 'Space Mono, monospace', marginBottom: 2 }}>
            WARNINGS ({dbStats.warnings.length})
          </div>
          {dbStats.warnings.slice(0, 5).map((w, i) => (
            <div key={i} style={{ fontSize: 11, color: P.warning, fontFamily: '-apple-system, sans-serif' }}>⚠ {w}</div>
          ))}
        </div>
      )}

      {/* Pre-Flight Duplicate Scan — auto-runs on folder load */}
      <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '14px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif' }}>
              Duplicate Scan
            </div>
            {/* Live status badge */}
            {preflightRunning && (
              <span style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace' }}>⟳ scanning…</span>
            )}
            {!preflightRunning && preflightRes && !preflightRes.error && (
              <span style={{
                fontSize: 10, fontFamily: 'Space Mono, monospace', fontWeight: 700,
                color: preflightRes.clean ? P.success : P.warning,
                background: (preflightRes.clean ? P.success : P.warning) + '18',
                padding: '2px 7px', borderRadius: 4,
              }}>
                {preflightRes.clean
                  ? `✓ CLEAR — 0 duplicates`
                  : `⚠ ${preflightRes.duplicate_groups} duplicate group${preflightRes.duplicate_groups !== 1 ? 's' : ''} found`}
              </span>
            )}
          </div>
          <Btn onClick={runPreflight} disabled={preflightRunning || !apiOnline || !dbStats}>
            ↺ Re-scan
          </Btn>
        </div>
        <div style={{ fontSize: 11, color: P.muted, fontFamily: '-apple-system, sans-serif',
          lineHeight: 1.5, marginBottom: preflightRes ? 10 : 0 }}>
          {preflightRunning
            ? 'Scanning for exact-match duplicates…'
            : preflightRes?.clean
            ? 'No exact-match duplicate footage detected — safe to start batch processing.'
            : !preflightRes
            ? <>
                Standalone pre-flight integrity check. Compares files by size + partial checksum
                (not just filename) to catch exact-match duplicates before they waste Compressor
                quota or Vertex AI credits. Runs automatically when a folder is loaded.
                Use <strong>Re-scan</strong> after adding or removing files.
              </>
            : ''}
        </div>
        {preflightRes && !preflightRes.clean && !preflightRes.error && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {preflightRes.duplicates?.map((g, i) => (
              <div key={i} style={{ background: P.warning + '15', borderRadius: 6, padding: '8px 10px' }}>
                <div style={{ fontSize: 10, color: P.warning, fontFamily: 'Space Mono, monospace', marginBottom: 4 }}>
                  {g.size_mb} MB — exact match ({g.files.length} copies)
                </div>
                {g.files.map(f => (
                  <div key={f} style={{ fontSize: 11, color: P.text, fontFamily: 'Space Mono, monospace', marginTop: 2 }}>· {f}</div>
                ))}
              </div>
            ))}
          </div>
        )}
        {preflightRes?.error && (
          <div style={{ fontSize: 11, color: P.error, fontFamily: '-apple-system, sans-serif' }}>✗ {preflightRes.error}</div>
        )}
      </div>

      {/* Batch pipeline */}
      {mode === 'pro' && (
        <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '14px 16px' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif', marginBottom: 4 }}>
            Batch Pipeline (FCP Mode)
          </div>
          <div style={{ fontSize: 11, color: P.muted, fontFamily: '-apple-system, sans-serif', marginBottom: 12 }}>
            Runs all pipeline stages: rename → proxy → Vertex AI → JSON index → Stage 10 location confirm
          </div>
          <div style={{ marginBottom: 4 }}>
            <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace',
              letterSpacing: '0.06em', marginBottom: 4 }}>
              LOCATION OVERRIDE  <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>— optional</span>
            </div>
            <input
              value={pipelineLoc}
              onChange={e => setPipelineLoc(e.target.value.toUpperCase())}
              placeholder="SACC location code, e.g. PDM · FLM · MAM · OFS"
              style={{ width: '100%', border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
                fontSize: 12, fontFamily: 'Space Mono, monospace', color: P.text,
                background: P.bg, outline: 'none', boxSizing: 'border-box',
                textTransform: 'uppercase', marginBottom: 4 }}
            />
            <div style={{ fontSize: 10, color: P.muted, fontFamily: '-apple-system, sans-serif', lineHeight: 1.5 }}>
              Must be a valid SACC code from the location database (PDM = Paddock Mall, FLM = Florida Mall, etc.).
              Sets the <code style={{ fontFamily: 'Space Mono, monospace', fontSize: 9 }}>[Custom Name]</code> token
              in the FCP filename — e.g. <code style={{ fontFamily: 'Space Mono, monospace', fontSize: 9 }}>PDM-MALL_20241221_iPhone15ProMax_IMG_3423.mov</code>.
              Leave blank to let Vertex AI detect location from video content (Stage 8), which uses
              <code style={{ fontFamily: 'Space Mono, monospace', fontSize: 9 }}> UNKNOWN_</code> as a placeholder until Stage 10 confirms it.
              This is <em>not</em> a free-text label — entering "b-roll" here will fail validation.
            </div>
          </div>
          <div style={{ marginBottom: 12 }} />
          <Btn primary onClick={runPipeline} disabled={pipelineRunning || !apiOnline}
            style={{ background: '#34c759', fontSize: 13, padding: '8px 20px' }}>
            {pipelineRunning ? '⟳ Pipeline Running…' : '▶  Start Batch Pipeline'}
          </Btn>

          {pipelineRes && (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {/* Status line + error code badge */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 12, fontWeight: 600,
                  color: pipelineRes.ok ? P.success : P.error,
                  fontFamily: '-apple-system, sans-serif' }}>
                  {pipelineRes.ok ? '✓ Pipeline completed' : '✗ Pipeline failed'}
                </span>
                {pipelineRes.error_code && (
                  <span style={{ fontSize: 9, fontFamily: 'Space Mono, monospace', fontWeight: 700,
                    color: P.error, background: P.error + '18',
                    padding: '2px 6px', borderRadius: 3 }}>
                    {pipelineRes.error_code}
                  </span>
                )}
              </div>
              {/* Error detail + hint */}
              {(pipelineRes.error || pipelineRes.hint) && (
                <div style={{ background: P.error + '10', border: `1px solid ${P.error}33`,
                  borderRadius: 6, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {pipelineRes.error && (
                    <div style={{ fontSize: 11, color: P.error, fontFamily: '-apple-system, sans-serif' }}>
                      {pipelineRes.error}
                    </div>
                  )}
                  {pipelineRes.hint && (
                    <div style={{ fontSize: 10, color: P.muted, fontFamily: '-apple-system, sans-serif' }}>
                      → {pipelineRes.hint}
                    </div>
                  )}
                </div>
              )}
              {/* stdout / stderr log */}
              {pipelineRes.stdout && (
                <div style={{ background: '#0d0d0f', borderRadius: 6, padding: 10,
                  maxHeight: 200, overflowY: 'auto' }}>
                  <pre style={{ fontSize: 10, fontFamily: 'Space Mono, monospace',
                    color: '#7ae', margin: 0, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                    {pipelineRes.stdout}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

window.DashboardView = DashboardView;

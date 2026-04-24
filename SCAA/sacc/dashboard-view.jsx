// SACC — Dashboard View
// Migrated from Streamlit Tab 1: KPI metrics, pre-flight scan, batch pipeline trigger

const API = 'http://localhost:5174';

function DashboardView({ mode, accent, folder, setFolder }) {
  const P = SACC_PALETTE;
  const [dbStats, setDbStats]     = React.useState(null);
  const [loading, setLoading]     = React.useState(false);
  const [preflightRes, setPreflight] = React.useState(null);
  const [preflightRunning, setPreflightRunning] = React.useState(false);
  const [pipelineRes, setPipelineRes] = React.useState(null);
  const [pipelineRunning, setPipelineRunning] = React.useState(false);
  const [pipelineLoc, setPipelineLoc] = React.useState('');
  const [folderInput, setFolderInput] = React.useState(folder || '/Volumes/Team Bank 12/Sneeaker Solo');
  const [apiOnline, setApiOnline] = React.useState(null);

  // Check API health on mount
  React.useEffect(() => {
    fetch(`${API}/api/health`)
      .then(r => r.json())
      .then(d => setApiOnline(d.status === 'ok'))
      .catch(() => setApiOnline(false));
  }, []);

  // Load folder stats
  const loadStats = React.useCallback(() => {
    const f = folderInput.trim();
    if (!f) return;
    setLoading(true);
    fetch(`${API}/api/folder-status?path=${encodeURIComponent(f)}`)
      .then(r => r.json())
      .then(d => { setDbStats(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [folderInput]);

  React.useEffect(() => { if (apiOnline) loadStats(); }, [apiOnline]);

  const runPreflight = () => {
    setPreflightRunning(true);
    setPreflight(null);
    fetch(`${API}/api/preflight`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: folderInput }),
    })
      .then(r => r.json())
      .then(d => { setPreflight(d); setPreflightRunning(false); })
      .catch(e => { setPreflight({ error: String(e) }); setPreflightRunning(false); });
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
  const kpis = [
    { val: s.total_videos  ?? '—', label: 'Total Videos',   accent: false },
    { val: s.paired        ?? '—', label: 'JSON Paired',     accent: true  },
    { val: s.unpaired      ?? '—', label: 'Needs Stage 8',   warn: (s.unpaired > 0) },
    { val: s.loc_confirmed ?? '—', label: 'Loc Confirmed',   success: true },
    { val: s.unknown_loc   ?? '—', label: 'Loc Unknown',     warn: (s.unknown_loc > 0) },
    { val: s.proxy_deleted ?? '—', label: 'Proxy Cleaned',   muted: true },
  ];

  const cardColor = (k) => {
    if (k.accent)   return P.accent;
    if (k.success)  return P.success;
    if (k.warn && k.val > 0) return P.warning;
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
        <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace', marginBottom: 6, letterSpacing: '0.06em' }}>
          SOURCE FOLDER
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            value={folderInput}
            onChange={e => setFolderInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && loadStats()}
            style={{ flex: 1, border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
              fontSize: 12, fontFamily: 'Space Mono, monospace', color: P.text,
              background: P.bg, outline: 'none' }}
            placeholder="/Volumes/Team Bank 12/Sneeaker Solo"
          />
          <Btn onClick={loadStats} disabled={loading}>
            {loading ? '…' : '↺ Refresh'}
          </Btn>
        </div>
      </div>

      {/* API offline warning */}
      {apiOnline === false && (
        <div style={{ background: P.error + '15', border: `1px solid ${P.error}44`,
          borderRadius: 8, padding: '10px 14px', fontSize: 12,
          color: P.error, fontFamily: '-apple-system, sans-serif' }}>
          ✗ API server offline — start it with: <code style={{ fontFamily: 'Space Mono, monospace', fontSize: 11 }}>python3 /Users/miniman/SACC/api.py</code>
        </div>
      )}

      {/* KPI cards */}
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

      {/* Errors / warnings from validator */}
      {dbStats?.errors?.length > 0 && (
        <div style={{ background: P.error + '10', border: `1px solid ${P.error}33`,
          borderRadius: 8, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 10, color: P.error, fontFamily: 'Space Mono, monospace', marginBottom: 2 }}>
            ERRORS ({dbStats.errors.length})
          </div>
          {dbStats.errors.slice(0, 5).map((e, i) => (
            <div key={i} style={{ fontSize: 11, color: P.error, fontFamily: '-apple-system, sans-serif' }}>✗ {e}</div>
          ))}
        </div>
      )}
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

      {/* Pre-flight dedup scan */}
      <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '14px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif' }}>
              Pre-Flight Duplicate Scan
            </div>
            <div style={{ fontSize: 11, color: P.muted, fontFamily: '-apple-system, sans-serif', marginTop: 2 }}>
              Checks for exact-match duplicate video files before batch processing
            </div>
          </div>
          <Btn onClick={runPreflight} disabled={preflightRunning || !apiOnline}>
            {preflightRunning ? '⟳ Scanning…' : '⊕ Run Pre-Flight'}
          </Btn>
        </div>
        {preflightRes && (
          preflightRes.error
            ? <div style={{ fontSize: 11, color: P.error }}>{preflightRes.error}</div>
            : preflightRes.clean
              ? <div style={{ fontSize: 12, color: P.success, fontFamily: '-apple-system, sans-serif' }}>
                  ✓ Pre-flight clear — no duplicate footage detected. Safe to start batch.
                </div>
              : <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ fontSize: 12, color: P.warning, fontWeight: 600, fontFamily: '-apple-system, sans-serif' }}>
                    ⚠ {preflightRes.duplicate_groups} duplicate group(s) found — review before processing
                  </div>
                  {preflightRes.duplicates?.map((g, i) => (
                    <div key={i} style={{ background: P.warning + '15', borderRadius: 6, padding: '8px 10px' }}>
                      <div style={{ fontSize: 10, color: P.warning, fontFamily: 'Space Mono, monospace' }}>
                        {g.size_mb} MB — exact match
                      </div>
                      {g.files.map(f => (
                        <div key={f} style={{ fontSize: 11, color: P.text, fontFamily: 'Space Mono, monospace', marginTop: 2 }}>· {f}</div>
                      ))}
                    </div>
                  ))}
                </div>
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
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input
              value={pipelineLoc}
              onChange={e => setPipelineLoc(e.target.value)}
              placeholder="Location override (e.g. PDM) — optional"
              style={{ flex: 1, border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
                fontSize: 12, fontFamily: 'Space Mono, monospace', color: P.text,
                background: P.bg, outline: 'none' }}
            />
          </div>
          <Btn primary onClick={runPipeline} disabled={pipelineRunning || !apiOnline}
            style={{ background: '#34c759', fontSize: 13, padding: '8px 20px' }}>
            {pipelineRunning ? '⟳ Pipeline Running…' : '▶  Start Batch Pipeline'}
          </Btn>

          {pipelineRes && (
            <div style={{ marginTop: 12 }}>
              {pipelineRes.error
                ? <div style={{ fontSize: 11, color: P.error }}>{pipelineRes.error}</div>
                : <div>
                    <div style={{ fontSize: 12, color: pipelineRes.ok ? P.success : P.error,
                      fontWeight: 600, fontFamily: '-apple-system, sans-serif', marginBottom: 8 }}>
                      {pipelineRes.ok ? '✓ Pipeline completed' : '✗ Pipeline failed (see log)'}
                    </div>
                    {pipelineRes.stdout && (
                      <div style={{ background: '#0d0d0f', borderRadius: 6, padding: 10, maxHeight: 180, overflowY: 'auto' }}>
                        <pre style={{ fontSize: 10, fontFamily: 'Space Mono, monospace', color: '#7ae',
                          margin: 0, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                          {pipelineRes.stdout}
                        </pre>
                      </div>
                    )}
                  </div>
              }
            </div>
          )}
        </div>
      )}
    </div>
  );
}

window.DashboardView = DashboardView;

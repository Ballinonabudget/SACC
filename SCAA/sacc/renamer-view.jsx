// SACC — Renamer View
// Migrated from Streamlit Tab 5 (Vibe Renamer) + Tab 6 (FCP Pipeline)
// Features: NLP location resolver, identifier input, green Run Batch Renamer,
//           FCP filename preview, live rename log, SACC JSON database table

const _API = 'http://localhost:5174';

function RenamerView({ mode, accent, folder }) {
  const P = SACC_PALETTE;
  const [folderInput, setFolderInput] = React.useState(folder || '/Volumes/Team Bank 12/Sneeaker Solo');
  const [locInput, setLocInput]       = React.useState('');
  const [locResult, setLocResult]     = React.useState(null);
  const [identifier, setIdentifier]   = React.useState('');
  const [dryRun, setDryRun]           = React.useState(true);
  const [renaming, setRenaming]       = React.useState(false);
  const [renameRes, setRenameRes]     = React.useState(null);
  const [dbRecords, setDbRecords]     = React.useState([]);
  const [dbLoading, setDbLoading]     = React.useState(false);
  const [locSearch, setLocSearch]     = React.useState('');
  const [locations, setLocations]     = React.useState([]);
  const [applyingLoc, setApplyingLoc] = React.useState(false);
  const [applyRes, setApplyRes]       = React.useState(null);
  const [activeTab, setActiveTab]     = React.useState('rename'); // 'rename' | 'database'
  const nlpTimer = React.useRef(null);

  // Load locations list once
  React.useEffect(() => {
    fetch(`${_API}/api/locations`)
      .then(r => r.json())
      .then(d => setLocations(d.locations || []))
      .catch(() => {});
  }, []);

  // NLP debounce: resolve location as user types
  React.useEffect(() => {
    clearTimeout(nlpTimer.current);
    if (!locInput.trim()) { setLocResult(null); return; }
    nlpTimer.current = setTimeout(() => {
      fetch(`${_API}/api/resolve-location`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: locInput }),
      })
        .then(r => r.json())
        .then(d => setLocResult(d))
        .catch(() => {});
    }, 300);
  }, [locInput]);

  // Load JSON database for folder
  const loadDb = React.useCallback(() => {
    setDbLoading(true);
    fetch(`${_API}/api/json-db?path=${encodeURIComponent(folderInput)}`)
      .then(r => r.json())
      .then(d => { setDbRecords(d.records || []); setDbLoading(false); })
      .catch(() => setDbLoading(false));
  }, [folderInput]);

  React.useEffect(() => { if (activeTab === 'database') loadDb(); }, [activeTab, folderInput]);

  const runRename = () => {
    const code = locResult?.code || locInput.trim().toUpperCase();
    setRenaming(true);
    setRenameRes(null);
    fetch(`${_API}/api/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: folderInput,
        loc: code,
        identifier: identifier,
        dry_run: dryRun,
      }),
    })
      .then(r => r.json())
      .then(d => { setRenameRes(d); setRenaming(false); })
      .catch(e => { setRenameRes({ error: String(e) }); setRenaming(false); });
  };

  const applyLocation = () => {
    const code = locResult?.code || locInput.trim().toUpperCase();
    if (!code) return;
    setApplyingLoc(true);
    fetch(`${_API}/api/apply-location`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: folderInput, loc_code: code }),
    })
      .then(r => r.json())
      .then(d => { setApplyRes(d); setApplyingLoc(false); if (activeTab === 'database') loadDb(); })
      .catch(e => { setApplyRes({ error: String(e) }); setApplyingLoc(false); });
  };

  // FCP preview filename
  const fcpPreview = React.useMemo(() => {
    const code = locResult?.code || '';
    const loc  = locations.find(l => l.code === code);
    const custom = loc ? loc.header : 'UNKNOWN';
    const today = new Date().toISOString().slice(0,10).replace(/-/g,'');
    const id    = (identifier || 'OriginalName').replace(/\s+/g, '-');
    return `${custom}_${today}_iPhone15ProMax_${id}.mov`;
  }, [locResult, locations, identifier]);

  // Filtered locations for dropdown
  const filteredLocs = React.useMemo(() => {
    if (!locSearch) return locations;
    const q = locSearch.toLowerCase();
    return locations.filter(l =>
      l.name.toLowerCase().includes(q) ||
      l.code.toLowerCase().includes(q) ||
      l.region.toLowerCase().includes(q)
    );
  }, [locations, locSearch]);

  const locConfColor = (r) => {
    const src  = r.loc_source || '';
    const conf = (r.Location_Confidence || '').toLowerCase();
    if (src === 'manual') return P.success;
    if (conf === 'high')  return P.success;
    if (conf === 'medium') return P.warning;
    if (conf === 'low')   return '#ff6b35';
    return P.muted;
  };

  return (
    <div style={{ flex: 1, overflowY: 'auto', background: P.bg, padding: 20,
      display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif' }}>
            Vibe Renamer + FCP Pipeline
          </div>
          <div style={{ fontSize: 11, color: P.muted, fontFamily: 'Space Mono, monospace', marginTop: 2 }}>
            NLP location · FCP-compliant filenames · Live rename log · JSON database
          </div>
        </div>
        {/* Tab switcher */}
        <div style={{ display: 'flex', background: P.border, borderRadius: 8, padding: 2, gap: 2 }}>
          {[['rename','Renamer'],['database','Database']].map(([id, label]) => (
            <div key={id} onClick={() => setActiveTab(id)}
              style={{ padding: '5px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
                fontWeight: 600, fontFamily: '-apple-system, sans-serif',
                background: activeTab === id ? P.panel : 'transparent',
                color: activeTab === id ? P.text : P.muted,
                boxShadow: activeTab === id ? '0 1px 4px rgba(0,0,0,0.08)' : 'none',
                transition: 'all 0.15s' }}>
              {label}
            </div>
          ))}
        </div>
      </div>

      {/* Folder */}
      <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '12px 14px' }}>
        <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace', marginBottom: 6, letterSpacing: '0.06em' }}>
          TARGET FOLDER
        </div>
        <input
          value={folderInput}
          onChange={e => setFolderInput(e.target.value)}
          style={{ width: '100%', border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
            fontSize: 12, fontFamily: 'Space Mono, monospace', color: P.text,
            background: P.bg, outline: 'none', boxSizing: 'border-box' }}
          placeholder="/Volumes/Team Bank 12/Sneeaker Solo"
        />
      </div>

      {/* ── RENAMER TAB ─────────────────────────────────────────────────────── */}
      {activeTab === 'rename' && (
        <>
          {/* Location + Identifier row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>

            {/* Location NLP */}
            <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace', marginBottom: 6, letterSpacing: '0.06em' }}>
                SEARCH LOCATION  <span style={{ color: P.accent }}>NLP</span>
              </div>
              <input
                value={locInput}
                onChange={e => setLocInput(e.target.value)}
                style={{ width: '100%', border: `1px solid ${locResult?.code ? P.success : P.border}`,
                  borderRadius: 6, padding: '6px 10px', fontSize: 12,
                  fontFamily: '-apple-system, sans-serif', color: P.text,
                  background: P.bg, outline: 'none', boxSizing: 'border-box',
                  transition: 'border-color 0.2s' }}
                placeholder="e.g. paddock mall, PDM, vineland…"
              />
              {locResult && (
                <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                  {locResult.code
                    ? <>
                        <div style={{ width: 6, height: 6, borderRadius: '50%', background: P.success }} />
                        <span style={{ fontSize: 11, fontWeight: 700, color: P.success, fontFamily: 'Space Mono, monospace' }}>
                          {locResult.code}
                        </span>
                        <span style={{ fontSize: 11, color: P.text, fontFamily: '-apple-system, sans-serif' }}>
                          {locResult.name}
                        </span>
                        <Tag style={{ marginLeft: 'auto' }}>{locResult.confidence}</Tag>
                      </>
                    : <span style={{ fontSize: 11, color: P.error, fontFamily: '-apple-system, sans-serif' }}>
                        No match — try a code (PDM) or full name
                      </span>
                  }
                </div>
              )}

              {/* Location dropdown */}
              {locations.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace', marginBottom: 4, letterSpacing: '0.06em' }}>
                    OR BROWSE ALL LOCATIONS
                  </div>
                  <input
                    value={locSearch}
                    onChange={e => setLocSearch(e.target.value)}
                    style={{ width: '100%', border: `1px solid ${P.border}`, borderRadius: 6,
                      padding: '5px 8px', fontSize: 11, fontFamily: '-apple-system, sans-serif',
                      color: P.text, background: P.bg, outline: 'none', boxSizing: 'border-box', marginBottom: 4 }}
                    placeholder="Filter locations…"
                  />
                  <div style={{ maxHeight: 120, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 1 }}>
                    {filteredLocs.slice(0, 20).map(l => (
                      <div key={l.code}
                        onClick={() => { setLocInput(l.name); setLocResult({ code: l.code, name: l.name, confidence: 'manual' }); }}
                        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px',
                          borderRadius: 4, cursor: 'pointer', fontSize: 11,
                          background: locResult?.code === l.code ? P.accentLight : 'transparent',
                          color: locResult?.code === l.code ? P.accent : P.text,
                          fontFamily: '-apple-system, sans-serif' }}>
                        <span style={{ fontFamily: 'Space Mono, monospace', fontSize: 10, color: P.muted, minWidth: 48 }}>
                          {l.code}
                        </span>
                        {l.name}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Identifier */}
            <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace', marginBottom: 6, letterSpacing: '0.06em' }}>
                IDENTIFIER  <span style={{ color: P.muted }}>(optional for FCP mode)</span>
              </div>
              <input
                value={identifier}
                onChange={e => setIdentifier(e.target.value)}
                style={{ width: '100%', border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
                  fontSize: 12, fontFamily: '-apple-system, sans-serif', color: P.text,
                  background: P.bg, outline: 'none', boxSizing: 'border-box' }}
                placeholder="e.g. Air-Jordan-1-Chicago"
              />
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace', marginBottom: 6, letterSpacing: '0.06em' }}>
                  FCP FILENAME PREVIEW
                </div>
                <div style={{ background: '#0d0d0f', borderRadius: 6, padding: '8px 10px',
                  fontSize: 10, fontFamily: 'Space Mono, monospace', color: '#7ae',
                  wordBreak: 'break-all', lineHeight: 1.6 }}>
                  {fcpPreview}
                </div>
              </div>
              <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
                  fontSize: 11, fontFamily: '-apple-system, sans-serif', color: P.text }}>
                  <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)}
                    style={{ accentColor: P.accent }} />
                  Dry run (preview only, no changes)
                </label>
              </div>
            </div>
          </div>

          {/* Run Batch Renamer — green button */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button onClick={runRename} disabled={renaming}
              style={{ flex: 1, padding: '12px 20px', borderRadius: 8, border: 'none',
                cursor: renaming ? 'not-allowed' : 'pointer', fontSize: 14, fontWeight: 700,
                fontFamily: '-apple-system, sans-serif', color: '#fff',
                background: renaming ? '#999' : '#34c759',
                boxShadow: renaming ? 'none' : '0 4px 14px rgba(52,199,89,0.35)',
                transition: 'all 0.2s', letterSpacing: '-0.2px' }}>
              {renaming ? '⟳  Renaming…' : '▶  Run Batch Renamer'}
            </button>
            {dryRun && (
              <Tag color={P.warning} style={{ fontSize: 10, padding: '4px 10px' }}>DRY RUN</Tag>
            )}
          </div>

          {/* Rename results */}
          {renameRes && (
            <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '14px 16px' }}>
              {renameRes.error
                ? <div style={{ fontSize: 12, color: P.error }}>✗ {renameRes.error}</div>
                : <>
                    <div style={{ fontSize: 13, fontWeight: 600, color: P.success,
                      fontFamily: '-apple-system, sans-serif', marginBottom: 10 }}>
                      ✓ {dryRun ? 'Dry run complete' : `Renamed ${renameRes.processed} files`}
                      {renameRes.elapsed_s && ` in ${renameRes.elapsed_s}s`}
                      {renameRes.mode && <span style={{ marginLeft: 8, fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace' }}>[{renameRes.mode}]</span>}
                    </div>
                    <div style={{ maxHeight: 200, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {renameRes.results?.map((r, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0',
                          borderBottom: `1px solid ${P.border}` }}>
                          <span style={{ fontSize: 10, fontFamily: 'Space Mono, monospace', color: P.muted, minWidth: 24 }}>
                            {i + 1}
                          </span>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace', textDecoration: 'line-through' }}>
                              {r.original}
                            </div>
                            <div style={{ fontSize: 11, color: P.text, fontFamily: 'Space Mono, monospace', fontWeight: 600 }}>
                              → {r.new}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
              }
            </div>
          )}
        </>
      )}

      {/* ── DATABASE TAB ──────────────────────────────────────────────────── */}
      {activeTab === 'database' && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 12, color: P.muted, fontFamily: '-apple-system, sans-serif' }}>
              {dbLoading ? 'Loading…' : `${dbRecords.length} records in JSON database`}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {locResult?.code && (
                <Btn onClick={applyLocation} disabled={applyingLoc}
                  style={{ background: P.accent, color: '#fff', fontSize: 11 }}>
                  {applyingLoc ? '…' : `Apply ${locResult.code} → UNKNOWN records`}
                </Btn>
              )}
              <Btn onClick={loadDb} disabled={dbLoading}>↺ Refresh</Btn>
            </div>
          </div>

          {applyRes && (
            <div style={{ fontSize: 12, padding: '8px 12px', borderRadius: 6,
              background: applyRes.error ? P.error + '15' : P.success + '15',
              color: applyRes.error ? P.error : P.success, fontFamily: '-apple-system, sans-serif' }}>
              {applyRes.error ? `✗ ${applyRes.error}` : `✓ Updated ${applyRes.updated} records → ${applyRes.loc_code}`}
            </div>
          )}

          {/* Database table */}
          <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, overflow: 'hidden' }}>
            {/* Table header */}
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1.2fr 1fr 1.2fr 80px',
              gap: 0, background: P.bg, borderBottom: `1px solid ${P.border}`,
              padding: '8px 14px', fontSize: 9, fontFamily: 'Space Mono, monospace',
              color: P.muted, letterSpacing: '0.06em' }}>
              {['FCP FILENAME','MODEL','SKU','LOCATION','PROXY'].map(h => (
                <div key={h}>{h}</div>
              ))}
            </div>
            {/* Rows */}
            <div style={{ maxHeight: 340, overflowY: 'auto' }}>
              {dbRecords.length === 0
                ? <div style={{ padding: '20px', textAlign: 'center', color: P.muted, fontSize: 12, fontFamily: '-apple-system, sans-serif' }}>
                    No JSON records found — run Stage 8 first
                  </div>
                : dbRecords.map((r, i) => {
                    const code  = r.loc_code_confirmed || '';
                    const conf  = (r.Location_Confidence || '').toLowerCase();
                    const src   = r.loc_source || '';
                    const dot   = src === 'manual' ? P.success : conf === 'high' ? P.success : conf === 'medium' ? P.warning : conf === 'low' ? '#ff6b35' : P.muted;
                    const origStem = (r.original_file || r._stem || '').replace(/\.[^.]+$/, '');
                    const today = (r.analysed_at || '').slice(0,10).replace(/-/g,'');
                    const locEntry = locations.find(l => l.code === code);
                    const custom = locEntry ? locEntry.header : (code ? `${code}-LOC` : 'UNKNOWN');
                    const fcp = `${custom}_${today || '______'}_${origStem || '?'}`;

                    return (
                      <div key={i} style={{ display: 'grid',
                        gridTemplateColumns: '2fr 1.2fr 1fr 1.2fr 80px',
                        padding: '9px 14px', borderBottom: `1px solid ${P.border}`,
                        background: i % 2 === 0 ? 'transparent' : P.bg + '80',
                        alignItems: 'center' }}>
                        <div style={{ fontSize: 10, fontFamily: 'Space Mono, monospace', color: P.text,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {fcp}
                        </div>
                        <div style={{ fontSize: 11, color: P.text, fontFamily: '-apple-system, sans-serif',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {r.Model || '—'}
                        </div>
                        <div style={{ fontSize: 10, fontFamily: 'Space Mono, monospace', color: P.textSub }}>
                          {r.SKU || '—'}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                          <div style={{ width: 6, height: 6, borderRadius: '50%', background: dot, flexShrink: 0 }} />
                          <span style={{ fontSize: 10, fontFamily: 'Space Mono, monospace', color: dot }}>
                            {code || 'UNKNOWN'}
                          </span>
                        </div>
                        <div style={{ fontSize: 10, color: r.proxy_deleted ? P.success : P.muted,
                          fontFamily: 'Space Mono, monospace' }}>
                          {r.proxy_deleted ? '✓' : '—'}
                        </div>
                      </div>
                    );
                  })
              }
            </div>
          </div>
        </>
      )}
    </div>
  );
}

window.RenamerView = RenamerView;

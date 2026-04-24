// SACC — Verify View
// Migrated from Streamlit Tab 3 (Whitelist Verification) + Tab 4 (Architect's Review)
// Features: whitelist coverage metrics, missing models, metadata patcher, problem record queue

const _VAPI = 'http://localhost:5174';

function VerifyView({ mode, accent, folder }) {
  const P = SACC_PALETTE;
  const [folderInput, setFolderInput] = React.useState(folder || '/Volumes/Team Bank 12/Sneeaker Solo');
  const [whitelistPath, setWhitelistPath] = React.useState('/Users/miniman/SACC/whitelist.json');
  const [activeTab, setActiveTab] = React.useState('whitelist'); // 'whitelist' | 'architect'
  const [whitelist, setWhitelist]  = React.useState([]);
  const [dbRecords, setDbRecords]  = React.useState([]);
  const [loading, setLoading]      = React.useState(false);
  const [viewMode, setViewMode]    = React.useState('All');
  const [modelFilter, setModelFilter] = React.useState('All');
  const [patchTarget, setPatchTarget] = React.useState(null);
  const [patchData, setPatchData]  = React.useState({ colorway: '', release_year: '', retail_price: '' });
  const [patching, setPatching]    = React.useState(false);
  const [patchRes, setPatchRes]    = React.useState(null);

  const loadAll = React.useCallback(() => {
    setLoading(true);
    Promise.all([
      fetch(`${_VAPI}/api/whitelist?path=${encodeURIComponent(whitelistPath)}`).then(r => r.json()),
      fetch(`${_VAPI}/api/json-db?path=${encodeURIComponent(folderInput)}`).then(r => r.json()),
    ])
      .then(([wl, db]) => {
        setWhitelist(wl.records || []);
        setDbRecords(db.records || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [whitelistPath, folderInput]);

  React.useEffect(() => { loadAll(); }, []);

  // ── Whitelist analysis ────────────────────────────────────────────────────
  const dbSkus = React.useMemo(() =>
    new Set(dbRecords.map(r => (r.SKU || '').toUpperCase()).filter(Boolean)),
    [dbRecords]
  );

  const wlAnnotated = React.useMemo(() =>
    whitelist.map(w => ({
      ...w,
      _found: dbSkus.has((w.style_code || w.sku || '').toUpperCase()),
    })),
    [whitelist, dbSkus]
  );

  const foundCount   = wlAnnotated.filter(w => w._found).length;
  const missingCount = wlAnnotated.filter(w => !w._found).length;
  const coverage     = whitelist.length ? Math.round(foundCount / whitelist.length * 100) : 0;

  const wlFiltered = React.useMemo(() => {
    let rows = wlAnnotated;
    if (viewMode === 'Found')   rows = rows.filter(w => w._found);
    if (viewMode === 'Missing') rows = rows.filter(w => !w._found);
    const models = [...new Set(rows.map(w => w.model_name || w.silhouette || '').filter(Boolean))];
    if (modelFilter !== 'All')  rows = rows.filter(w => (w.model_name || w.silhouette) === modelFilter);
    return { rows, models };
  }, [wlAnnotated, viewMode, modelFilter]);

  // ── Architect Review ──────────────────────────────────────────────────────
  const problems = React.useMemo(() =>
    dbRecords.filter(r => {
      const issues = [];
      if (!r.SKU)   issues.push('No SKU');
      if (!r.Model) issues.push('No Model');
      if (!r.Size)  issues.push('No Size');
      if (!r.loc_code_confirmed) issues.push('No Location');
      r._issues = issues;
      return issues.length > 0;
    }),
    [dbRecords]
  );

  const applyPatch = () => {
    if (!patchTarget) return;
    setPatching(true);
    const body = {
      path: folderInput,
      stem: patchTarget._stem,
      ...Object.fromEntries(Object.entries(patchData).filter(([, v]) => v.trim())),
    };
    fetch(`${_VAPI}/api/json-db`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(d => {
        setPatchRes(d);
        setPatching(false);
        if (d.ok) { setPatchTarget(null); loadAll(); }
      })
      .catch(e => { setPatchRes({ error: String(e) }); setPatching(false); });
  };

  const allModels = ['All', ...[...new Set(wlAnnotated.map(w => w.model_name || w.silhouette || '').filter(Boolean))]];

  return (
    <div style={{ flex: 1, overflowY: 'auto', background: P.bg, padding: 20,
      display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif' }}>
            Verification + Architect Review
          </div>
          <div style={{ fontSize: 11, color: P.muted, fontFamily: 'Space Mono, monospace', marginTop: 2 }}>
            Whitelist coverage · Missing models · Metadata patcher
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, background: P.border, borderRadius: 8, padding: 2 }}>
          {[['whitelist','Whitelist'],['architect','Architect Review']].map(([id,label]) => (
            <div key={id} onClick={() => setActiveTab(id)}
              style={{ padding: '5px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
                fontWeight: 600, fontFamily: '-apple-system, sans-serif',
                background: activeTab === id ? P.panel : 'transparent',
                color: activeTab === id ? P.text : P.muted,
                transition: 'all 0.15s' }}>
              {label}
              {id === 'architect' && problems.length > 0 && (
                <span style={{ marginLeft: 5, background: P.warning + '33', color: P.warning,
                  borderRadius: 10, padding: '0 5px', fontSize: 10 }}>
                  {problems.length}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Folder / whitelist paths */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        {[
          ['SOURCE FOLDER', folderInput, setFolderInput, '/Volumes/Team Bank 12/Sneeaker Solo'],
          ['WHITELIST PATH', whitelistPath, setWhitelistPath, '/Users/miniman/SACC/whitelist.json'],
        ].map(([label, val, setter, ph]) => (
          <div key={label} style={{ background: P.panel, border: `1px solid ${P.border}`,
            borderRadius: 8, padding: '10px 12px' }}>
            <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace',
              marginBottom: 4, letterSpacing: '0.06em' }}>{label}</div>
            <input value={val} onChange={e => setter(e.target.value)} placeholder={ph}
              style={{ width: '100%', border: `1px solid ${P.border}`, borderRadius: 5,
                padding: '5px 8px', fontSize: 11, fontFamily: 'Space Mono, monospace',
                color: P.text, background: P.bg, outline: 'none', boxSizing: 'border-box' }} />
          </div>
        ))}
      </div>
      <Btn onClick={loadAll} disabled={loading} style={{ alignSelf: 'flex-start' }}>
        {loading ? '⟳ Loading…' : '↺ Reload Data'}
      </Btn>

      {/* ── WHITELIST TAB ──────────────────────────────────────────────────── */}
      {activeTab === 'whitelist' && (
        <>
          {/* Coverage KPIs */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
            {[
              { val: whitelist.length, label: 'Whitelist Total', color: P.text },
              { val: `${coverage}%`,   label: 'Coverage',        color: coverage >= 80 ? P.success : P.warning },
              { val: foundCount,       label: 'Found in DB',     color: P.success },
              { val: missingCount,     label: 'Still Missing',   color: missingCount > 0 ? P.error : P.success },
            ].map((k, i) => (
              <div key={i} style={{ background: P.panel, border: `1px solid ${P.border}`,
                borderRadius: 10, padding: '14px 16px' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: k.color,
                  fontFamily: '-apple-system, sans-serif', lineHeight: 1 }}>{k.val}</div>
                <div style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace', marginTop: 4 }}>
                  {k.label}
                </div>
              </div>
            ))}
          </div>

          {/* Progress bar */}
          <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, padding: '12px 14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: P.text, fontFamily: '-apple-system, sans-serif' }}>
                Collection coverage
              </span>
              <span style={{ fontSize: 11, fontFamily: 'Space Mono, monospace', color: coverage >= 80 ? P.success : P.warning }}>
                {coverage}%
              </span>
            </div>
            <div style={{ height: 8, background: P.border, borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ width: `${coverage}%`, height: '100%',
                background: coverage >= 80 ? P.success : P.warning, borderRadius: 4,
                transition: 'width 0.4s' }} />
            </div>
          </div>

          {/* Filters */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <SmartFilter label="SHOW" options={['All', 'Found', 'Missing']}
              value={viewMode} onChange={setViewMode} />
            <SmartFilter label="MODEL" options={allModels}
              value={modelFilter} onChange={setModelFilter} />
            <span style={{ marginLeft: 'auto', fontSize: 11, color: P.muted,
              fontFamily: '-apple-system, sans-serif' }}>
              {wlFiltered.rows.length} records
            </span>
          </div>

          {/* Whitelist table */}
          <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1.2fr 1fr 80px 80px',
              padding: '8px 14px', background: P.bg, borderBottom: `1px solid ${P.border}`,
              fontSize: 9, fontFamily: 'Space Mono, monospace', color: P.muted, letterSpacing: '0.06em' }}>
              {['MODEL','SKU','COLORWAY','RELEASE','PRICE','STATUS'].map(h => <div key={h}>{h}</div>)}
            </div>
            <div style={{ maxHeight: 320, overflowY: 'auto' }}>
              {wlFiltered.rows.length === 0
                ? <div style={{ padding: 20, textAlign: 'center', color: P.muted,
                    fontSize: 12, fontFamily: '-apple-system, sans-serif' }}>
                    No whitelist data — check the path above
                  </div>
                : wlFiltered.rows.map((w, i) => (
                    <div key={i} style={{ display: 'grid',
                      gridTemplateColumns: '1.5fr 1fr 1.2fr 1fr 80px 80px',
                      padding: '8px 14px', alignItems: 'center',
                      borderBottom: `1px solid ${P.border}`,
                      background: i % 2 === 0 ? 'transparent' : P.bg + '80' }}>
                      <div style={{ fontSize: 11, color: P.text, fontFamily: '-apple-system, sans-serif',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {w.model_name || w.silhouette || '—'}
                      </div>
                      <div style={{ fontSize: 10, fontFamily: 'Space Mono, monospace', color: P.textSub }}>
                        {w.style_code || w.sku || '—'}
                      </div>
                      <div style={{ fontSize: 11, color: P.text, overflow: 'hidden',
                        textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: '-apple-system, sans-serif' }}>
                        {w.colorway_name || w.colorway || '—'}
                      </div>
                      <div style={{ fontSize: 11, color: P.muted, fontFamily: '-apple-system, sans-serif' }}>
                        {w.release_date || w.release_year || '—'}
                      </div>
                      <div style={{ fontSize: 11, color: P.text, fontFamily: '-apple-system, sans-serif' }}>
                        {w.retail_price ? `$${w.retail_price}` : '—'}
                      </div>
                      <div>
                        <Tag color={w._found ? P.success : P.error} dot>
                          {w._found ? 'Found' : 'Missing'}
                        </Tag>
                      </div>
                    </div>
                  ))
              }
            </div>
          </div>
        </>
      )}

      {/* ── ARCHITECT REVIEW TAB ──────────────────────────────────────────── */}
      {activeTab === 'architect' && (
        <>
          {problems.length === 0
            ? <div style={{ background: P.success + '15', border: `1px solid ${P.success}44`,
                borderRadius: 10, padding: '20px', textAlign: 'center' }}>
                <div style={{ fontSize: 24, marginBottom: 6 }}>🎉</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: P.success, fontFamily: '-apple-system, sans-serif' }}>
                  All records passed metadata validation
                </div>
              </div>
            : <>
                <div style={{ fontSize: 12, color: P.warning, fontFamily: '-apple-system, sans-serif', fontWeight: 600 }}>
                  ⚠ {problems.length} record(s) require manual verification
                </div>

                {/* Problem list */}
                <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10, overflow: 'hidden' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1.5fr',
                    padding: '8px 14px', background: P.bg, borderBottom: `1px solid ${P.border}`,
                    fontSize: 9, fontFamily: 'Space Mono, monospace', color: P.muted, letterSpacing: '0.06em' }}>
                    {['JSON FILE','MODEL','SKU','ISSUES'].map(h => <div key={h}>{h}</div>)}
                  </div>
                  <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                    {problems.map((r, i) => (
                      <div key={i}
                        onClick={() => { setPatchTarget(r); setPatchData({ colorway:'', release_year:'', retail_price:'' }); setPatchRes(null); }}
                        style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1.5fr',
                          padding: '9px 14px', borderBottom: `1px solid ${P.border}`,
                          cursor: 'pointer', alignItems: 'center',
                          background: patchTarget?._stem === r._stem
                            ? P.accentLight : i % 2 === 0 ? 'transparent' : P.bg + '80' }}>
                        <div style={{ fontSize: 10, fontFamily: 'Space Mono, monospace', color: P.text,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {r._stem || r.original_file || '—'}
                        </div>
                        <div style={{ fontSize: 11, color: P.text, fontFamily: '-apple-system, sans-serif',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {r.Model || '—'}
                        </div>
                        <div style={{ fontSize: 10, fontFamily: 'Space Mono, monospace', color: P.textSub }}>
                          {r.SKU || '—'}
                        </div>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {(r._issues || []).map(iss => (
                            <Tag key={iss} color={P.warning} style={{ fontSize: 9 }}>{iss}</Tag>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Metadata patcher */}
                {patchTarget && (
                  <div style={{ background: P.panel, border: `1px solid ${P.accent}44`,
                    borderRadius: 10, padding: '14px 16px' }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: P.text,
                      fontFamily: '-apple-system, sans-serif', marginBottom: 4 }}>
                      Metadata Patcher
                    </div>
                    <div style={{ fontSize: 11, color: P.muted, fontFamily: 'Space Mono, monospace',
                      marginBottom: 12 }}>
                      {patchTarget._stem || patchTarget.original_file}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 12 }}>
                      {[
                        ['colorway',      'Colorway',     'e.g. Chicago'],
                        ['release_year',  'Release Year', 'e.g. 2015'],
                        ['retail_price',  'Retail Price', 'e.g. 180'],
                      ].map(([field, label, ph]) => (
                        <div key={field}>
                          <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace',
                            marginBottom: 4, letterSpacing: '0.06em' }}>{label.toUpperCase()}</div>
                          <input
                            value={patchData[field]}
                            onChange={e => setPatchData(d => ({ ...d, [field]: e.target.value }))}
                            placeholder={ph}
                            style={{ width: '100%', border: `1px solid ${P.border}`, borderRadius: 6,
                              padding: '6px 10px', fontSize: 12, fontFamily: '-apple-system, sans-serif',
                              color: P.text, background: P.bg, outline: 'none', boxSizing: 'border-box' }} />
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <Btn primary onClick={applyPatch} disabled={patching}>
                        {patching ? '⟳ Saving…' : '✓ Patch & Save JSON'}
                      </Btn>
                      <Btn ghost onClick={() => setPatchTarget(null)}>Cancel</Btn>
                    </div>
                    {patchRes && (
                      <div style={{ marginTop: 8, fontSize: 12,
                        color: patchRes.error ? P.error : P.success,
                        fontFamily: '-apple-system, sans-serif' }}>
                        {patchRes.error ? `✗ ${patchRes.error}` : `✓ Patched successfully`}
                      </div>
                    )}
                  </div>
                )}
              </>
          }
        </>
      )}
    </div>
  );
}

window.VerifyView = VerifyView;

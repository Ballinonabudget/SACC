// SACC — Search & Index View (v3.0)
// [Custom Name] now resolved by AI visual/audio analysis — GPS rescinded.
// New fields: loc_source, loc_confidence, loc_visual, loc_audio
// Exports: SearchView

function SearchView({ sneakers, whitelist, locations, mode, accent, onSelectSneaker }) {
  const P = SACC_PALETTE;

  const [query,       setQuery]       = React.useState('');
  const [scope,       setScope]       = React.useState('archive');
  const [statusFilter,setStatusFilter]= React.useState('All');
  const [locFilter,   setLocFilter]   = React.useState('All');
  const [locSrcFilter,setLocSrcFilter]= React.useState('All'); // All | manual | ai_confirmed | unknown
  const [sortBy,      setSortBy]      = React.useState('release');
  const [sortDir,     setSortDir]     = React.useState('desc');
  const [selected,    setSelected]    = React.useState(null);
  const inputRef = React.useRef(null);

  React.useEffect(() => { setTimeout(() => inputRef.current?.focus(), 80); }, []);

  // ── Location confidence helpers ───────────────────────────────────────────────
  const LOC_CONF_COLOR = {
    manual:       '#34c759',  // green — operator confirmed
    ai_high:      '#34c759',  // green — AI high confidence
    ai_medium:    '#f5a623',  // amber — AI medium
    ai_low:       '#ff6b35',  // orange — AI low
    unknown:      '#8e8e93',  // grey  — unresolved
  };

  const locConfKey = (s) => {
    if (s.loc_source === 'manual')        return 'manual';
    if (s.loc_source === 'unknown')       return 'unknown';
    if (s.loc_confidence === 'high')      return 'ai_high';
    if (s.loc_confidence === 'medium')    return 'ai_medium';
    if (s.loc_confidence === 'low')       return 'ai_low';
    return 'unknown';
  };

  const locConfLabel = (s) => {
    const k = locConfKey(s);
    return { manual:'manual', ai_high:'AI ✓ high', ai_medium:'AI ~ med', ai_low:'AI ? low', unknown:'UNKNOWN' }[k];
  };

  const locConfDot = (s) => (
    <span style={{
      width: 6, height: 6, borderRadius: '50%', flexShrink: 0, display: 'inline-block',
      background: LOC_CONF_COLOR[locConfKey(s)],
      boxShadow: locConfKey(s) === 'unknown' ? 'none' : `0 0 4px ${LOC_CONF_COLOR[locConfKey(s)]}80`
    }} />
  );

  // ── FCP filename builder (mirrors fcp_namer.buildSACCFilename) ────────────────
  const getFCPFilename = (s) => {
    const loc        = locations[s.loc];
    const customName = (loc && s.loc_source !== 'unknown') ? `${s.loc}-${loc.type}` : 'UNKNOWN';
    const date       = (s.release || '').replace(/-/g, '');
    const cam        = (s.camModel || 'Cam').replace(/\s+/g, '');
    return `${customName}_${date}_${cam}_${s.origFile}${s.ext}`;
  };

  // ── Metadata completeness ─────────────────────────────────────────────────────
  const metaStatus = (s) => {
    const issues = [];
    if (!s.sku)                         issues.push('SKU');
    if (!s.colorway)                    issues.push('Colorway');
    if (!s.release)                     issues.push('Date');
    if (!s.retail)                      issues.push('Price');
    if (s.loc_source === 'unknown' || !s.loc) issues.push('Location');
    if (!issues.length) return { label: 'Complete', dot: P.success };
    if (issues.length <= 2) return { label: `Missing: ${issues.join(', ')}`, dot: P.warning };
    return { label: `Incomplete (${issues.length})`, dot: P.error };
  };

  // ── Derived data ──────────────────────────────────────────────────────────────
  const allLocs = ['All', ...Object.keys(locations)];

  const archiveResults = React.useMemo(() => {
    if (scope === 'whitelist') return [];
    const q = query.toLowerCase().trim();
    let rows = sneakers.filter(s => {
      if (!q) return true;
      return (
        s.name.toLowerCase().includes(q)          ||
        s.sku.toLowerCase().includes(q)            ||
        s.colorway.toLowerCase().includes(q)       ||
        s.silhouette.toLowerCase().includes(q)     ||
        s.loc.toLowerCase().includes(q)            ||
        (s.loc_visual  || '').toLowerCase().includes(q) ||
        (s.loc_audio   || '').toLowerCase().includes(q) ||
        (s.tags || []).join(' ').toLowerCase().includes(q) ||
        s.release.includes(q)
      );
    });
    if (statusFilter !== 'All') rows = rows.filter(s => s.status === statusFilter);
    if (locFilter    !== 'All') rows = rows.filter(s => s.loc    === locFilter);
    if (locSrcFilter !== 'All') rows = rows.filter(s => s.loc_source === locSrcFilter);

    rows.sort((a, b) => {
      let av, bv;
      if      (sortBy === 'release') { av = a.release; bv = b.release; }
      else if (sortBy === 'price')   { av = a.retail;  bv = b.retail; return sortDir === 'desc' ? bv - av : av - bv; }
      else if (sortBy === 'name')    { av = a.name;    bv = b.name; }
      else if (sortBy === 'status')  { av = a.status;  bv = b.status; }
      else { av = a.ts; bv = b.ts; }
      const cmp = String(av).localeCompare(String(bv));
      return sortDir === 'desc' ? -cmp : cmp;
    });
    return rows;
  }, [query, scope, statusFilter, locFilter, locSrcFilter, sortBy, sortDir, sneakers]);

  const whitelistResults = React.useMemo(() => {
    if (scope === 'archive') return [];
    const q = query.toLowerCase().trim();
    return Object.entries(whitelist).filter(([sku, w]) => {
      if (!q) return true;
      return (
        sku.toLowerCase().includes(q)                ||
        w.colorway_name.toLowerCase().includes(q)    ||
        w.silhouette.toLowerCase().includes(q)       ||
        String(w.retail_price).includes(q)           ||
        String(w.release_date).includes(q)
      );
    }).map(([sku, w]) => ({ sku, ...w }));
  }, [query, scope, whitelist]);

  const totalResults = archiveResults.length + whitelistResults.length;

  // ── CSV export ────────────────────────────────────────────────────────────────
  const exportCSV = () => {
    const headers = ['name','sku','colorway','release','retail','loc','loc_source',
                     'loc_confidence','loc_visual','loc_audio','status','camModel','filename'];
    const rows = archiveResults.map(s => {
      const vals = [s.name, s.sku, s.colorway, s.release, s.retail, s.loc,
                    s.loc_source, s.loc_confidence, s.loc_visual, s.loc_audio,
                    s.status, s.camModel, getFCPFilename(s)];
      return vals.map(v => `"${String(v ?? '').replace(/"/g,'""')}"`).join(',');
    });
    const csv = [headers.join(','), ...rows].join('\n');
    const a   = document.createElement('a');
    a.href    = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `sacc_search_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
  };

  // ── Chip styles ───────────────────────────────────────────────────────────────
  const chipStyle = (active) => ({
    padding: '3px 10px', borderRadius: 4, fontSize: 11, fontWeight: active ? 700 : 500,
    fontFamily: '-apple-system, sans-serif',
    border: `1px solid ${active ? P.accent : P.border}`,
    background: active ? P.accentLight : 'transparent',
    color: active ? P.accent : P.muted,
    cursor: 'pointer', transition: 'all 0.12s', whiteSpace: 'nowrap',
  });

  const sortBtn = (key, label) => (
    <span key={key} onClick={() => {
        if (sortBy === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
        else { setSortBy(key); setSortDir('desc'); }
      }} style={chipStyle(sortBy === key)}>
      {label}{sortBy === key ? (sortDir === 'desc' ? ' ↓' : ' ↑') : ''}
    </span>
  );

  const statusDot = (status) => {
    const c = { synced: P.success, pending: P.warning, error: P.error }[status] || P.muted;
    return <span style={{ width:6, height:6, borderRadius:'50%', background:c, display:'inline-block', marginRight:5 }} />;
  };

  const QUICK = ['Chicago','Bred','Mocha','Royal','Shadow','Travis','University Blue','Shattered'];

  // ── Location summary stats ────────────────────────────────────────────────────
  const locStats = React.useMemo(() => {
    const all = scope === 'whitelist' ? [] : sneakers;
    return {
      manual:       all.filter(s => s.loc_source === 'manual').length,
      ai_confirmed: all.filter(s => s.loc_source === 'ai_confirmed').length,
      unknown:      all.filter(s => s.loc_source === 'unknown' || !s.loc_source).length,
    };
  }, [sneakers, scope]);

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', background:P.bg, overflow:'hidden' }}>

      {/* ── Search bar ── */}
      <div style={{ padding:'12px 16px', background:P.panel,
        borderBottom:`1px solid ${P.border}`, flexShrink:0 }}>

        {/* Input row */}
        <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:8 }}>
          <div style={{ flex:1, position:'relative' }}>
            <span style={{ position:'absolute', left:10, top:'50%', transform:'translateY(-50%)',
              fontSize:14, color:P.muted, pointerEvents:'none' }}>⌕</span>
            <input ref={inputRef} value={query} onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Escape' && setQuery('')}
              placeholder="Search name, SKU, colorway, location, signage text, audio…"
              style={{ width:'100%', border:`1px solid ${P.border}`, borderRadius:7,
                padding:'8px 12px 8px 32px', fontSize:13,
                fontFamily:'-apple-system, sans-serif', color:P.text,
                background:P.bg, outline:'none' }}
              autoComplete="off" />
          </div>
          {query && (
            <span onClick={() => setQuery('')}
              style={{ fontSize:11, color:P.muted, cursor:'pointer', padding:'0 4px',
                fontFamily:'-apple-system, sans-serif' }}>✕</span>
          )}
          <button onClick={exportCSV}
            style={{ padding:'6px 12px', fontSize:11, fontWeight:600, borderRadius:6,
              border:`1px solid ${P.border}`, background:P.panel, color:P.textSub,
              cursor:'pointer', fontFamily:'-apple-system, sans-serif', whiteSpace:'nowrap' }}>
            ⬇ CSV
          </button>
        </div>

        {/* Filter row */}
        <div style={{ display:'flex', gap:6, alignItems:'center', flexWrap:'wrap' }}>
          <span style={{ fontSize:10, color:P.muted, fontFamily:'Space Mono, monospace', marginRight:2 }}>SCOPE</span>
          {[['archive','Archive'],['whitelist','Whitelist'],['both','Both']].map(([v,l]) => (
            <span key={v} onClick={() => setScope(v)} style={chipStyle(scope === v)}>{l}</span>
          ))}
          <span style={{ width:1, height:16, background:P.border, margin:'0 4px' }} />

          <span style={{ fontSize:10, color:P.muted, fontFamily:'Space Mono, monospace', marginRight:2 }}>STATUS</span>
          {['All','synced','pending','error'].map(s => (
            <span key={s} onClick={() => setStatusFilter(s)} style={chipStyle(statusFilter === s)}>
              {s !== 'All' && <span style={{ marginRight:4, fontSize:9,
                color:{synced:P.success,pending:P.warning,error:P.error}[s] }}>●</span>}
              {s}
            </span>
          ))}
          <span style={{ width:1, height:16, background:P.border, margin:'0 4px' }} />

          <span style={{ fontSize:10, color:P.muted, fontFamily:'Space Mono, monospace', marginRight:2 }}>SORT</span>
          {[['release','Date'],['price','Price'],['name','Name'],['status','Status']].map(([k,l]) => sortBtn(k,l))}
        </div>

        {/* Location source filter row */}
        <div style={{ display:'flex', gap:6, alignItems:'center', flexWrap:'wrap', marginTop:6 }}>
          <span style={{ fontSize:10, color:P.muted, fontFamily:'Space Mono, monospace', marginRight:2 }}>LOC SRC</span>
          {[
            ['All',          'All',         null],
            ['manual',       'Manual',      '#34c759'],
            ['ai_confirmed', 'AI Confirmed','#34c759'],
            ['unknown',      'Unknown',     '#8e8e93'],
          ].map(([v, l, dot]) => (
            <span key={v} onClick={() => setLocSrcFilter(v)} style={{
              ...chipStyle(locSrcFilter === v),
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              {dot && <span style={{ width:5, height:5, borderRadius:'50%',
                background: dot, display:'inline-block' }} />}
              {l}
            </span>
          ))}
          <span style={{ marginLeft:'auto', fontSize:10, color:P.muted,
            fontFamily:'Space Mono, monospace', display:'flex', gap:10 }}>
            <span style={{ color:'#34c759' }}>●{locStats.manual} manual</span>
            <span style={{ color:'#34c759' }}>◉{locStats.ai_confirmed} AI</span>
            <span style={{ color:'#8e8e93' }}>○{locStats.unknown} unknown</span>
          </span>
        </div>

        {/* Quick chips */}
        <div style={{ display:'flex', gap:5, marginTop:7, flexWrap:'wrap' }}>
          {QUICK.map(q => (
            <span key={q} onClick={() => setQuery(q)}
              style={{ padding:'2px 9px', borderRadius:20, fontSize:10, fontWeight:500,
                fontFamily:'-apple-system, sans-serif', background:P.bg,
                border:`1px solid ${P.border}`, color:P.textSub, cursor:'pointer' }}>
              {q}
            </span>
          ))}
        </div>
      </div>

      {/* ── Results count bar ── */}
      <div style={{ padding:'5px 16px', background:P.panel,
        borderBottom:`1px solid ${P.border}`, flexShrink:0,
        display:'flex', alignItems:'center', gap:12 }}>
        <span style={{ fontSize:11, color:P.muted, fontFamily:'Space Mono, monospace' }}>
          {totalResults} result{totalResults !== 1 ? 's' : ''}
          {query ? ` for "${query}"` : ''}
        </span>
        {(statusFilter !== 'All' || locFilter !== 'All' || locSrcFilter !== 'All') && (
          <span onClick={() => { setStatusFilter('All'); setLocFilter('All'); setLocSrcFilter('All'); }}
            style={{ fontSize:10, color:P.accent, cursor:'pointer',
              fontFamily:'-apple-system, sans-serif' }}>Clear filters ×</span>
        )}
        <span style={{ marginLeft:'auto', fontSize:10, color:P.muted,
          fontFamily:'Space Mono, monospace' }}>
          {archiveResults.length} archive · {whitelistResults.length} whitelist
        </span>
      </div>

      {/* ── Results ── */}
      <div style={{ flex:1, overflowY:'auto' }}>

        {/* Archive results */}
        {archiveResults.length > 0 && (
          <div>
            {scope === 'both' && (
              <div style={{ padding:'8px 16px 4px', fontSize:9, fontWeight:700,
                color:P.muted, fontFamily:'Space Mono, monospace', letterSpacing:'0.08em' }}>
                ARCHIVE — {archiveResults.length} entries
              </div>
            )}
            <table style={{ width:'100%', borderCollapse:'collapse', tableLayout:'fixed' }}>
              <colgroup>
                <col style={{ width:'27%' }} /><col style={{ width:'12%' }} />
                <col style={{ width:'13%' }} /><col style={{ width:'8%'  }} />
                <col style={{ width:'7%'  }} /><col style={{ width:'14%' }} />
                <col style={{ width:'7%'  }} /><col style={{ width:'12%' }} />
              </colgroup>
              <thead>
                <tr style={{ background:P.bg }}>
                  {['Name','SKU','Colorway','Release','Retail','Location','Status','Metadata'].map(h => (
                    <th key={h} style={{ padding:'6px 10px', fontSize:9, fontWeight:700,
                      color:P.muted, textAlign:'left', fontFamily:'Space Mono, monospace',
                      letterSpacing:'0.06em', borderBottom:`1px solid ${P.border}`,
                      borderTop:`1px solid ${P.border}` }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {archiveResults.map(s => {
                  const meta  = metaStatus(s);
                  const loc   = locations[s.loc];
                  const isSel = selected === s.id;
                  const ck    = locConfKey(s);
                  return (
                    <React.Fragment key={s.id}>
                      <tr onClick={() => { setSelected(isSel ? null : s.id); onSelectSneaker?.(s.id); }}
                        style={{ cursor:'pointer',
                          background: isSel ? P.accentLight : 'transparent',
                          borderBottom: isSel ? 'none' : `1px solid ${P.border}` }}>
                        <td style={{ padding:'7px 10px', fontSize:12,
                          color: isSel ? P.accent : P.text,
                          fontFamily:'-apple-system, sans-serif', fontWeight: isSel ? 600 : 400,
                          overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}
                          title={s.name}>{s.name}</td>
                        <td style={{ padding:'7px 10px', fontSize:11, color:P.textSub,
                          fontFamily:'Space Mono, monospace', overflow:'hidden',
                          textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{s.sku}</td>
                        <td style={{ padding:'7px 10px', fontSize:11, color:P.textSub,
                          fontFamily:'-apple-system, sans-serif', overflow:'hidden',
                          textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{s.colorway}</td>
                        <td style={{ padding:'7px 10px', fontSize:11, color:P.textSub,
                          fontFamily:'Space Mono, monospace' }}>{s.release.slice(0,7)}</td>
                        <td style={{ padding:'7px 10px', fontSize:11, color:P.textSub,
                          fontFamily:'Space Mono, monospace' }}>${s.retail}</td>

                        {/* Location — code + confidence indicator */}
                        <td style={{ padding:'7px 10px' }}>
                          <div style={{ display:'flex', alignItems:'center', gap:4 }}>
                            {locConfDot(s)}
                            <span style={{ fontSize:11, fontFamily:'Space Mono, monospace',
                              color: s.loc_source === 'unknown' ? P.muted : P.accent,
                              fontWeight: 700 }}>
                              {s.loc || 'UNK'}
                            </span>
                          </div>
                          <div style={{ fontSize:9, color: LOC_CONF_COLOR[ck],
                            fontFamily:'Space Mono, monospace', marginTop:1, lineHeight:1.2 }}>
                            {locConfLabel(s)}
                          </div>
                        </td>

                        <td style={{ padding:'7px 10px' }}>
                          {statusDot(s.status)}
                          <span style={{ fontSize:11, color:P.textSub,
                            fontFamily:'-apple-system, sans-serif' }}>{s.status}</span>
                        </td>
                        <td style={{ padding:'7px 10px' }}>
                          <span style={{ display:'inline-flex', alignItems:'center', gap:4,
                            fontSize:10, fontFamily:'-apple-system, sans-serif',
                            color: meta.dot === P.success ? '#34c759' :
                                   meta.dot === P.warning ? '#f5a623' : '#ff3b30' }}>
                            <span style={{ width:5, height:5, borderRadius:'50%',
                              background:meta.dot, display:'inline-block', flexShrink:0 }} />
                            {meta.label}
                          </span>
                        </td>
                      </tr>

                      {/* ── Expanded detail panel ── */}
                      {isSel && (() => {
                        const fn = getFCPFilename(s);
                        const wl = whitelist[s.sku];
                        return (
                          <tr key={`${s.id}-detail`}>
                            <td colSpan={8} style={{ padding:0,
                              borderBottom:`1px solid ${P.border}` }}>
                              <div style={{ margin:'0 0 0', padding:'12px 14px',
                                background:P.panel,
                                borderTop:`2px solid ${P.accent}`,
                                borderLeft:`1px solid ${P.accent}44`,
                                borderRight:`1px solid ${P.accent}44`,
                                borderBottom:`1px solid ${P.accent}44` }}>

                                <div style={{ display:'flex', gap:16, flexWrap:'wrap' }}>

                                  {/* FCP Filename */}
                                  <div style={{ flex:'2 1 260px' }}>
                                    <div style={{ fontSize:9, color:P.muted,
                                      fontFamily:'Space Mono, monospace',
                                      letterSpacing:'0.06em', marginBottom:4 }}>
                                      FCP FILENAME  [Custom Name]_[Date]_[Model]_[Original]
                                    </div>
                                    <div style={{ fontSize:11, color:P.text,
                                      fontFamily:'Space Mono, monospace',
                                      wordBreak:'break-all', lineHeight:1.6,
                                      background:P.bg, padding:'6px 9px', borderRadius:5,
                                      border:`1px solid ${P.border}` }}>
                                      {fn}
                                    </div>
                                  </div>

                                  {/* Location Detection */}
                                  <div style={{ flex:'1 1 200px',
                                    background:P.bg, borderRadius:6,
                                    border:`1px solid ${P.border}`,
                                    padding:'8px 10px' }}>
                                    <div style={{ fontSize:9, color:P.muted,
                                      fontFamily:'Space Mono, monospace',
                                      letterSpacing:'0.06em', marginBottom:6 }}>
                                      LOCATION DETECTION
                                    </div>
                                    {/* Source badge */}
                                    <div style={{ display:'flex', alignItems:'center',
                                      gap:5, marginBottom:5 }}>
                                      <span style={{
                                        padding:'2px 6px', borderRadius:3, fontSize:9,
                                        fontWeight:700, fontFamily:'Space Mono, monospace',
                                        background: s.loc_source === 'unknown'
                                          ? '#8e8e9320' : `${LOC_CONF_COLOR[locConfKey(s)]}20`,
                                        color: LOC_CONF_COLOR[locConfKey(s)],
                                      }}>
                                        {s.loc_source === 'manual'       ? '● MANUAL'       :
                                         s.loc_source === 'ai_confirmed' ? '◉ AI CONFIRMED' :
                                                                           '○ UNKNOWN'}
                                      </span>
                                      {s.loc_confidence && (
                                        <span style={{ fontSize:9, color:P.muted,
                                          fontFamily:'Space Mono, monospace' }}>
                                          conf: {s.loc_confidence}
                                        </span>
                                      )}
                                    </div>
                                    {/* Visual evidence */}
                                    {s.loc_visual && (
                                      <div style={{ marginBottom:4 }}>
                                        <span style={{ fontSize:9, color:P.muted,
                                          fontFamily:'Space Mono, monospace' }}>VISUAL </span>
                                        <span style={{ fontSize:10,
                                          color:P.text,
                                          fontFamily:'-apple-system, sans-serif' }}>
                                          {s.loc_visual}
                                        </span>
                                      </div>
                                    )}
                                    {/* Audio evidence */}
                                    {s.loc_audio && (
                                      <div>
                                        <span style={{ fontSize:9, color:P.muted,
                                          fontFamily:'Space Mono, monospace' }}>AUDIO  </span>
                                        <span style={{ fontSize:10,
                                          color:P.text, fontStyle:'italic',
                                          fontFamily:'-apple-system, sans-serif' }}>
                                          "{s.loc_audio}"
                                        </span>
                                      </div>
                                    )}
                                    {s.loc_source === 'unknown' && !s.loc_visual && (
                                      <div style={{ fontSize:10, color:P.muted,
                                        fontFamily:'-apple-system, sans-serif',
                                        fontStyle:'italic' }}>
                                        No location identified — run Stage 8 AI analysis
                                        or provide --loc override
                                      </div>
                                    )}
                                  </div>

                                  {/* Whitelist match */}
                                  {wl && (
                                    <div style={{ flex:'1 1 160px' }}>
                                      <div style={{ fontSize:9, color:P.muted,
                                        fontFamily:'Space Mono, monospace',
                                        letterSpacing:'0.06em', marginBottom:4 }}>
                                        WHITELIST MATCH
                                      </div>
                                      <div style={{ fontSize:11, color:P.success,
                                        fontFamily:'-apple-system, sans-serif', fontWeight:600 }}>
                                        ✓ {wl.silhouette}
                                      </div>
                                      <div style={{ fontSize:10, color:P.textSub,
                                        fontFamily:'-apple-system, sans-serif', marginTop:2 }}>
                                        {wl.colorway_name} · ${wl.retail_price} · {wl.release_date}
                                      </div>
                                    </div>
                                  )}

                                  {/* Tags */}
                                  <div style={{ flex:'0 0 auto' }}>
                                    <div style={{ fontSize:9, color:P.muted,
                                      fontFamily:'Space Mono, monospace',
                                      letterSpacing:'0.06em', marginBottom:4 }}>TAGS</div>
                                    <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
                                      {(s.tags || []).map(t => (
                                        <span key={t} onClick={() => setQuery(t)}
                                          style={{ padding:'2px 7px', fontSize:10,
                                            borderRadius:3, background:P.accentLight,
                                            color:P.accent,
                                            fontFamily:'-apple-system, sans-serif',
                                            cursor:'pointer' }}>
                                          {t}
                                        </span>
                                      ))}
                                    </div>
                                  </div>

                                </div>
                              </div>
                            </td>
                          </tr>
                        );
                      })()}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Whitelist results */}
        {whitelistResults.length > 0 && (
          <div style={{ marginTop: archiveResults.length > 0 ? 12 : 0 }}>
            {scope === 'both' && (
              <div style={{ padding:'8px 16px 4px', fontSize:9, fontWeight:700,
                color:P.muted, fontFamily:'Space Mono, monospace', letterSpacing:'0.08em' }}>
                MASTER WHITELIST — {whitelistResults.length} entries
              </div>
            )}
            <table style={{ width:'100%', borderCollapse:'collapse', tableLayout:'fixed' }}>
              <colgroup>
                <col style={{ width:'30%' }} /><col style={{ width:'15%' }} />
                <col style={{ width:'22%' }} /><col style={{ width:'10%' }} />
                <col style={{ width:'10%' }} /><col style={{ width:'13%' }} />
              </colgroup>
              <thead>
                <tr style={{ background:P.bg }}>
                  {['Silhouette','SKU','Colorway','Year','Retail','Target Filename'].map(h => (
                    <th key={h} style={{ padding:'6px 10px', fontSize:9, fontWeight:700,
                      color:P.muted, textAlign:'left', fontFamily:'Space Mono, monospace',
                      letterSpacing:'0.06em', borderBottom:`1px solid ${P.border}`,
                      borderTop:`1px solid ${P.border}` }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {whitelistResults.map(w => (
                  <tr key={w.sku} style={{ borderBottom:`1px solid ${P.border}` }}>
                    <td style={{ padding:'7px 10px', fontSize:12, color:P.text,
                      fontFamily:'-apple-system, sans-serif', overflow:'hidden',
                      textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{w.silhouette}</td>
                    <td style={{ padding:'7px 10px', fontSize:11, color:P.textSub,
                      fontFamily:'Space Mono, monospace' }}>{w.sku}</td>
                    <td style={{ padding:'7px 10px', fontSize:11, color:P.textSub,
                      fontFamily:'-apple-system, sans-serif', overflow:'hidden',
                      textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{w.colorway_name}</td>
                    <td style={{ padding:'7px 10px', fontSize:11, color:P.textSub,
                      fontFamily:'Space Mono, monospace' }}>{w.release_date}</td>
                    <td style={{ padding:'7px 10px', fontSize:11, color:P.textSub,
                      fontFamily:'Space Mono, monospace' }}>${w.retail_price}</td>
                    <td style={{ padding:'7px 10px', fontSize:10, color:P.textSub,
                      fontFamily:'Space Mono, monospace', overflow:'hidden',
                      textOverflow:'ellipsis', whiteSpace:'nowrap' }}
                      title={w.new_filename}>{w.new_filename}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Empty state */}
        {totalResults === 0 && (
          <div style={{ padding:'48px 24px', textAlign:'center', color:P.muted,
            fontFamily:'-apple-system, sans-serif' }}>
            <div style={{ fontSize:28, marginBottom:8 }}>⌕</div>
            <div style={{ fontSize:14, marginBottom:4 }}>No results</div>
            <div style={{ fontSize:12 }}>
              {query ? `No matches for "${query}"` : 'No entries match current filters'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

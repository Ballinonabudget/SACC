// SACC — Timeline / List View (v2.0)
// + Bulk-select · Batch export · Real LOC-TYPE filenames
// Exports: TimelineView

function TimelineView({ sneakers, selectedId, onSelect, filters, setFilters }) {
  const P = SACC_PALETTE;
  const [selected, setSelected] = React.useState(new Set()); // bulk-select ids
  const [exportOpen, setExportOpen] = React.useState(false);

  const brands   = ['All', ...new Set(sneakers.map(s => (s.brand || 'Jordan Brand') || 'Jordan Brand'))];
  const statuses = ['All', 'synced', 'pending', 'error'];
  const sorts    = ['Date ↓', 'Date ↑', 'Price ↓', 'Price ↑', 'Name A–Z'];

  const filtered = sneakers.filter(s => {
    if (filter(s.brand || 'Jordan Brand')  !== 'All' && (s.brand || 'Jordan Brand')  !== filter(s.brand || 'Jordan Brand'))  return false;
    if (filters.status !== 'All' && s.status !== filters.status) return false;
    return true;
  }).sort((a, b) => {
    switch (filters.sort) {
      case 'Date ↑':  return a.release.localeCompare(b.release);
      case 'Price ↓': return b.retail - a.retail;
      case 'Price ↑': return a.retail - b.retail;
      case 'Name A–Z': return a.name.localeCompare(b.name);
      default:        return b.release.localeCompare(a.release);
    }
  });

  const allChecked = filtered.length > 0 && filtered.every(s => selected.has(s.id));
  const toggleAll  = () => {
    if (allChecked) setSelected(new Set());
    else setSelected(new Set(filtered.map(s => s.id)));
  };
  const toggleOne  = (id) => {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  };

  const selCount   = selected.size;
  const selItems   = sneakers.filter(s => selected.has(s.id));
  const totalRetail = selItems.reduce((a, s) => a + s.retail, 0);

  // Scrubber
  const totalSecs = 24 * 60 + 15;
  const [scrubSecs, setScrubSecs] = React.useState(42);
  const tsToPct = (ts) => { const [m,s] = ts.split(':').map(Number); return ((m*60+s)/totalSecs)*100; };
  const secsToTs = (s) => `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;

  const statusColor = { synced: P.success, pending: P.warning, error: P.error };

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', background: P.bg }}>

      {/* ── Toolbar ── */}
      <div style={{ padding:'8px 14px', borderBottom:`1px solid ${P.border}`,
        background: P.panel, display:'flex', gap:8, alignItems:'center', flexWrap:'wrap' }}>
        <SmartFilter label="Brand:"  options={brands}   value={filter(s.brand || 'Jordan Brand')}  onChange={v => setFilters(f => ({...f, brand: v}))} />
        <SmartFilter label="Status:" options={statuses} value={filters.status} onChange={v => setFilters(f => ({...f, status: v}))} />
        <SmartFilter label="Sort:"   options={sorts}    value={filters.sort}   onChange={v => setFilters(f => ({...f, sort: v}))} />

        {/* Bulk action bar — appears when items selected */}
        {selCount > 0 ? (
          <div style={{ marginLeft:'auto', display:'flex', gap:8, alignItems:'center' }}>
            <div style={{ background: P.accent+'22', border:`1px solid ${P.accent}44`,
              borderRadius:6, padding:'4px 12px', fontSize:11, fontWeight:700,
              color: P.accent, fontFamily:'-apple-system, sans-serif' }}>
              {selCount} selected · ${totalRetail.toLocaleString()} retail
            </div>
            <div style={{ position:'relative' }}>
              <Btn primary small onClick={() => setExportOpen(o => !o)}>
                ↗ Batch Export ▾
              </Btn>
              {exportOpen && (
                <div style={{ position:'absolute', top:'100%', right:0, marginTop:4,
                  background: P.panel, border:`1px solid ${P.border}`, borderRadius:8,
                  boxShadow:'0 8px 24px rgba(0,0,0,0.12)', zIndex:100, minWidth:170, overflow:'hidden' }}>
                  {['Export as JSON', 'Export as CSV', 'Copy filenames', 'Mark as synced', 'Remove from archive'].map(opt => (
                    <div key={opt} onClick={() => setExportOpen(false)}
                      style={{ padding:'9px 14px', fontSize:12, cursor:'pointer',
                        color: opt.includes('Remove') ? P.error : P.text,
                        fontFamily:'-apple-system, sans-serif',
                        background:'transparent' }}>
                      {opt}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <Btn ghost small onClick={() => setSelected(new Set())}>× Clear</Btn>
          </div>
        ) : (
          <div style={{ marginLeft:'auto', display:'flex', gap:6, alignItems:'center' }}>
            <StatsWidget sneakers={sneakers} />
            <Btn primary small>⚡ Sync All</Btn>
          </div>
        )}
      </div>

      {/* ── Video Scrubber ── */}
      <div style={{ padding:'7px 14px', borderBottom:`1px solid ${P.border}`,
        background: P.panel, display:'flex', alignItems:'center', gap:10 }}>
        <div style={{ background: P.text, color:'#fff', borderRadius:5, padding:'4px 10px',
          fontFamily:'Space Mono, monospace', fontSize:12, fontWeight:700,
          cursor:'pointer', flexShrink:0 }}>
          ▶ {secsToTs(scrubSecs)}
        </div>
        <div style={{ flex:1, height:24, position:'relative', cursor:'pointer' }}
          onClick={e => {
            const rect = e.currentTarget.getBoundingClientRect();
            setScrubSecs(Math.round((e.clientX - rect.left) / rect.width * totalSecs));
          }}>
          <div style={{ position:'absolute', top:10, left:0, right:0, height:4,
            background: P.border, borderRadius:2 }}>
            <div style={{ width:`${(scrubSecs/totalSecs)*100}%`, height:'100%',
              background: P.accent, borderRadius:2 }} />
          </div>
          {sneakers.map(s => (
            <div key={s.id}
              title={`${s.name} @ ${s.ts}`}
              onClick={e => { e.stopPropagation();
                const [m,sec] = s.ts.split(':').map(Number);
                setScrubSecs(m*60+sec); onSelect(s.id); }}
              style={{ position:'absolute', top:4, left:`${tsToPct(s.ts)}%`,
                transform:'translateX(-50%)', width: s.id === selectedId ? 3 : 2,
                height: s.id === selectedId ? 16 : 14,
                background: s.id === selectedId ? P.accent : P.warning,
                borderRadius:1, zIndex:2, transition:'all 0.15s' }} />
          ))}
          <div style={{ position:'absolute', top:6, left:`${(scrubSecs/totalSecs)*100}%`,
            transform:'translateX(-50%)', width:12, height:12, borderRadius:'50%',
            background:'#fff', border:`2px solid ${P.accent}`, zIndex:3 }} />
        </div>
        <span style={{ fontSize:10, color: P.muted, fontFamily:'Space Mono, monospace', flexShrink:0 }}>
          {secsToTs(totalSecs)}
        </span>
        <span style={{ fontSize:10, color: P.muted, fontFamily:'Space Mono, monospace', flexShrink:0 }}>
          {filtered.length} entries
        </span>
      </div>

      {/* ── Table ── */}
      <div style={{ flex:1, overflowY:'auto' }}
        onClick={e => { if (!e.target.closest('tr[data-row]')) setExportOpen(false); }}>
        <table style={{ width:'100%', borderCollapse:'collapse',
          fontFamily:'-apple-system, sans-serif', fontSize:12 }}>
          <thead>
            <tr style={{ background: P.panel, borderBottom:`1px solid ${P.border}`,
              position:'sticky', top:0, zIndex:1 }}>
              {/* Select-all checkbox */}
              <th style={{ padding:'7px 0 7px 14px', width:36 }}>
                <input type="checkbox" checked={allChecked} onChange={toggleAll}
                  style={{ width:14, height:14, cursor:'pointer', accentColor: P.accent }} />
              </th>
              {['','Model','Colorway','Loc','Retail','Release','Timestamp','File','Status',''].map((h,i) => (
                <th key={i} style={{ padding:'7px 10px 7px', textAlign:'left',
                  fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace',
                  fontWeight:400, whiteSpace:'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((s, i) => {
              const isSelected = s.id === selectedId;
              const isBulk     = selected.has(s.id);
              const loc        = SACC_DATA.locations[s.loc];
              return (
                <tr key={s.id} data-row="1"
                  onClick={() => onSelect(s.id)}
                  style={{ borderBottom:`1px solid ${P.border}`, cursor:'pointer',
                    background: isBulk ? P.accentLight : isSelected ? 'oklch(96% 0.04 45)' : i%2===0 ? P.panel : P.bg,
                    outline: isSelected ? `1.5px solid ${P.accent}` : 'none',
                    transition:'background 0.1s' }}>
                  {/* Row checkbox */}
                  <td style={{ padding:'6px 0 6px 14px' }}
                    onClick={e => { e.stopPropagation(); toggleOne(s.id); }}>
                    <input type="checkbox" checked={isBulk} onChange={() => toggleOne(s.id)}
                      style={{ width:14, height:14, cursor:'pointer', accentColor: P.accent }} />
                  </td>
                  {/* Thumb */}
                  <td style={{ padding:'6px 8px' }}>
                    <SketchImg width={38} height={32} style={{ borderRadius:4 }} />
                  </td>
                  <td style={{ padding:'6px 10px', fontWeight:700, whiteSpace:'nowrap', maxWidth:180 }}>
                    {s.name}
                  </td>
                  <td style={{ padding:'6px 10px', color: P.textSub, fontSize:11, maxWidth:160,
                    overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                    {s.colorway}
                  </td>
                  {/* Location badge */}
                  <td style={{ padding:'6px 10px' }}>
                    <div title={loc?.name} style={{ display:'inline-flex', alignItems:'center', gap:4,
                      background: P.bg, border:`1px solid ${P.border}`, borderRadius:4,
                      padding:'2px 7px', fontSize:10, fontFamily:'Space Mono, monospace', cursor:'default' }}>
                      {s.loc}
                      <span style={{ fontSize:9, color: P.muted }}>{loc?.type}</span>
                    </div>
                  </td>
                  <td style={{ padding:'6px 10px', fontFamily:'Space Mono, monospace', fontWeight:700, fontSize:11 }}>
                    ${s.retail}
                  </td>
                  <td style={{ padding:'6px 10px', color: P.textSub, fontFamily:'Space Mono, monospace', fontSize:10 }}>
                    {s.release}
                  </td>
                  <td style={{ padding:'6px 10px' }}>
                    <div style={{ background: P.text, color:'#fff', borderRadius:4,
                      padding:'2px 7px', fontFamily:'Space Mono, monospace', fontSize:10,
                      display:'inline-block', cursor:'pointer' }}
                      onClick={e => { e.stopPropagation();
                        const [m,sec] = s.ts.split(':').map(Number);
                        setScrubSecs(m*60+sec); }}>
                      ⏱ {s.ts}
                    </div>
                  </td>
                  <td style={{ padding:'6px 10px', fontFamily:'Space Mono, monospace', fontSize:9,
                    color: P.muted, maxWidth:160, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                    {s.file}
                  </td>
                  <td style={{ padding:'6px 10px' }}>
                    <Tag color={s.status} dot>{s.status}</Tag>
                  </td>
                  <td style={{ padding:'6px 14px 6px 0' }}>
                    <Btn ghost small onClick={e => e.stopPropagation()}>↗</Btn>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

Object.assign(window, { TimelineView });

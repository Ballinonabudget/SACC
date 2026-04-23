// SACC — Import View (v2.0 — real backend wiring)
// renamer_logic.py · LOCATION_DATA · Master_Whitelist_v1 · run_vibe_renamer generator
// Pre-Flight Scan: ffprobe metadata layer — filters empty/low-data clips before Vortex API
// Exports: ImportView

// ── Pre-Flight Scan Panel ──────────────────────────────────────────────────────
function PreFlightPanel({ queue, onSkipToggle, skipSet }) {
  const P = SACC_PALETTE;
  const [scanning, setScanning] = React.useState(false);
  const [scanDone, setScanDone] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const [scanLog,  setScanLog]  = React.useState([]);
  const logRef = React.useRef(null);

  const flagged  = queue.filter(q => q.preflight?.verdict === 'flag');   // auto-skip: duration / zero motion only
  const reviewed = queue.filter(q => q.preflight?.verdict === 'review');  // amber: black frames, user decides
  const passed   = queue.filter(q => q.preflight?.verdict === 'pass');

  const COST_PER_MIN = 0.10;
  const totalMins   = queue.reduce((s, q) => s + (q.preflight?.durationSecs || 0) / 60, 0);
  const skippedMins = queue.filter(q => skipSet.has(q.id))
                           .reduce((s, q) => s + (q.preflight?.durationSecs || 0) / 60, 0);
  const totalCost   = (totalMins * COST_PER_MIN).toFixed(3);
  const savedCost   = (skippedMins * COST_PER_MIN).toFixed(3);
  const netCost     = ((totalMins - skippedMins) * COST_PER_MIN).toFixed(3);

  // verdict → color/label: flag=red auto-skip, review=amber user-decides, pass=green clear
  const verdictColor = { pass: P.success, review: P.warning, flag: P.error };
  const verdictLabel = { pass: '✓ PASS', review: '● REVIEW', flag: '⚠ SKIP' };

  const runScan = () => {
    if (scanning) return;
    setScanning(true); setScanDone(false); setProgress(0); setScanLog([]);
    const autoFlagCost = (flagged.reduce((s,q)=>s+(q.preflight?.durationSecs||0),0)/60*COST_PER_MIN).toFixed(3);
    const lines = [
      '> [preflight] init — ffprobe v6.1 ready',
      `> criteria: duration · motion score · black frames (audio/size exempt)`,
      `> scanning ${queue.length} files in import queue…`,
      ...queue.flatMap((q, i) => {
        const pf = q.preflight || {};
        const verdict = pf.verdict;
        const statusLine = verdict === 'flag'
          ? `>   ⚠ AUTO-SKIP — ${(pf.flagReasons||[]).join(' | ')}`
          : verdict === 'review'
          ? `>   ● REVIEW — ${(pf.reviewReasons||[]).join(' | ')}`
          : `>   ✓ PASS — cleared for Vortex API`;
        return [
          `> [${i+1}/${queue.length}] ${q.origFile}`,
          `>   size=${q.size} · duration=${pf.durationSecs ?? '?'}s · motion=${pf.motionScore ?? 0}/100 · black=${pf.blackFramePct ?? 0}%`,
          statusLine,
        ];
      }),
      `> scan complete — ${passed.length} pass · ${reviewed.length} review · ${flagged.length} auto-skip`,
      `> Vortex cost (full queue): $${totalCost}`,
      flagged.length > 0 ? `> auto-skip applied to ${flagged.length} clip(s) — saves $${autoFlagCost} per run` : `> no hard flags — all clips eligible`,
      reviewed.length > 0 ? `> ${reviewed.length} clip(s) queued for manual review — not skipped automatically` : '',
    ].filter(Boolean);
    let i = 0;
    const step = () => {
      if (i < lines.length) {
        setScanLog(prev => [...prev, lines[i++]]);
        setProgress(Math.round((i / lines.length) * 100));
        if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
        setTimeout(step, 110);
      } else {
        setScanning(false); setScanDone(true);
        // Auto-skip ONLY hard-flagged clips (duration/motion) — review clips stay accessible
        flagged.forEach(q => { if (!skipSet.has(q.id)) onSkipToggle(q.id); });
      }
    };
    setTimeout(step, 80);
  };

  return (
    <div style={{ background: P.panel, borderRadius:10, border:`1px solid ${P.border}`, overflow:'hidden', marginBottom:12 }}>
      {/* Header */}
      <div style={{ padding:'9px 14px', borderBottom:`1px solid ${P.border}`,
        background: scanDone ? (flagged.length > 0 ? P.error+'0a' : P.success+'0a') : P.bg,
        display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:13, fontWeight:700, color: P.text, fontFamily:'-apple-system, sans-serif' }}>⚡ Pre-Flight Scan</span>
          {scanDone && (
            <div style={{ display:'flex', gap:5 }}>
              {flagged.length > 0 && (
                <Tag style={{ background:P.error+'22', color:P.error }}>{flagged.length} skip</Tag>
              )}
              {reviewed.length > 0 && (
                <Tag style={{ background:P.warning+'22', color:P.warning }}>{reviewed.length} review</Tag>
              )}
              {flagged.length === 0 && reviewed.length === 0 && (
                <Tag style={{ background:P.success+'22', color:P.success }}>all clear</Tag>
              )}
            </div>
          )}
        </div>
        <div style={{ display:'flex', gap:8, alignItems:'center' }}>
          {scanDone && parseFloat(savedCost) > 0 && (
            <div style={{ fontSize:10, color:P.success, fontFamily:'Space Mono, monospace',
              background:P.success+'11', border:`1px solid ${P.success}33`, borderRadius:4, padding:'3px 8px' }}>
              saving ${savedCost} / run
            </div>
          )}
          <Btn primary small onClick={runScan} disabled={scanning}>
            {scanning ? '⏳ Scanning…' : scanDone ? '↺ Re-scan' : '▶ Run Scan'}
          </Btn>
        </div>
      </div>

      {/* Progress bar */}
      {(scanning || scanDone) && (
        <div style={{ height:3, background:P.border }}>
          <div style={{ width:`${progress}%`, height:'100%', transition:'width 0.1s',
            background: scanning ? P.warning : (flagged.length>0 ? P.error : P.success) }} />
        </div>
      )}

      {/* Results table */}
      {scanDone && (
        <div style={{ overflowX:'auto' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontFamily:'-apple-system, sans-serif', fontSize:11 }}>
            <thead>
              <tr style={{ borderBottom:`1px solid ${P.border}` }}>
                {['Skip','File','Size','Duration','Motion','Black%','Audio','Verdict'].map(h => (
                  <th key={h} style={{ padding:'5px 10px', textAlign:'left', fontSize:9,
                    color:P.muted, fontFamily:'Space Mono, monospace', fontWeight:400, whiteSpace:'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {queue.map(q => {
                const pf = q.preflight || {};
                const isFlagged = pf.verdict === 'flag';
                const isSkipped = skipSet.has(q.id);
                return (
                  <tr key={q.id} style={{ borderBottom:`1px solid ${P.border}`,
                    background: isSkipped ? P.error+'08' : isFlagged ? P.error+'04' : 'transparent',
                    opacity: isSkipped ? 0.6 : 1 }}>
                    <td style={{ padding:'6px 10px' }}>
                      <input type="checkbox" checked={isSkipped} onChange={() => onSkipToggle(q.id)}
                        style={{ accentColor:P.error, cursor:'pointer' }} />
                    </td>
                    <td style={{ padding:'6px 10px', fontFamily:'Space Mono, monospace', fontSize:9,
                      color:P.textSub, maxWidth:150, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                      {q.origFile}
                    </td>
                    <td style={{ padding:'6px 10px', fontFamily:'Space Mono, monospace', fontSize:9, color:P.text }}>
                      {q.size}
                    </td>
                    <td style={{ padding:'6px 10px' }}>
                      <span style={{ fontFamily:'Space Mono, monospace', fontSize:9,
                        color:(pf.durationSecs||0)<3 ? P.error : P.text }}>
                        {pf.durationSecs ?? '?'}s
                      </span>
                    </td>
                    <td style={{ padding:'6px 10px' }}>
                      <div style={{ display:'flex', alignItems:'center', gap:5 }}>
                        <div style={{ width:38, height:4, background:P.border, borderRadius:3 }}>
                          <div style={{ width:`${pf.motionScore||0}%`, height:'100%', borderRadius:3,
                            background:(pf.motionScore||0)<20?P.error:(pf.motionScore||0)<50?P.warning:P.success }} />
                        </div>
                        <span style={{ fontSize:9, fontFamily:'Space Mono, monospace', color:P.muted }}>
                          {pf.motionScore??0}
                        </span>
                      </div>
                    </td>
                    <td style={{ padding:'6px 10px' }}>
                      <span style={{ fontFamily:'Space Mono, monospace', fontSize:9,
                        color:(pf.blackFramePct||0)>50?P.error:P.muted }}>
                        {pf.blackFramePct??0}%
                      </span>
                    </td>
                    <td style={{ padding:'6px 10px' }}>
                      <span style={{ fontSize:11, color:pf.hasAudio?P.success:P.error }}>
                        {pf.hasAudio ? '♪' : '✕'}
                      </span>
                    </td>
                    <td style={{ padding:'6px 10px 6px 6px' }}>
                      <Tag style={{ background:(verdictColor[pf.verdict]||P.muted)+'22',
                        color:verdictColor[pf.verdict]||P.muted }}>
                        {verdictLabel[pf.verdict]||'—'}
                      </Tag>
                      {pf.flagReasons && pf.flagReasons.length > 0 && (
                        <div style={{ fontSize:8, color:P.error, marginTop:2,
                          fontFamily:'Space Mono, monospace', lineHeight:1.6 }}>
                          {pf.flagReasons.map((r,i)=><div key={i}>{r}</div>)}
                        </div>
                      )}
                      {pf.reviewReasons && pf.reviewReasons.length > 0 && (
                        <div style={{ fontSize:8, color:P.warning, marginTop:2,
                          fontFamily:'Space Mono, monospace', lineHeight:1.6 }}>
                          {pf.reviewReasons.map((r,i)=><div key={i}>↳ {r}</div>)}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {/* Cost summary bar */}
          <div style={{ padding:'7px 14px', borderTop:`1px solid ${P.border}`,
            display:'flex', gap:16, alignItems:'center', background:P.bg,
            fontSize:10, fontFamily:'Space Mono, monospace', flexWrap:'wrap' }}>
            <span style={{ color:P.muted }}>FULL QUEUE: <strong style={{ color:P.text }}>${totalCost}</strong></span>
            <span style={{ color:P.muted }}>SKIPPED: <strong style={{ color:P.error }}>${savedCost}</strong></span>
            <span style={{ color:P.muted }}>NET VORTEX: <strong style={{ color:P.success }}>${netCost}</strong></span>
            <span style={{ marginLeft:'auto', color:P.muted }}>{queue.length-skipSet.size} of {queue.length} clips → API</span>
          </div>
        </div>
      )}

      {/* Scan terminal log */}
      {(scanning || scanDone) && (
        <div ref={logRef} style={{ maxHeight:88, overflowY:'auto', background:'#0d0d0f', padding:'7px 12px', fontFamily:'Space Mono, monospace' }}>
          {scanLog.map((line,i) => (
            <div key={i} style={{ fontSize:8.5, lineHeight:1.8,
              color: line.includes('FLAGGED')||line.includes('⚠') ? '#ff6b6b'
                : line.includes('PASS')||line.includes('✓') ? '#7ae'
                : line.includes('saving')||line.includes('complete') ? '#c9a84c'
                : '#7a9' }}>
              {line}
            </div>
          ))}
          {scanning && <div style={{ fontSize:8.5, color:'#555' }}>█</div>}
        </div>
      )}

      {!scanDone && !scanning && (
        <div style={{ padding:'10px 14px', fontSize:11, color:P.muted,
          fontFamily:'-apple-system, sans-serif', lineHeight:1.7 }}>
          Runs <strong style={{ color:P.text }}>ffprobe</strong> on each clip before Vortex API submission.
          {' '}<span style={{ color:P.error }}>Auto-skip</span>: duration &lt; 3s or zero motion.
          {' '}<span style={{ color:P.warning }}>Review</span>: high black-frame ratio — partial footage stays accessible, not auto-omitted.
          {' '}Audio absence and file size are <strong style={{ color:P.text }}>not flagging criteria</strong> (legacy footage &amp; B-roll exempt).
        </div>
      )}
    </div>
  );
}

// ── Import View ───────────────────────────────────────────────────────────────
function ImportView({ queue, log, mode }) {
  const P = SACC_PALETTE;
  const [dragOver, setDragOver]   = React.useState(false);
  const [selectedQ, setSelectedQ] = React.useState('q1');
  const [streaming, setStreaming] = React.useState(false);
  const [streamLog, setStreamLog] = React.useState(log);
  const [skuInput, setSkuInput]   = React.useState('');
  const [skuResult, setSkuResult] = React.useState(null);
  const [skuErr, setSkuErr]       = React.useState(false);
  const [skipSet,  setSkipSet]    = React.useState(new Set());
  const logRef = React.useRef(null);

  const onSkipToggle = (id) => setSkipSet(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const item      = queue.find(q => q.id === selectedQ);
  const locations = SACC_DATA.locations;
  const typeLabels = SACC_DATA.typeLabels;
  const whitelist  = SACC_DATA.whitelist;

  // Editable fields for selected queue item
  const [locCode,     setLocCode]     = React.useState(item?.suggestedLoc || 'FLM');
  const [identifier,  setIdentifier]  = React.useState('');

  // Update fields when queue selection changes
  React.useEffect(() => {
    const q = queue.find(x => x.id === selectedQ);
    setLocCode(q?.suggestedLoc || 'FLM');
    setIdentifier('');
    setSkuInput('');
    setSkuResult(null);
    setSkuErr(false);
  }, [selectedQ]);

  // Auto-fill identifier from whitelist match
  React.useEffect(() => {
    if (item?.sku && whitelist[item.sku]) {
      const w = whitelist[item.sku];
      setIdentifier(`${w.silhouette.replace(/\s+/g,'-')} ${w.colorway_name}`.trim());
    }
  }, [selectedQ]);

  const locObj  = locations[locCode] || {};
  const dateStr = item?.creationTime
    ? item.creationTime.slice(2,10).replace(/-/g,'')  // YYMMDD
    : new Date().toISOString().slice(2,10).replace(/-/g,'');
  const camModel  = item?.camModel || 'Cam';
  const origFile  = item?.origFile || '';
  const ext       = origFile.includes('.mov') ? '.mov' : '.mp4';

  const identClean  = identifier.trim().replace(/\s+/g, '-');
  const generatedName = locCode && locObj.type && identifier && origFile
    ? `${locCode}-${locObj.type}_${dateStr}_${identClean}_${camModel}_${origFile}`
    : null;

  // SKU whitelist lookup
  const lookupSku = () => {
    const key = skuInput.trim().toUpperCase();
    if (whitelist[key]) {
      const w = whitelist[key];
      setSkuResult(w);
      setSkuErr(false);
      setIdentifier(`${w.silhouette.replace(/\s+/g,'-')} ${w.colorway_name}`);
    } else {
      setSkuResult(null);
      setSkuErr(true);
    }
  };

  // Simulate run_vibe_renamer generator yield stream
  const runScript = () => {
    if (streaming) return;
    setStreaming(true);
    const lines = [
      `> [renamer_logic.py] run_vibe_renamer() — starting batch…`,
      `> folder: /Volumes/SneakerDrive/Footage/2025/`,
      `> loc_header: ${locCode}-${locObj.type || 'MALL'}`,
      `> scanning queue: ${queue.length} files`,
      `> ffprobe q3: creation_time fallback → ${dateStr} ✓`,
      `> ffprobe q4: creation_time fallback → ${dateStr} ✓`,
      `> yield {current:2, total:4, done:false}`,
      `> Vortex API: q3 → no high-confidence match`,
      `> regex: no existing SACC prefix on q3 — clean`,
      generatedName
        ? `> renamed q2 → ${generatedName} ✓`
        : `> awaiting identifier input for q2…`,
      `> yield {current:3, total:4, done:false}`,
      `> renamed q3 → ${locCode}-${locObj.type || 'MALL'}_${dateStr}_Unknown_${camModel}_unknown_footage.mov ⚠ (no match)`,
      `> yield {done:true, processed_count:3, elapsed_seconds:4.21}`,
      `> batch complete ✓`,
    ];
    let i = 0;
    const iv = setInterval(() => {
      if (i < lines.length) {
        setStreamLog(prev => [...prev, lines[i++]]);
        if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
      } else {
        clearInterval(iv);
        setStreaming(false);
      }
    }, 280);
  };

  React.useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [streamLog]);

  const statusColor = { done: P.success, processing: P.warning, queued: P.muted, error: P.error };
  const whitelistMatch = item?.sku ? whitelist[item.sku] : null;

  // Group locations by region for the dropdown
  const locGroups = Object.entries(locations).reduce((acc, [code, loc]) => {
    if (!acc[loc.region]) acc[loc.region] = [];
    acc[loc.region].push([code, loc]);
    return acc;
  }, {});

  return (
    <div style={{ display:'flex', height:'100%', background: P.bg }}>

      {/* ── Col 1: Queue ──────────────────────────────────────────── */}
      <div style={{ width:254, borderRight:`1px solid ${P.border}`, background: P.panel,
        display:'flex', flexDirection:'column' }}>

        <div style={{ padding:'10px 14px', borderBottom:`1px solid ${P.border}`,
          display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          <span style={{ fontSize:13, fontWeight:700, color: P.text,
            fontFamily:'-apple-system, sans-serif' }}>↓ Import Queue</span>
          <div style={{ display:'flex', gap:5 }}>
            <Btn small ghost style={{ fontSize:10 }}>📁 Folder Path</Btn>
            <Btn small primary>+ Add</Btn>
          </div>
        </div>

        {/* Path field — v2.0 objective: replace drag-drop with path input */}
        <div style={{ padding:'6px 10px', borderBottom:`1px solid ${P.border}`, background: P.bg }}>
          <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:3 }}>
            DRIVE PATH
          </div>
          <div style={{ display:'flex', gap:6, alignItems:'center' }}>
            <input readOnly value="/Volumes/SneakerDrive/Footage/2025/"
              style={{ flex:1, border:`1px solid ${P.border}`, borderRadius:4, padding:'4px 6px',
                fontSize:9, fontFamily:'Space Mono, monospace', color: P.textSub,
                background: P.panel, outline:'none', overflow:'hidden', textOverflow:'ellipsis' }} />
            <Btn small ghost style={{ fontSize:9, padding:'3px 7px' }}>Browse</Btn>
          </div>
        </div>

        {/* Drop zone */}
        <div onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => { e.preventDefault(); setDragOver(false); }}
          style={{ margin:'8px 10px 4px', border:`2px dashed ${dragOver ? P.accent : P.border}`,
            borderRadius:8, padding:'12px', textAlign:'center',
            background: dragOver ? P.accentLight : P.bg, transition:'all 0.15s', cursor:'pointer' }}>
          <div style={{ fontSize:16, marginBottom:2, opacity:0.3 }}>⊕</div>
          <div style={{ fontSize:10, color: P.muted, fontFamily:'-apple-system, sans-serif', lineHeight:1.5 }}>
            Drop <strong>.mov</strong> / <strong>.mp4</strong> or paste path above
          </div>
        </div>

        {/* Queue items */}
        <div style={{ flex:1, overflowY:'auto', padding:'0 10px 8px' }}>
          {queue.map(q => {
            const wl = q.sku ? whitelist[q.sku] : null;
            return (
              <div key={q.id} onClick={() => setSelectedQ(q.id)}
                style={{ borderRadius:8, padding:'9px 10px', marginBottom:6, cursor:'pointer',
                  border:`1.5px solid ${selectedQ === q.id ? P.accent : P.border}`,
                  background: selectedQ === q.id ? P.accentLight : P.bg, transition:'all 0.12s' }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3 }}>
                  <span style={{ fontSize:9, fontWeight:700, color: P.text,
                    fontFamily:'Space Mono, monospace', maxWidth:145,
                    overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                    {q.origFile}
                  </span>
                  <Tag color={q.status} dot>{q.status}</Tag>
                </div>
                <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace' }}>
                  {q.size}
                  {q.camModel && <span style={{ color: P.textSub }}> · {q.camModel}</span>}
                </div>
                {wl && (
                  <div style={{ marginTop:3, fontSize:10, color: P.accent,
                    fontFamily:'-apple-system, sans-serif', fontWeight:600, lineHeight:1.3 }}>
                    ✦ {wl.colorway_name}
                  </div>
                )}
                {q.status === 'processing' && (
                  <div style={{ marginTop:5, height:3, background: P.border, borderRadius:2 }}>
                    <div style={{ width:`${q.progress}%`, height:'100%',
                      background: P.warning, borderRadius:2 }} />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ padding:'10px', borderTop:`1px solid ${P.border}` }}>
          {skipSet.size > 0 && (
            <div style={{ fontSize:9, color:P.muted, fontFamily:'Space Mono, monospace',
              textAlign:'center', marginBottom:5 }}>
              {skipSet.size} clip{skipSet.size>1?'s':''} skipped by Pre-Flight
            </div>
          )}
          <Btn primary onClick={runScript} disabled={streaming} style={{ width:'100%' }}>
            {streaming ? '⚡ Running…' : `⚡ run_vibe_renamer() (${queue.length - skipSet.size} clips)`}
          </Btn>
        </div>
      </div>

      {/* ── Col 2: Rename Builder ──────────────────────────────────── */}
      <div style={{ flex:1, display:'flex', flexDirection:'column', overflowY:'auto' }}>

        <div style={{ padding:'10px 16px', borderBottom:`1px solid ${P.border}`,
          background: P.panel, display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          <div style={{ display:'flex', gap:10, alignItems:'center' }}>
            <span style={{ fontSize:13, fontWeight:700, color: P.text,
              fontFamily:'-apple-system, sans-serif' }}>Rename Builder</span>
            <Tag dot style={{ color: P.success, background: P.success + '22' }}>Vortex connected</Tag>
          </div>
          {mode === 'pro' && (
            <Tag style={{ background: P.accent + '22', color: P.accent }}>AI Auto-tag</Tag>
          )}
        </div>

        <div style={{ flex:1, padding:'14px 16px', display:'flex', flexDirection:'column', gap:12 }}>

          {/* Pre-Flight Scan — runs before Vortex API submission */}
          <PreFlightPanel queue={queue} onSkipToggle={onSkipToggle} skipSet={skipSet} />

          {/* Whitelist match card */}
          {whitelistMatch && (
            <div style={{ background: P.panel, borderRadius:10, border:`1px solid ${P.border}`, overflow:'hidden' }}>
              <div style={{ padding:'8px 12px', background: P.success + '0f',
                borderBottom:`1px solid ${P.success}22`,
                display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <span style={{ fontSize:10, color: P.success, fontFamily:'Space Mono, monospace', fontWeight:700 }}>
                  ✓ WHITELIST MATCH · {item?.sku}
                </span>
                <Tag style={{ background: P.success + '22', color: P.success }}>WHITELIST</Tag>
              </div>
              <div style={{ padding:12, display:'flex', gap:12 }}>
                <SketchImg width={96} height={96} label="sneaker photo" style={{ borderRadius:6, flexShrink:0 }} />
                <div style={{ flex:1, display:'flex', flexDirection:'column', gap:5 }}>
                  <div style={{ fontSize:13, fontWeight:700, color: P.text,
                    fontFamily:'-apple-system, sans-serif', lineHeight:1.3 }}>
                    {whitelistMatch.silhouette}
                  </div>
                  <div style={{ fontSize:12, color: P.textSub, fontFamily:'-apple-system, sans-serif' }}>
                    {whitelistMatch.colorway_name}
                  </div>
                  {[['SKU', whitelistMatch.style_code], ['Retail', `$${whitelistMatch.retail_price}`],
                    ['Release', whitelistMatch.release_date],
                    ['New filename', whitelistMatch.new_filename]].map(([k,v]) => (
                    <div key={k} style={{ display:'flex', justifyContent:'space-between', gap:8 }}>
                      <span style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', flexShrink:0 }}>{k}</span>
                      <span style={{ fontSize:10, fontWeight:600, color: P.text,
                        fontFamily: k==='New filename' ? 'Space Mono, monospace' : '-apple-system, sans-serif',
                        textAlign:'right', wordBreak:'break-all', lineHeight:1.3 }}>{v}</span>
                    </div>
                  ))}
                  {whitelistMatch.notes && (
                    <div style={{ fontSize:10, color: P.muted, fontStyle:'italic',
                      fontFamily:'-apple-system, sans-serif' }}>{whitelistMatch.notes}</div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* SKU lookup (for unmatched items) */}
          {!whitelistMatch && (
            <div style={{ background: P.panel, borderRadius:8, border:`1px solid ${P.border}`, padding:12 }}>
              <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:8 }}>
                SKU LOOKUP — Master_Whitelist_v1 ({Object.keys(whitelist).length} entries)
              </div>
              <div style={{ display:'flex', gap:8 }}>
                <input value={skuInput} onChange={e => { setSkuInput(e.target.value); setSkuErr(false); }}
                  onKeyDown={e => e.key === 'Enter' && lookupSku()}
                  placeholder="e.g. 555088-101"
                  style={{ flex:1, border:`1px solid ${skuErr ? P.error : P.border}`,
                    borderRadius:6, padding:'6px 10px', fontSize:12,
                    fontFamily:'Space Mono, monospace', outline:'none',
                    background: skuErr ? P.error + '0a' : P.bg, color: P.text }} />
                <Btn primary small onClick={lookupSku}>Lookup</Btn>
              </div>
              {skuErr && (
                <div style={{ fontSize:10, color: P.error, marginTop:5,
                  fontFamily:'-apple-system, sans-serif' }}>
                  SKU not in whitelist — enter identifier manually below
                </div>
              )}
              {skuResult && (
                <div style={{ marginTop:8, padding:8, background: P.success + '0f',
                  border:`1px solid ${P.success}33`, borderRadius:6 }}>
                  <div style={{ fontSize:11, fontWeight:700, color: P.success }}>
                    ✓ {skuResult.silhouette} — {skuResult.colorway_name}
                  </div>
                  <div style={{ fontSize:10, color: P.muted, fontFamily:'Space Mono, monospace', marginTop:2 }}>
                    ${skuResult.retail_price} · {skuResult.release_date}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Rename Schema Builder ── */}
          <div style={{ background: P.panel, borderRadius:10, border:`1px solid ${P.border}`, padding:14 }}>
            <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:10,
              display:'flex', justifyContent:'space-between' }}>
              <span>NAMING SCHEMA · run_vibe_renamer()</span>
              <span style={{ color: P.accent }}>{locCode}-{locObj.type}_{dateStr}_{identClean || 'ID'}_{camModel}_orig{ext}</span>
            </div>

            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:12 }}>

              {/* Location picker — grouped by region */}
              <div>
                <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:4 }}>
                  LOC CODE — {typeLabels[locObj.type] || locObj.type}
                </div>
                <select value={locCode} onChange={e => setLocCode(e.target.value)}
                  style={{ width:'100%', border:`1px solid ${P.border}`, borderRadius:6,
                    padding:'6px 8px', fontSize:11, fontFamily:'Space Mono, monospace',
                    background: P.bg, color: P.text, outline:'none' }}>
                  {Object.entries(locGroups).map(([region, locs]) => (
                    <optgroup key={region} label={region}>
                      {locs.map(([code, loc]) => (
                        <option key={code} value={code}>{code} — {loc.name}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>

              {/* Type badge (auto) */}
              <div>
                <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:4 }}>
                  TYPE (auto-derived)
                </div>
                <div style={{ border:`1px solid ${P.border}`, borderRadius:6, padding:'6px 8px',
                  display:'flex', alignItems:'center', gap:8, background: P.bg }}>
                  <span style={{ fontSize:12, fontFamily:'Space Mono, monospace',
                    fontWeight:700, color: P.accent }}>{locObj.type || '—'}</span>
                  <span style={{ fontSize:10, color: P.muted,
                    fontFamily:'-apple-system, sans-serif' }}>{typeLabels[locObj.type] || ''}</span>
                </div>
              </div>

              {/* Date (ffprobe) */}
              <div>
                <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:4 }}>
                  YYMMDD (ffprobe creation_time)
                </div>
                <div style={{ border:`1px solid ${P.border}`, borderRadius:6, padding:'6px 8px',
                  fontFamily:'Space Mono, monospace', fontSize:12, color: P.textSub, background: P.bg }}>
                  {dateStr}
                  {!item?.creationTime && (
                    <span style={{ color: P.warning, fontSize:9, marginLeft:6 }}>⚠ fallback</span>
                  )}
                </div>
              </div>

              {/* Camera (ffprobe) */}
              <div>
                <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:4 }}>
                  CAM MODEL (ffprobe quicktime.model)
                </div>
                <div style={{ border:`1px solid ${P.border}`, borderRadius:6, padding:'6px 8px',
                  fontFamily:'Space Mono, monospace', fontSize:11, color: P.textSub, background: P.bg }}>
                  {camModel}
                </div>
              </div>

              {/* Identifier (full width) */}
              <div style={{ gridColumn:'1/-1' }}>
                <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:4 }}>
                  IDENTIFIER (spaces → hyphens)
                </div>
                <input value={identifier} onChange={e => setIdentifier(e.target.value)}
                  placeholder="e.g. Air Jordan 1 Retro High OG Chicago"
                  style={{ width:'100%', border:`1px solid ${P.accent}66`, borderRadius:6,
                    padding:'6px 10px', fontSize:12, fontFamily:'-apple-system, sans-serif',
                    background: P.panel, color: P.text, outline:'none' }} />
              </div>
            </div>

            {/* Generated filename preview */}
            <div style={{ background:'#0d0d0f', borderRadius:6, padding:'10px 12px', marginBottom:10 }}>
              <div style={{ fontSize:9, color:'#555', fontFamily:'Space Mono, monospace', marginBottom:5 }}>
                GENERATED FILENAME · renamer_logic.py output
              </div>
              {generatedName ? (
                <>
                  <div style={{ fontSize:10, fontFamily:'Space Mono, monospace',
                    color:'#7ae', wordBreak:'break-all', lineHeight:1.7 }}>
                    {generatedName}
                  </div>
                  {/* Token breakdown */}
                  <div style={{ marginTop:8, display:'flex', gap:3, flexWrap:'wrap' }}>
                    {[
                      [locCode, 'LOC'], [locObj.type, 'TYPE'], [dateStr, 'DATE'],
                      [identClean || '—', 'ID'], [camModel, 'CAM'], [origFile, 'ORIG']
                    ].map(([v, k]) => (
                      <div key={k} style={{ display:'flex', overflow:'hidden', borderRadius:3,
                        border:'1px solid #333', fontSize:8 }}>
                        <span style={{ background:'#222', padding:'2px 4px',
                          fontFamily:'Space Mono, monospace', color:'#666' }}>{k}</span>
                        <span style={{ background:'#111', padding:'2px 5px',
                          fontFamily:'Space Mono, monospace', color:'#aaa' }}>{v}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div style={{ fontSize:10, fontFamily:'Space Mono, monospace', color:'#555' }}>
                  — fill identifier to preview filename —
                </div>
              )}
            </div>

            <div style={{ display:'flex', gap:8 }}>
              <Btn ghost style={{ flex:1 }}>✎ Edit Fields</Btn>
              <Btn primary style={{ flex:1 }} disabled={!generatedName}>✓ Confirm &amp; Queue Rename</Btn>
            </div>
          </div>

          {/* Pro: AI tags */}
          {mode === 'pro' && whitelistMatch && (
            <div style={{ background: P.panel, borderRadius:8,
              border:`1px solid ${P.accent}44`, padding:12 }}>
              <div style={{ fontSize:9, color: P.accent, fontFamily:'Space Mono, monospace', marginBottom:8 }}>
                AI AUTO-TAG SUGGESTIONS (PRO)
              </div>
              <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
                {['retro', 'og colorway', 'jordan brand', 'high demand',
                  whitelistMatch.colorway_name.toLowerCase(),
                  whitelistMatch.release_date, 'mall drop'].map(tag => (
                  <span key={tag} style={{ background: P.accentLight,
                    border:`1px solid ${P.accent}44`, borderRadius:4,
                    padding:'2px 8px', fontSize:11, color: P.accent, cursor:'pointer',
                    fontFamily:'-apple-system, sans-serif' }}>
                    + {tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Col 3: Generator Log ──────────────────────────────────── */}
      <div style={{ width:244, borderLeft:`1px solid ${P.border}`, background: P.panel,
        display:'flex', flexDirection:'column' }}>

        <div style={{ padding:'10px 14px', borderBottom:`1px solid ${P.border}`,
          display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          <span style={{ fontSize:13, fontWeight:700, color: P.text,
            fontFamily:'-apple-system, sans-serif' }}>Generator Log</span>
          {streaming && <Tag dot style={{ color: P.warning, background: P.warning + '22' }}>live</Tag>}
        </div>

        {/* Terminal — mirrors Python generator yield stream */}
        <div ref={logRef} style={{ flex:1, background:'#0d0d0f',
          padding:'10px 12px', overflowY:'auto', fontFamily:'Space Mono, monospace' }}>
          {streamLog.map((line, i) => {
            const color = line.includes('error') || line.includes('⚠')
              ? '#ff6b6b'
              : line.includes('renamed') || line.includes('✓')
              ? '#7ae'
              : line.includes('yield') || line.includes('renamer_logic')
              ? '#c9a84c'
              : '#7a9';
            return <div key={i} style={{ fontSize:9, color, lineHeight:1.9 }}>{line}</div>;
          })}
          {streaming && <div style={{ fontSize:9, color:'#555', lineHeight:1.9 }}>█</div>}
        </div>

        {/* Session stats — matches generator done dict */}
        <div style={{ padding:'10px 14px', borderTop:`1px solid ${P.border}` }}>
          <div style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace', marginBottom:6 }}>
            YIELD SUMMARY
          </div>
          {[['processed_count','1 / 4'],['elapsed_seconds','—'],['failures','1'],['fallbacks','2']].map(([k,v]) => (
            <div key={k} style={{ display:'flex', justifyContent:'space-between', marginBottom:3 }}>
              <span style={{ fontSize:9, color: P.muted, fontFamily:'Space Mono, monospace' }}>{k}</span>
              <span style={{ fontSize:10, fontWeight:700, color: P.text, fontFamily:'Space Mono, monospace' }}>{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ImportView });

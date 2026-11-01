// SACC Multi-Modal Search PoC
// Whole-asset shoe entities grouped with video and image media.

function PocAssetCard({ asset, type }) {
  const ref = React.useRef(null);
  const videoRef = React.useRef(null);
  const [visible, setVisible] = React.useState(false);

  React.useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: '240px' });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  const shell = {
    position:'relative', minHeight:150, borderRadius:8, overflow:'hidden',
    background:'#161618', border:`1px solid ${P.border}`,
  };

  return (
    <div ref={ref} style={shell}>
      {!visible && (
        <div style={{ height:150, display:'flex', alignItems:'center', justifyContent:'center',
          color:'#ffffff55', fontSize:10, fontFamily:'Space Mono, monospace' }}>queued</div>
      )}
      {visible && type === 'video' && (
        <video ref={videoRef} src={asset.path} muted loop playsInline controls preload="metadata"
          onMouseEnter={() => videoRef.current?.play().catch(() => {})}
          onMouseLeave={() => { if (videoRef.current) videoRef.current.pause(); }}
          style={{ width:'100%', height:150, display:'block', objectFit:'cover', background:'#000' }} />
      )}
      {visible && type === 'image' && (
        <img src={asset.path} alt="Sneaker archive asset" loading="lazy"
          style={{ width:'100%', height:150, display:'block', objectFit:'cover' }} />
      )}
      <div style={{ position:'absolute', left:7, bottom:7, right:7, display:'flex',
        alignItems:'center', justifyContent:'space-between', pointerEvents:'none' }}>
        <span style={{ background:'rgba(0,0,0,.72)', color:'#fff', borderRadius:4,
          padding:'2px 6px', fontSize:9, fontFamily:'Space Mono, monospace' }}>
          {type.toUpperCase()} {asset.resolution || ''}
        </span>
        {asset.needs_review && (
          <span title={asset.review_reason || 'Manual review required'}
            style={{ background:'#f5a623', color:'#1c1c1e', borderRadius:4,
            padding:'2px 6px', fontSize:9, fontWeight:700 }}>REVIEW</span>
        )}
      </div>
    </div>
  );
}


function PocSearchView({ mode, accent }) {
  const [query, setQuery] = React.useState('');
  const [filterVideo, setFilterVideo] = React.useState(true);
  const [filterImage, setFilterImage] = React.useState(true);
  const [items, setItems] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [offset, setOffset] = React.useState(0);
  const [hasMore, setHasMore] = React.useState(true);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const sentinelRef = React.useRef(null);
  const requestRef = React.useRef(0);
  const loadingRef = React.useRef(false);
  const PAGE_SIZE = 24;

  const selectedTypes = React.useMemo(() => [
    ...(filterVideo ? ['video'] : []),
    ...(filterImage ? ['image'] : []),
  ], [filterVideo, filterImage]);

  const loadPage = React.useCallback(async (nextOffset, replace = false) => {
    if (!selectedTypes.length || loadingRef.current) return;
    const requestId = ++requestRef.current;
    loadingRef.current = true;
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ q: query, limit: PAGE_SIZE, offset: nextOffset });
      selectedTypes.forEach(type => params.append('media_types', type));
      const response = await fetch(`/api/v1/search?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      if (requestId !== requestRef.current) return;
      const rows = data.results || [];
      setItems(previous => replace ? rows : [...previous, ...rows]);
      setTotal(data.total || 0);
      setOffset(nextOffset + rows.length);
      setHasMore(nextOffset + rows.length < (data.total || 0));
    } catch (err) {
      if (requestId === requestRef.current) setError(err.message);
    } finally {
      if (requestId === requestRef.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [query, selectedTypes.join('|')]);

  React.useEffect(() => {
    requestRef.current += 1;
    loadingRef.current = false;
    setLoading(false);
    setItems([]); setOffset(0); setTotal(0); setHasMore(selectedTypes.length > 0);
    if (!selectedTypes.length) return;
    const timer = setTimeout(() => loadPage(0, true), 250);
    return () => clearTimeout(timer);
  }, [query, filterVideo, filterImage]);

  React.useEffect(() => {
    if (!sentinelRef.current || offset === 0 || !hasMore || loading) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) loadPage(offset, false);
    }, { rootMargin: '320px' });
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [offset, hasMore, loading, loadPage]);

  const toggleStyle = active => ({
    border:`1px solid ${active ? accent : P.border}`, borderRadius:6,
    background:active ? accent + '18' : P.panel, color:active ? accent : P.textSub,
    padding:'6px 10px', fontSize:11, fontWeight:600, cursor:'pointer',
  });

  return (
    <div style={{ flex:1, minWidth:0, display:'flex', flexDirection:'column', background:P.bg }}>
      <div style={{ padding:'14px 16px', background:P.panel, borderBottom:`1px solid ${P.border}` }}>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <input value={query} onChange={event => setQuery(event.target.value)}
            placeholder="Search SKU, model, colorway, or brand…"
            style={{ flex:1, border:`1px solid ${P.border}`, borderRadius:7, padding:'8px 11px',
              fontSize:13, outline:'none', background:P.bg, color:P.text }} />
          <button onClick={() => setFilterVideo(v => !v)} style={toggleStyle(filterVideo)}>
            {filterVideo ? '✓ ' : ''}Video
          </button>
          <button onClick={() => setFilterImage(v => !v)} style={toggleStyle(filterImage)}>
            {filterImage ? '✓ ' : ''}Image
          </button>
        </div>
        <div style={{ marginTop:7, fontSize:10, color:P.muted, fontFamily:'Space Mono, monospace' }}>
          {loading && !items.length ? 'SEARCHING…' : `${total} SHOE ENTIT${total === 1 ? 'Y' : 'IES'}`}
          {' · '}whole-asset PoC · timestamps disabled
        </div>
      </div>

      <div style={{ flex:1, overflowY:'auto', padding:16 }}>
        {!selectedTypes.length && (
          <div style={{ padding:48, textAlign:'center', color:P.muted, fontSize:13 }}>
            Enable Video, Image, or both to search the archive.
          </div>
        )}
        {error && (
          <div style={{ padding:12, marginBottom:12, borderRadius:7, color:P.error,
            background:'#ff3b3010', border:'1px solid #ff3b3040', fontSize:12 }}>
            Multi-modal API unavailable: {error}
          </div>
        )}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(300px, 1fr))', gap:12 }}>
          {items.map(shoe => {
            const media = [
              ...(shoe.media?.videos || []).map(asset => ({ asset, type:'video' })),
              ...(shoe.media?.images || []).map(asset => ({ asset, type:'image' })),
            ];
            return (
              <section key={shoe.id} style={{ background:P.panel, border:`1px solid ${P.border}`,
                borderRadius:10, overflow:'hidden' }}>
                <div style={{ padding:'11px 12px', borderBottom:`1px solid ${P.border}` }}>
                  <div style={{ display:'flex', justifyContent:'space-between', gap:8 }}>
                    <div style={{ minWidth:0 }}>
                      <div style={{ fontSize:13, fontWeight:700, color:P.text,
                        whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
                        {shoe.model || 'Unresolved shoe'}
                      </div>
                      <div style={{ fontSize:11, color:P.textSub, marginTop:2 }}>
                        {[shoe.brand, shoe.colorway].filter(Boolean).join(' · ') || 'Metadata pending'}
                      </div>
                    </div>
                    <span style={{ fontSize:9, color:accent, fontFamily:'Space Mono, monospace',
                      border:`1px solid ${accent}55`, borderRadius:4, padding:'3px 5px', height:'fit-content' }}>
                      {shoe.sku}
                    </span>
                  </div>
                </div>
                <div style={{ padding:10, display:'grid', gridTemplateColumns:media.length > 1 ? '1fr 1fr' : '1fr', gap:8 }}>
                  {media.map(({asset, type}) => (
                    <PocAssetCard key={`${type}-${asset.asset_id}`} asset={asset} type={type} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
        {!loading && selectedTypes.length > 0 && !items.length && !error && (
          <div style={{ padding:48, textAlign:'center', color:P.muted, fontSize:13 }}>
            No indexed assets match this search.
          </div>
        )}
        <div ref={sentinelRef} style={{ height:2 }} />
        {loading && items.length > 0 && (
          <div style={{ padding:16, textAlign:'center', color:P.muted,
            fontFamily:'Space Mono, monospace', fontSize:10 }}>LOADING MORE…</div>
        )}
      </div>
    </div>
  );
}

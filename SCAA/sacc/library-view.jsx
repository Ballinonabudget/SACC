// Recovered-media library. All requests remain on the local SACC origin.
const SACC_LIBRARY_API = '/api/library';
const SACC_LIBRARY_FILTERS = { q:'', media_type:'all', year:'all', month:'all',
  gps:'all', review:'all', reason:'', store:'all', privacy:'all' };

function libraryText(value) {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(v => v?.msg || libraryText(v)).join('; ');
  const detail=value.message || value.detail || value.error;
  return detail ? libraryText(detail) : 'The request could not be completed.';
}
function libraryLabel(value) {
  return String(value || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
}
function libraryCount(value) { return Number(value || 0).toLocaleString(); }
function libraryBytes(value) {
  if (!Number.isFinite(Number(value))) return '—';
  const n=Number(value); return n>=1073741824 ? `${(n/1073741824).toFixed(2)} GiB` :
    n>=1048576 ? `${(n/1048576).toFixed(1)} MiB` : `${libraryCount(n)} bytes`;
}
function libraryAssetUrl(item, download=false) {
  if (!item?.asset_url) return '';
  try {
    const u=new URL(item.asset_url,window.location.href);
    if (u.origin!==window.location.origin || !u.pathname.startsWith(`${SACC_LIBRARY_API}/assets/`)) return '';
    if (download) u.searchParams.set('download','1');
    return u.pathname+u.search;
  } catch { return ''; }
}
function libraryOutcome(status) {
  return ({metadata_write_readback_passed:'Write/readback passed',manifest_only_format:'Metadata record only',
    unchanged_needs_review:'Unchanged · needs review',source_verified_only:'Source checked'})[status] || libraryLabel(status) || 'Not recorded';
}

function LibraryDialog({title,onClose,children,wide=false}) {
  const ref=React.useRef(null);
  React.useEffect(()=>{
    const previous=document.activeElement;
    const first=ref.current?.querySelector('button,input,select,textarea,[tabindex="0"]');first?.focus();
    return ()=>previous?.focus?.();
  },[]);
  function keyDown(e) {
    if (e.key==='Escape') {e.preventDefault();e.stopPropagation();onClose();}
    if (e.key==='Tab') {
      const nodes=[...(ref.current?.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]') || [])];
      if (!nodes.length) return;
      if (e.shiftKey && document.activeElement===nodes[0]) {e.preventDefault();nodes[nodes.length-1].focus();}
      if (!e.shiftKey && document.activeElement===nodes[nodes.length-1]) {e.preventDefault();nodes[0].focus();}
    }
  }
  return <div className="sl-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}>
    <section ref={ref} role="dialog" aria-modal="true" aria-label={title} onKeyDown={keyDown}
      className={`sl-dialog${wide?' sl-dialog-wide':''}`}>
      <header className="sl-dialog-head"><h3>{title}</h3><button className="sl-icon" onClick={onClose} aria-label="Close dialog">×</button></header>
      <div className="sl-dialog-body">{children}</div>
    </section>
  </div>;
}

function LibraryReviewForm({targets,stores,api,onSaved,onReload}) {
  const first=targets[0] || {};
  const [action,setAction]=React.useState('note');
  const [value,setValue]=React.useState('');
  const [reviewer,setReviewer]=React.useState('Nitty');
  const [evidence,setEvidence]=React.useState('');
  const [saving,setSaving]=React.useState(false);
  const [error,setError]=React.useState('');
  const [stale,setStale]=React.useState(false);
  const [success,setSuccess]=React.useState('');
  const [history,setHistory]=React.useState('');
  React.useEffect(()=>{setAction('note');setValue('');setEvidence('');setHistory('');setError('');setSuccess('');setStale(false);},[targets.map(t=>t.id).join('|')]);
  function changeAction(next) {
    setAction(next);setError('');setSuccess('');setStale(false);setHistory('');
    setValue(next==='screenshot'?String(!!first.screenshot):next==='privacy'?(first.privacy||'unknown'):
      next==='capture_date'?(first.capture_date||'').slice(0,10):next==='store'?(first.store?.id||''):next==='clear'?'capture_date':'');
  }
  async function reload(){setError('');setSaving(true);try{await onReload();setStale(false);setSuccess('Latest record revisions loaded. Check your decision, then save again.');}catch(e){setError(e.message);}finally{setSaving(false);}}
  async function submit(e) {
    e.preventDefault();setError('');setSuccess('');setSaving(true);setStale(false);
    try {
      const changed=action==='screenshot'?value==='true':action==='store'?(value||null):value;
      const data=await api('/reviews',{method:'POST',body:{items:targets.map(t=>({id:t.id,expected_revision:Number(t.review_revision)||0})),
        action,value:changed,evidence:evidence.trim(),reviewer:reviewer.trim(),...(history.trim()?{historical_evidence:history.trim()}:{})}});
      setSuccess('Review saved. Original media and source metadata were preserved.');
      await onSaved(data.updated||[]);
    } catch(e) {setStale(e.status===409);setError(e.status===409?'This selection changed since it was opened. Reload the latest details before saving.':e.message);}
    finally {setSaving(false);}
  }
  const store=stores.find(s=>s.id===value);
  return <form onSubmit={submit} className="sl-review-form">
    <p className="sl-help">Review changes apply only to {targets.length===1?'this item':`these ${targets.length} selected items`}. They update the library record, not the embedded file.</p>
    <label>Action<select value={action} onChange={e=>changeAction(e.target.value)} disabled={saving}>
      <option value="note">Add a note</option><option value="capture_date">Confirm capture calendar date</option>
      <option value="screenshot">Set screenshot status</option><option value="privacy">Set privacy status</option>
      <option value="store" disabled={!stores.length}>Confirm exact store branch</option><option value="clear">Clear a reviewed override</option>
    </select></label>
    {action==='note'&&<label>Note<textarea required maxLength={4000} rows={3} value={value} onChange={e=>setValue(e.target.value)} placeholder="What should be retained with this item?"/></label>}
    {action==='capture_date'&&<label>Capture date<input required type="date" value={value} onChange={e=>setValue(e.target.value)}/><span className="sl-help">A calendar-date correction does not invent a camera time or timezone. An incompatible store confirmation will be cleared.</span></label>}
    {action==='screenshot'&&<label>Screenshot<select value={value} onChange={e=>setValue(e.target.value)}><option value="true">Confirmed screenshot · GPS not expected</option><option value="false">Not a screenshot · normal GPS checks</option></select></label>}
    {action==='privacy'&&<label>Privacy<select value={value} onChange={e=>setValue(e.target.value)}><option value="unknown">Unknown</option><option value="personal">Personal</option><option value="mixed">Mixed personal/non-personal</option><option value="non_personal">Non-personal</option></select><span className="sl-help">All media remain local. This label does not authorize cloud analysis.</span></label>}
    {action==='store'&&<><label>Historical branch<select value={value} onChange={e=>setValue(e.target.value)} required><option value="">Choose an exact branch…</option>{stores.map(s=><option key={s.id} value={s.id}>{s.label}{s.code?` · ${s.code}`:''}</option>)}</select></label>
      {store&&<p className="sl-help">Known dates: {store.valid_from||'opening unknown'} — {store.valid_to||'no closing date supplied'}. Only compatible capture dates can be confirmed.</p>}
      <label>Historical evidence{store&&!store.valid_from?' (required)':' (if needed)'}<textarea rows={2} maxLength={2000} required={!!store&&!store.valid_from} value={history} onChange={e=>setHistory(e.target.value)} placeholder="Evidence that this exact branch existed on the capture date"/></label></>}
    {action==='clear'&&<label>Override to clear<select value={value} onChange={e=>setValue(e.target.value)}><option value="capture_date">Capture calendar date</option><option value="store">Store confirmation</option><option value="privacy">Privacy label</option><option value="screenshot">Screenshot status</option></select></label>}
    {!stores.length&&<p className="sl-help">No historical store directory is loaded. GPS remains available; branch names will stay unconfirmed until reviewed directory data is added.</p>}
    <div className="sl-two"><label>Reviewer<input required maxLength={100} value={reviewer} onChange={e=>setReviewer(e.target.value)} autoComplete="name"/></label>
      <label>Evidence<input required maxLength={2000} value={evidence} onChange={e=>setEvidence(e.target.value)} placeholder="What supports this decision?"/></label></div>
    {error&&<div className="sl-alert" role="alert">{error}{stale&&<button type="button" className="sl-button" disabled={saving} onClick={reload}>Reload latest details</button>}</div>}
    {success&&<p className="sl-success" role="status">{success}</p>}
    <button type="submit" className="sl-button sl-primary" disabled={saving||stale||!targets.length||!evidence.trim()||!reviewer.trim()}>{saving?'Saving review…':`Save review${targets.length>1?` for ${targets.length} items`:''}`}</button>
  </form>;
}

function LibraryMedia({item,compact=false}) {
  const [failed,setFailed]=React.useState(false);
  React.useEffect(()=>setFailed(false),[item.id]);
  const url=libraryAssetUrl(item),supported=item.preview_supported&&url&&!failed;
  if (supported&&item.media_type==='image') return <img className={compact?'sl-thumb':'sl-preview-image'} src={url} alt={item.original_name||'Recovered image'} loading="lazy" onError={()=>setFailed(true)}/>;
  if (supported&&item.media_type==='video'&&!compact) return <video className="sl-preview-video" src={url} controls playsInline preload="metadata" onError={()=>setFailed(true)}/>;
  return <div className={`sl-media-fallback${compact?' sl-compact':''}`}>
    <span aria-hidden="true">{item.media_type==='video'?'▷':item.media_type==='image'?'▧':'◇'}</span>
    {!compact&&<><strong>{failed?'Preview unavailable':item.preview_supported?'Select to preview':'This format has no browser preview'}</strong><p>The original working file and its metadata record are retained.</p></>}
  </div>;
}

function LibraryDetail({data,loading,error,onClose,onSelect,stores,api,onSaved,onReload}) {
  const item=data?.item;
  const gps=item?.observed_gps?.selected||item?.observed_gps;
  const notes=Array.isArray(item?.notes)?item.notes: item?.notes?[item.notes]:[];
  return <aside className="sl-detail" aria-label="Selected media details">
    <div className="sl-detail-head"><span className="sl-eyebrow">SELECTED ITEM</span><button className="sl-icon" onClick={onClose} aria-label="Close media details">×</button></div>
    {loading&&<p className="sl-placeholder" role="status">Loading details…</p>}
    {error&&<div className="sl-alert" role="alert">{error}<button className="sl-button" onClick={onReload}>Retry details</button></div>}
    {item&&!loading&&<>
      <div className="sl-preview"><LibraryMedia item={item}/></div>
      <div className="sl-detail-content"><h3 className="sl-file-title">{item.original_name||'Unnamed source item'}</h3>
        <div className="sl-badges"><span className="sl-pill">{libraryLabel(item.media_type)}</span><span className="sl-pill">{libraryOutcome(item.embedding_status)}</span></div>
        {libraryAssetUrl(item,true)&&<a className="sl-download" href={libraryAssetUrl(item,true)} download>Download working file ↗</a>}
        <dl className="sl-facts"><dt>Capture date</dt><dd>{item.capture_date||'Undated'}{!item.date_trusted&&<small>Needs date review</small>}</dd>
          <dt>Date basis</dt><dd>{libraryLabel(item.date_basis)||'Not established'}</dd>
          {item.capture_utc&&<><dt>Source UTC time</dt><dd>{item.capture_utc}</dd></>}
          <dt>Store branch</dt><dd>{item.store?.label||'Not confirmed'}{item.store?.code&&<small>{item.store.code}</small>}</dd>
          <dt>Observed GPS</dt><dd>{item.gps_requirement==='not_expected_screenshot'?'Not expected · confirmed screenshot':item.has_gps?'Source observation available':'No selected observation'}
            {typeof gps?.latitude==='number'&&typeof gps?.longitude==='number'&&<small>{gps.latitude.toFixed(6)}, {gps.longitude.toFixed(6)}<br/>{gps.accuracy_m==null?'Accuracy not supplied':`Supplied accuracy: ${gps.accuracy_m} m`}</small>}</dd>
          <dt>Privacy</dt><dd>{libraryLabel(item.privacy||'unknown')}<small>{item.privacy_source==='reviewed'?'Your reviewed label':item.privacy_source==='automatic'?'Automatic suggestion · needs your review':'Not yet classified'} · local only</small></dd>
          <dt>Record review</dt><dd>{libraryLabel(item.review_status)||'Unreviewed'}</dd>
          <dt>Original path</dt><dd className="sl-path">{item.original_path||item.original_name}</dd>
        </dl>
        {!!item.review_reasons?.length&&<section className="sl-section"><h4>Source flags</h4><div className="sl-reasons">{item.review_reasons.map(reason=><span key={reason}>{libraryLabel(reason)}</span>)}</div></section>}
        {item.write_readback_review&&<div className="sl-notice"><strong>Retained unchanged after a write check</strong><p>{libraryText(item.write_readback_review.reason)||'A candidate failed readback. The source copy was retained.'}</p></div>}
        {!!notes.length&&<section className="sl-section"><h4>Notes</h4>{notes.map((n,i)=><p key={i} className="sl-note">{libraryText(typeof n==='object'?(n.note??n.value??n.evidence??n.text):n)}</p>)}</section>}
        <section className="sl-section"><h4>Review this item</h4><LibraryReviewForm targets={[item]} stores={stores} api={api} onSaved={onSaved} onReload={onReload}/></section>
        {!!item.review_events?.length&&<section className="sl-section"><h4>Recent review history</h4>{item.review_events.slice(0,5).map((e,i)=><div className="sl-history" key={e.id||i}><strong>{libraryLabel(e.action||e.kind)}</strong><span>{e.reviewer||'Local reviewer'}{e.created_at?` · ${e.created_at}`:''}</span><p>{libraryText(e.evidence)}</p></div>)}</section>}
        {!!data.related?.length&&<section className="sl-section"><h4>Nearby in capture time</h4><p className="sl-help">Time proximity does not confirm a shared store or product.</p>{data.related.filter(r=>r.id!==item.id).slice(0,12).map(r=><button key={r.id} className="sl-related" onClick={()=>onSelect(r.id)}><span>{r.original_name}</span><small>{r.capture_date||'Undated'} · {libraryLabel(r.media_type)}</small></button>)}</section>}
      </div>
    </>}
  </aside>;
}

function FootwearSearchPilot({ api, accent }) {
  const [q, setQ] = React.useState('Kobe');
  const [store, setStore] = React.useState('store-mkt');
  const [captureType, setCaptureType] = React.useState('all');
  const [selectedYears, setSelectedYears] = React.useState(['2015', '2016']);
  const [availableYears, setAvailableYears] = React.useState(['2015', '2016', '2017', '2018', 'undated']);
  const [availableStores, setAvailableStores] = React.useState([
    { id: 'all', label: 'All stores' },
    { id: 'store-mkt', label: 'Nike Clearance Store - Marketplace', code: 'ORL-MKT-CLR' },
    { id: 'store-idr', label: 'Nike Factory Store - International Drive', code: 'ORL-IDR-FAC' },
    { id: 'store-adi', label: 'Adidas Outlet - Orlando International', code: 'ORL-ADI-OUT' },
  ]);
  const [results, setResults] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');

  const loadFacets = React.useCallback(async () => {
    try {
      const qParams = new URLSearchParams();
      if (q.trim()) qParams.set('q', q.trim());
      if (store !== 'all') qParams.set('store', store);
      if (captureType !== 'all') qParams.set('capture_type', captureType);
      const data = await api('/pilot/facets?' + qParams.toString());
      if (data && data.stores && data.stores.length) {
        setAvailableStores([
          { id: 'all', label: 'All stores' },
          ...data.stores
        ]);
      }
      if (data && data.years && data.years.length) {
        const yVals = data.years.map(y => String(y.value));
        setAvailableYears(prev => Array.from(new Set([...prev, ...yVals])));
      }
    } catch (e) {
      // ignore facet fetch errors
    }
  }, [api, q, store, captureType]);

  const doSearch = React.useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set('q', q.trim());
      if (store && store !== 'all') params.set('store', store);
      if (captureType && captureType !== 'all') params.set('capture_type', captureType);
      params.set('years', selectedYears.join(','));
      params.set('limit', '50');

      const data = await api(`/pilot/search?${params.toString()}`);
      setResults(data.results || []);
      setTotal(Number(data.total) || 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [api, q, store, captureType, selectedYears]);

  React.useEffect(() => {
    loadFacets();
  }, [loadFacets]);

  React.useEffect(() => {
    const timer = setTimeout(() => {
      doSearch();
    }, 150);
    return () => clearTimeout(timer);
  }, [doSearch]);

  const toggleYear = (yr) => {
    setSelectedYears(prev => {
      if (prev.includes(yr)) return prev.filter(y => y !== yr);
      return [...prev, yr];
    });
  };

  const selectAllYears = () => setSelectedYears([...availableYears]);
  const clearAllYears = () => setSelectedYears([]);

  const setPreset = (presetQ, presetStore, presetYears, presetCtype) => {
    setQ(presetQ);
    if (presetStore !== undefined) setStore(presetStore);
    if (presetYears !== undefined) setSelectedYears(presetYears);
    if (presetCtype !== undefined) setCaptureType(presetCtype);
  };

  return (
    <div className="sl-pilot-wrap">
      {/* Pilot sub-header info banner */}
      <div className="sl-pilot-banner">
        <div className="sl-pilot-banner-content">
          <span className="sl-pilot-badge">STAGE 1 PILOT</span>
          <strong>Footwear Library Search Engine (Private Staging)</strong>
          <p>
            Search footwear occurrences across solo shots and multi-shoe wall displays.
            Distinguishes authentic in-store camera captures from studio cutouts / background-removed reference graphics.
          </p>
        </div>
        <div className="sl-pilot-presets">
          <span className="sl-preset-label">Verification Presets:</span>
          <button type="button" className="sl-pill-btn" onClick={() => setPreset('Kobe', 'store-mkt', ['2015', '2016'], 'in_store_photo')}>
            📸 Kobe In-Store (Marketplace)
          </button>
          <button type="button" className="sl-pill-btn" onClick={() => setPreset('Kobe', 'all', ['2015', '2016', '2017', '2018', 'undated'], 'studio_cutout')}>
            🎨 Kobe Studio Cutouts (Ref Renders)
          </button>
          <button type="button" className="sl-pill-btn" onClick={() => setPreset('822675-706', 'all', ['2015', '2016', '2017', '2018', 'undated'], 'all')}>
            SKU: 822675-706 (Solo + Wall + Repeats)
          </button>
          <button type="button" className="sl-pill-btn" onClick={() => setPreset('Nike Multiples', 'all', ['2015', '2016', '2017', '2018', 'undated'], 'all')}>
            Wall Shot: Nike Multiples
          </button>
        </div>
      </div>

      {/* Search Input Bar */}
      <div className="sl-pilot-toolbar">
        <div className="sl-search sl-pilot-search-box">
          <span aria-hidden="true">⌕</span>
          <input
            placeholder="Search by shoe line, model, colorway, or exact SKU (e.g. Kobe, Kobe 11, Bruce Lee, 822675-706)..."
            value={q}
            onChange={e => setQ(e.target.value)}
          />
          {q && (
            <button className="sl-icon" onClick={() => setQ('')} aria-label="Clear search">×</button>
          )}
        </div>
      </div>

      {/* Filter controls: Store, Capture Type and Multi-Year Checkboxes */}
      <div className="sl-pilot-filters-card">
        <div className="sl-pilot-filter-group">
          <label className="sl-pilot-label">Store Location</label>
          <select
            className="sl-pilot-select"
            value={store}
            onChange={e => setStore(e.target.value)}
          >
            {availableStores.map(s => (
              <option key={s.id} value={s.id}>
                {s.label}{s.code ? ` (${s.code})` : ''}
              </option>
            ))}
          </select>
        </div>

        <div className="sl-pilot-filter-group">
          <label className="sl-pilot-label">Capture Type</label>
          <select
            className="sl-pilot-select"
            value={captureType}
            onChange={e => setCaptureType(e.target.value)}
          >
            <option value="all">All Captures</option>
            <option value="in_store_photo">📸 In-Store Photos Only</option>
            <option value="studio_cutout">🎨 Studio Cutouts / Renders</option>
          </select>
        </div>

        <div className="sl-pilot-filter-group sl-pilot-years-group">
          <div className="sl-pilot-years-header">
            <span className="sl-pilot-label">Capture Years (Multi-select)</span>
            <div className="sl-pilot-year-actions">
              <button type="button" className="sl-link-btn" onClick={selectAllYears}>All</button>
              <span className="sl-sep">·</span>
              <button type="button" className="sl-link-btn" onClick={clearAllYears}>None</button>
            </div>
          </div>
          <div className="sl-pilot-checkboxes">
            {availableYears.map(yr => {
              const isChecked = selectedYears.includes(yr);
              return (
                <label key={yr} className={`sl-pilot-checkbox-label ${isChecked ? 'checked' : ''}`}>
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggleYear(yr)}
                  />
                  <span>{yr === 'undated' ? 'Undated' : yr}</span>
                </label>
              );
            })}
          </div>
          {selectedYears.length === 0 && (
            <span className="sl-pilot-warning">All years unchecked (yields 0 results)</span>
          )}
        </div>
      </div>

      {/* Results header */}
      <div className="sl-pilot-results-bar">
        <span className="sl-pilot-count">
          {loading ? 'Searching catalog…' : `${total} matching sighting${total === 1 ? '' : 's'}`}
        </span>
        <span className="sl-pilot-subtext">
          In-store camera photos and background-removed studio cutouts cataloged and categorized separately.
        </span>
      </div>

      {/* Results Content */}
      <div className="sl-pilot-results-container">
        {error && (
          <div className="sl-alert" role="alert">
            <strong>Search Error</strong>
            <p>{error}</p>
          </div>
        )}

        {!loading && !error && results.length === 0 && (
          <div className="sl-empty">
            <span>⌕</span>
            <h3>No matching sightings found</h3>
            <p>
              {selectedYears.length === 0
                ? 'Check one or more capture years to see occurrences.'
                : 'Try adjusting your search query, store filter, capture type, or selected capture years.'}
            </p>
            <button className="sl-button" onClick={() => { setQ('Kobe'); setStore('all'); setCaptureType('all'); selectAllYears(); }}>
              Reset to All Kobe Sightings
            </button>
          </div>
        )}

        {results.length > 0 && (
          <div className="sl-pilot-cards-grid">
            {results.map(item => {
              const isWall = item.is_wall_shot;
              const shoeCount = (item.shoes || []).length;
              const isInStore = item.capture_type === 'in_store_photo';
              return (
                <article key={item.id} className="sl-pilot-card">
                  {item.asset_url && (
                    <div className="sl-pilot-thumb-wrap">
                      <img
                        className="sl-pilot-thumb"
                        src={item.asset_url}
                        alt={item.display_title || item.original_name}
                        loading="lazy"
                        onError={(e) => { e.currentTarget.style.display = 'none'; }}
                      />
                      <span className={`sl-pilot-photo-tag ${isInStore ? 'in-store' : 'studio'}`}>
                        {isInStore ? '📸 In-Store Photo' : '🎨 Studio Cutout'}
                      </span>
                    </div>
                  )}
                  <div className="sl-pilot-card-header">
                    <div className="sl-pilot-card-title-row">
                      <span className={`sl-pilot-type-pill ${isWall ? 'wall' : 'solo'}`}>
                        {isWall ? `Wall Shot · ${shoeCount} Shoes` : 'Solo Sighting'}
                      </span>
                      <span className="sl-pilot-date-badge">
                        {item.capture_month_year || 'Undated'}
                      </span>
                    </div>
                    <h4 className="sl-pilot-title">{item.display_title}</h4>
                    <div className="sl-pilot-store-tag">
                      <span className="sl-store-icon">📍</span>
                      <span>{item.store ? item.store.label : 'Store not confirmed'}</span>
                      {item.store?.code && <small> ({item.store.code})</small>}
                    </div>
                    {item.camera_model && (
                      <div className="sl-pilot-camera-tag">
                        <span>📷 {item.camera_model}</span>
                        {item.photo_resolution && <small>· {item.photo_resolution}</small>}
                      </div>
                    )}
                  </div>

                  <div className="sl-pilot-card-shoes">
                    <div className="sl-pilot-shoes-header">Identified Footwear ({shoeCount}):</div>
                    <ul className="sl-pilot-shoes-list">
                      {(item.shoes || []).map((shoe, idx) => (
                        <li key={shoe.shoe_id || idx} className="sl-pilot-shoe-item">
                          <div className="sl-pilot-shoe-main">
                            <span className="sl-shoe-brand">{shoe.brand}</span>
                            <strong className="sl-shoe-model">{shoe.model}</strong>
                            {shoe.colorway && <span className="sl-shoe-colorway">"{shoe.colorway}"</span>}
                          </div>
                          <div className="sl-pilot-shoe-meta">
                            <code className="sl-sku-code">SKU: {shoe.sku || 'N/A'}</code>
                            {shoe.price_observed != null && (
                              <span className="sl-price-badge">
                                Observed: ${Number(shoe.price_observed).toFixed(2)}
                              </span>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="sl-pilot-card-footer">
                    <span className="sl-card-id">ID: {item.id}</span>
                    <span className="sl-card-file">{item.filename}</span>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function LibraryView({mode,accent}) {
  const [viewTab,setViewTab]=React.useState('pilot');
  const [session,setSession]=React.useState(null),[status,setStatus]=React.useState(null),[facets,setFacets]=React.useState({years:[],months:[],stores:[],review_reasons:[]});
  const [stores,setStores]=React.useState([]),[filters,setFilters]=React.useState({...SACC_LIBRARY_FILTERS});
  const [items,setItems]=React.useState([]),[total,setTotal]=React.useState(0),[page,setPage]=React.useState(0),[layout,setLayout]=React.useState('list');
  const [loading,setLoading]=React.useState(true),[error,setError]=React.useState(''),[notice,setNotice]=React.useState(''),[refresh,setRefresh]=React.useState(0);
  const [selected,setSelected]=React.useState(null),[detail,setDetail]=React.useState(null),[detailLoading,setDetailLoading]=React.useState(false),[detailError,setDetailError]=React.useState('');
  const [checked,setChecked]=React.useState({}),[batchReview,setBatchReview]=React.useState(false),[directoryOpen,setDirectoryOpen]=React.useState(false);
  const [previewOpen,setPreviewOpen]=React.useState(false),[preview,setPreview]=React.useState(null),[previewLoading,setPreviewLoading]=React.useState(false),[previewError,setPreviewError]=React.useState('');
  const [directoryJson,setDirectoryJson]=React.useState(''),[directoryReviewer,setDirectoryReviewer]=React.useState('Nitty'),[directoryEvidence,setDirectoryEvidence]=React.useState(''),[directoryError,setDirectoryError]=React.useState(''),[directoryLoading,setDirectoryLoading]=React.useState(false);
  const csrf=React.useRef(''),requestId=React.useRef(0),detailRequest=React.useRef(0),previewAbort=React.useRef(null);
  const PAGE_SIZE=30,chosen=Object.values(checked),ready=!!session&&session.ready!==false&&status?.ready===true;
  const api=React.useCallback(async(path,options={})=>{
    const config={...options,credentials:'same-origin',headers:{...(options.headers||{})}};
    if (options.body!==undefined) {config.headers['Content-Type']='application/json';config.headers['X-SACC-Library-Token']=csrf.current;config.body=JSON.stringify(options.body);}
    const response=await fetch(SACC_LIBRARY_API+path,config);
    let data;try{data=await response.json();}catch{data={detail:'SACC returned an unreadable response.'};}
    if (!response.ok) {const e=new Error(libraryText(data.detail||data.error)||`Request failed (${response.status}).`);e.status=response.status;throw e;}
    return data;
  },[]);
  const overview=React.useCallback(async()=>{
    const [s,f,d]=await Promise.all([api('/status'),api('/facets'),api('/directory')]);setStatus(s);setFacets(f);setStores(d.stores||[]);
  },[api]);
  const connect=React.useCallback(async()=>{
    setLoading(true);setError('');
    try{const s=await api('/session');csrf.current=s.csrf_token||'';setSession(s);await overview();setRefresh(x=>x+1);}
    catch(e){setError(e.message);setLoading(false);}
  },[api,overview]);
  React.useEffect(()=>{connect();return()=>{requestId.current++;detailRequest.current++;previewAbort.current?.abort();};},[connect]);
  React.useEffect(()=>{
    if (!session||status===null) return;
    if (session.ready===false||status.ready!==true) {setLoading(false);return;}
    setLoading(true);
    const id=++requestId.current,controller=new AbortController();
    const timer=setTimeout(async()=>{
      setLoading(true);setError('');
      const params=new URLSearchParams({...filters,limit:String(PAGE_SIZE),offset:String(page*PAGE_SIZE)});
      try{const d=await api(`/items?${params}`,{signal:controller.signal});if(id!==requestId.current)return;setItems(d.results||[]);setTotal(Number(d.total)||0);if(page>0&&page*PAGE_SIZE>=(Number(d.total)||0))setPage(0);}
      catch(e){if(e.name!=='AbortError'&&id===requestId.current)setError(e.message);}
      finally{if(id===requestId.current)setLoading(false);}
    },200);
    return()=>{clearTimeout(timer);controller.abort();};
  },[session,status?.ready,filters,page,refresh,api]);
  const loadDetail=React.useCallback(async(id)=>{
    if(!id)return;const seq=++detailRequest.current;setDetailLoading(true);setDetailError('');
    try{const d=await api(`/items/${encodeURIComponent(id)}`);if(seq===detailRequest.current)setDetail(d);}
    catch(e){if(seq===detailRequest.current)setDetailError(e.message);}
    finally{if(seq===detailRequest.current)setDetailLoading(false);}
  },[api]);
  function select(id){setSelected(id);setDetail(null);loadDetail(id);}
  function closeDetail(){detailRequest.current++;setSelected(null);setDetail(null);setDetailError('');}
  React.useEffect(()=>{function esc(e){if(e.key==='Escape'){if(previewOpen){closePreview();}else if(batchReview)setBatchReview(false);else if(directoryOpen)setDirectoryOpen(false);else if(selected)closeDetail();}}window.addEventListener('keydown',esc);return()=>window.removeEventListener('keydown',esc);},[previewOpen,batchReview,directoryOpen,selected]);
  function filter(key,value){setFilters(old=>({...old,[key]:value}));setPage(0);setNotice('');}
  function toggle(item){if(!checked[item.id]&&chosen.length>=100){setNotice('Select up to 100 explicit items for one review.');return;}setChecked(old=>{if(old[item.id]){const next={...old};delete next[item.id];return next;}return{...old,[item.id]:item};});}
  async function saved(updated){setNotice(`Review saved for ${updated.length} ${updated.length===1?'item':'items'}. Original media were preserved.`);setChecked(old=>{const next={...old};updated.forEach(i=>{if(next[i.id])next[i.id]=i;});return next;});setRefresh(x=>x+1);await overview();if(selected)await loadDetail(selected);}
  async function reloadSelected(){await Promise.all(chosen.map(async i=>{const d=await api(`/items/${encodeURIComponent(i.id)}`);setChecked(old=>({...old,[i.id]:d.item}));}));if(selected)await loadDetail(selected);}
  function closePreview(){previewAbort.current?.abort();setPreviewOpen(false);}
  async function organizationPreview(){
    setPreviewOpen(true);setPreview(null);setPreviewError('');setPreviewLoading(true);previewAbort.current?.abort();const controller=new AbortController();previewAbort.current=controller;
    try{const d=await api('/organization/preview',{method:'POST',signal:controller.signal,body:chosen.length?{ids:chosen.map(i=>i.id)}:{filters}});setPreview(d);}
    catch(e){if(e.name!=='AbortError')setPreviewError(e.message);}
    finally{if(!controller.signal.aborted)setPreviewLoading(false);}
  }
  async function loadDirectoryFile(e){const f=e.target.files?.[0];if(!f)return;if(f.size>2*1024*1024){setDirectoryError('Choose a JSON directory smaller than 2 MiB.');return;}setDirectoryJson(await f.text());setDirectoryError('');}
  async function importDirectory(e){e.preventDefault();setDirectoryError('');setDirectoryLoading(true);try{let directory;try{directory=JSON.parse(directoryJson);}catch{throw new Error('The file is not valid JSON.');}await api('/directory',{method:'POST',body:{directory,reviewer:directoryReviewer.trim(),evidence:directoryEvidence.trim()}});await overview();setDirectoryOpen(false);setNotice('Historical directory loaded. It has not assigned locations to your media.');}catch(e){setDirectoryError(e.message);}finally{setDirectoryLoading(false);}}
  const totals=status?.totals||{},pages=Math.max(1,Math.ceil(total/PAGE_SIZE));
  const controls=[['media_type','Type',[['all','All media'],['image','Photos'],['video','Videos'],['unknown','Unknown formats']]],
    ['year','Capture year',[['all','All years'],['undated','Undated'],...(facets.years||[]).filter(y=>String(y.value)!=='undated').map(y=>[String(y.value),`${y.value} (${libraryCount(y.count)})`])]],
    ['month','Month',[['all','All months'],...Array.from({length:12},(_,i)=>[String(i+1),new Intl.DateTimeFormat('en',{month:'long',timeZone:'UTC'}).format(new Date(Date.UTC(2000,i,1)))])]],
    ['store','Store branch',[['all','All branches'],['unknown','Not confirmed'],...(facets.stores||[]).map(s=>[s.id,`${s.label} (${libraryCount(s.count)})`])]],
    ['gps','GPS',[['all','All GPS states'],['present','Observation available'],['missing','Missing observation'],['not_expected','Not expected · screenshot']]],
    ['review','Review',[['all','All review states'],['attention','Needs attention'],['annotated','Reviewed / annotated'],['unreviewed','Not reviewed']]],
    ['reason','Source flag',[['','All source flags'],...(facets.review_reasons||[]).map(r=>[r.value,`${r.label||libraryLabel(r.value)} (${libraryCount(r.count)})`])]],
    ['privacy','Privacy',[['all','All privacy states'],['unknown','Unknown'],['personal','Personal'],['mixed','Mixed'],['non_personal','Non-personal']]]];
  return <div className={`sacc-library ${selected?'sl-has-detail':''}`} style={{'--sl-accent':accent||P.accent}}>
    <style>{SACC_LIBRARY_CSS}</style>
    <header className="sl-header">
      <div>
        <span className="sl-eyebrow">SACC LIBRARY</span>
        <h2>Library</h2>
        <div className="sl-nav-tabs">
          <button
            type="button"
            className={`sl-nav-tab ${viewTab === 'pilot' ? 'active' : ''}`}
            onClick={() => setViewTab('pilot')}
          >
            Footwear Search Pilot (Staging)
          </button>
          <button
            type="button"
            className={`sl-nav-tab ${viewTab === 'media' ? 'active' : ''}`}
            onClick={() => setViewTab('media')}
          >
            Recovered Media Catalog
          </button>
        </div>
      </div>
      <div className="sl-header-actions">
        <span className="sl-local">● Local only</span>
        {viewTab === 'media' && <button className="sl-button" onClick={()=>setDirectoryOpen(true)} disabled={!ready}>Store directory</button>}
        {viewTab === 'media' && <button className="sl-button" onClick={()=>{overview().then(()=>setRefresh(x=>x+1)).catch(e=>setError(e.message));}} disabled={!session||loading}>Refresh</button>}
      </div>
    </header>

    {viewTab === 'pilot' ? (
      <FootwearSearchPilot api={api} accent={accent} />
    ) : (
      <>
        <div className="sl-metrics" aria-label="Library overview">{[['All items',totals.occurrences],['Photos',totals.images],['Videos',totals.videos],['Needs attention',totals.needs_review]].map(([label,n])=><div key={label}><span>{label}</span><strong>{status?libraryCount(n):'—'}</strong></div>)}</div>
        <div className="sl-toolbar"><label className="sl-search"><span aria-hidden="true">⌕</span><input aria-label="Search library" placeholder="Search original names, notes or store aliases…" value={filters.q} maxLength={200} onChange={e=>filter('q',e.target.value)} disabled={!ready}/></label>
          <div className="sl-view-switch" role="group" aria-label="Library view"><button className={layout==='list'?'active':''} onClick={()=>setLayout('list')} aria-pressed={layout==='list'}>☰ List</button><button className={layout==='grid'?'active':''} onClick={()=>setLayout('grid')} aria-pressed={layout==='grid'}>⊞ Grid</button></div></div>
        <div className="sl-filters">{controls.map(([key,label,options])=><label key={key}>{label}<select value={filters[key]} onChange={e=>filter(key,e.target.value)} disabled={!ready}>{options.map(([value,text])=><option key={value} value={value}>{text}</option>)}</select></label>)}<button className="sl-reset" onClick={()=>{setFilters({...SACC_LIBRARY_FILTERS});setPage(0);}}>Reset filters</button></div>
        <div className="sl-results-head"><span aria-live="polite">{loading?'Loading library…':`${libraryCount(total)} matching ${total===1?'item':'items'}`}{chosen.length?` · ${chosen.length} selected`:''}</span>
          <div>{chosen.length>0&&<><button className="sl-button" onClick={()=>setChecked({})}>Clear selection</button><button className="sl-button" onClick={()=>setBatchReview(true)}>Review selected</button></>}
          <button className="sl-button sl-primary" disabled={!ready||loading||!total} onClick={organizationPreview}>Preview organization{chosen.length?` (${chosen.length})`:''}</button></div></div>
        {notice&&<div className="sl-notice" role="status">{notice}<button className="sl-icon" onClick={()=>setNotice('')} aria-label="Dismiss notice">×</button></div>}
        {error&&<div className="sl-alert" role="alert"><strong>Library connection unavailable</strong><p>{error}</p><button className="sl-button" onClick={connect}>Retry connection</button></div>}
        {status?.ready===false&&!error&&<div className="sl-empty"><span>◇</span><h3>Your recovered library is not loaded yet</h3><p>The recovery files are preserved. Library setup must finish before browsing is available.</p><button className="sl-button" onClick={connect}>Check again</button></div>}
        <div className="sl-body"><div className="sl-results" aria-busy={loading}>
          {!loading&&ready&&!error&&!items.length&&<div className="sl-empty"><span>⌕</span><h3>No matching media</h3><p>Try a different year, type or source flag. Unconfirmed stores remain searchable under “Not confirmed”.</p><button className="sl-button" onClick={()=>{setFilters({...SACC_LIBRARY_FILTERS});setPage(0);}}>Show all items</button></div>}
          {loading&&!items.length&&!error&&<div className="sl-placeholder" role="status">Loading recovered records…</div>}
          {items.length>0&&layout==='list'&&<div className="sl-table-wrap"><table className="sl-table"><thead><tr><th className="sl-select-cell"><span className="sl-sr">Select</span></th><th>Original filename</th><th>Capture date</th><th>Store / GPS</th><th>Metadata outcome</th></tr></thead><tbody>{items.map(item=><tr key={item.id} className={selected===item.id?'selected':''}><td className="sl-select-cell"><input type="checkbox" aria-label={`Select ${item.original_name}`} checked={!!checked[item.id]} onChange={()=>toggle(item)}/></td>
            <td><button className="sl-row-open" onClick={()=>select(item.id)}><span className="sl-type-mark" aria-hidden="true">{item.media_type==='video'?'▷':item.media_type==='image'?'▧':'◇'}</span><span><strong>{item.original_name||'Unnamed source'}</strong><small>{libraryLabel(item.media_type)} · {libraryLabel(item.privacy||'unknown')}</small></span></button></td>
            <td>{item.capture_date||'Undated'}{!item.date_trusted&&<small>Needs date review</small>}</td><td>{item.store?.label||'Not confirmed'}<small>{item.gps_requirement==='not_expected_screenshot'?'GPS not expected':item.has_gps?'GPS observation':'GPS missing'}</small></td>
            <td><span className={`sl-outcome ${item.embedding_status==='metadata_write_readback_passed'?'sl-ok':''}`}>{libraryOutcome(item.embedding_status)}</span><small>{item.review_reasons?.length?`${item.review_reasons.length} source ${item.review_reasons.length===1?'flag':'flags'}`:'No source flags'}</small></td></tr>)}</tbody></table></div>}
          {items.length>0&&layout==='grid'&&<div className="sl-grid">{items.map(item=><article className={`sl-card ${selected===item.id?'selected':''}`} key={item.id}><label className="sl-card-check"><input type="checkbox" aria-label={`Select ${item.original_name}`} checked={!!checked[item.id]} onChange={()=>toggle(item)}/></label><button className="sl-card-open" onClick={()=>select(item.id)}><LibraryMedia item={item} compact/><div className="sl-card-copy"><strong>{item.original_name||'Unnamed source'}</strong><small>{item.capture_date||'Undated'} · {libraryLabel(item.media_type)}</small><span>{item.store?.label||'Store not confirmed'}</span><em>{libraryOutcome(item.embedding_status)}</em></div></button></article>)}</div>}
        </div>{selected&&<LibraryDetail data={detail} loading={detailLoading} error={detailError} onClose={closeDetail} onSelect={select} stores={stores} api={api} onSaved={saved} onReload={()=>loadDetail(selected)}/>}</div>
        <footer className="sl-footer"><span>{total?`${libraryCount(page*PAGE_SIZE+1)}–${libraryCount(Math.min((page+1)*PAGE_SIZE,total))} of ${libraryCount(total)}`:'No results'}<small> · Source metadata and reviewed labels are separate.</small></span><div><button className="sl-button" disabled={page===0||loading} onClick={()=>setPage(p=>Math.max(0,p-1))}>← Previous</button><span>Page {page+1} / {libraryCount(pages)}</span><button className="sl-button" disabled={(page+1)*PAGE_SIZE>=total||loading} onClick={()=>setPage(p=>p+1)}>Next →</button></div></footer>
      </>
    )}
    {batchReview&&<LibraryDialog title={`Review ${chosen.length} selected items`} onClose={()=>setBatchReview(false)}><LibraryReviewForm targets={chosen} stores={stores} api={api} onSaved={saved} onReload={reloadSelected}/></LibraryDialog>}
    {previewOpen&&<LibraryDialog title="Organization preview" onClose={closePreview} wide>{previewLoading?<p className="sl-placeholder" role="status">Preparing a saved naming and folder preview…</p>:previewError?<div className="sl-alert" role="alert">{previewError}<button className="sl-button" onClick={organizationPreview}>Try again</button></div>:preview&&<>
      <div className="sl-preview-summary"><div><span>Planned items</span><strong>{libraryCount(preview.files)}</strong></div><div><span>Held for review</span><strong>{libraryCount(typeof preview.held==='number'?preview.held:Object.values(preview.held||{}).reduce((a,b)=>a+Number(b||0),0))}</strong></div><div><span>Source data represented</span><strong>{libraryBytes(preview.bytes)}</strong></div></div>
      <p className="sl-notice">Preview only. Recovery files stay in place. Creating the organized working copies requires a separately reviewed execution plan.</p>
      <p className="sl-help">Plan {preview.plan_id} · {preview.strategy==='clone'?'Independent copy-on-write outputs':libraryLabel(preview.strategy)}. Source data size is not a promise of new storage used or reserved.</p>
      <div className="sl-plan-paths">{(preview.sample||[]).map((r,i)=><div key={r.id||i}><span className="sl-eyebrow">{r.held_reason?'HELD FOR REVIEW':'PROPOSED OUTPUT'}</span><p className="sl-path">{r.source}</p><strong className="sl-path">{r.target||'No safe target proposed'}</strong>{r.held_reason&&<small>{libraryLabel(r.held_reason)}</small>}</div>)}</div>
      {!(preview.sample||[]).length&&<p className="sl-help">This plan contains no previewable target rows.</p>}
    </>}</LibraryDialog>}
    {directoryOpen&&<LibraryDialog title="Historical store directory" onClose={()=>setDirectoryOpen(false)}><p className="sl-help">Load an approved local JSON directory with exact branch IDs and historical dates. Importing it does not assign stores to any media.</p><p>{libraryCount(stores.length)} historical branch versions currently available.</p>
      <form className="sl-review-form" onSubmit={importDirectory}><label>Local directory JSON<input type="file" accept=".json,application/json" onChange={loadDirectoryFile}/></label><label>Directory data<textarea required rows={5} maxLength={2097152} value={directoryJson} onChange={e=>setDirectoryJson(e.target.value)} spellCheck="false" placeholder="Select a local JSON file or paste the approved directory contract"/></label>
        <label>Reviewer<input required maxLength={100} value={directoryReviewer} onChange={e=>setDirectoryReviewer(e.target.value)}/></label><label>Source / approval evidence<textarea required rows={2} maxLength={2000} value={directoryEvidence} onChange={e=>setDirectoryEvidence(e.target.value)}/></label>{directoryError&&<div className="sl-alert" role="alert">{directoryError}</div>}
        <button className="sl-button sl-primary" disabled={directoryLoading||!directoryJson.trim()||!directoryReviewer.trim()||!directoryEvidence.trim()}>{directoryLoading?'Validating directory…':'Validate and import directory'}</button></form></LibraryDialog>}
  </div>;
}

const SACC_LIBRARY_CSS = `
.sacc-library{position:relative;display:flex;flex-direction:column;flex:1;min-width:0;min-height:0;height:100%;overflow:hidden;background:#f5f2ed;color:#1c1c1e;font:12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;--sl-accent:#277f53}
.sacc-library *{box-sizing:border-box}.sacc-library button,.sacc-library input,.sacc-library select,.sacc-library textarea{font:inherit}.sacc-library button,.sacc-library a,.sacc-library input,.sacc-library select,.sacc-library textarea{outline-offset:3px}.sacc-library button:focus-visible,.sacc-library a:focus-visible{outline:2px solid var(--sl-accent)}
.sl-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 24px 15px;background:#fff;border-bottom:1px solid #e5e2dc}.sl-header h2{font-size:25px;letter-spacing:-1px;margin:3px 0 5px}.sl-header p{color:#6b6864;margin:0;font-size:12px}.sl-eyebrow{font-size:9px;font-weight:700;letter-spacing:.11em;color:#8c8780}.sl-header-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}.sl-local{font-size:10px;color:#387859;white-space:nowrap;margin-right:4px}
.sl-button{border:1px solid #dcd7cf;border-radius:6px;background:#fff;color:#373531;font-size:11px;font-weight:600;padding:7px 10px;cursor:pointer;white-space:nowrap}.sl-button:hover:not(:disabled){background:#f0ede7;border-color:#bcb5aa}.sl-button:disabled{opacity:.45;cursor:default}.sl-primary{color:#fff;background:var(--sl-accent);border-color:var(--sl-accent)}.sl-primary:hover:not(:disabled){background:var(--sl-accent);filter:brightness(.95)}.sl-icon{border:0;background:transparent;color:#7b756c;font-size:22px;line-height:1;padding:3px 6px;cursor:pointer;border-radius:4px}
.sl-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:#e5e2dc;margin:16px 24px 12px;border:1px solid #e5e2dc;border-radius:8px;overflow:hidden}.sl-metrics>div{background:#fff;padding:12px 14px;display:flex;align-items:center;justify-content:space-between;gap:8px}.sl-metrics span{font-size:10px;color:#817b73}.sl-metrics strong{font-size:21px;letter-spacing:-.7px;font-weight:650}
.sl-toolbar{display:flex;gap:10px;margin:0 24px 10px}.sl-search{display:flex;align-items:center;gap:8px;flex:1;min-width:0;background:#fff;border:1px solid #dcd7cf;border-radius:7px;padding:0 10px}.sl-search>span{font-size:21px;color:#8c8780}.sl-search input{width:100%;border:0;background:transparent;outline:none;padding:10px 0;font-size:12px}.sl-view-switch{display:flex;align-items:center;gap:2px;padding:3px;background:#e9e4dc;border-radius:7px}.sl-view-switch button{padding:6px 9px;background:transparent;border:0;border-radius:5px;color:#817b73;cursor:pointer;font-size:11px}.sl-view-switch .active{background:#fff;color:#1c1c1e;box-shadow:0 1px 3px #00000012}
.sl-filters{display:flex;align-items:end;gap:8px;padding:0 24px 12px;flex-wrap:wrap}.sl-filters label{display:flex;flex-direction:column;gap:4px;font-size:9px;color:#817b73;flex:1;min-width:110px;max-width:190px}.sl-filters select{width:100%;height:30px;font-size:11px;border:1px solid #dcd7cf;border-radius:5px;padding:4px 7px;background:#fff;color:#373531}.sl-reset{border:0;background:none;color:#7b756c;font-size:10px;cursor:pointer;padding:7px 2px;text-decoration:underline}
.sl-results-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 24px;border-top:1px solid #e5e2dc;border-bottom:1px solid #e5e2dc;background:#efebe4;font-size:10px;color:#817b73}.sl-results-head>div{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}.sl-results-head .sl-button{font-size:10px;padding:5px 8px}.sl-body{display:flex;flex:1;min-height:0;min-width:0;position:relative}.sl-results{flex:1;overflow:auto;min-width:0;position:relative}.sl-table-wrap{min-width:650px}.sl-table{width:100%;border-collapse:collapse;text-align:left;table-layout:fixed}.sl-table th{position:sticky;top:0;background:#f5f2ed;z-index:1;color:#928b81;font-size:9px;font-weight:650;letter-spacing:.03em;padding:10px 8px;border-bottom:1px solid #e5e2dc}.sl-table th:nth-child(2){width:31%}.sl-table th:nth-child(3){width:16%}.sl-table th:nth-child(4){width:23%}.sl-table th:nth-child(5){width:24%}.sl-table .sl-select-cell{width:34px;padding-left:15px;padding-right:0}.sl-table td{padding:11px 8px;vertical-align:middle;border-bottom:1px solid #e5e2dc;color:#46423c;font-size:11px;overflow-wrap:anywhere}.sl-table tr:hover td{background:#ffffffa8}.sl-table tr.selected td{background:#e7efe9}.sl-table small{display:block;font-size:9px;color:#9b9388;margin-top:4px;line-height:1.5}.sl-row-open{background:none;border:0;padding:0;display:flex;align-items:center;gap:9px;cursor:pointer;text-align:left;color:inherit;width:100%}.sl-row-open strong{font-size:11px;font-weight:600;display:block;overflow-wrap:anywhere}.sl-type-mark{display:flex;align-items:center;justify-content:center;width:27px;height:32px;border-radius:4px;background:#e7e2d9;color:#8d8476;font-size:17px;flex-shrink:0}.sl-outcome{font-size:9px;display:inline-block;color:#956b20;background:#f4ead5;border-radius:4px;padding:3px 5px;line-height:1.35}.sl-outcome.sl-ok{background:#e4eee6;color:#39774b}
.sl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:12px;padding:16px}.sl-card{position:relative;border:1px solid #ded8ce;border-radius:8px;background:#fff;overflow:hidden}.sl-card.selected{outline:2px solid var(--sl-accent);outline-offset:-1px}.sl-card-check{position:absolute;top:8px;left:8px;z-index:1;background:#fffffff0;border-radius:4px;padding:3px;display:flex}.sl-card-open{display:block;width:100%;text-align:left;border:0;background:none;cursor:pointer;padding:0;color:inherit}.sl-thumb{display:block;width:100%;height:145px;object-fit:cover;background:#e8e3db}.sl-card-copy{padding:10px}.sl-card-copy strong{display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sl-card-copy small,.sl-card-copy span,.sl-card-copy em{display:block;font-size:9px;color:#8c8478;margin-top:5px;line-height:1.4;font-style:normal}.sl-card-copy em{color:#a17a39}
.sl-detail{width:350px;min-width:350px;border-left:1px solid #dcd7cf;background:#fff;overflow:auto;flex-shrink:0;box-shadow:-3px 0 12px #00000003}.sl-detail-head{display:flex;align-items:center;justify-content:space-between;padding:10px 15px;position:sticky;top:0;background:#ffffffed;z-index:3;border-bottom:1px solid #e5e2dc}.sl-preview{background:#e5e0d8;min-height:150px}.sl-preview-image,.sl-preview-video{display:block;width:100%;max-height:330px;object-fit:contain;background:#161618}.sl-media-fallback{min-height:180px;display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;gap:8px;padding:22px;background:#e9e4dc;color:#938a7c}.sl-media-fallback>span{font-size:40px;line-height:1}.sl-media-fallback strong{font-size:11px;color:#746b5f}.sl-media-fallback p{font-size:10px;line-height:1.5;margin:0;max-width:240px}.sl-media-fallback.sl-compact{height:145px;min-height:145px;padding:0}.sl-detail-content{padding:16px}.sl-file-title{font-size:14px;margin:0 0 10px;overflow-wrap:anywhere;letter-spacing:-.3px}.sl-badges{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px}.sl-pill{display:inline-block;background:#f0ece6;color:#847a6a;border-radius:4px;padding:3px 6px;font-size:9px}.sl-download{display:inline-block;color:var(--sl-accent);font-size:10px;margin-bottom:12px;text-decoration:none;font-weight:600}.sl-facts{display:grid;grid-template-columns:95px minmax(0,1fr);gap:10px 8px;font-size:10px;line-height:1.4}.sl-facts dt{color:#9a9184}.sl-facts dd{margin:0;color:#4e483f;overflow-wrap:anywhere}.sl-facts small{display:block;color:#9a9184;font-size:9px;margin-top:3px;line-height:1.5}.sl-path{overflow-wrap:anywhere;word-break:break-word;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px;line-height:1.5}.sl-section{border-top:1px solid #e5e2dc;margin-top:18px;padding-top:14px}.sl-section h4{font-size:11px;margin:0 0 10px}.sl-reasons{display:flex;flex-wrap:wrap;gap:5px}.sl-reasons>span{font-size:9px;color:#9b7738;background:#f6efdf;border:1px solid #eee2c9;padding:4px 6px;border-radius:4px}.sl-note{font-size:11px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere;color:#6b6256}.sl-help{font-size:10px;color:#938a7c;line-height:1.55;display:block;margin:4px 0 10px}.sl-notice{background:#e9efe7;border:1px solid #d7e1d3;color:#617454;font-size:10px;line-height:1.5;padding:9px 12px;border-radius:5px;margin:8px 16px;display:block;position:relative}.sl-notice .sl-icon{position:absolute;right:5px;top:5px}.sl-notice p{margin:4px 0 0}.sl-detail .sl-notice{margin:12px 0}.sl-history{border-left:2px solid #ded8cd;padding:0 0 0 9px;margin:12px 0;font-size:10px}.sl-history strong{display:block}.sl-history span{display:block;color:#a1988c;font-size:9px;margin:3px 0}.sl-history p{line-height:1.5;margin:4px 0;overflow-wrap:anywhere}.sl-related{display:block;width:100%;text-align:left;background:#f8f6f2;border:1px solid #e5e2dc;border-radius:5px;padding:7px 8px;margin-top:5px;cursor:pointer;color:#5f574b}.sl-related span{display:block;overflow-wrap:anywhere;font-size:10px}.sl-related small{display:block;font-size:9px;color:#a1988c;margin-top:3px}
.sl-review-form{display:flex;flex-direction:column;gap:10px}.sl-review-form>label,.sl-two>label{display:flex;flex-direction:column;gap:5px;font-size:10px;font-weight:600;color:#766d60}.sl-review-form input:not([type=file]),.sl-review-form textarea,.sl-review-form select{width:100%;border:1px solid #d9d2c7;border-radius:5px;background:#fff;padding:7px 8px;outline-color:var(--sl-accent);font-size:11px;color:#453e34;font-weight:400}.sl-review-form textarea{resize:vertical;min-height:48px;line-height:1.5}.sl-review-form input[type=file]{font-size:10px;font-weight:400;max-width:100%}.sl-review-form .sl-help{font-weight:400;margin:0}.sl-two{display:grid;grid-template-columns:1fr 1fr;gap:8px}.sl-success{color:#39774b;background:#e5f0e6;border-radius:5px;padding:9px;font-size:10px;line-height:1.5;margin:0}.sl-alert{border:1px solid #ebc5bd;background:#fff0ed;color:#a04f40;border-radius:6px;padding:12px;margin:10px 16px;font-size:11px;line-height:1.5;overflow-wrap:anywhere}.sl-alert p{margin:5px 0}.sl-alert .sl-button{display:block;margin-top:9px}.sl-review-form .sl-alert,.sl-dialog-body>.sl-alert{margin:0}.sl-footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 18px;border-top:1px solid #ded8ce;background:#fff;font-size:10px;color:#92887a}.sl-footer>div{display:flex;align-items:center;gap:9px}.sl-footer small{font-size:9px;color:#aaa194}.sl-footer .sl-button{padding:5px 8px;font-size:10px}.sl-empty{padding:45px 24px;text-align:center;color:#938a7c;max-width:550px;margin:auto}.sl-empty>span{font-size:35px;color:#b7ae9f}.sl-empty h3{font-size:15px;color:#6e6456;margin:12px 0 7px;font-weight:600}.sl-empty p{font-size:11px;line-height:1.6;margin-bottom:15px}.sl-placeholder{padding:40px 20px;text-align:center;color:#9a9184;font-size:12px}.sl-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
.sl-overlay{position:absolute;inset:0;background:#1f1c1770;z-index:25;display:flex;align-items:center;justify-content:center;padding:22px;backdrop-filter:blur(3px)}.sl-dialog{display:flex;flex-direction:column;max-height:94%;width:min(520px,100%);background:#fff;border:1px solid #e5e2dc;border-radius:12px;box-shadow:0 18px 70px #00000035;overflow:hidden}.sl-dialog-wide{width:min(790px,100%)}.sl-dialog-head{display:flex;align-items:center;justify-content:space-between;padding:13px 17px;border-bottom:1px solid #e5e2dc;background:#f8f6f2}.sl-dialog-head h3{font-size:14px;margin:0;letter-spacing:-.3px}.sl-dialog-body{padding:18px;overflow:auto}.sl-dialog-body>.sl-notice{margin:12px 0}.sl-preview-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.sl-preview-summary>div{background:#f5f2ed;border:1px solid #e5e2dc;border-radius:6px;padding:11px}.sl-preview-summary span{display:block;font-size:9px;color:#9a9184}.sl-preview-summary strong{display:block;font-size:20px;margin-top:5px;letter-spacing:-.5px}.sl-plan-paths>div{padding:13px 0;border-top:1px solid #e5e2dc}.sl-plan-paths p{color:#a1988c;margin:5px 0}.sl-plan-paths strong{display:block;color:#5e6e51;font-weight:500}.sl-plan-paths small{display:block;color:#aa7936;margin-top:6px}
@media(max-width:1150px){.sl-header{padding:16px}.sl-metrics{margin:12px 16px 10px}.sl-toolbar{margin:0 16px 10px}.sl-filters{padding:0 16px 10px}.sl-results-head{padding:9px 16px}.sl-detail{position:absolute;right:0;top:0;bottom:0;width:min(390px,100%);min-width:0;z-index:5;box-shadow:-12px 0 35px #00000019}.sl-metrics>div{display:block;padding:10px}.sl-metrics strong{display:block;margin-top:4px}.sl-footer>span small{display:none}}
@media(max-width:760px){.sl-header{padding:12px;align-items:flex-start}.sl-header h2{font-size:22px}.sl-header p{font-size:10px;max-width:190px}.sl-header-actions{gap:5px;max-width:160px}.sl-header-actions .sl-button{font-size:9px;padding:5px 6px}.sl-local{font-size:9px}.sl-metrics{margin:10px 12px;gap:0}.sl-metrics>div{padding:8px;border-right:1px solid #e5e2dc}.sl-metrics span{font-size:8px}.sl-metrics strong{font-size:17px}.sl-toolbar{margin:0 12px 8px;gap:6px}.sl-search input{font-size:10px}.sl-view-switch button{font-size:9px;padding:6px}.sl-filters{padding:0 12px 9px;gap:6px;max-height:120px;overflow:auto}.sl-filters label{min-width:95px;max-width:none;font-size:8px}.sl-filters select{font-size:10px;height:28px}.sl-results-head{padding:7px 12px;font-size:9px;align-items:flex-start}.sl-results-head>span{padding-top:4px}.sl-results-head>div{max-width:220px}.sl-results-head .sl-button{font-size:9px}.sl-footer{padding:8px 10px;font-size:9px;flex-wrap:wrap}.sl-footer>div{margin-left:auto;gap:5px}.sl-footer .sl-button{font-size:9px;padding:5px}.sl-overlay{padding:10px}.sl-dialog{max-height:98%}.sl-preview-summary{gap:5px}.sl-preview-summary>div{padding:8px}.sl-preview-summary strong{font-size:16px}.sl-two{grid-template-columns:1fr}.sl-grid{padding:12px;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:9px}}

/* --- Footwear Search Pilot Tabs & Styling --- */
.sl-nav-tabs{display:flex;gap:6px;margin-top:10px}
.sl-nav-tab{background:#eee9e0;border:1px solid #dcd7cf;color:#6b6459;padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;transition:all 0.15s ease}
.sl-nav-tab:hover{background:#e4ded4;color:#1c1c1e}
.sl-nav-tab.active{background:var(--sl-accent);color:#fff;border-color:var(--sl-accent);box-shadow:0 1px 3px rgba(0,0,0,0.12)}

.sl-pilot-wrap{display:flex;flex-direction:column;flex:1;min-height:0;overflow:auto;padding:16px 24px;gap:14px}
.sl-pilot-banner{background:#fff;border:1px solid #e5e2dc;border-radius:8px;padding:14px 16px;display:flex;flex-direction:column;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04)}
.sl-pilot-banner-content strong{display:block;font-size:14px;color:#1c1c1e;margin:4px 0 2px}
.sl-pilot-banner-content p{margin:0;font-size:11px;color:#6b6864;line-height:1.4}
.sl-pilot-banner-content code{background:#f0ede7;padding:2px 5px;border-radius:4px;font-size:10px}
.sl-pilot-badge{display:inline-block;background:#e5f0e6;color:#2e7545;font-size:9px;font-weight:700;letter-spacing:0.08em;padding:2px 6px;border-radius:4px}
.sl-pilot-presets{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding-top:8px;border-top:1px solid #f0ede7}
.sl-preset-label{font-size:10px;color:#8c8780;font-weight:600}
.sl-pill-btn{background:#f5f2ed;border:1px solid #dcd7cf;border-radius:12px;padding:4px 9px;font-size:10px;font-weight:500;color:#46423c;cursor:pointer;transition:background 0.12s ease}
.sl-pill-btn:hover{background:#e7e2d9;border-color:#beb7ab}

.sl-pilot-toolbar{display:flex}
.sl-pilot-search-box{background:#fff;border:1px solid #dcd7cf;border-radius:8px;padding:0 12px;box-shadow:0 1px 2px rgba(0,0,0,0.03)}
.sl-pilot-search-box input{padding:12px 0;font-size:13px}

.sl-pilot-filters-card{display:grid;grid-template-columns:220px 190px 1fr;gap:16px;background:#fff;border:1px solid #e5e2dc;border-radius:8px;padding:14px 16px}
.sl-pilot-filter-group{display:flex;flex-direction:column;gap:6px}
.sl-pilot-label{font-size:10px;font-weight:700;letter-spacing:0.04em;color:#766d60;text-transform:uppercase}
.sl-pilot-select{height:34px;border:1px solid #dcd7cf;border-radius:6px;padding:0 8px;font-size:11px;background:#fff;color:#1c1c1e}
.sl-pilot-years-header{display:flex;align-items:center;justify-content:space-between}
.sl-pilot-year-actions{display:flex;align-items:center;gap:4px;font-size:10px}
.sl-link-btn{background:none;border:0;color:var(--sl-accent);font-size:10px;cursor:pointer;padding:0 2px;font-weight:600}
.sl-link-btn:hover{text-decoration:underline}
.sl-sep{color:#bcb5aa}
.sl-pilot-checkboxes{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.sl-pilot-checkbox-label{display:flex;align-items:center;gap:5px;background:#f5f2ed;border:1px solid #ded8ce;padding:5px 9px;border-radius:6px;cursor:pointer;font-size:11px;color:#373531;user-select:none;transition:all 0.12s ease}
.sl-pilot-checkbox-label.checked{background:#e8f0ec;border-color:#b4cebe;color:#1b5731;font-weight:600}
.sl-pilot-checkbox-label input{margin:0;cursor:pointer}
.sl-pilot-warning{font-size:10px;color:#ba3a2a;font-style:italic;margin-top:2px}

.sl-pilot-results-bar{display:flex;align-items:baseline;justify-content:space-between;padding:4px 2px}
.sl-pilot-count{font-size:13px;font-weight:700;color:#1c1c1e}
.sl-pilot-subtext{font-size:10px;color:#8c8780}

.sl-pilot-results-container{flex:1;min-height:0}
.sl-pilot-cards-grid{display:grid;grid-template-columns:repeat(auto-fill, minmax(320px, 1fr));gap:14px;padding-bottom:24px}
.sl-pilot-thumb-wrap{position:relative;width:100%;height:200px;background:#f0ede7;border-radius:6px;overflow:hidden;display:flex;align-items:center;justify-content:center;border:1px solid #e5e2dc}
.sl-pilot-thumb{width:100%;height:100%;object-fit:cover;display:block}
.sl-pilot-photo-tag{position:absolute;bottom:8px;left:8px;font-size:9px;font-weight:700;border-radius:4px;padding:3px 7px;text-transform:uppercase;letter-spacing:0.04em}
.sl-pilot-photo-tag.in-store{background:rgba(21,128,61,0.92);color:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.25)}
.sl-pilot-photo-tag.studio{background:rgba(126,34,206,0.92);color:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.25)}
.sl-pilot-camera-tag{display:flex;align-items:center;gap:4px;font-size:10px;color:#766d60;margin-top:3px;font-weight:500}
.sl-pilot-camera-tag small{color:#9c9489}

.sl-pilot-card{background:#fff;border:1px solid #ded8ce;border-radius:8px;padding:14px 16px;display:flex;flex-direction:column;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04);transition:transform 0.1s ease, box-shadow 0.1s ease}
.sl-pilot-card:hover{border-color:#bcb5aa;box-shadow:0 3px 8px rgba(0,0,0,0.07)}

.sl-pilot-card-header{display:flex;flex-direction:column;gap:4px}
.sl-pilot-card-title-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
.sl-pilot-type-pill{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.04em;padding:3px 7px;border-radius:4px}
.sl-pilot-type-pill.solo{background:#e3f2fd;color:#1565c0}
.sl-pilot-type-pill.wall{background:#f3e5f5;color:#7b1fa2}
.sl-pilot-date-badge{font-size:10px;font-weight:700;background:#fff8e1;color:#f57f17;padding:3px 7px;border-radius:4px;border:1px solid #ffe082}

.sl-pilot-title{font-size:13px;font-weight:700;color:#1c1c1e;margin:2px 0 0;overflow-wrap:anywhere}
.sl-pilot-store-tag{display:flex;align-items:center;gap:4px;font-size:10px;color:#6b6459;margin-top:2px}
.sl-pilot-store-tag small{color:#9e978d}

.sl-pilot-card-shoes{background:#faf8f5;border:1px solid #ede8e1;border-radius:6px;padding:10px 12px}
.sl-pilot-shoes-header{font-size:9px;font-weight:700;text-transform:uppercase;color:#8c8780;letter-spacing:0.04em;margin-bottom:6px}
.sl-pilot-shoes-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.sl-pilot-shoe-item{display:flex;align-items:baseline;justify-content:space-between;gap:8px;font-size:11px}
.sl-pilot-shoe-main{display:flex;align-items:baseline;gap:5px;flex-wrap:wrap}
.sl-shoe-brand{color:#8c8780;font-size:10px}
.sl-shoe-model{color:#1c1c1e;font-weight:600}
.sl-shoe-colorway{color:#766d60;font-style:italic;font-size:10px}
.sl-pilot-shoe-meta{display:flex;align-items:center;gap:6px;flex-shrink:0}
.sl-sku-code{font-family:ui-monospace,SFMono-Regular,monospace;font-size:10px;background:#ede8e1;padding:2px 5px;border-radius:3px;color:#373531}
.sl-price-badge{background:#e8f5e9;color:#2e7d32;font-weight:600;font-size:10px;padding:2px 5px;border-radius:3px}

.sl-pilot-card-footer{display:flex;align-items:center;justify-content:space-between;gap:8px;border-top:1px solid #f0ede7;padding-top:8px;font-size:9px;color:#a19b91}
.sl-card-file{font-family:ui-monospace,SFMono-Regular,monospace}
`;

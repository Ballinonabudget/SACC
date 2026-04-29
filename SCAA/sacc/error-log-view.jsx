// SACC — Error Repository
// Persistent log of runtime events + pre-documented known errors with resolution steps.

const _EAPI = 'http://localhost:5174';

const CATEGORY_META = {
  config:     { label: 'Config',     color: '#ff9f0a' },
  system:     { label: 'System',     color: '#ff453a' },
  pipeline:   { label: 'Pipeline',   color: '#ff6b35' },
  validation: { label: 'Validation', color: '#ffd60a' },
  renamer:    { label: 'Renamer',    color: '#30d158' },
  preflight:  { label: 'Pre-flight', color: '#64d2ff' },
  api:        { label: 'API',        color: '#bf5af2' },
};

function ErrorLogView({ mode, accent }) {
  const P = SACC_PALETTE;
  const [tab, setTab]         = React.useState('known');   // 'known' | 'history'
  const [data, setData]       = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [filter, setFilter]   = React.useState('all');
  const [search, setSearch]   = React.useState('');
  const [expanded, setExpanded] = React.useState(null);
  const [clearing, setClearing] = React.useState(false);

  const load = React.useCallback(() => {
    setLoading(true);
    fetch(`${_EAPI}/api/errors`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const markResolved = (id) => {
    fetch(`${_EAPI}/api/errors/${id}`, { method: 'PATCH' })
      .then(() => load());
  };

  const clearHistory = () => {
    if (!window.confirm('Clear all error history? This cannot be undone.')) return;
    setClearing(true);
    fetch(`${_EAPI}/api/errors/history`, { method: 'DELETE' })
      .then(() => { load(); setClearing(false); });
  };

  const catColor = (cat) => CATEGORY_META[cat]?.color || P.muted;

  // ── Filter + search ────────────────────────────────────────────────────────
  const known = React.useMemo(() => {
    if (!data?.known) return [];
    return data.known.filter(e => {
      if (filter !== 'all' && e.category !== filter) return false;
      if (search) {
        const q = search.toLowerCase();
        return e.code.toLowerCase().includes(q) ||
               e.title.toLowerCase().includes(q) ||
               e.description.toLowerCase().includes(q);
      }
      return true;
    });
  }, [data, filter, search]);

  const history = React.useMemo(() => {
    if (!data?.history) return [];
    const h = [...data.history].reverse();
    return h.filter(e => {
      if (filter !== 'all' && !e.code?.startsWith(filter)) return false;
      if (search) {
        const q = search.toLowerCase();
        return (e.code || '').toLowerCase().includes(q) ||
               (e.message || '').toLowerCase().includes(q);
      }
      return true;
    });
  }, [data, filter, search]);

  const unresolved = data?.history?.filter(e => !e.resolved).length ?? 0;

  return (
    <div style={{ flex: 1, overflowY: 'auto', background: P.bg, padding: 20,
      display: 'flex', flexDirection: 'column', gap: 14, fontFamily: '-apple-system, sans-serif' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: P.text }}>Error Repository</div>
          <div style={{ fontSize: 11, color: P.muted, fontFamily: 'Space Mono, monospace', marginTop: 2 }}>
            Runtime event log · Pre-documented error codes · Resolution steps
          </div>
        </div>
        {/* Tab switcher */}
        <div style={{ display: 'flex', background: P.border, borderRadius: 8, padding: 2, gap: 2 }}>
          {[
            ['known',   'Known Errors'],
            ['history', `History${unresolved > 0 ? ` (${unresolved})` : ''}`],
          ].map(([id, label]) => (
            <div key={id} onClick={() => setTab(id)}
              style={{ padding: '5px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
                fontWeight: 600, background: tab === id ? P.panel : 'transparent',
                color: tab === id ? P.text : P.muted,
                boxShadow: tab === id ? '0 1px 4px rgba(0,0,0,0.08)' : 'none',
                transition: 'all 0.15s' }}>
              {label}
            </div>
          ))}
        </div>
      </div>

      {/* Search + category filter */}
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search codes, titles, descriptions…"
          style={{ flex: 1, border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
            fontSize: 12, fontFamily: '-apple-system, sans-serif', color: P.text,
            background: P.bg, outline: 'none' }}
        />
        <select
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{ border: `1px solid ${P.border}`, borderRadius: 6, padding: '6px 10px',
            fontSize: 11, fontFamily: 'Space Mono, monospace', color: P.text,
            background: P.bg, outline: 'none', cursor: 'pointer' }}>
          <option value="all">All categories</option>
          {Object.entries(CATEGORY_META).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
      </div>

      {/* ── KNOWN ERRORS TAB ──────────────────────────────────────────────── */}
      {tab === 'known' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {loading && <div style={{ fontSize: 12, color: P.muted }}>Loading…</div>}
          {!loading && known.length === 0 && (
            <div style={{ fontSize: 12, color: P.muted, textAlign: 'center', padding: 24 }}>
              No matching errors
            </div>
          )}
          {known.map(e => {
            const isOpen = expanded === e.code;
            const col = catColor(e.category);
            return (
              <div key={e.code}
                style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10,
                  overflow: 'hidden', transition: 'box-shadow 0.15s',
                  boxShadow: isOpen ? '0 2px 12px rgba(0,0,0,0.08)' : 'none' }}>
                {/* Row header — always visible */}
                <div onClick={() => setExpanded(isOpen ? null : e.code)}
                  style={{ display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px', cursor: 'pointer' }}>
                  <span style={{ fontSize: 10, fontFamily: 'Space Mono, monospace',
                    fontWeight: 700, color: col, minWidth: 36 }}>
                    {e.code}
                  </span>
                  <span style={{ fontSize: 9, fontFamily: 'Space Mono, monospace',
                    color: col, background: col + '18',
                    padding: '2px 6px', borderRadius: 3, minWidth: 72, textAlign: 'center' }}>
                    {CATEGORY_META[e.category]?.label || e.category}
                  </span>
                  <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: P.text }}>
                    {e.title}
                  </span>
                  <span style={{ fontSize: 12, color: P.muted }}>
                    {isOpen ? '▲' : '▼'}
                  </span>
                </div>
                {/* Expanded detail */}
                {isOpen && (
                  <div style={{ padding: '0 14px 14px', display: 'flex', flexDirection: 'column', gap: 10,
                    borderTop: `1px solid ${P.border}` }}>
                    <div style={{ paddingTop: 10 }}>
                      <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace',
                        letterSpacing: '0.06em', marginBottom: 4 }}>DESCRIPTION</div>
                      <div style={{ fontSize: 12, color: P.text, lineHeight: 1.6 }}>
                        {e.description}
                      </div>
                    </div>
                    <div style={{ background: '#34c759' + '12', border: `1px solid #34c75933`,
                      borderRadius: 6, padding: '10px 12px' }}>
                      <div style={{ fontSize: 9, color: '#34c759', fontFamily: 'Space Mono, monospace',
                        letterSpacing: '0.06em', marginBottom: 4 }}>RESOLUTION</div>
                      <div style={{ fontSize: 12, color: P.text, lineHeight: 1.6 }}>
                        {e.resolution}
                      </div>
                    </div>
                    {e.example && (
                      <div style={{ background: '#0d0d0f', borderRadius: 6, padding: '8px 10px' }}>
                        <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace',
                          letterSpacing: '0.06em', marginBottom: 4 }}>EXAMPLE</div>
                        <code style={{ fontSize: 10, fontFamily: 'Space Mono, monospace',
                          color: '#7ae', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                          {e.example}
                        </code>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── HISTORY TAB ───────────────────────────────────────────────────── */}
      {tab === 'history' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 11, color: P.muted }}>
              {data?.history?.length ?? 0} event{data?.history?.length !== 1 ? 's' : ''} logged
              {unresolved > 0 && (
                <span style={{ marginLeft: 8, color: P.error, fontWeight: 600 }}>
                  · {unresolved} unresolved
                </span>
              )}
            </div>
            <Btn onClick={clearHistory} disabled={clearing || !data?.history?.length}>
              {clearing ? '…' : '✕ Clear history'}
            </Btn>
          </div>

          {history.length === 0 && !loading && (
            <div style={{ background: P.panel, border: `1px solid ${P.border}`, borderRadius: 10,
              padding: '32px 20px', textAlign: 'center' }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>✓</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: P.success, marginBottom: 4 }}>
                No errors recorded
              </div>
              <div style={{ fontSize: 11, color: P.muted, lineHeight: 1.6 }}>
                Runtime errors from the pipeline, renamer, and validator are logged here automatically.
              </div>
            </div>
          )}

          {history.map(e => {
            const col = e.resolved ? P.success : P.error;
            const ts  = new Date(e.timestamp).toLocaleString();
            return (
              <div key={e.id}
                style={{ background: P.panel, border: `1px solid ${e.resolved ? P.border : P.error + '44'}`,
                  borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'flex-start', gap: 10,
                  opacity: e.resolved ? 0.65 : 1 }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%',
                  background: col, marginTop: 5, flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                    <span style={{ fontSize: 10, fontFamily: 'Space Mono, monospace',
                      fontWeight: 700, color: col }}>{e.code}</span>
                    <span style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace' }}>
                      {ts}
                    </span>
                    {e.resolved && (
                      <span style={{ fontSize: 9, color: P.success, fontFamily: 'Space Mono, monospace' }}>
                        RESOLVED
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 12, color: P.text, marginBottom: e.context ? 4 : 0,
                    wordBreak: 'break-word' }}>
                    {e.message}
                  </div>
                  {e.context && (
                    <div style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace',
                      wordBreak: 'break-word' }}>
                      {e.context}
                    </div>
                  )}
                </div>
                {!e.resolved && (
                  <button onClick={() => markResolved(e.id)}
                    style={{ fontSize: 10, color: P.success, background: P.success + '15',
                      border: `1px solid ${P.success}33`, borderRadius: 4, padding: '3px 8px',
                      cursor: 'pointer', flexShrink: 0, fontFamily: '-apple-system, sans-serif' }}>
                    Mark resolved
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

window.ErrorLogView = ErrorLogView;

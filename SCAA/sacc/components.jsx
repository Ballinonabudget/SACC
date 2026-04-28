// SACC — Shared UI Primitives & Sidebar
// Exports to window: SidebarNav, DetailPanel, Btn, Tag, SketchImg, SmartFilter, StatsWidget

const SACC_PALETTE = {
  sidebar: '#161618',
  sidebarText: '#ffffffcc',
  sidebarMuted: '#ffffff55',
  sidebarActive: 'rgba(255,255,255,0.12)',
  bg: '#f5f2ed',
  panel: '#ffffff',
  border: '#e5e2dc',
  accent: 'oklch(62% 0.18 45)',     // amber
  accentHover: 'oklch(58% 0.18 45)',
  accentLight: 'oklch(96% 0.04 45)',
  success: '#34c759',
  warning: '#f5a623',
  error: '#ff3b30',
  muted: '#9b9792',
  text: '#1c1c1e',
  textSub: '#6b6864',
};
const P = SACC_PALETTE;

// ── Img placeholder ─────────────────────────────────────────────────────────
function SketchImg({ width, height, label = '', bg = '#ebe7e0', style = {} }) {
  const w = typeof width === 'number' ? width : '100%';
  const h = typeof height === 'number' ? height : height || 120;
  return (
    <div style={{ width: w, height: h, background: bg, position: 'relative',
      overflow: 'hidden', borderRadius: 4, flexShrink: 0, ...style }}>
      <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0 }}>
        <line x1="0" y1="0" x2="100%" y2="100%" stroke="#ccc" strokeWidth="1.2"/>
        <line x1="100%" y1="0" x2="0" y2="100%" stroke="#ccc" strokeWidth="1.2"/>
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontSize: 10, color: '#aaa',
        fontFamily: 'Space Mono, monospace', textAlign: 'center', padding: '0 8px', lineHeight: 1.4 }}>
        {label}
      </div>
    </div>
  );
}

// ── Button ───────────────────────────────────────────────────────────────────
function Btn({ children, primary, danger, ghost, small, onClick, disabled, style = {} }) {
  const base = {
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro", sans-serif',
    fontSize: small ? 11 : 12, fontWeight: 600,
    padding: small ? '4px 10px' : '6px 14px',
    borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
    border: 'none', transition: 'all 0.15s', whiteSpace: 'nowrap',
    opacity: disabled ? 0.4 : 1,
  };
  const variant = primary
    ? { background: P.accent, color: '#fff' }
    : danger
    ? { background: P.error, color: '#fff' }
    : ghost
    ? { background: 'transparent', color: P.textSub, border: `1px solid ${P.border}` }
    : { background: P.panel, color: P.text, border: `1px solid ${P.border}` };
  return (
    <button onClick={disabled ? undefined : onClick}
      style={{ ...base, ...variant, ...style }}>
      {children}
    </button>
  );
}

// ── Tag/Badge ────────────────────────────────────────────────────────────────
function Tag({ children, color, dot, style = {} }) {
  const statusColors = { synced: P.success, pending: P.warning, error: P.error, queued: P.muted, done: P.success, processing: P.warning };
  const bg = statusColors[color] || color || P.muted;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
      background: bg + '22', color: bg, borderRadius: 4,
      padding: '2px 7px', fontSize: 10, fontWeight: 600,
      fontFamily: 'Space Mono, monospace', whiteSpace: 'nowrap', ...style }}>
      {dot && <span style={{ width: 5, height: 5, borderRadius: '50%', background: bg, display: 'inline-block' }} />}
      {children}
    </span>
  );
}

// ── Smart Filter Dropdown ────────────────────────────────────────────────────
function SmartFilter({ label, options, value, onChange }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef();
  React.useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);
  const active = value && value !== 'All';
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button onClick={() => setOpen(o => !o)} style={{
        display: 'flex', alignItems: 'center', gap: 5,
        background: active ? P.accentLight : P.panel,
        color: active ? P.accent : P.textSub,
        border: `1px solid ${active ? P.accent : P.border}`,
        borderRadius: 6, padding: '5px 10px', fontSize: 11, fontWeight: 600,
        fontFamily: '-apple-system, sans-serif', cursor: 'pointer',
      }}>
        <span style={{ color: P.muted, fontSize: 10 }}>{label}</span>
        <span style={{ color: active ? P.accent : P.text }}>{value || 'All'}</span>
        <span style={{ fontSize: 8, color: P.muted }}>▾</span>
      </button>
      {open && (
        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 4,
          background: P.panel, border: `1px solid ${P.border}`, borderRadius: 8,
          boxShadow: '0 8px 24px rgba(0,0,0,0.12)', zIndex: 100, minWidth: 140, overflow: 'hidden' }}>
          {options.map(opt => (
            <div key={opt} onClick={() => { onChange(opt); setOpen(false); }}
              style={{ padding: '8px 14px', fontSize: 12, cursor: 'pointer',
                background: value === opt ? P.accentLight : 'transparent',
                color: value === opt ? P.accent : P.text,
                fontFamily: '-apple-system, sans-serif',
                fontWeight: value === opt ? 600 : 400 }}>
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Sidebar Nav ──────────────────────────────────────────────────────────────
function SidebarNav({ view, setView, mode, setMode, visibleViews, accent,
                      collections, activeCollection, onCollectionSelect, onNewCollection }) {
  const [newColOpen, setNewColOpen] = React.useState(false);
  const [newColName, setNewColName] = React.useState('');

  const navItems = visibleViews || [
    { id: 'gallery',  icon: '⊞', label: 'Archive' },
    { id: 'timeline', icon: '☰', label: 'Timeline' },
    { id: 'import',   icon: '↓', label: 'Import' },
  ];
  const collectionList = collections || [];

  return (
    <div style={{ width: 196, background: P.sidebar, display: 'flex',
      flexDirection: 'column', height: '100%', userSelect: 'none' }}>

      {/* Traffic lights */}
      <div style={{ padding: '14px 16px 10px', display: 'flex', alignItems: 'center', gap: 6 }}>
        {['#ff5f56', '#ffbd2e', '#27c93f'].map((c, i) => (
          <div key={i} style={{ width: 12, height: 12, borderRadius: '50%', background: c }} />
        ))}
        <span style={{ marginLeft: 8, fontSize: 12, fontWeight: 700, color: P.sidebarText,
          fontFamily: '-apple-system, sans-serif', letterSpacing: '-0.3px' }}>SACC</span>
      </div>

      {/* Search */}
      <div style={{ margin: '4px 10px 8px', background: 'rgba(255,255,255,0.08)',
        borderRadius: 6, padding: '5px 10px', display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: P.sidebarMuted }}>⌕</span>
        <span style={{ fontSize: 12, color: P.sidebarMuted, fontFamily: '-apple-system, sans-serif' }}>Search…</span>
        <span style={{ marginLeft: 'auto', fontSize: 9, color: P.sidebarMuted, fontFamily: 'Space Mono, monospace' }}>⌘K</span>
      </div>

      {/* Nav */}
      <div style={{ padding: '0 8px' }}>
        <div style={{ fontSize: 9, color: P.sidebarMuted, fontFamily: 'Space Mono, monospace',
          padding: '4px 8px 4px', letterSpacing: '0.08em' }}>VIEWS</div>
        {navItems.map(item => (
          <div key={item.id} onClick={() => setView(item.id)}
            style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '7px 10px',
              borderRadius: 6, cursor: 'pointer', marginBottom: 1,
              background: view === item.id ? P.sidebarActive : 'transparent',
              color: view === item.id ? '#fff' : P.sidebarText,
              fontFamily: '-apple-system, sans-serif', fontSize: 13, fontWeight: view === item.id ? 600 : 400,
              transition: 'background 0.1s' }}>
            <span style={{ fontSize: 14, width: 18, textAlign: 'center' }}>{item.icon}</span>
            {item.label}
            {item.id === 'import' && (
              <span style={{ marginLeft: 'auto', background: P.warning + '33', color: P.warning,
                borderRadius: 10, padding: '0px 6px', fontSize: 10, fontWeight: 700 }}>3</span>
            )}
          </div>
        ))}
      </div>

      {/* Collections */}
      <div style={{ padding: '8px 8px 0', marginTop: 8 }}>
        <div style={{ fontSize: 9, color: P.sidebarMuted, fontFamily: 'Space Mono, monospace',
          padding: '4px 8px 4px', letterSpacing: '0.08em' }}>COLLECTIONS</div>
        {collectionList.map(c => {
          const isActive = activeCollection === c.id;
          return (
            <div key={c.id} onClick={() => onCollectionSelect?.(c)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px',
                borderRadius: 6, cursor: 'pointer',
                background: isActive ? 'rgba(255,255,255,0.12)' : 'transparent',
                color: isActive ? '#fff' : P.sidebarText,
                fontFamily: '-apple-system, sans-serif', fontSize: 12,
                fontWeight: isActive ? 600 : 400,
                transition: 'background 0.1s' }}>
              <span style={{ fontSize: 11, opacity: 0.7 }}>▤</span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {c.name}
              </span>
              {c.count != null && (
                <span style={{ fontSize: 9, color: P.sidebarMuted, fontFamily: 'Space Mono, monospace' }}>
                  {c.count}
                </span>
              )}
            </div>
          );
        })}

        {/* New Collection inline form */}
        {newColOpen ? (
          <div style={{ padding: '6px 10px' }}>
            <input
              autoFocus
              value={newColName}
              onChange={e => setNewColName(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && newColName.trim()) {
                  onNewCollection?.(newColName.trim());
                  setNewColName(''); setNewColOpen(false);
                }
                if (e.key === 'Escape') { setNewColName(''); setNewColOpen(false); }
              }}
              placeholder="Collection name…"
              style={{ width: '100%', fontSize: 11, padding: '4px 7px', borderRadius: 4,
                border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.08)',
                color: '#fff', fontFamily: '-apple-system, sans-serif', outline: 'none',
                boxSizing: 'border-box' }}
            />
            <div style={{ fontSize: 9, color: P.sidebarMuted, marginTop: 3,
              fontFamily: 'Space Mono, monospace' }}>↵ save · Esc cancel</div>
          </div>
        ) : (
          <div onClick={() => setNewColOpen(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px',
              borderRadius: 6, cursor: 'pointer', color: P.sidebarMuted,
              fontFamily: '-apple-system, sans-serif', fontSize: 12,
              transition: 'color 0.1s' }}>
            <span style={{ fontSize: 14, lineHeight: 1 }}>+</span> New Collection
          </div>
        )}
      </div>

      {/* Bottom */}
      <div style={{ marginTop: 'auto', padding: '8px 8px 12px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
        {/* Pro/Lite toggle */}
        <div style={{ margin: '0 2px 8px', background: 'rgba(255,255,255,0.06)', borderRadius: 8, padding: 3,
          display: 'flex' }}>
          {['Pro', 'Lite'].map(m => (
            <div key={m} onClick={() => setMode(m.toLowerCase())}
              style={{ flex: 1, textAlign: 'center', padding: '5px 0', borderRadius: 6, cursor: 'pointer',
                background: mode === m.toLowerCase() ? P.accent : 'transparent',
                color: mode === m.toLowerCase() ? '#fff' : P.sidebarMuted,
                fontFamily: '-apple-system, sans-serif', fontSize: 11, fontWeight: 600,
                transition: 'all 0.2s' }}>
              {m}
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px',
          borderRadius: 6, cursor: 'pointer', color: P.sidebarMuted,
          fontFamily: '-apple-system, sans-serif', fontSize: 12 }}>
          ⚙ Settings
        </div>
      </div>
    </div>
  );
}

// ── Stats Widget (secondary) ─────────────────────────────────────────────────
function StatsWidget({ sneakers }) {
  const synced = sneakers.filter(s => s.status === 'synced').length;
  const brands = [...new Set(sneakers.map(s => s.brand))].length;
  const totalRetail = sneakers.reduce((a, s) => a + s.retail, 0);
  return (
    <div style={{ display: 'flex', gap: 1, background: P.border, borderRadius: 8,
      overflow: 'hidden', border: `1px solid ${P.border}` }}>
      {[
        [sneakers.length, 'Entries'],
        [brands, 'Brands'],
        [`$${(totalRetail / 1000).toFixed(1)}k`, 'Retail'],
        [synced, 'Synced'],
      ].map(([v, l]) => (
        <div key={l} style={{ background: P.panel, padding: '6px 14px', textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif', lineHeight: 1 }}>{v}</div>
          <div style={{ fontSize: 9, color: P.muted, fontFamily: 'Space Mono, monospace', marginTop: 1 }}>{l}</div>
        </div>
      ))}
    </div>
  );
}

// ── Detail Panel ──────────────────────────────────────────────────────────────
function DetailPanel({ sneaker, mode, onClose }) {
  const [jsonOpen, setJsonOpen] = React.useState(false);
  const [scrubPct, setScrubPct] = React.useState(14);

  if (!sneaker) {
    return (
      <div style={{ width: 264, background: P.panel, borderLeft: `1px solid ${P.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column',
        gap: 8, color: P.muted, fontFamily: '-apple-system, sans-serif' }}>
        <span style={{ fontSize: 32, opacity: 0.3 }}>◉</span>
        <span style={{ fontSize: 12 }}>Select an entry</span>
      </div>
    );
  }

  const statusColor = { synced: P.success, pending: P.warning, error: P.error };

  return (
    <div style={{ width: 264, background: P.panel, borderLeft: `1px solid ${P.border}`,
      display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{ padding: '10px 14px', borderBottom: `1px solid ${P.border}`,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif' }}>Detail</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <Tag color={sneaker.status} dot>{sneaker.status}</Tag>
          <span onClick={onClose} style={{ fontSize: 16, cursor: 'pointer', color: P.muted, lineHeight: 1 }}>×</span>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* Photo */}
        <SketchImg height={150} label={`sneaker photo\n${sneaker.name}`} />

        {/* Name & brand */}
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: P.text, fontFamily: '-apple-system, sans-serif', lineHeight: 1.3 }}>
            {sneaker.name}
          </div>
          <div style={{ fontSize: 11, color: P.muted, fontFamily: '-apple-system, sans-serif', marginTop: 2 }}>
            {sneaker.brand} · {sneaker.sku}
          </div>
          {sneaker.loc && window.SACC_DATA?.locations?.[sneaker.loc] && (
            <div style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace', marginTop: 2 }}>
              {sneaker.loc}-{window.SACC_DATA.locations[sneaker.loc].type} · {window.SACC_DATA.locations[sneaker.loc].name}
            </div>
          )}
          <div style={{ marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {sneaker.tags.map(t => (
              <span key={t} style={{ background: P.bg, border: `1px solid ${P.border}`, borderRadius: 4,
                padding: '1px 6px', fontSize: 10, color: P.textSub, fontFamily: '-apple-system, sans-serif' }}>
                {t}
              </span>
            ))}
          </div>
        </div>

        {/* Metadata */}
        <div style={{ background: P.bg, borderRadius: 8, padding: '10px 12px',
          display: 'flex', flexDirection: 'column', gap: 7 }}>
          {[
            ['Colorway', sneaker.colorway],
            ['Silhouette', sneaker.silhouette || sneaker.model || '—'],
            ['Retail', `$${sneaker.retail}`],
            ['Release', sneaker.release],
            ['SKU', sneaker.sku || '—'],
            ['Cam', sneaker.camModel || '—'],
            ['File', (window.buildSACCFilename && sneaker.loc)
              ? (window.buildSACCFilename({ locCode: sneaker.loc, identifier: sneaker.name, camModel: sneaker.camModel, origFile: sneaker.origFile, ext: sneaker.ext }) || sneaker.file || sneaker.origFile || '—')
              : (sneaker.file || sneaker.origFile || '—')],
          ].map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
              <span style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace', flexShrink: 0 }}>{k}</span>
              <span style={{ fontSize: 11, fontWeight: 600, color: P.text, textAlign: 'right',
                fontFamily: k === 'File' ? 'Space Mono, monospace' : '-apple-system, sans-serif',
                wordBreak: 'break-all', lineHeight: 1.3 }}>{v}</span>
            </div>
          ))}
        </div>

        {/* Video Timestamp Scrubber */}
        <div style={{ background: '#0d0d0f', borderRadius: 8, padding: 10 }}>
          <div style={{ fontSize: 9, color: '#666', fontFamily: 'Space Mono, monospace', marginBottom: 8 }}>VIDEO TIMESTAMP</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <div style={{ background: P.accent, borderRadius: 4, padding: '4px 10px',
              fontFamily: 'Space Mono, monospace', fontSize: 13, fontWeight: 700, color: '#fff', cursor: 'pointer' }}>
              ▶ {sneaker.ts}
            </div>
            <span style={{ fontSize: 10, color: '#555', fontFamily: '-apple-system, sans-serif' }}>{sneaker.file}</span>
          </div>
          {/* Scrubber track */}
          <div style={{ position: 'relative', height: 20, cursor: 'pointer' }}
            onClick={e => {
              const rect = e.currentTarget.getBoundingClientRect();
              setScrubPct(Math.round((e.clientX - rect.left) / rect.width * 100));
            }}>
            <div style={{ position: 'absolute', top: 7, left: 0, right: 0, height: 4,
              background: '#333', borderRadius: 2 }}>
              <div style={{ width: `${scrubPct}%`, height: '100%', background: P.accent, borderRadius: 2 }} />
            </div>
            {/* Timestamp marker */}
            <div style={{ position: 'absolute', top: 2, left: `${scrubPct}%`, transform: 'translateX(-50%)',
              width: 10, height: 10, borderRadius: '50%', background: '#fff', border: `2px solid ${P.accent}` }} />
          </div>
        </div>

        {/* JSON preview (Pro only) */}
        {mode === 'pro' && (
          <div>
            <div onClick={() => setJsonOpen(o => !o)}
              style={{ fontSize: 10, color: P.muted, fontFamily: 'Space Mono, monospace',
                cursor: 'pointer', display: 'flex', justifyContent: 'space-between', padding: '0 2px' }}>
              JSON RECORD <span>{jsonOpen ? '▲' : '▼'}</span>
            </div>
            {jsonOpen && (
              <div style={{ background: '#0d0d0f', borderRadius: 6, padding: 10, marginTop: 6 }}>
                <pre style={{ fontSize: 9, fontFamily: 'Space Mono, monospace', color: '#7ae', lineHeight: 1.7, margin: 0 }}>
{JSON.stringify({
  id: sneaker.id,
  sku: sneaker.sku,
  silhouette: sneaker.silhouette,
  colorway: sneaker.colorway,
  retail: sneaker.retail,
  release: sneaker.release,
  loc: sneaker.loc,
  loc_type: window.SACC_DATA?.locations?.[sneaker.loc]?.type,
  cam: sneaker.camModel,
  ts: sneaker.ts,
  file: (window.buildSACCFilename && sneaker.loc)
    ? window.buildSACCFilename({ locCode: sneaker.loc, identifier: sneaker.name, camModel: sneaker.camModel, origFile: sneaker.origFile, ext: sneaker.ext })
    : (sneaker.file || sneaker.origFile || null),
  status: sneaker.status,
}, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Actions */}
      <div style={{ padding: '10px 14px', borderTop: `1px solid ${P.border}`, display: 'flex', gap: 6 }}>
        <Btn ghost small style={{ flex: 1 }}>✎ Edit</Btn>
        <Btn primary small style={{ flex: 1 }}>↗ Export</Btn>
      </div>
    </div>
  );
}

Object.assign(window, { SidebarNav, DetailPanel, Btn, Tag, SketchImg, SmartFilter, StatsWidget, SACC_PALETTE });

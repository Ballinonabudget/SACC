// SACC — Gallery View
// + Temporal search: SKU · model · colorway · date · location · tag → timestamps
// Exports: GalleryView

function GalleryView({ sneakers, selectedId, onSelect, filters, setFilters, mode, searchQuery, setSearchQuery }) {
  const P = SACC_PALETTE;

  // Search — runs against full sneaker dataset, bypasses dropdown filters
  const searchResults = React.useMemo(
    () => searchSneakers(sneakers, searchQuery),
    [sneakers, searchQuery]
  );
  const isSearching = searchQuery && searchQuery.trim().length > 0;
  const displayList = isSearching ? searchResults : null; // null = use dropdown filters

  const brands = ['All', ...new Set(sneakers.map(s => s.brand || s.silhouette?.split(' ')[0] || 'Unknown'))];
  const years  = ['All', ...new Set(sneakers.map(s => s.release.slice(0,4))).values()].sort().reverse();
  const sorts  = ['Date ↓', 'Date ↑', 'Price ↓', 'Price ↑', 'Name A–Z'];
  const statuses = ['All', 'synced', 'pending', 'error'];

  const dropdownFiltered = sneakers.filter(s => {
    if (filters.brand !== 'All' && s.brand !== filters.brand) return false;
    if (filters.year  !== 'All' && !s.release.startsWith(filters.year)) return false;
    if (filters.status !== 'All' && s.status !== filters.status) return false;
    return true;
  }).sort((a, b) => {
    switch (filters.sort) {
      case 'Date ↑': return a.release.localeCompare(b.release);
      case 'Price ↓': return b.retail - a.retail;
      case 'Price ↑': return a.retail - b.retail;
      case 'Name A–Z': return a.name.localeCompare(b.name);
      default: return b.release.localeCompare(a.release);
    }
  });

  // When searching, bypass dropdown filters and use search results directly
  const filtered = isSearching ? searchResults : dropdownFiltered;

  const starColor = s => s.rating === 5 ? P.accent : P.muted;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: P.bg }}>

      {/* Toolbar */}
      <div style={{ padding: '8px 14px', borderBottom: `1px solid ${P.border}`,
        background: P.panel, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>

        {/* Search bar — takes priority over dropdown filters when active */}
        <SearchBar
          value={searchQuery}
          onChange={setSearchQuery}
          resultCount={searchResults.length}
          onClear={() => setSearchQuery('')}
        />

        {/* Dropdown filters — dimmed when search is active */}
        {!isSearching && (
          <>
            <SmartFilter label="Brand:" options={brands} value={filters.brand} onChange={v => setFilters(f => ({...f, brand: v}))} />
            <SmartFilter label="Year:" options={years} value={filters.year} onChange={v => setFilters(f => ({...f, year: v}))} />
            <SmartFilter label="Status:" options={statuses} value={filters.status} onChange={v => setFilters(f => ({...f, status: v}))} />
            <SmartFilter label="Sort:" options={sorts} value={filters.sort} onChange={v => setFilters(f => ({...f, sort: v}))} />
          </>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <StatsWidget sneakers={sneakers} />
        </div>
      </div>

      {/* Timestamp results bar — shown only during active search */}
      {isSearching && (
        <TimestampResultsBar
          results={searchResults}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      )}

      {/* Count bar */}
      <div style={{ padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, color: P.muted, fontFamily: 'Space Mono, monospace' }}>
          {isSearching
            ? `${filtered.length} search result${filtered.length !== 1 ? 's' : ''}`
            : `${filtered.length} of ${sneakers.length} entries`}
        </span>
        {!isSearching && Object.entries(filters).some(([k, v]) => k !== 'sort' && v !== 'All') && (
          <span onClick={() => setFilters({ brand: 'All', year: 'All', status: 'All', sort: 'Date ↓' })}
            style={{ fontSize: 10, color: P.accent, cursor: 'pointer', fontFamily: '-apple-system, sans-serif' }}>
            Clear filters ×
          </span>
        )}
      </div>

      {/* Grid */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 14px 14px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(162px, 1fr))', gap: 10 }}>
          {filtered.map(s => {
            const selected = s.id === selectedId;
            const statusColor = { synced: P.success, pending: P.warning, error: P.error };
            return (
              <div key={s.id} onClick={() => onSelect(s.id)}
                style={{ background: P.panel, borderRadius: 10, overflow: 'hidden', cursor: 'pointer',
                  border: `1.5px solid ${selected ? P.accent : P.border}`,
                  boxShadow: selected ? `0 0 0 2px ${P.accent}33` : '0 1px 4px rgba(0,0,0,0.05)',
                  transition: 'all 0.15s' }}>
                <div style={{ position: 'relative' }}>
                  <SketchImg height={110} bg={selected ? 'oklch(96% 0.04 45)' : '#ebe7e0'} />
                  <div style={{ position: 'absolute', top: 6, right: 6,
                    background: 'rgba(0,0,0,0.65)', color: '#fff', borderRadius: 4,
                    padding: '2px 6px', fontSize: 9, fontFamily: 'Space Mono, monospace' }}>
                    ⏱ {s.ts}
                  </div>
                  <div style={{ position: 'absolute', top: 6, left: 6,
                    width: 7, height: 7, borderRadius: '50%',
                    background: statusColor[s.status],
                    boxShadow: `0 0 0 2px ${P.panel}` }} />
                </div>
                <div style={{ padding: '8px 10px 10px' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: P.text,
                    fontFamily: '-apple-system, sans-serif', lineHeight: 1.3, marginBottom: 2 }}>
                    {s.name}
                  </div>
                  <div style={{ fontSize: 10, color: P.textSub, fontFamily: '-apple-system, sans-serif', marginBottom: 6 }}>
                    {s.brand || 'Jordan Brand'}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: P.text, fontFamily: 'Space Mono, monospace' }}>
                      ${s.retail}
                    </span>
                    <span style={{ fontSize: 11, color: starColor(s) }}>
                      {'★'.repeat(s.rating)}{'☆'.repeat(5 - s.rating)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: 60, color: P.muted,
            fontFamily: '-apple-system, sans-serif', fontSize: 13 }}>
            No entries match these filters.
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { GalleryView });

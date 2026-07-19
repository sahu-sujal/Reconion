import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { gfApi } from '../api/gf'
import { scopesApi } from '../api/scopes'
import { ChevronRightIcon, SearchIcon } from '../components/icons'
import GfAssetDrawer from '../components/GfAssetDrawer'

const PAGE_SIZE = 100
const ASSET_TYPES = ['URL', 'ENDPOINT']
const QUEUE_TOOLS = [
  { id: 'nuclei', label: 'Queue for Nuclei' },
  { id: 'dalfox', label: 'Queue for Dalfox' },
  { id: 'ghauri', label: 'Queue for Ghauri' },
  { id: 'custom', label: 'Queue for Custom Scan' },
]

function num(n) {
  return (n ?? 0).toLocaleString()
}

function StatCard({ label, value, tone }) {
  return (
    <div className={`gf-stat-card${tone ? ` ${tone}` : ''}`}>
      <span className="gf-stat-value">{num(value)}</span>
      <span className="gf-stat-label">{label}</span>
    </div>
  )
}

/** Horizontal bar list used for the statistics charts. */
function BarList({ title, rows, labelKey, valueKey, onPick }) {
  const max = Math.max(1, ...rows.map((r) => r[valueKey] || 0))
  if (rows.length === 0) return null
  return (
    <section className="gf-chart">
      <h3 className="dd-section-title">{title}</h3>
      <ul className="gf-bars">
        {rows.map((r, i) => {
          const label = r[labelKey] ?? '—'
          const value = r[valueKey] || 0
          return (
            <li key={`${label}-${i}`}>
              <button
                type="button"
                className="gf-bar-row"
                onClick={onPick ? () => onPick(r) : undefined}
                disabled={!onPick}
              >
                <span className="gf-bar-label" title={String(label)}>
                  {label}
                </span>
                <span className="gf-bar-track">
                  <span
                    className="gf-bar-fill"
                    style={{ width: `${Math.max(2, (value / max) * 100)}%` }}
                  />
                </span>
                <span className="gf-bar-value">{num(value)}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export default function GfIntelligencePage() {
  const { scopeId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()

  const [scope, setScope] = useState(null)
  const [stats, setStats] = useState(null)
  const [categories, setCategories] = useState([])
  const [hosts, setHosts] = useState([])

  const [assets, setAssets] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)

  const [loading, setLoading] = useState(true)
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [error, setError] = useState(null)

  // ---- Filters (multi-select) ----
  const initialCategory = searchParams.get('category')
  const [selectedCategories, setSelectedCategories] = useState(
    initialCategory ? [initialCategory] : [],
  )
  const [selectedHosts, setSelectedHosts] = useState([])
  const [selectedTypes, setSelectedTypes] = useState([])
  const [matchAll, setMatchAll] = useState(false)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [sortBy, setSortBy] = useState('gf_tag_count')
  const [sortDir, setSortDir] = useState('desc')

  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [drawerIdx, setDrawerIdx] = useState(null)
  const [queueMsg, setQueueMsg] = useState(null)

  // Debounce the search box so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search), 350)
    return () => clearTimeout(id)
  }, [search])

  const filters = useMemo(
    () => ({
      // Always scope-bound: GF classification is produced per scope, so this
      // page never queries across scopes.
      scopeId: [scopeId],
      category: selectedCategories.length ? selectedCategories : undefined,
      host: selectedHosts.length ? selectedHosts : undefined,
      assetType: selectedTypes.length ? selectedTypes : undefined,
      matchAll,
      search: debouncedSearch || undefined,
    }),
    [scopeId, selectedCategories, selectedHosts, selectedTypes, matchAll, debouncedSearch],
  )

  // ---- Load dashboard-level data (once per scope) ----
  const loadShell = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const scopeArg = { scopeId: [scopeId] }
      const [scopeData, statsData, cats, hostList] = await Promise.all([
        scopesApi.get(scopeId).catch(() => null),
        gfApi.statistics({ ...scopeArg, top: 10 }).catch(() => null),
        gfApi.categories(scopeArg).catch(() => []),
        gfApi.hosts(scopeArg).catch(() => []),
      ])
      setScope(scopeData)
      setStats(statsData)
      setCategories(Array.isArray(cats) ? cats : [])
      setHosts(Array.isArray(hostList) ? hostList : [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [scopeId])

  useEffect(() => {
    loadShell()
  }, [loadShell])

  // ---- Load the asset page (server-side filter/sort/paginate) ----
  const reqId = useRef(0)
  const loadAssets = useCallback(async () => {
    setAssetsLoading(true)
    const myReq = ++reqId.current
    try {
      const data = await gfApi.assets({
        ...filters,
        sortBy,
        sortDir,
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      })
      // Ignore responses that arrive out of order after a newer request.
      if (myReq !== reqId.current) return
      setAssets(data?.items || [])
      setTotal(data?.total || 0)
    } catch (err) {
      if (myReq === reqId.current) setError(err.message)
    } finally {
      if (myReq === reqId.current) setAssetsLoading(false)
    }
  }, [filters, sortBy, sortDir, page])

  useEffect(() => {
    loadAssets()
  }, [loadAssets])

  // Any filter change resets to the first page and clears the selection.
  useEffect(() => {
    setPage(0)
    setSelectedIds(new Set())
    setDrawerIdx(null)
  }, [filters, sortBy, sortDir])

  // Keep ?category= in the URL so a category view is shareable.
  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    if (selectedCategories.length === 1) next.set('category', selectedCategories[0])
    else next.delete('category')
    setSearchParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategories])

  function toggle(list, setList, value) {
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])
  }

  function toggleSort(column) {
    if (sortBy === column) setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    else {
      setSortBy(column)
      setSortDir('desc')
    }
  }

  function clearFilters() {
    setSelectedCategories([])
    setSelectedHosts([])
    setSelectedTypes([])
    setMatchAll(false)
    setSearch('')
  }

  // ---- Bulk actions ----
  const selectedAssets = assets.filter((a) => selectedIds.has(a.id))

  function toggleRow(id) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAllOnPage() {
    setSelectedIds((prev) => {
      const allSelected = assets.every((a) => prev.has(a.id))
      const next = new Set(prev)
      assets.forEach((a) => (allSelected ? next.delete(a.id) : next.add(a.id)))
      return next
    })
  }

  async function copyUrls() {
    const text = selectedAssets.map((a) => a.url).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setQueueMsg(`Copied ${selectedAssets.length} URL(s) to clipboard.`)
    } catch {
      setQueueMsg('Clipboard unavailable — select and copy manually.')
    }
  }

  async function queueFor(tool) {
    try {
      const res = await gfApi.queueScan({
        assetIds: selectedAssets.map((a) => a.id),
        tool,
      })
      setQueueMsg(`Queued ${res.queued} asset(s) for ${tool}. ${res.detail || ''}`)
    } catch (err) {
      setQueueMsg(`Queue failed: ${err.message}`)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const activeFilters =
    selectedCategories.length > 0 ||
    selectedHosts.length > 0 ||
    selectedTypes.length > 0 ||
    Boolean(debouncedSearch)

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link to="/">Programs</Link>
        <ChevronRightIcon className="crumb-sep" width={14} height={14} />
        {scope?.program_id && (
          <>
            <Link to={`/programs/${scope.program_id}`}>Program</Link>
            <ChevronRightIcon className="crumb-sep" width={14} height={14} />
          </>
        )}
        <Link to={`/scopes/${scopeId}`}>{scope?.target || 'Scope'}</Link>
        <ChevronRightIcon className="crumb-sep" width={14} height={14} />
        <span>GF Intelligence</span>
        {selectedCategories.length === 1 && (
          <>
            <ChevronRightIcon className="crumb-sep" width={14} height={14} />
            <span className="cell-mono">{selectedCategories[0]}</span>
          </>
        )}
      </div>

      <header className="page-header">
        <div>
          <h1>GF Intelligence</h1>
          <p className="subtitle">
            Browse recon results by <strong>security relevance</strong> — every URL and
            endpoint tagged by GF pattern matching.
          </p>
        </div>
      </header>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={loadShell}>
            Retry
          </button>
        </div>
      )}

      {/* ---- Dashboard summary ---- */}
      {stats && (
        <div className="gf-stats">
          <StatCard label="Total Assets Classified" value={stats.classified_assets} />
          <StatCard label="Assets With GF Matches" value={stats.assets_with_matches} tone="hit" />
          <StatCard label="Assets Without Matches" value={stats.assets_without_matches} />
          <StatCard label="Unique GF Categories" value={stats.unique_categories} />
        </div>
      )}

      {/* ---- Categories ---- */}
      <section className="dd-section">
        <h3 className="dd-section-title">GF Categories ({categories.length})</h3>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : categories.length === 0 ? (
          <div className="empty-state">
            <p>
              No GF classifications yet — run a <strong>GF</strong> scan for this scope to
              tag its URLs and endpoints.
            </p>
            <Link to={`/scopes/${scopeId}/scans`} className="btn btn-primary">
              Go to scans
            </Link>
          </div>
        ) : (
          <div className="gf-category-grid">
            {categories.map((c) => {
              const active = selectedCategories.includes(c.category)
              return (
                <button
                  key={c.category}
                  type="button"
                  className={`gf-category-card${active ? ' selected' : ''}`}
                  onClick={() => toggle(selectedCategories, setSelectedCategories, c.category)}
                  aria-pressed={active}
                >
                  <span className="gf-category-name">{c.category}</span>
                  <span className="gf-category-count">{num(c.asset_count)}</span>
                  <span className="gf-category-sub muted">
                    {num(c.url_count)} url · {num(c.endpoint_count)} ep · {num(c.host_count)} hosts
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </section>

      {/* ---- Filters ---- */}
      <div className="filter-bar gf-filter-bar">
        <div className="search-box">
          <SearchIcon className="search-icon" />
          <input
            type="search"
            placeholder="Search URL, endpoint or host…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              type="button"
              className="search-clear"
              onClick={() => setSearch('')}
              aria-label="Clear search"
            >
              ✕
            </button>
          )}
        </div>

        <select
          value=""
          onChange={(e) => e.target.value && toggle(selectedHosts, setSelectedHosts, e.target.value)}
          disabled={hosts.length === 0}
        >
          <option value="">Add host filter…</option>
          {hosts.map((h) => (
            <option key={h} value={h}>
              {h}
            </option>
          ))}
        </select>

        {ASSET_TYPES.map((t) => (
          <button
            key={t}
            type="button"
            className={`btn btn-sm${selectedTypes.includes(t) ? ' btn-primary' : ''}`}
            onClick={() => toggle(selectedTypes, setSelectedTypes, t)}
            aria-pressed={selectedTypes.includes(t)}
          >
            {t}
          </button>
        ))}

        {selectedCategories.length > 1 && (
          <label className="gf-inline-check">
            <input
              type="checkbox"
              checked={matchAll}
              onChange={(e) => setMatchAll(e.target.checked)}
            />
            Match all
          </label>
        )}

        {activeFilters && (
          <button type="button" className="btn btn-sm btn-ghost" onClick={clearFilters}>
            Clear
          </button>
        )}
        <span className="muted result-count">{num(total)} assets</span>
      </div>

      {/* Active filter chips */}
      {(selectedCategories.length > 0 || selectedHosts.length > 0) && (
        <div className="flag-tags wrap gf-active-filters">
          {selectedCategories.map((c) => (
            <button
              key={`c-${c}`}
              type="button"
              className="badge badge-gf removable"
              onClick={() => toggle(selectedCategories, setSelectedCategories, c)}
            >
              {c} ✕
            </button>
          ))}
          {selectedHosts.map((h) => (
            <button
              key={`h-${h}`}
              type="button"
              className="badge badge-type removable"
              onClick={() => toggle(selectedHosts, setSelectedHosts, h)}
            >
              {h} ✕
            </button>
          ))}
        </div>
      )}

      {/* ---- Bulk actions ---- */}
      {selectedAssets.length > 0 && (
        <div className="gf-bulk-bar">
          <span>{selectedAssets.length} selected</span>
          <button type="button" className="btn btn-sm" onClick={copyUrls}>
            Copy URLs
          </button>
          <a
            className="btn btn-sm"
            href={gfApi.exportUrl('csv', filters)}
            target="_blank"
            rel="noreferrer noopener"
          >
            Export CSV
          </a>
          <a
            className="btn btn-sm"
            href={gfApi.exportUrl('json', filters)}
            target="_blank"
            rel="noreferrer noopener"
          >
            Export JSON
          </a>
          {QUEUE_TOOLS.map((t) => (
            <button
              key={t.id}
              type="button"
              className="btn btn-sm"
              onClick={() => queueFor(t.id)}
            >
              {t.label}
            </button>
          ))}
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => setSelectedIds(new Set())}
          >
            Clear selection
          </button>
        </div>
      )}

      {queueMsg && (
        <div className="alert">
          <span>{queueMsg}</span>
          <button type="button" className="btn btn-sm" onClick={() => setQueueMsg(null)}>
            Dismiss
          </button>
        </div>
      )}

      {/* ---- Asset table ---- */}
      {assetsLoading && assets.length === 0 ? (
        <p className="muted">Loading assets…</p>
      ) : assets.length === 0 ? (
        <div className="empty-state">
          <p>No GF-classified assets match the current filters.</p>
          {activeFilters && (
            <button type="button" className="btn" onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="gf-table-wrap">
          <table className="data-table clickable-rows gf-table">
            <thead>
              <tr>
                <th className="gf-check-col">
                  <input
                    type="checkbox"
                    checked={assets.length > 0 && assets.every((a) => selectedIds.has(a.id))}
                    onChange={toggleAllOnPage}
                    aria-label="Select all on page"
                  />
                </th>
                <SortableTh label="URL / Endpoint" column="url" {...{ sortBy, sortDir, toggleSort }} />
                <SortableTh label="Type" column="asset_type" {...{ sortBy, sortDir, toggleSort }} />
                <SortableTh label="Host" column="host" {...{ sortBy, sortDir, toggleSort }} />
                <th>GF Tags</th>
                <th>Status</th>
                <th>Category</th>
                <SortableTh
                  label="Params"
                  column="parameter_count"
                  {...{ sortBy, sortDir, toggleSort }}
                />
                <SortableTh label="Last Seen" column="last_seen" {...{ sortBy, sortDir, toggleSort }} />
                <th />
              </tr>
            </thead>
            <tbody>
              {assets.map((a, i) => (
                <tr key={a.id} className="row-clickable" onClick={() => setDrawerIdx(i)}>
                  <td onClick={(e) => e.stopPropagation()} className="gf-check-col">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(a.id)}
                      onChange={() => toggleRow(a.id)}
                      aria-label={`Select ${a.url}`}
                    />
                  </td>
                  <td className="cell-mono gf-url-cell" title={a.url}>
                    {a.url}
                  </td>
                  <td>
                    <span className="badge badge-type">{a.asset_type}</span>
                  </td>
                  <td className="cell-mono">{a.host || '—'}</td>
                  <td className="gf-tags-cell">
                    <span className="flag-tags">
                      {(a.gf_tags || []).slice(0, 3).map((t) => (
                        <span key={t} className="badge badge-gf">
                          {t}
                        </span>
                      ))}
                      {(a.gf_tags || []).length > 3 && (
                        <span className="muted">+{a.gf_tags.length - 3}</span>
                      )}
                    </span>
                  </td>
                  <td className="cell-mono">{a.status ?? '—'}</td>
                  <td className="muted">{a.asset_category || '—'}</td>
                  <td className="cell-mono">{a.parameter_count ?? 0}</td>
                  <td className="muted">
                    {a.last_seen ? new Date(a.last_seen).toLocaleDateString() : '—'}
                  </td>
                  <td>
                    <ChevronRightIcon className="row-chevron" width={16} height={16} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>

          <div className="pagination">
            <button
              type="button"
              className="btn btn-sm"
              disabled={page === 0 || assetsLoading}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              ← Prev
            </button>
            <span className="muted">
              Page {page + 1} of {num(totalPages)}
              {assetsLoading ? ' · loading…' : ''}
            </span>
            <button
              type="button"
              className="btn btn-sm"
              disabled={page >= totalPages - 1 || assetsLoading}
              onClick={() => setPage((p) => p + 1)}
            >
              Next →
            </button>
          </div>
        </>
      )}

      {/* ---- Statistics ---- */}
      {stats && (
        <div className="gf-charts">
          <BarList
            title="Top GF Categories"
            rows={stats.top_categories || []}
            labelKey="category"
            valueKey="asset_count"
            onPick={(r) => toggle(selectedCategories, setSelectedCategories, r.category)}
          />
          <BarList
            title="Assets per Host"
            rows={stats.assets_per_host || []}
            labelKey="host"
            valueKey="asset_count"
            onPick={(r) => r.host && toggle(selectedHosts, setSelectedHosts, r.host)}
          />
          <BarList
            title="Assets per Program"
            rows={stats.assets_per_program || []}
            labelKey="program_name"
            valueKey="asset_count"
          />
          <BarList
            title="Assets per Scope"
            rows={stats.assets_per_scope || []}
            labelKey="scope_target"
            valueKey="asset_count"
          />
        </div>
      )}

      {drawerIdx != null && assets[drawerIdx] && (
        <GfAssetDrawer
          asset={assets[drawerIdx]}
          scopeId={scopeId}
          position={{ index: page * PAGE_SIZE + drawerIdx, total }}
          onPrev={drawerIdx > 0 ? () => setDrawerIdx((i) => i - 1) : null}
          onNext={drawerIdx < assets.length - 1 ? () => setDrawerIdx((i) => i + 1) : null}
          onClose={() => setDrawerIdx(null)}
        />
      )}
    </div>
  )
}

function SortableTh({ label, column, sortBy, sortDir, toggleSort }) {
  const active = sortBy === column
  return (
    <th>
      <button type="button" className="th-sort" onClick={() => toggleSort(column)}>
        {label}
        {active && <span className="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>}
      </button>
    </th>
  )
}

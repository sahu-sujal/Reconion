import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { endpointsApi, ENDPOINT_TOOLS } from '../api/endpoints'
import { HUNT_CATEGORIES, categorize } from '../lib/huntCategories'

const PAGE_SIZE = 25
// Max rows pulled for client-side hunting categorization (API hard cap).
const HUNT_SAMPLE_LIMIT = 10000

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function ToolBadges({ tools }) {
  if (!tools || tools.length === 0) return <span className="muted">—</span>
  return (
    <span className="src-badges">
      {tools.map((t) => (
        <span key={t} className="badge badge-type src-badge">
          {t}
        </span>
      ))}
    </span>
  )
}

// Sortable column definitions (must match EndpointRepository._SORTABLE).
const COLUMNS = [
  { key: 'normalized_url', label: 'Endpoint', sortable: true },
  { key: 'host', label: 'Host', sortable: true },
  { key: 'source_js', label: 'Source JS', sortable: false },
  { key: 'tools', label: 'Discovery Tools', sortable: false },
  { key: 'first_seen', label: 'First Seen', sortable: true },
  { key: 'last_seen', label: 'Last Seen', sortable: true },
]

/**
 * The unified Endpoint Inventory explorer (Phase 6.1).
 *
 * Two modes:
 *   - scope mode:      pass `scopeId` → lists every endpoint in the scope, with
 *                      an optional host filter dropdown.
 *   - subdomain mode:  pass `subdomainId` (+ `subdomainLabel`) → lists only that
 *                      subdomain's endpoints (host filter is hidden, since the
 *                      host is already fixed).
 */
export default function EndpointExplorer({ scopeId, subdomainId, subdomainLabel }) {
  const subdomainMode = Boolean(subdomainId)

  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [hostFilter, setHostFilter] = useState('')
  const [toolFilter, setToolFilter] = useState('')
  const [sortBy, setSortBy] = useState('normalized_url')
  const [sortDir, setSortDir] = useState('asc')
  const [page, setPage] = useState(0)

  const [data, setData] = useState({ total: 0, items: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

  // ---- Hunt (category) state — mirrors the Content Discovery (URLs) page ----
  const [showHunt, setShowHunt] = useState(true)
  const [activeCat, setActiveCat] = useState('') // '' = no category filter
  const [sample, setSample] = useState([]) // broad slice for client-side categorization
  const [sampleLoading, setSampleLoading] = useState(false)
  const [sampleTruncated, setSampleTruncated] = useState(false)

  // Host filter values (scope mode only).
  const [hosts, setHosts] = useState([])
  useEffect(() => {
    if (subdomainMode || !scopeId) return
    let active = true
    endpointsApi
      .hosts(scopeId)
      .then((list) => active && setHosts(Array.isArray(list) ? list : []))
      .catch(() => active && setHosts([]))
    return () => {
      active = false
    }
  }, [scopeId, subdomainMode])

  // Debounce the search box.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setDebounced(search.trim())
      setPage(0)
    }, 350)
    return () => clearTimeout(debounceRef.current)
  }, [search])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const opts = {
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: debounced || undefined,
        tool: toolFilter || undefined,
        sortBy,
        sortDir,
      }
      const res = subdomainMode
        ? await endpointsApi.bySubdomain(subdomainId, opts)
        : await endpointsApi.byScope(scopeId, { ...opts, host: hostFilter || undefined })
      setData(res || { total: 0, items: [] })
    } catch (err) {
      setError(err.message)
      setData({ total: 0, items: [] })
    } finally {
      setLoading(false)
    }
  }, [scopeId, subdomainId, subdomainMode, debounced, hostFilter, toolFilter, sortBy, sortDir, page])

  useEffect(() => {
    load()
  }, [load])

  // Reset paging when any filter changes.
  useEffect(() => {
    setPage(0)
  }, [hostFilter, toolFilter, sortBy, sortDir])

  // ---- Load a broad sample for client-side hunting categorization ----
  // Reloads whenever the scope/subdomain/host/tool/search changes (NOT on page
  // change — categorization is over the whole filtered result set, not one page).
  useEffect(() => {
    let active = true
    setSampleLoading(true)
    const opts = {
      offset: 0,
      limit: HUNT_SAMPLE_LIMIT,
      search: debounced || undefined,
      tool: toolFilter || undefined,
    }
    const req = subdomainMode
      ? endpointsApi.bySubdomain(subdomainId, opts)
      : endpointsApi.byScope(scopeId, { ...opts, host: hostFilter || undefined })
    req
      .then((res) => {
        if (!active) return
        const items = res?.items || []
        setSample(items)
        setSampleTruncated((res?.total || 0) > items.length)
      })
      .catch(() => {
        if (active) {
          setSample([])
          setSampleTruncated(false)
        }
      })
      .finally(() => active && setSampleLoading(false))
    return () => {
      active = false
    }
  }, [scopeId, subdomainId, subdomainMode, debounced, hostFilter, toolFilter])

  // Categorize the sample once → counts per category + a matcher for the active one.
  // Endpoints are always URL-like (never JS files), so isJs is false.
  const { counts, matches } = useMemo(
    () => categorize(sample, { isJs: false }),
    [sample],
  )

  // Categories that actually have matches, ordered by count desc (most useful first).
  const presentCategories = useMemo(
    () =>
      HUNT_CATEGORIES.filter((c) => counts[c.id] > 0).sort(
        (a, b) => counts[b.id] - counts[a.id],
      ),
    [counts],
  )

  // When a category is active, results are filtered + paginated client-side over
  // the sample. Otherwise we use the server-paginated `data`.
  const catMatches = useMemo(
    () => (activeCat ? matches(activeCat) : null),
    [activeCat, matches],
  )

  // Clear the active category when filters invalidate it.
  useEffect(() => {
    if (activeCat && counts[activeCat] === 0) setActiveCat('')
  }, [counts, activeCat])

  // Reset paging when the active category changes.
  useEffect(() => {
    setPage(0)
  }, [activeCat])

  // When a category is active, page over the client-filtered matches; otherwise
  // use the server-paginated data.
  const catActive = Boolean(activeCat) && Array.isArray(catMatches)
  const total = catActive ? catMatches.length : data.total || 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rows = catActive
    ? catMatches.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
    : data.items || []

  const toggleSort = (key) => {
    if (sortBy === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(key)
      setSortDir('asc')
    }
  }

  const sortIndicator = (key) =>
    sortBy === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''

  const hostOptions = useMemo(() => hosts.slice(0, 1000), [hosts])

  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="section-title">
          Endpoint Explorer
          {subdomainMode && subdomainLabel && (
            <span className="muted"> · {subdomainLabel}</span>
          )}
        </h2>
      </header>

      <div className="cd-toolbar">
        <input
          type="search"
          className="input"
          placeholder="Search endpoint, host, or path…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        {!subdomainMode && (
          <select
            className="input cd-host-select"
            value={hostFilter}
            onChange={(e) => setHostFilter(e.target.value)}
            disabled={hostOptions.length === 0}
          >
            <option value="">All hosts ({hosts.length})</option>
            {hostFilter && !hostOptions.includes(hostFilter) && (
              <option value={hostFilter}>{hostFilter}</option>
            )}
            {hostOptions.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        )}

        <select
          className="input cd-host-select"
          value={toolFilter}
          onChange={(e) => setToolFilter(e.target.value)}
        >
          <option value="">All tools</option>
          {ENDPOINT_TOOLS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        {(hostFilter || toolFilter) && (
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => {
              setHostFilter('')
              setToolFilter('')
            }}
          >
            Clear filters
          </button>
        )}

        <span className="muted cd-count">
          {total.toLocaleString()} endpoints
          {catActive && (
            <span className="muted">
              {' '}· {HUNT_CATEGORIES.find((c) => c.id === activeCat)?.label}
            </span>
          )}
        </span>
      </div>

      {/* ---- Hunt: category suggestion chips (computed from loaded data) ---- */}
      <div className="cd-hunt">
        <button
          type="button"
          className="cd-hunt-toggle"
          onClick={() => setShowHunt((s) => !s)}
          aria-expanded={showHunt}
        >
          🎯 Hunt {showHunt ? '▾' : '▸'}
          {sampleTruncated && (
            <span className="muted cd-hunt-note"> (first {HUNT_SAMPLE_LIMIT.toLocaleString()})</span>
          )}
        </button>
        {showHunt && (
          <div className="cd-chips">
            {sampleLoading && presentCategories.length === 0 ? (
              <span className="muted">Analyzing…</span>
            ) : presentCategories.length === 0 ? (
              <span className="muted">No category matches in the loaded data.</span>
            ) : (
              <>
                {activeCat && (
                  <button
                    type="button"
                    className="cd-chip cd-chip-clear"
                    onClick={() => setActiveCat('')}
                  >
                    ✕ Clear
                  </button>
                )}
                {presentCategories.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    title={c.hint}
                    className={`cd-chip${activeCat === c.id ? ' active' : ''}`}
                    onClick={() => setActiveCat((cur) => (cur === c.id ? '' : c.id))}
                  >
                    {c.label}
                    <span className="cd-chip-count">{counts[c.id].toLocaleString()}</span>
                  </button>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {(catActive ? sampleLoading : loading) ? (
        <p className="muted panel-empty">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted panel-empty">
          {catActive
            ? 'No endpoints match this category.'
            : debounced || hostFilter || toolFilter
              ? 'No endpoints match these filters.'
              : 'No endpoints discovered yet. Run a JS endpoint scan.'}
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    className={c.sortable ? 'sortable' : undefined}
                    onClick={c.sortable ? () => toggleSort(c.key) : undefined}
                    style={c.sortable ? { cursor: 'pointer' } : undefined}
                  >
                    {c.label}
                    {c.sortable && sortIndicator(c.key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((ep) => (
                <tr key={ep.id}>
                  <td className="cell-mono">
                    <a
                      href={ep.absolute_url}
                      target="_blank"
                      rel="noreferrer"
                      className="cd-url"
                      title={ep.absolute_url}
                    >
                      {ep.normalized_url}
                    </a>
                  </td>
                  <td className="cell-mono">{ep.host || '—'}</td>
                  <td className="cell-mono">
                    {ep.source_js_file ? (
                      <a
                        href={ep.source_js_file}
                        target="_blank"
                        rel="noreferrer"
                        title={ep.source_js_file}
                        className="cd-url"
                      >
                        {shorten(ep.source_js_file)}
                      </a>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>
                    <ToolBadges tools={ep.discovery_tools} />
                  </td>
                  <td className="muted">{formatDate(ep.first_seen)}</td>
                  <td className="muted">{formatDate(ep.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="cd-pager">
          <button
            type="button"
            className="btn btn-sm"
            disabled={page === 0 || (catActive ? sampleLoading : loading)}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            ← Prev
          </button>
          <span className="muted">
            Page {page + 1} of {totalPages}
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={page >= totalPages - 1 || (catActive ? sampleLoading : loading)}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </button>
        </div>
      )}
    </section>
  )
}

// Shorten a long JS URL to "…/tail" for the table cell.
function shorten(url) {
  try {
    const u = new URL(url)
    const parts = u.pathname.split('/').filter(Boolean)
    const tail = parts.slice(-1)[0] || u.hostname
    return `${u.hostname}/…/${tail}`
  } catch {
    return url.length > 40 ? `…${url.slice(-38)}` : url
  }
}

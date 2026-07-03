import { useCallback, useEffect, useRef, useState } from 'react'
import { parametersApi } from '../api/parameters'

const PAGE_SIZE = 50

// Parameter type → a coarse "interesting" flag drives the badge colour. Filled
// from /parameter-types so the legend stays in lock-step with the backend.
function typeClass(type, interestingSet) {
  return interestingSet.has(type) ? 'badge badge-type param-type interesting' : 'badge badge-type param-type'
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

function fmtTime(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

/**
 * Parameter Explorer (Phase 6.4).
 *
 * Two modes:
 *   - scope inventory: pass { scopeId } → full searchable/filterable table.
 *   - asset drill-down: pass { assetId, assetUrl, onClose } → the parameters
 *     discovered on one asset (opened from the Asset Explorer).
 */
export default function ParameterExplorer({ scopeId, assetId, assetUrl, onClose }) {
  const drillDown = Boolean(assetId)

  const [types, setTypes] = useState([])
  const [interesting, setInteresting] = useState(() => new Set())
  const [stats, setStats] = useState(null)

  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [tool, setTool] = useState('')
  const [parameterType, setParameterType] = useState('')

  const [page, setPage] = useState(0)
  const [data, setData] = useState({ total: 0, items: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

  // ---- Load type taxonomy + (scope only) stats ----
  useEffect(() => {
    parametersApi
      .types()
      .then((t) => {
        setTypes(t || [])
        setInteresting(new Set((t || []).filter((x) => x.interesting).map((x) => x.type)))
      })
      .catch(() => setTypes([]))
  }, [])

  const loadStats = useCallback(() => {
    if (drillDown || !scopeId) return
    parametersApi
      .scopeStats(scopeId)
      .then(setStats)
      .catch(() => setStats(null))
  }, [scopeId, drillDown])

  useEffect(() => {
    loadStats()
  }, [loadStats])

  // ---- Debounce search ----
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setDebounced(search.trim())
      setPage(0)
    }, 350)
    return () => clearTimeout(debounceRef.current)
  }, [search])

  useEffect(() => {
    setPage(0)
  }, [tool, parameterType])

  // ---- Load current page ----
  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    const opts = {
      offset: page * PAGE_SIZE,
      limit: PAGE_SIZE,
      search: debounced || undefined,
      tool: tool || undefined,
      parameterType: parameterType || undefined,
    }
    try {
      const res = drillDown
        ? await parametersApi.listByAsset(assetId, opts)
        : await parametersApi.listByScope(scopeId, opts)
      setData(res || { total: 0, items: [] })
    } catch (err) {
      setError(err.message)
      setData({ total: 0, items: [] })
    } finally {
      setLoading(false)
    }
  }, [scopeId, assetId, drillDown, page, debounced, tool, parameterType])

  useEffect(() => {
    load()
  }, [load])

  const total = data.total || 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rows = data.items || []

  const body = (
    <>
      {/* ---- Dashboard stat tiles (scope inventory only) ---- */}
      {!drillDown && stats && (
        <div className="param-stats">
          <div className="stat-card">
            <span className="stat-label">Total Parameters</span>
            <span className="stat-value">{stats.total_parameters.toLocaleString()}</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">Unique Parameters</span>
            <span className="stat-value">{stats.unique_parameters.toLocaleString()}</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">New (24h)</span>
            <span className="stat-value">{stats.new_parameters.toLocaleString()}</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">Arjun</span>
            <span className="stat-value">{(stats.by_tool?.ARJUN || 0).toLocaleString()}</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">ParamSpider</span>
            <span className="stat-value">{(stats.by_tool?.PARAMSPIDER || 0).toLocaleString()}</span>
          </div>
        </div>
      )}

      {/* ---- Most common parameters (scope inventory only) ---- */}
      {!drillDown && stats && stats.most_common?.length > 0 && (
        <div className="param-common">
          <span className="muted">Most common:</span>
          {stats.most_common.slice(0, 12).map((c) => (
            <button
              key={c.name}
              type="button"
              className="badge badge-type param-common-chip"
              onClick={() => setSearch(c.name)}
              title={`${c.count.toLocaleString()} occurrences — click to filter`}
            >
              {c.name} <span className="muted">{c.count}</span>
            </button>
          ))}
        </div>
      )}

      <div className="cd-toolbar">
        <input
          type="search"
          className="input"
          placeholder="Search parameters by name, URL or host…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <select className="input cd-host-select" value={tool} onChange={(e) => setTool(e.target.value)}>
          <option value="">All tools</option>
          <option value="ARJUN">Arjun</option>
          <option value="PARAMSPIDER">ParamSpider</option>
        </select>

        <select
          className="input cd-host-select"
          value={parameterType}
          onChange={(e) => setParameterType(e.target.value)}
        >
          <option value="">All types</option>
          {types.map((t) => (
            <option key={t.type} value={t.type}>
              {t.label}
            </option>
          ))}
        </select>

        {(tool || parameterType || debounced) && (
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => {
              setTool('')
              setParameterType('')
              setSearch('')
              setDebounced('')
            }}
          >
            Clear filters
          </button>
        )}

        <span className="muted cd-count">{total.toLocaleString()} parameters</span>
      </div>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <p className="muted panel-empty">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted panel-empty">
          {debounced || tool || parameterType
            ? 'No parameters match these filters.'
            : 'No parameters discovered yet. Run a parameter discovery scan.'}
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Parameter Name</th>
                <th>Type</th>
                {!drillDown && <th>Asset URL</th>}
                <th>Discovery Tools</th>
                <th>First Seen</th>
                <th>Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="cell-mono">{p.parameter_name}</td>
                  <td>
                    <span className={typeClass(p.parameter_type, interesting)}>
                      {p.parameter_type}
                    </span>
                  </td>
                  {!drillDown && (
                    <td>
                      <a href={p.asset_url} target="_blank" rel="noreferrer" className="cd-url" title={p.asset_url}>
                        {p.asset_url}
                      </a>
                    </td>
                  )}
                  <td>
                    <ToolBadges tools={p.discovery_tools} />
                  </td>
                  <td className="muted">{fmtTime(p.first_seen)}</td>
                  <td className="muted">{fmtTime(p.last_seen)}</td>
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
            disabled={page === 0 || loading}
            onClick={() => setPage((v) => Math.max(0, v - 1))}
          >
            ← Prev
          </button>
          <span className="muted">
            Page {page + 1} of {totalPages}
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={page >= totalPages - 1 || loading}
            onClick={() => setPage((v) => v + 1)}
          >
            Next →
          </button>
        </div>
      )}
    </>
  )

  // Drill-down renders inside a modal overlay opened from the Asset Explorer.
  if (drillDown) {
    return (
      <div className="param-modal-backdrop" onClick={onClose} role="presentation">
        <div className="param-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
          <header className="panel-header">
            <h2 className="section-title">
              Parameters <span className="muted">({total.toLocaleString()})</span>
            </h2>
            <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
              ✕ Close
            </button>
          </header>
          {assetUrl && (
            <p className="muted param-modal-url" title={assetUrl}>
              {assetUrl}
            </p>
          )}
          {body}
        </div>
      </div>
    )
  }

  return <section className="panel">{body}</section>
}

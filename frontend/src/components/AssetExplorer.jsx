import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { assetsApi } from '../api/assets'
import ParameterExplorer from './ParameterExplorer'

const PAGE_SIZE = 25

// Coarse groups → the sidebar section order. Matches CategoryMeta.group on the
// backend; categories with no assets are hidden so the sidebar stays relevant.
const GROUP_ORDER = ['Dynamic', 'Pages', 'Code', 'Static', 'Documents', 'Sensitive', 'Interesting', 'Unknown']

function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function hostOf(url) {
  try {
    return new URL(url).host
  } catch {
    return '—'
  }
}

function fileNameOf(url) {
  try {
    const p = new URL(url).pathname
    const base = p.split('/').filter(Boolean).pop()
    return base || p
  } catch {
    return url
  }
}

function AssetLink({ url }) {
  return (
    <a href={url} target="_blank" rel="noreferrer" className="cd-url" title={url}>
      {url}
    </a>
  )
}

function SourceBadges({ source }) {
  if (!source) return <span className="muted">—</span>
  const parts = String(source).split(',').filter(Boolean)
  return (
    <span className="src-badges">
      {parts.map((p) => (
        <span key={p} className="badge badge-type src-badge">
          {p}
        </span>
      ))}
    </span>
  )
}

/**
 * Per-category table shapes. Each returns { columns: [labels], row: (asset) => cells }.
 * This is how the Asset Explorer shows the right fields per category
 * (JS → size/endpoints/secrets; API → params/methods/source; etc.) without a
 * separate component per category.
 */
// A clickable parameter-count cell that opens the Parameter Explorer drill-down
// for the asset. Shows a plain count when zero (nothing to open).
function ParamCount({ asset, onOpenParams }) {
  const n = asset.parameter_count || 0
  if (n === 0) return <span className="muted">0</span>
  return (
    <button
      type="button"
      className="badge badge-type param-count-chip"
      onClick={() => onOpenParams(asset)}
      title="View discovered parameters"
    >
      {n.toLocaleString()}
    </button>
  )
}

function columnsFor(category, onOpenParams) {
  const link = (a) => <AssetLink url={a.normalized_url} />
  const src = (a) => <SourceBadges source={a.discovery_source} />
  const params = (a) => <ParamCount asset={a} onOpenParams={onOpenParams} />
  switch (category) {
    case 'JAVASCRIPT':
      return {
        head: ['JS URL', 'Host', 'Size', 'Source', 'Endpoints', 'Secrets'],
        cells: (a) => [
          link(a),
          a.host || hostOf(a.normalized_url),
          formatBytes(a.size_bytes),
          src(a),
          a.endpoints_extracted ?? '—',
          a.secrets_found ?? '—',
        ],
      }
    case 'API':
      return {
        head: ['Endpoint', 'Parameters', 'Host', 'Source'],
        cells: (a) => [link(a), params(a), a.host || hostOf(a.normalized_url), src(a)],
      }
    case 'DOCUMENT':
      return {
        head: ['File Name', 'Extension', 'URL', 'MIME Type'],
        cells: (a) => [
          fileNameOf(a.normalized_url),
          a.extension || '—',
          link(a),
          a.mime_type || '—',
        ],
      }
    case 'ARCHIVE':
    case 'CONFIGURATION':
    case 'LOG_BACKUP':
    case 'SCRIPT':
      // Sensitive files.
      return {
        head: ['URL', 'Extension', 'Category', 'Host'],
        cells: (a) => [link(a), a.extension || '—', a.asset_category, a.host || hostOf(a.normalized_url)],
      }
    default:
      return {
        head: ['URL', 'Host', 'Category', 'Parameters', 'Source'],
        cells: (a) => [
          link(a),
          a.host || hostOf(a.normalized_url),
          a.asset_category || 'UNKNOWN',
          params(a),
          src(a),
        ],
      }
  }
}

export default function AssetExplorer({ scopeId }) {
  const [meta, setMeta] = useState([]) // category metadata (label/group/order)
  const [counts, setCounts] = useState({}) // { CATEGORY: n }
  const [totalAssets, setTotalAssets] = useState(0)
  const [category, setCategory] = useState('') // '' = all categories

  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [host, setHost] = useState('')
  const [extension, setExtension] = useState('')
  const [hosts, setHosts] = useState([])
  const [extensions, setExtensions] = useState([])

  const [page, setPage] = useState(0)
  const [data, setData] = useState({ total: 0, items: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

  // Parameter Explorer drill-down: the asset whose parameters are being viewed.
  const [paramAsset, setParamAsset] = useState(null)

  // ---- Load taxonomy + per-category counts (stats) + facets ----
  const loadStats = useCallback(() => {
    assetsApi
      .stats(scopeId)
      .then((s) => {
        setMeta(s?.categories || [])
        setCounts(s?.by_category || {})
        setTotalAssets(s?.total_assets || 0)
      })
      .catch(() => {
        setMeta([])
        setCounts({})
        setTotalAssets(0)
      })
  }, [scopeId])

  useEffect(() => {
    loadStats()
    assetsApi.hosts(scopeId).then((h) => setHosts(h || [])).catch(() => setHosts([]))
    assetsApi.extensions(scopeId).then((e) => setExtensions(e || [])).catch(() => setExtensions([]))
  }, [scopeId, loadStats])

  // ---- Debounce search ----
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setDebounced(search.trim())
      setPage(0)
    }, 350)
    return () => clearTimeout(debounceRef.current)
  }, [search])

  // ---- Reset paging when filters change ----
  useEffect(() => {
    setPage(0)
  }, [category, host, extension])

  // ---- Load the current page ----
  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await assetsApi.list(scopeId, {
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        category: category || undefined,
        search: debounced || undefined,
        host: host || undefined,
        extension: extension || undefined,
      })
      setData(res || { total: 0, items: [] })
    } catch (err) {
      setError(err.message)
      setData({ total: 0, items: [] })
    } finally {
      setLoading(false)
    }
  }, [scopeId, page, category, debounced, host, extension])

  useEffect(() => {
    load()
  }, [load])

  // ---- Sidebar categories grouped, only those with assets ----
  const grouped = useMemo(() => {
    const byGroup = {}
    for (const m of meta) {
      const n = counts[m.category] || 0
      if (n === 0) continue
      ;(byGroup[m.group] ||= []).push({ ...m, count: n })
    }
    return GROUP_ORDER.filter((g) => byGroup[g]).map((g) => ({ group: g, items: byGroup[g] }))
  }, [meta, counts])

  const activeMeta = meta.find((m) => m.category === category)
  const { head, cells } = columnsFor(category, setParamAsset)

  const total = data.total || 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rows = data.items || []

  const clearFilters = () => {
    setHost('')
    setExtension('')
    setSearch('')
    setDebounced('')
  }

  return (
    <div className="asset-explorer">
      {/* ---- Category sidebar ---- */}
      <aside className="asset-sidebar">
        <button
          type="button"
          className={`asset-cat${category === '' ? ' active' : ''}`}
          onClick={() => setCategory('')}
        >
          <span>All Assets</span>
          <span className="asset-cat-count">{totalAssets.toLocaleString()}</span>
        </button>
        {grouped.map(({ group, items }) => (
          <div key={group} className="asset-cat-group">
            <div className="asset-cat-group-label">{group}</div>
            {items.map((m) => (
              <button
                key={m.category}
                type="button"
                className={`asset-cat${category === m.category ? ' active' : ''}${
                  m.sensitive ? ' sensitive' : ''
                }`}
                onClick={() => setCategory(m.category)}
                title={m.sensitive ? 'Sensitive asset category' : undefined}
              >
                <span>{m.label}</span>
                <span className="asset-cat-count">{m.count.toLocaleString()}</span>
              </button>
            ))}
          </div>
        ))}
      </aside>

      {/* ---- Main panel ---- */}
      <section className="panel asset-main">
        <header className="panel-header">
          <h2 className="section-title">
            {activeMeta ? activeMeta.label : 'All Assets'}
            <span className="muted"> ({total.toLocaleString()})</span>
          </h2>
        </header>

        <div className="cd-toolbar">
          <input
            type="search"
            className="input"
            placeholder="Search assets by URL or host…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          <select
            className="input cd-host-select"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            disabled={hosts.length === 0}
          >
            <option value="">All hosts ({hosts.length})</option>
            {host && !hosts.includes(host) && <option value={host}>{host}</option>}
            {hosts.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>

          <select
            className="input cd-host-select"
            value={extension}
            onChange={(e) => setExtension(e.target.value)}
            disabled={extensions.length === 0}
          >
            <option value="">All extensions</option>
            {extensions.map((e) => (
              <option key={e} value={e}>
                .{e}
              </option>
            ))}
          </select>

          {(host || extension || debounced) && (
            <button type="button" className="btn btn-sm btn-ghost" onClick={clearFilters}>
              Clear filters
            </button>
          )}

          <span className="muted cd-count">{total.toLocaleString()} assets</span>
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
            {debounced || host || extension
              ? 'No assets match these filters.'
              : 'No assets classified yet. Run a content discovery + JS endpoint scan.'}
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {head.map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={`${a.source_kind}-${a.id}`}>
                    {cells(a).map((cell, i) => (
                      // eslint-disable-next-line react/no-array-index-key
                      <td key={`${a.source_kind}-${a.id}-${i}`} className={i === 0 ? 'cell-mono' : undefined}>
                        {cell}
                      </td>
                    ))}
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
              disabled={page >= totalPages - 1 || loading}
              onClick={() => setPage((p) => p + 1)}
            >
              Next →
            </button>
          </div>
        )}
      </section>

      {/* ---- Parameter Explorer drill-down (Phase 6.4) ---- */}
      {paramAsset && (
        <ParameterExplorer
          assetId={paramAsset.id}
          assetUrl={paramAsset.normalized_url}
          onClose={() => setParamAsset(null)}
        />
      )}
    </div>
  )
}

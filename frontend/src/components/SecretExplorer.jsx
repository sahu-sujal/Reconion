import { useCallback, useEffect, useRef, useState } from 'react'
import { secretsApi, SECRET_SEVERITIES, SECRET_TOOLS } from '../api/secrets'

const PAGE_SIZE = 25

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function SeverityBadge({ severity }) {
  const s = (severity || 'INFO').toUpperCase()
  const cls = {
    CRITICAL: 'badge-failed',
    HIGH: 'badge-pending',
    MEDIUM: 'badge-type',
    LOW: 'badge-archived',
    INFO: 'badge-archived',
  }[s] || 'badge-archived'
  return <span className={`badge ${cls}`}>{s}</span>
}

function ToolBadges({ tools }) {
  if (!tools || tools.length === 0) return <span className="muted">—</span>
  return (
    <span className="src-badges">
      {tools.map((t) => (
        <span key={t} className="badge badge-type src-badge">{t}</span>
      ))}
    </span>
  )
}

// Unmasked secret value with a click-to-copy affordance (analysts must verify).
function SecretValue({ value }) {
  const [copied, setCopied] = useState(false)
  const copy = (e) => {
    e.stopPropagation()
    navigator.clipboard?.writeText(value).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }
  return (
    <span className="secret-value" title="Click to copy" onClick={copy}>
      <code>{value}</code>
      <button type="button" className="btn btn-sm btn-ghost secret-copy" onClick={copy}>
        {copied ? '✓' : '⧉'}
      </button>
    </span>
  )
}

const COLUMNS = [
  { key: 'secret_type', label: 'Secret Type', sortable: true },
  { key: 'secret_value', label: 'Secret Value', sortable: false },
  { key: 'severity', label: 'Severity', sortable: true },
  { key: 'host', label: 'Host', sortable: true },
  { key: 'js_file', label: 'JavaScript File', sortable: false },
  { key: 'tools', label: 'Discovery Tools', sortable: false },
  { key: 'confidence', label: 'Confidence', sortable: true },
  { key: 'first_seen', label: 'First Seen', sortable: true },
  { key: 'last_seen', label: 'Last Seen', sortable: true },
]

/**
 * The centralized Secret Inventory explorer (Phase 6.2).
 *
 * Modes: pass one of scopeId / programId / subdomainId / hostId / jsFileId.
 * Secrets are shown UNMASKED (analysts must be able to verify/report). The
 * originating JavaScript file URL is clickable.
 */
export default function SecretExplorer({
  scopeId, programId, subdomainId, hostId, jsFileId, subdomainLabel,
}) {
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [severity, setSeverity] = useState('')
  const [secretType, setSecretType] = useState('')
  const [tool, setTool] = useState('')
  const [sortBy, setSortBy] = useState('severity')
  const [sortDir, setSortDir] = useState('asc')
  const [page, setPage] = useState(0)

  const [data, setData] = useState({ total: 0, items: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

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
        severity: severity || undefined,
        secret_type: secretType || undefined,
        tool: tool || undefined,
        sort_by: sortBy,
        sort_dir: sortDir,
      }
      let res
      if (subdomainId) res = await secretsApi.bySubdomain(subdomainId, opts)
      else if (hostId) res = await secretsApi.byHost(hostId, opts)
      else if (jsFileId) res = await secretsApi.byJsFile(jsFileId, opts)
      else if (programId) res = await secretsApi.byProgram(programId, opts)
      else res = await secretsApi.byScope(scopeId, opts)
      setData(res || { total: 0, items: [] })
    } catch (err) {
      setError(err.message)
      setData({ total: 0, items: [] })
    } finally {
      setLoading(false)
    }
  }, [scopeId, programId, subdomainId, hostId, jsFileId,
      debounced, severity, secretType, tool, sortBy, sortDir, page])

  useEffect(() => { load() }, [load])
  useEffect(() => { setPage(0) }, [severity, secretType, tool, sortBy, sortDir])

  const total = data.total || 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rows = data.items || []

  const toggleSort = (key) => {
    if (sortBy === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortBy(key); setSortDir('asc') }
  }
  const sortIndicator = (key) => (sortBy === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')

  // Distinct secret types present (for the filter dropdown) — from current page + all severities.
  const typeOptions = Array.from(new Set(rows.map((r) => r.secret_type))).sort()

  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="section-title">
          Secret Explorer
          {subdomainLabel && <span className="muted"> · {subdomainLabel}</span>}
        </h2>
      </header>

      <div className="cd-toolbar">
        <input
          type="search"
          className="input"
          placeholder="Search value, type, host, or JS URL…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="input cd-host-select" value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">All severities</option>
          {SECRET_SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="input cd-host-select" value={secretType} onChange={(e) => setSecretType(e.target.value)}>
          <option value="">All types</option>
          {(typeOptions.length ? typeOptions : []).map((t) => <option key={t} value={t}>{t}</option>)}
          {secretType && !typeOptions.includes(secretType) && (
            <option value={secretType}>{secretType}</option>
          )}
        </select>
        <select className="input cd-host-select" value={tool} onChange={(e) => setTool(e.target.value)}>
          <option value="">All tools</option>
          {SECRET_TOOLS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        {(severity || secretType || tool) && (
          <button type="button" className="btn btn-sm btn-ghost"
            onClick={() => { setSeverity(''); setSecretType(''); setTool('') }}>
            Clear filters
          </button>
        )}
        <span className="muted cd-count">{total.toLocaleString()} secrets</span>
      </div>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={load}>Retry</button>
        </div>
      )}

      {loading ? (
        <p className="muted panel-empty">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted panel-empty">
          {debounced || severity || secretType || tool
            ? 'No secrets match these filters.'
            : 'No secrets discovered yet. Run a JS secret scan.'}
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key}
                    className={c.sortable ? 'sortable' : undefined}
                    onClick={c.sortable ? () => toggleSort(c.key) : undefined}
                    style={c.sortable ? { cursor: 'pointer' } : undefined}>
                    {c.label}{c.sortable && sortIndicator(c.key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td><span className="badge badge-type">{s.secret_type}</span></td>
                  <td className="cell-mono"><SecretValue value={s.secret_value} /></td>
                  <td><SeverityBadge severity={s.severity} /></td>
                  <td className="cell-mono">{s.host || '—'}</td>
                  <td className="cell-mono">
                    {s.js_file_url ? (
                      <a href={s.js_file_url} target="_blank" rel="noreferrer"
                        className="cd-url" title={s.js_file_url}>
                        {s.js_file_url}
                      </a>
                    ) : '—'}
                  </td>
                  <td><ToolBadges tools={s.discovery_tools} /></td>
                  <td className="muted">{s.confidence}%</td>
                  <td className="muted">{formatDate(s.first_seen)}</td>
                  <td className="muted">{formatDate(s.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="cd-pager">
          <button type="button" className="btn btn-sm" disabled={page === 0 || loading}
            onClick={() => setPage((p) => Math.max(0, p - 1))}>← Prev</button>
          <span className="muted">Page {page + 1} of {totalPages}</span>
          <button type="button" className="btn btn-sm" disabled={page >= totalPages - 1 || loading}
            onClick={() => setPage((p) => p + 1)}>Next →</button>
        </div>
      )}
    </section>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { scopesApi } from '../api/scopes'
import { SearchIcon, ChevronRightIcon } from '../components/icons'
import SubdomainDrawer from '../components/SubdomainDrawer'

const PAGE_SIZE = 50

function StatusPill({ code }) {
  if (code == null) return <span className="muted">—</span>
  const cls =
    code >= 200 && code < 300
      ? 'status-2xx'
      : code >= 300 && code < 400
        ? 'status-3xx'
        : code >= 400 && code < 500
          ? 'status-4xx'
          : 'status-5xx'
  return <span className={`status-pill ${cls}`}>{code}</span>
}

// Build the absolute URL for a live host from its scheme/host/port.
function hostUrl(h) {
  const scheme = h.scheme || (h.port === 443 ? 'https' : 'http')
  const defaultPort = scheme === 'https' ? 443 : 80
  const portPart = h.port && h.port !== defaultPort ? `:${h.port}` : ''
  return `${scheme}://${h.host}${portPart}`
}

export default function ScopeLiveDomainsPage() {
  const { scopeId } = useParams()

  const [scope, setScope] = useState(null)
  const [hosts, setHosts] = useState([])
  const [httpResponses, setHttpResponses] = useState([])
  const [dnsRecords, setDnsRecords] = useState([])
  const [technologies, setTechnologies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Filters
  const [query, setQuery] = useState('')
  const [techFilter, setTechFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(0)

  const [selected, setSelected] = useState(null) // host object for drawer

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // live_only → resolved hosts that returned an HTTP status code.
      const [scopeData, liveHosts, http, dns, tech] = await Promise.all([
        scopesApi.get(scopeId),
        scopesApi.hosts(scopeId, { limit: 10000, liveOnly: true }).catch(() => []),
        scopesApi.httpResponses(scopeId, { limit: 10000 }).catch(() => []),
        scopesApi.dnsRecords(scopeId, { limit: 10000 }).catch(() => []),
        scopesApi.technologies(scopeId, { limit: 10000 }).catch(() => []),
      ])
      setScope(scopeData)
      setHosts(Array.isArray(liveHosts) ? liveHosts : [])
      setHttpResponses(Array.isArray(http) ? http : [])
      setDnsRecords(Array.isArray(dns) ? dns : [])
      setTechnologies(Array.isArray(tech) ? tech : [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [scopeId])

  useEffect(() => {
    load()
  }, [load])

  // ---- Indices: relate http / dns / tech to a host by host_id ----
  const indices = useMemo(() => {
    const techByHostId = new Map()
    technologies.forEach((t) => {
      if (!techByHostId.has(t.host_id)) techByHostId.set(t.host_id, [])
      techByHostId.get(t.host_id).push(t)
    })
    const httpByHostId = new Map()
    httpResponses.forEach((r) => {
      if (!httpByHostId.has(r.host_id)) httpByHostId.set(r.host_id, [])
      httpByHostId.get(r.host_id).push(r)
    })
    const dnsByHostId = new Map()
    dnsRecords.forEach((d) => {
      if (!dnsByHostId.has(d.host_id)) dnsByHostId.set(d.host_id, [])
      dnsByHostId.get(d.host_id).push(d)
    })
    return { techByHostId, httpByHostId, dnsByHostId }
  }, [technologies, httpResponses, dnsRecords])

  // Reuse SubdomainDrawer by synthesizing a subdomain-shaped object from the host.
  const resolveBundle = useCallback(
    (host) => ({
      subdomain: {
        id: host.id,
        subdomain: host.host,
        scope_id: host.scope_id,
        source: '—',
        endpoint_count: 0,
        first_seen: host.first_seen,
        last_seen: host.last_seen,
      },
      host,
      technologies: indices.techByHostId.get(host.id) || [],
      httpResponses: indices.httpByHostId.get(host.id) || [],
      dnsRecords: indices.dnsByHostId.get(host.id) || [],
    }),
    [indices],
  )

  // ---- Dropdown option lists (from real data) ----
  const techOptions = useMemo(
    () => [...new Set(technologies.map((t) => t.technology).filter(Boolean))].sort(),
    [technologies],
  )
  const statusOptions = useMemo(
    () =>
      [...new Set(hosts.map((h) => h.status_code).filter((c) => c != null))].sort(
        (a, b) => a - b,
      ),
    [hosts],
  )

  // ---- Apply filters ----
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return hosts.filter((h) => {
      if (q && !h.host.toLowerCase().includes(q)) return false
      if (statusFilter && String(h.status_code) !== statusFilter) return false
      if (techFilter) {
        const techs = indices.techByHostId.get(h.id) || []
        if (!techs.some((t) => t.technology === techFilter)) return false
      }
      return true
    })
  }, [hosts, query, statusFilter, techFilter, indices])

  useEffect(() => {
    setPage(0)
  }, [query, techFilter, statusFilter])

  const pageRows = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const activeFilters = Boolean(query) || Boolean(techFilter) || Boolean(statusFilter)

  function clearFilters() {
    setQuery('')
    setTechFilter('')
    setStatusFilter('')
  }

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
        <Link to={`/scopes/${scopeId}`}>{scope?.target}</Link>
        <ChevronRightIcon className="crumb-sep" width={14} height={14} />
        <span>Live Domains</span>
      </div>

      <header className="page-header">
        <div>
          <h1>Live Domains</h1>
          <p className="subtitle">
            {hosts.length} live host{hosts.length === 1 ? '' : 's'} · resolved &amp; responding to
            HTTP · click any row for full detail
          </p>
        </div>
      </header>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {/* ---- Filters ---- */}
      <div className="filter-bar">
        <div className="search-box">
          <SearchIcon className="search-icon" />
          <input
            type="search"
            placeholder="Search live domains…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button
              type="button"
              className="search-clear"
              onClick={() => setQuery('')}
              aria-label="Clear search"
            >
              ✕
            </button>
          )}
        </div>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          disabled={statusOptions.length === 0}
        >
          <option value="">Any status</option>
          {statusOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        <select
          value={techFilter}
          onChange={(e) => setTechFilter(e.target.value)}
          disabled={techOptions.length === 0}
        >
          <option value="">Any technology</option>
          {techOptions.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        {activeFilters && (
          <button type="button" className="btn btn-sm btn-ghost" onClick={clearFilters}>
            Clear
          </button>
        )}
        <span className="muted result-count">
          {filtered.length} of {hosts.length}
        </span>
      </div>

      {loading ? (
        <p className="muted">Loading…</p>
      ) : hosts.length === 0 ? (
        <div className="empty-state">
          <p>No live domains yet — run DNS resolution and HTTP probing first.</p>
          <Link to={`/scopes/${scopeId}/scans`} className="btn btn-primary">
            Go to scans
          </Link>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <p>No live domains match the current filters.</p>
          <button type="button" className="btn" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      ) : (
        <table className="data-table clickable-rows">
          <thead>
            <tr>
              <th>Domain</th>
              <th>Status</th>
              <th>Port</th>
              <th>Title</th>
              <th>Technologies</th>
              <th>URL</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((h) => {
              const techs = indices.techByHostId.get(h.id) || []
              const url = hostUrl(h)
              return (
                <tr key={h.id} className="row-clickable" onClick={() => setSelected(h)}>
                  <td className="cell-mono">{h.host}</td>
                  <td>
                    <StatusPill code={h.status_code} />
                  </td>
                  <td className="cell-mono">{h.port ?? '—'}</td>
                  <td className="cell-title">{h.title || '—'}</td>
                  <td>
                    {techs.length > 0 ? (
                      <span className="flag-tags wrap">
                        {techs.slice(0, 3).map((t) => (
                          <span key={t.id} className="badge badge-type">
                            {t.technology}
                          </span>
                        ))}
                        {techs.length > 3 && (
                          <span className="muted">+{techs.length - 3}</span>
                        )}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="cell-mono">
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer noopener"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {url}
                    </a>
                  </td>
                  <td>
                    <ChevronRightIcon className="row-chevron" width={16} height={16} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {/* ---- Pagination (client-side over filtered result) ---- */}
      {filtered.length > PAGE_SIZE && (
        <div className="pagination">
          <button
            type="button"
            className="btn btn-sm"
            disabled={page === 0}
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
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
          >
            Next →
          </button>
        </div>
      )}

      {selected && (
        <SubdomainDrawer data={resolveBundle(selected)} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}

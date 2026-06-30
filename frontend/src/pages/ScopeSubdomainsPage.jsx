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

export default function ScopeSubdomainsPage() {
  const { scopeId } = useParams()

  const [scope, setScope] = useState(null)
  const [subdomains, setSubdomains] = useState([])
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
  const [dataFilter, setDataFilter] = useState('') // '', 'live', 'tech', 'dns'
  const [page, setPage] = useState(0)

  const [selected, setSelected] = useState(null) // subdomain object for drawer

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [scopeData, subs, hostList, http, dns, tech] = await Promise.all([
        scopesApi.get(scopeId),
        scopesApi.subdomains(scopeId, { limit: 10000 }).catch(() => []),
        scopesApi.hosts(scopeId, { limit: 10000 }).catch(() => []),
        scopesApi.httpResponses(scopeId, { limit: 10000 }).catch(() => []),
        scopesApi.dnsRecords(scopeId, { limit: 10000 }).catch(() => []),
        scopesApi.technologies(scopeId, { limit: 10000 }).catch(() => []),
      ])
      setScope(scopeData)
      setSubdomains(Array.isArray(subs) ? subs : [])
      setHosts(Array.isArray(hostList) ? hostList : [])
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

  // ---- Indices: relate everything to a subdomain by host name / host_id ----
  const indices = useMemo(() => {
    const hostByName = new Map() // fqdn -> host
    hosts.forEach((h) => hostByName.set(h.host, h))

    const techByHostId = new Map() // host_id -> [tech]
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

    return { hostByName, techByHostId, httpByHostId, dnsByHostId }
  }, [hosts, technologies, httpResponses, dnsRecords])

  // Resolve the full related bundle for one subdomain.
  const resolveBundle = useCallback(
    (sub) => {
      const host = indices.hostByName.get(sub.subdomain) || null
      const hid = host?.id
      return {
        subdomain: sub,
        host,
        technologies: hid ? indices.techByHostId.get(hid) || [] : [],
        httpResponses: hid ? indices.httpByHostId.get(hid) || [] : [],
        dnsRecords: hid ? indices.dnsByHostId.get(hid) || [] : [],
      }
    },
    [indices],
  )

  // ---- Calculated dropdown option lists (from real data) ----
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
    return subdomains.filter((sub) => {
      if (q && !sub.subdomain.toLowerCase().includes(q)) return false

      const host = indices.hostByName.get(sub.subdomain)
      const hid = host?.id

      if (dataFilter === 'live' && host?.status_code == null) return false
      if (dataFilter === 'tech' && !(hid && indices.techByHostId.has(hid))) return false
      if (dataFilter === 'dns' && !(hid && indices.dnsByHostId.has(hid))) return false

      if (statusFilter && String(host?.status_code) !== statusFilter) return false

      if (techFilter) {
        const techs = hid ? indices.techByHostId.get(hid) || [] : []
        if (!techs.some((t) => t.technology === techFilter)) return false
      }
      return true
    })
  }, [subdomains, query, dataFilter, statusFilter, techFilter, indices])

  // Reset to first page whenever filters change.
  useEffect(() => {
    setPage(0)
  }, [query, techFilter, statusFilter, dataFilter])

  const pageRows = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))

  const activeFilters =
    Boolean(query) || Boolean(techFilter) || Boolean(statusFilter) ||
    Boolean(dataFilter)

  function clearFilters() {
    setQuery('')
    setTechFilter('')
    setStatusFilter('')
    setDataFilter('')
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
        <span>Subdomains</span>
      </div>

      <header className="page-header">
        <div>
          <h1>Subdomains</h1>
          <p className="subtitle">
            {subdomains.length} discovered · click any row for full DNS / HTTP / tech
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
            placeholder="Search subdomains…"
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

        <select value={dataFilter} onChange={(e) => setDataFilter(e.target.value)}>
          <option value="">All</option>
          <option value="live">Live only</option>
          <option value="tech">Has technologies</option>
          <option value="dns">Has DNS records</option>
        </select>

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
          {filtered.length} of {subdomains.length}
        </span>
      </div>

      {loading ? (
        <p className="muted">Loading…</p>
      ) : subdomains.length === 0 ? (
        <div className="empty-state">
          <p>No subdomains discovered yet.</p>
          <Link to={`/scopes/${scopeId}/scans`} className="btn btn-primary">
            Go to scans
          </Link>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <p>No subdomains match the current filters.</p>
          <button type="button" className="btn" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      ) : (
        <table className="data-table clickable-rows">
          <thead>
            <tr>
              <th>Subdomain</th>
              <th>Status</th>
              <th>Port</th>
              <th>Title</th>
              <th>Technologies</th>
              <th>Source</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((sub) => {
              const host = indices.hostByName.get(sub.subdomain)
              const hid = host?.id
              const techs = hid ? indices.techByHostId.get(hid) || [] : []
              return (
                <tr
                  key={sub.id}
                  className="row-clickable"
                  onClick={() => setSelected(sub)}
                >
                  <td className="cell-mono">{sub.subdomain}</td>
                  <td>
                    <StatusPill code={host?.status_code} />
                  </td>
                  <td className="cell-mono">{host?.port ?? '—'}</td>
                  <td className="cell-title">{host?.title || '—'}</td>
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
                  <td className="muted cell-source">{sub.source || '—'}</td>
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

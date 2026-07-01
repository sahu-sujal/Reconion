import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { scopesApi } from '../api/scopes'
import { endpointsApi } from '../api/endpoints'
import { ChevronRightIcon } from '../components/icons'
import EndpointExplorer from '../components/EndpointExplorer'

function StatCard({ label, value }) {
  return (
    <div className="stat-card">
      <div className="stat-value">{(value ?? 0).toLocaleString()}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

export default function ScopeEndpointsPage() {
  const { scopeId } = useParams()
  const [searchParams] = useSearchParams()
  // Optional subdomain filter passed from the subdomain drawer:
  //   /scopes/:id/endpoints?subdomain_id=…&subdomain=api.example.com
  const subdomainId = searchParams.get('subdomain_id') || undefined
  const subdomainLabel = searchParams.get('subdomain') || undefined

  const [scope, setScope] = useState(null)
  const [stats, setStats] = useState(null)

  useEffect(() => {
    let active = true
    Promise.all([
      scopesApi.get(scopeId).catch(() => null),
      endpointsApi.stats(scopeId).catch(() => null),
    ]).then(([s, st]) => {
      if (!active) return
      setScope(s)
      setStats(st)
    })
    return () => {
      active = false
    }
  }, [scopeId])

  const topHosts = stats?.endpoints_per_host
    ? Object.entries(stats.endpoints_per_host).slice(0, 6)
    : []

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
        <span>Endpoints</span>
      </div>

      <header className="page-header">
        <div>
          <h1>Endpoint Inventory</h1>
          <p className="subtitle">
            {(stats?.total_endpoints ?? 0).toLocaleString()} endpoints ·{' '}
            {(stats?.new_endpoints ?? 0).toLocaleString()} new (24h)
            {subdomainLabel && <span className="muted"> · filtered: {subdomainLabel}</span>}
          </p>
        </div>
      </header>

      {/* Dashboard counters (Phase 6.1) */}
      <div className="stats-grid">
        <StatCard label="Total Endpoints" value={stats?.total_endpoints} />
        <StatCard label="New Endpoints (24h)" value={stats?.new_endpoints} />
        <StatCard
          label="Hosts with Endpoints"
          value={stats?.endpoints_per_host ? Object.keys(stats.endpoints_per_host).length : 0}
        />
      </div>

      {topHosts.length > 0 && (
        <section className="panel">
          <header className="panel-header">
            <h2 className="section-title">Endpoints per host</h2>
          </header>
          <ul className="cd-list">
            {topHosts.map(([host, count]) => (
              <li key={host} className="cd-row">
                <span className="cd-url">{host}</span>
                <span className="badge badge-type">{count.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <EndpointExplorer
        scopeId={scopeId}
        subdomainId={subdomainId}
        subdomainLabel={subdomainLabel}
      />
    </div>
  )
}

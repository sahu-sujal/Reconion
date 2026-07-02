import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { scopesApi } from '../api/scopes'
import { secretsApi } from '../api/secrets'
import { ChevronRightIcon } from '../components/icons'
import SecretExplorer from '../components/SecretExplorer'

function StatCard({ label, value, danger }) {
  return (
    <div className="stat-card">
      <div className={`stat-value${danger && value > 0 ? ' accent' : ''}`}>
        {(value ?? 0).toLocaleString()}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

export default function ScopeSecretsPage() {
  const { scopeId } = useParams()
  const [searchParams] = useSearchParams()
  const subdomainId = searchParams.get('subdomain_id') || undefined
  const subdomainLabel = searchParams.get('subdomain') || undefined

  const [scope, setScope] = useState(null)
  const [stats, setStats] = useState(null)

  useEffect(() => {
    let active = true
    Promise.all([
      scopesApi.get(scopeId).catch(() => null),
      secretsApi.scopeStats(scopeId).catch(() => null),
    ]).then(([s, st]) => {
      if (!active) return
      setScope(s)
      setStats(st)
    })
    return () => { active = false }
  }, [scopeId])

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
        <span>Secrets</span>
      </div>

      <header className="page-header">
        <div>
          <h1>Secret Inventory</h1>
          <p className="subtitle">
            {(stats?.total_secrets ?? 0).toLocaleString()} secrets ·{' '}
            {(stats?.critical_secrets ?? 0).toLocaleString()} critical ·{' '}
            {(stats?.high_secrets ?? 0).toLocaleString()} high
            {subdomainLabel && <span className="muted"> · filtered: {subdomainLabel}</span>}
          </p>
        </div>
      </header>

      {/* Dashboard counters (Phase 6.2) */}
      <div className="stats-grid">
        <StatCard label="Total Secrets" value={stats?.total_secrets} />
        <StatCard label="Critical" value={stats?.critical_secrets} danger />
        <StatCard label="High Severity" value={stats?.high_secrets} danger />
        <StatCard label="AWS Keys" value={stats?.aws_keys} />
        <StatCard label="GitHub Tokens" value={stats?.github_tokens} />
        <StatCard label="JWT Tokens" value={stats?.jwt_tokens} />
        <StatCard label="Private Keys" value={stats?.private_keys} danger />
        <StatCard label="DB Credentials" value={stats?.database_credentials} danger />
        <StatCard label="Slack Tokens" value={stats?.slack_tokens} />
        <StatCard label="Google API Keys" value={stats?.google_api_keys} />
      </div>

      <SecretExplorer
        scopeId={scopeId}
        subdomainId={subdomainId}
        subdomainLabel={subdomainLabel}
      />
    </div>
  )
}

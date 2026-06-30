import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { scopesApi } from '../api/scopes'
import { ChevronRightIcon } from '../components/icons'
import ContentDiscoveryPanel from '../components/ContentDiscoveryPanel'

export default function ScopeContentPage() {
  const { scopeId } = useParams()

  const [scope, setScope] = useState(null)
  const [stats, setStats] = useState(null)

  useEffect(() => {
    let active = true
    Promise.all([
      scopesApi.get(scopeId).catch(() => null),
      scopesApi.stats(scopeId).catch(() => null),
    ]).then(([s, st]) => {
      if (!active) return
      setScope(s)
      setStats(st)
    })
    return () => {
      active = false
    }
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
        <span>Content Discovery</span>
      </div>

      <header className="page-header">
        <div>
          <h1>Content Discovery</h1>
          <p className="subtitle">
            {(stats?.urls_count ?? 0).toLocaleString()} URLs ·{' '}
            {(stats?.js_count ?? 0).toLocaleString()} JS files · 25 per page
          </p>
        </div>
      </header>

      <ContentDiscoveryPanel scopeId={scopeId} stats={stats} />
    </div>
  )
}

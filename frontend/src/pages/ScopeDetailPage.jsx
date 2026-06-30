import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { scopesApi } from '../api/scopes'
import { scansApi, ACTIVE_SCAN_STATUSES } from '../api/scans'
import { ChevronRightIcon } from '../components/icons'

function StatCard({ label, value, accent }) {
  return (
    <div className="stat-card">
      <span className={`stat-value${accent ? ' accent' : ''}`}>{value ?? 0}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function ScanStatusBadge({ status }) {
  const s = (status || '').toUpperCase()
  const map = {
    RUNNING: 'badge-running',
    PENDING: 'badge-pending',
    COMPLETED: 'badge-active',
    FAILED: 'badge-failed',
    CANCELLED: 'badge-archived',
  }
  return <span className={`badge ${map[s] || 'badge-archived'}`}>{s || 'unknown'}</span>
}

// One row in a scan list.
function ScanRow({ scan }) {
  const found = scan.records_found ?? scan.unique_count ?? 0
  return (
    <li className="scan-row">
      <div className="scan-row-main">
        <ScanStatusBadge status={scan.status} />
        <span className="scan-type">{scan.scan_type}</span>
        {scan.worker_name && <span className="muted scan-worker">{scan.worker_name}</span>}
      </div>
      <div className="scan-row-meta">
        <span className="muted">{found} found</span>
        <span className="muted">{formatDate(scan.started_at)}</span>
      </div>
      {scan.error_message && <p className="scan-error">{scan.error_message}</p>}
    </li>
  )
}

export default function ScopeDetailPage() {
  const { scopeId } = useParams()

  const [scope, setScope] = useState(null)
  const [stats, setStats] = useState(null)
  const [scans, setScans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [scopeData, statsData, scanList] = await Promise.all([
        scopesApi.get(scopeId),
        scopesApi.stats(scopeId).catch(() => null), // stats best-effort
        scansApi.list({ scopeId }).catch(() => []),
      ])
      setScope(scopeData)
      setStats(statsData)
      setScans(Array.isArray(scanList) ? scanList : [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [scopeId])

  useEffect(() => {
    load()
  }, [load])

  // Split into active (running/pending) and recent (everything else).
  const { activeScans, recentScans } = useMemo(() => {
    const byNewest = [...scans].sort(
      (a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0),
    )
    return {
      activeScans: byNewest.filter((s) =>
        ACTIVE_SCAN_STATUSES.includes((s.status || '').toUpperCase()),
      ),
      recentScans: byNewest.filter(
        (s) => !ACTIVE_SCAN_STATUSES.includes((s.status || '').toUpperCase()),
      ),
    }
  }, [scans])

  // Auto-refresh while a scan is active so progress shows live.
  useEffect(() => {
    if (activeScans.length === 0) return undefined
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [activeScans.length, load])

  if (loading) {
    return (
      <div className="page">
        <div className="breadcrumb">
          <Link to="/">Programs</Link>
          <ChevronRightIcon className="crumb-sep" width={14} height={14} />
          <span className="muted">Loading…</span>
        </div>
        <div className="stats-grid">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton skeleton-stat" />
          ))}
        </div>
      </div>
    )
  }

  if (error && !scope) {
    return (
      <div className="page">
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
        <Link to="/" className="btn">
          ← Back to programs
        </Link>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link to="/">Programs</Link>
        <ChevronRightIcon className="crumb-sep" width={14} height={14} />
        {scope?.program_id ? (
          <Link to={`/programs/${scope.program_id}`}>Program</Link>
        ) : (
          <span>Program</span>
        )}
        <ChevronRightIcon className="crumb-sep" width={14} height={14} />
        <span>{scope?.target}</span>
      </div>

      <header className="page-header">
        <div>
          <h1>{scope?.target}</h1>
          <p className="subtitle">
            <span className="badge badge-type">{scope?.scope_type}</span>
            {scope?.is_active ? (
              <span className="badge badge-active">active</span>
            ) : (
              <span className="badge badge-archived">inactive</span>
            )}
            <span>Priority {scope?.priority}</span>
          </p>
        </div>
        {scope?.program_id && (
          <Link to={`/programs/${scope.program_id}`} className="btn">
            ← Back to program
          </Link>
        )}
      </header>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {/* ---- Scope stats ---- */}
      <div className="stats-grid">
        <StatCard label="Assets" value={stats?.assets_count} accent />
        <StatCard label="URLs" value={stats?.urls_count} />
        <StatCard label="JS files" value={stats?.js_count} />
        <StatCard label="Findings" value={stats?.findings_count} />
        <StatCard label="Total scans" value={scans.length} />
        <StatCard label="Active scans" value={activeScans.length} accent />
      </div>

      {stats && (
        <div className="stat-meta-row">
          <span>
            Last scan: <strong>{formatDate(stats.last_scan_at)}</strong>
          </span>
          <span>
            Last notification: <strong>{formatDate(stats.last_notification_at)}</strong>
          </span>
        </div>
      )}

      {/* ---- Active scans ---- */}
      <section className="panel">
        <header className="panel-header">
          <h2 className="section-title">
            Active scans
            {activeScans.length > 0 && (
              <span className="live-pill">
                <span className="health-dot up" /> live
              </span>
            )}
          </h2>
        </header>
        {activeScans.length === 0 ? (
          <p className="muted panel-empty">No scans currently running.</p>
        ) : (
          <ul className="scan-list">
            {activeScans.map((scan) => (
              <ScanRow key={scan.id} scan={scan} />
            ))}
          </ul>
        )}
      </section>

      {/* ---- Recent scans ---- */}
      <section className="panel">
        <header className="panel-header">
          <h2 className="section-title">Recent scans</h2>
        </header>
        {recentScans.length === 0 ? (
          <p className="muted panel-empty">No completed scans yet.</p>
        ) : (
          <ul className="scan-list">
            {recentScans.slice(0, 10).map((scan) => (
              <ScanRow key={scan.id} scan={scan} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

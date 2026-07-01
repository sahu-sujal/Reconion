import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { scopesApi } from '../api/scopes'
import {
  scansApi,
  ACTIVE_SCAN_STATUSES,
  PAUSABLE_SCAN_STATUSES,
  RESUMABLE_SCAN_STATUSES,
} from '../api/scans'
import { PlusIcon, TrashIcon, ChevronRightIcon } from '../components/icons'
import ScanReport from '../components/ScanReport'
import StartScanModal from '../components/StartScanModal'

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
    PAUSED: 'badge-pending',
    COMPLETED: 'badge-active',
    FAILED: 'badge-failed',
    CANCELLED: 'badge-archived',
  }
  return <span className={`badge ${map[s] || 'badge-archived'}`}>{s || 'unknown'}</span>
}

function isActive(scan) {
  return ACTIVE_SCAN_STATUSES.includes((scan.status || '').toUpperCase())
}

function isPausable(scan) {
  return PAUSABLE_SCAN_STATUSES.includes((scan.status || '').toUpperCase())
}

function isResumable(scan) {
  return RESUMABLE_SCAN_STATUSES.includes((scan.status || '').toUpperCase())
}

export default function ScopeScansPage() {
  const { scopeId } = useParams()

  const [scope, setScope] = useState(null)
  const [scans, setScans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [showStart, setShowStart] = useState(false)
  const [starting, setStarting] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [controllingId, setControllingId] = useState(null) // pause/resume/stop in flight
  const [selectedId, setSelectedId] = useState(null) // expanded scan report

  const load = useCallback(async () => {
    setError(null)
    try {
      const [scopeData, scanList] = await Promise.all([
        scopesApi.get(scopeId),
        scansApi.list({ scopeId }).catch(() => []),
      ])
      setScope(scopeData)
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

  const sorted = useMemo(
    () =>
      [...scans].sort(
        (a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0),
      ),
    [scans],
  )

  const activeScan = sorted.find(isActive)

  // Live-refresh while a scan is active (scans run sequentially).
  useEffect(() => {
    if (!activeScan) return undefined
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [activeScan, load])

  async function startScan(scanType) {
    if (!scope) return
    setActionError(null)
    setStarting(true)
    try {
      await scansApi.start({
        program_id: scope.program_id,
        scope_id: scopeId,
        scan_type: scanType,
      })
      setShowStart(false)
      await load()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setStarting(false)
    }
  }

  async function deleteScan(scan, e) {
    e.stopPropagation()
    setActionError(null)
    if (!window.confirm(`Delete this ${scan.scan_type} scan? This cannot be undone.`)) {
      return
    }
    setDeletingId(scan.id)
    try {
      await scansApi.remove(scan.id)
      if (selectedId === scan.id) setSelectedId(null)
      await load()
    } catch (err) {
      // Backend rejects deleting PENDING/RUNNING scans with 409.
      setActionError(err.message)
    } finally {
      setDeletingId(null)
    }
  }

  // Pause / resume / stop a scan. `action` is 'pause' | 'resume' | 'stop'.
  async function controlScan(scan, action, e) {
    e.stopPropagation()
    setActionError(null)
    if (action === 'stop' &&
        !window.confirm('Stop this scan? It will be cancelled and can then be deleted.')) {
      return
    }
    setControllingId(scan.id)
    try {
      await scansApi[action](scan.id)
      await load()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setControllingId(null)
    }
  }

  if (loading) {
    return (
      <div className="page">
        <p className="muted">Loading scans…</p>
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
      </div>
    )
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
        <span>Scans</span>
      </div>

      <header className="page-header">
        <div>
          <h1>Scans</h1>
          <p className="subtitle">Start and manage scans for {scope?.target}</p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setShowStart(true)}
        >
          <PlusIcon />
          Start scan
        </button>
      </header>

      {activeScan && (
        <div className="alert alert-info">
          <span>
            <span className="health-dot up" /> A {activeScan.scan_type} scan is{' '}
            {activeScan.status.toLowerCase()} — scans run one at a time.
          </span>
        </div>
      )}

      {actionError && (
        <div className="alert alert-error">
          <span>{actionError}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setActionError(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {sorted.length === 0 ? (
        <div className="empty-state">
          <p>No scans yet for this scope.</p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowStart(true)}
          >
            <PlusIcon />
            Start your first scan
          </button>
        </div>
      ) : (
        <ul className="scan-cards">
          {sorted.map((scan) => {
            const expanded = selectedId === scan.id
            const found = scan.records_found ?? scan.unique_count ?? 0
            const active = isActive(scan)
            return (
              <li key={scan.id}>
                <div
                  className={`scan-card${expanded ? ' expanded' : ''}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedId(expanded ? null : scan.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') setSelectedId(expanded ? null : scan.id)
                  }}
                >
                  <div className="scan-card-main">
                    <ScanStatusBadge status={scan.status} />
                    <span className="scan-type">{scan.scan_type}</span>
                    <span className="muted scan-worker">{scan.worker_name}</span>
                  </div>
                  <div className="scan-card-meta">
                    <span className="muted">{found} found</span>
                    <span className="muted">{formatDate(scan.started_at)}</span>

                    {/* Pause — while running/pending */}
                    {isPausable(scan) && (
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={(e) => controlScan(scan, 'pause', e)}
                        disabled={controllingId === scan.id}
                        title="Pause at the next safe boundary"
                      >
                        {controllingId === scan.id ? '…' : '⏸ Pause'}
                      </button>
                    )}

                    {/* Resume — while paused */}
                    {isResumable(scan) && (
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        onClick={(e) => controlScan(scan, 'resume', e)}
                        disabled={controllingId === scan.id}
                        title="Resume from where it stopped"
                      >
                        {controllingId === scan.id ? '…' : '▶ Resume'}
                      </button>
                    )}

                    {/* Stop — while active or paused */}
                    {(isPausable(scan) || isResumable(scan)) && (
                      <button
                        type="button"
                        className="btn btn-sm btn-warning"
                        onClick={(e) => controlScan(scan, 'stop', e)}
                        disabled={controllingId === scan.id}
                        title="Stop (cancel) this scan"
                      >
                        ⏹ Stop
                      </button>
                    )}

                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      onClick={(e) => deleteScan(scan, e)}
                      disabled={active || deletingId === scan.id}
                      title={
                        active
                          ? 'Stop the scan first, then delete'
                          : 'Delete scan'
                      }
                    >
                      <TrashIcon />
                      {deletingId === scan.id ? 'Deleting…' : 'Delete'}
                    </button>
                    <ChevronRightIcon
                      className={`scan-chevron${expanded ? ' open' : ''}`}
                      width={16}
                      height={16}
                    />
                  </div>
                  {scan.error_message && (
                    <p className="scan-error">{scan.error_message}</p>
                  )}
                </div>

                {expanded && <ScanReport scanId={scan.id} />}
              </li>
            )
          })}
        </ul>
      )}

      {showStart && (
        <StartScanModal
          target={scope?.target}
          busy={starting}
          activeScan={activeScan}
          onStart={startScan}
          onClose={() => setShowStart(false)}
        />
      )}
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { programsApi } from '../api/programs'
import { scopesApi } from '../api/scopes'
import ScopeForm from '../components/ScopeForm'
import { PlusIcon, EditIcon, TrashIcon, ChevronRightIcon } from '../components/icons'

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

export default function ProgramDetailPage() {
  const { programId } = useParams()
  const navigate = useNavigate()

  const [program, setProgram] = useState(null)
  const [stats, setStats] = useState(null)
  const [scopes, setScopes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [prog, scopeList, statsData] = await Promise.all([
        programsApi.get(programId),
        scopesApi.list(programId),
        programsApi.stats(programId).catch(() => null), // stats are best-effort
      ])
      setProgram(prog)
      setScopes(Array.isArray(scopeList) ? scopeList : [])
      setStats(statsData)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [programId])

  useEffect(() => {
    load()
  }, [load])

  function openAdd() {
    setEditing(null)
    setShowForm(true)
  }

  function openEdit(scope, e) {
    e?.stopPropagation()
    setEditing(scope)
    setShowForm(true)
  }

  function closeForm() {
    setShowForm(false)
    setEditing(null)
  }

  async function handleSubmit(payload) {
    setSubmitting(true)
    try {
      if (editing) {
        await scopesApi.update(editing.id, payload)
      } else {
        await scopesApi.create({ ...payload, program_id: programId })
      }
      await load()
      closeForm()
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(scope, e) {
    e?.stopPropagation()
    if (!window.confirm(`Delete scope "${scope.target}"? This cannot be undone.`)) {
      return
    }
    try {
      await scopesApi.remove(scope.id)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="breadcrumb">
          <Link to="/">Programs</Link>
          <span>/</span>
          <span className="muted">Loading…</span>
        </div>
        <div className="stats-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton skeleton-stat" />
          ))}
        </div>
        <div className="scope-grid">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton skeleton-card" />
          ))}
        </div>
      </div>
    )
  }

  if (error && !program) {
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
        <span>{program?.name}</span>
      </div>

      <header className="page-header">
        <div>
          <h1>{program?.name}</h1>
          <p className="subtitle">
            {program?.platform && <span>{program.platform}</span>}
            <span className={`badge badge-${(program?.status || 'active').toLowerCase()}`}>
              {program?.status || 'active'}
            </span>
          </p>
        </div>
      </header>

      {/* ---- Program stats (key metrics only) ---- */}
      <div className="stats-grid">
        <StatCard label="Scopes" value={stats?.total_scopes ?? scopes.length} accent />
        <StatCard label="Subdomains" value={stats?.total_subdomains} />
        <StatCard label="Live hosts" value={stats?.live_hosts} />
        <StatCard label="URLs" value={stats?.total_urls} />
        <StatCard label="JS files" value={stats?.total_js_files} />
        <StatCard label="Technologies" value={stats?.total_technologies} />
        <StatCard label="Scan runs" value={stats?.total_scan_runs} />
        <StatCard label="Open findings" value={stats?.open_findings} accent />
      </div>

      {stats && (
        <div className="stat-meta-row">
          <span>
            Last scan: <strong>{formatDate(stats.last_scan_at)}</strong>
          </span>
          <span>
            Findings: <strong>{stats.total_findings ?? 0}</strong>
          </span>
          <span>
            DNS records: <strong>{stats.total_dns_records ?? 0}</strong>
          </span>
          <span>
            New URLs: <strong>{stats.new_urls ?? 0}</strong>
          </span>
          <span>
            New JS: <strong>{stats.new_js_files ?? 0}</strong>
          </span>
          <span>
            Notifications: <strong>{stats.total_notifications ?? 0}</strong>
          </span>
        </div>
      )}

      {/* ---- Scopes ---- */}
      <header className="page-header">
        <div>
          <h2 className="section-title">Scopes</h2>
          <p className="subtitle">
            {scopes.length} scope{scopes.length === 1 ? '' : 's'} in this program
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={openAdd}>
          <PlusIcon />
          Add scope
        </button>
      </header>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {scopes.length === 0 ? (
        <div className="empty-state">
          <p>No scopes for this program yet.</p>
          <button type="button" className="btn btn-primary" onClick={openAdd}>
            Add the first scope
          </button>
        </div>
      ) : (
        <ul className="scope-grid">
          {scopes.map((scope) => (
            <li key={scope.id}>
              {/* Clicking the card opens the scope dashboard (stats + scans).
                  Edit/Delete are explicit buttons that stop propagation. */}
              <div
                className="scope-card"
                role="button"
                tabIndex={0}
                onClick={() => navigate(`/scopes/${scope.id}`)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') navigate(`/scopes/${scope.id}`)
                }}
              >
                <div className="scope-card-top">
                  <span className="scope-target">{scope.target}</span>
                  <span className="badge badge-type">{scope.scope_type}</span>
                </div>

                <div className="scope-tags">
                  {scope.is_active ? (
                    <span className="badge badge-active">active</span>
                  ) : (
                    <span className="badge badge-archived">inactive</span>
                  )}
                  <span className="scope-priority">
                    Priority <strong>{scope.priority}</strong>
                  </span>
                </div>

                {scope.notes && <p className="scope-notes">{scope.notes}</p>}

                <div className="scope-card-actions">
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={(e) => openEdit(scope, e)}
                  >
                    <EditIcon />
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    onClick={(e) => handleDelete(scope, e)}
                  >
                    <TrashIcon />
                    Delete
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {showForm && (
        <div className="modal-overlay" onClick={closeForm}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <ScopeForm
              initial={editing}
              onSubmit={handleSubmit}
              onCancel={closeForm}
              submitting={submitting}
            />
          </div>
        </div>
      )}
    </div>
  )
}

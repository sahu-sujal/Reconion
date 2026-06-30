import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { programsApi } from '../api/programs'
import { statsApi } from '../api/stats'
import ProgramForm from '../components/ProgramForm'
import {
  PlusIcon,
  SearchIcon,
  ArrowRightIcon,
  EditIcon,
  TrashIcon,
} from '../components/icons'

function StatusBadge({ status }) {
  const cls = `badge badge-${(status || 'active').toLowerCase()}`
  return <span className={cls}>{status || 'active'}</span>
}

function StatCard({ label, value, accent }) {
  return (
    <div className="stat-card">
      <span className={`stat-value${accent ? ' accent' : ''}`}>{value ?? 0}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}

export default function ProgramsPage() {
  const navigate = useNavigate()
  const [programs, setPrograms] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [query, setQuery] = useState('')
  // modal: null = closed, 'new' = create, program object = edit
  const [modal, setModal] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [progList, statsData] = await Promise.all([
        programsApi.list(),
        statsApi.global().catch(() => null), // stats best-effort
      ])
      setPrograms(Array.isArray(progList) ? progList : [])
      setStats(statsData)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return programs
    return programs.filter((p) =>
      [p.name, p.platform, p.description, p.created_by, p.status]
        .filter(Boolean)
        .some((field) => field.toLowerCase().includes(q)),
    )
  }, [programs, query])

  function openProgram(program) {
    navigate(`/programs/${program.id}`)
  }

  function openEdit(program, e) {
    e.stopPropagation()
    setModal(program)
  }

  async function handleSubmit(payload) {
    setSubmitting(true)
    try {
      if (modal === 'new') {
        await programsApi.create(payload)
      } else {
        await programsApi.update(modal.id, payload)
      }
      await load()
      setModal(null)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(program, e) {
    e.stopPropagation()
    if (!window.confirm(`Delete program "${program.name}"? This cannot be undone.`)) {
      return
    }
    try {
      await programsApi.remove(program.id)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="subtitle">Manage your recon programs and scopes</p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setModal('new')}
        >
          <PlusIcon />
          New program
        </button>
      </header>

      {/* ---- Global stats ---- */}
      <div className="stats-grid">
        <StatCard label="Programs" value={stats?.total_programs ?? programs.length} accent />
        <StatCard label="Active" value={stats?.active_programs} />
        <StatCard label="Inactive" value={stats?.inactive_programs} />
        <StatCard label="Running scans" value={stats?.running_scans} accent />
        <StatCard label="Pending scans" value={stats?.pending_scans} />
      </div>

      {/* ---- Search ---- */}
      <div className="toolbar">
        <div className="search-box">
          <SearchIcon className="search-icon" />
          <input
            type="search"
            placeholder="Search programs by name, platform, owner…"
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
        <span className="muted result-count">
          {filtered.length} of {programs.length}
        </span>
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
        <ul className="program-list">
          {Array.from({ length: 4 }).map((_, i) => (
            <li key={i}>
              <div className="skeleton skeleton-row" />
            </li>
          ))}
        </ul>
      ) : programs.length === 0 ? (
        <div className="empty-state">
          <p>No programs yet.</p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setModal('new')}
          >
            Create your first program
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <p>No programs match “{query}”.</p>
          <button type="button" className="btn" onClick={() => setQuery('')}>
            Clear search
          </button>
        </div>
      ) : (
        <ul className="program-list">
          {filtered.map((program) => (
            <li key={program.id}>
              <div
                className="program-row"
                role="button"
                tabIndex={0}
                onClick={() => openProgram(program)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') openProgram(program)
                }}
              >
                <div className="program-row-body">
                  <div className="program-main">
                    <span className="program-name">{program.name}</span>
                    {program.platform && (
                      <span className="program-platform">{program.platform}</span>
                    )}
                    <StatusBadge status={program.status} />
                  </div>
                  {program.description && (
                    <p className="program-desc">{program.description}</p>
                  )}
                  {program.created_by && (
                    <span className="program-owner muted">{program.created_by}</span>
                  )}
                </div>

                <div className="program-row-actions">
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={(e) => openEdit(program, e)}
                    title="Edit program"
                  >
                    <EditIcon />
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    onClick={(e) => handleDelete(program, e)}
                    title="Delete program"
                  >
                    <TrashIcon />
                  </button>
                  <span className="program-arrow">
                    Open <ArrowRightIcon />
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {modal && (
        <div className="modal-overlay" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <ProgramForm
              initial={modal === 'new' ? null : modal}
              onSubmit={handleSubmit}
              onCancel={() => setModal(null)}
              submitting={submitting}
            />
          </div>
        </div>
      )}
    </div>
  )
}

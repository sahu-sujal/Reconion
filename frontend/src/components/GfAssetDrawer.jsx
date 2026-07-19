import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeftIcon, ArrowRightIcon } from './icons'

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function StatusPill({ code }) {
  const n = Number(code)
  if (code == null || Number.isNaN(n)) return <span className="muted">—</span>
  const cls =
    n >= 200 && n < 300
      ? 'status-2xx'
      : n >= 300 && n < 400
        ? 'status-3xx'
        : n >= 400 && n < 500
          ? 'status-4xx'
          : 'status-5xx'
  return <span className={`status-pill ${cls}`}>{n}</span>
}

function Field({ label, value, mono }) {
  return (
    <div className="kv">
      <span className="kv-label">{label}</span>
      <span className={`kv-value${mono ? ' mono' : ''}`}>{value ?? '—'}</span>
    </div>
  )
}

/**
 * Side drawer for one GF-classified asset.
 *
 * Props: asset, scopeId, position {index,total}, onPrev, onNext, onClose
 */
export default function GfAssetDrawer({
  asset,
  scopeId,
  position,
  onPrev,
  onNext,
  onClose,
}) {
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose?.()
      else if (e.key === 'ArrowLeft' && onPrev) onPrev()
      else if (e.key === 'ArrowRight' && onNext) onNext()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onPrev, onNext, onClose])

  if (!asset) return null

  const tags = asset.gf_tags || []
  const sid = scopeId || asset.scope_id

  // Quick links into the existing explorers, pre-filtered to this asset's host.
  const hostQuery = asset.host ? `?host=${encodeURIComponent(asset.host)}` : ''
  const related = [
    { to: `/scopes/${sid}/content${hostQuery}`, label: 'Asset Explorer' },
    { to: `/scopes/${sid}/endpoints${hostQuery}`, label: 'Endpoints' },
    { to: `/scopes/${sid}/secrets${hostQuery}`, label: 'Secrets' },
    { to: `/scopes/${sid}/live`, label: 'Live Domains / Screenshot' },
  ]

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="drawer gf-drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-header">
          <div className="dd-head-main">
            <h2 className="drawer-title">{asset.host || asset.url}</h2>
            <p className="subtitle dd-subtitle">
              <span className="badge badge-type">{asset.asset_type}</span>
              <StatusPill code={asset.status} />
              {asset.asset_category && (
                <span className="badge badge-archived">{asset.asset_category}</span>
              )}
            </p>
          </div>
          <div className="dd-nav">
            <button
              type="button"
              className="btn btn-sm"
              onClick={onPrev}
              disabled={!onPrev}
              aria-label="Previous asset"
              title="Previous (←)"
            >
              <ArrowLeftIcon width={16} height={16} />
            </button>
            {position && (
              <span className="muted dd-position">
                {position.index + 1} / {position.total}
              </span>
            )}
            <button
              type="button"
              className="btn btn-sm"
              onClick={onNext}
              disabled={!onNext}
              aria-label="Next asset"
              title="Next (→)"
            >
              <ArrowRightIcon width={16} height={16} />
            </button>
            <button type="button" className="drawer-close" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
        </header>

        <div className="drawer-body">
          <div className="dd-url">
            <a href={asset.url} target="_blank" rel="noreferrer noopener" className="cell-mono">
              {asset.url}
            </a>
          </div>

          <section className="dd-section">
            <h3 className="dd-section-title">GF Profile ({tags.length})</h3>
            {tags.length > 0 ? (
              <ul className="gf-profile">
                {tags.map((t) => (
                  <li key={t}>
                    <span className="gf-check">✓</span>
                    <span className="badge badge-gf">{t}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No GF matches for this asset.</p>
            )}
          </section>

          <section className="dd-section">
            <h3 className="dd-section-title">Basic Information</h3>
            <div className="kv-list">
              <Field label="Host" value={asset.host} mono />
              <Field label="Asset type" value={asset.asset_type} />
              <Field label="HTTP status" value={asset.status} mono />
              <Field label="Content type" value={asset.mime_type} mono />
              <Field label="Asset category" value={asset.asset_category} />
              <Field label="Extension" value={asset.extension} mono />
              <Field label="Parameters" value={asset.parameter_count} mono />
              <Field label="Discovery source" value={asset.discovery_source} />
              <Field label="Classified" value={formatDate(asset.gf_classified_at)} />
              <Field label="First seen" value={formatDate(asset.first_seen)} />
              <Field label="Last seen" value={formatDate(asset.last_seen)} />
            </div>
          </section>

          <section className="dd-section">
            <h3 className="dd-section-title">Related</h3>
            <div className="flag-tags wrap">
              {related.map((r) => (
                <Link key={r.label} to={r.to} className="btn btn-sm">
                  {r.label}
                </Link>
              ))}
            </div>
          </section>
        </div>
      </aside>
    </div>
  )
}

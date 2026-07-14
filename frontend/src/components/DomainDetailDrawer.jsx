import { useEffect, useState } from 'react'
import { storageUrl } from '../api/client'
import { ArrowLeftIcon, ArrowRightIcon } from './icons'

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

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function hostUrl(h) {
  const scheme = h.scheme || (h.port === 443 ? 'https' : 'http')
  const defaultPort = scheme === 'https' ? 443 : 80
  const portPart = h.port && h.port !== defaultPort ? `:${h.port}` : ''
  return `${scheme}://${h.host}${portPart}`
}

function Stat({ label, value }) {
  return (
    <div className="dd-stat">
      <span className="dd-stat-value">{value ?? 0}</span>
      <span className="dd-stat-label">{label}</span>
    </div>
  )
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
 * Slide-over detail view for a single live domain.
 *
 * Props:
 *   host           - the currently displayed host object
 *   technologies   - technology[] for this host
 *   httpResponses  - httpResponse[] for this host
 *   dnsRecords     - dnsRecord[] for this host
 *   screenshots    - screenshot[] for this host (from the screenshots endpoint)
 *   position       - { index, total } for the "n of m" label
 *   onPrev/onNext  - navigate to the adjacent domain (null when unavailable)
 *   onClose
 */
export default function DomainDetailDrawer({
  host,
  technologies = [],
  httpResponses = [],
  dnsRecords = [],
  screenshots = [],
  position,
  onPrev,
  onNext,
  onClose,
}) {
  const [imgError, setImgError] = useState(false)
  const [shotIdx, setShotIdx] = useState(0)

  // Reset gallery + error state whenever the host changes.
  useEffect(() => {
    setImgError(false)
    setShotIdx(0)
  }, [host?.id])

  // Keyboard navigation between domains.
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose?.()
      else if (e.key === 'ArrowLeft' && onPrev) onPrev()
      else if (e.key === 'ArrowRight' && onNext) onNext()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onPrev, onNext, onClose])

  if (!host) return null

  // Prefer captured shots (not failed, with a file_path); fall back to host.screenshot_path.
  const captured = screenshots.filter((s) => s.file_path && !s.failed)
  const activeShot = captured[shotIdx] || null
  const imgSrc = activeShot
    ? storageUrl(activeShot.file_path)
    : host.screenshot_path
      ? storageUrl(host.screenshot_path)
      : null

  const url = hostUrl(host)

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="drawer dd-drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-header">
          <div className="dd-head-main">
            <h2 className="drawer-title">{host.host}</h2>
            <p className="subtitle dd-subtitle">
              <StatusPill code={host.status_code} />
              {host.ip && <span className="muted">{host.ip}</span>}
              {host.title && <span className="dd-page-title">{host.title}</span>}
            </p>
          </div>
          <div className="dd-nav">
            <button
              type="button"
              className="btn btn-sm"
              onClick={onPrev}
              disabled={!onPrev}
              aria-label="Previous domain"
              title="Previous domain (←)"
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
              aria-label="Next domain"
              title="Next domain (→)"
            >
              <ArrowRightIcon width={16} height={16} />
            </button>
            <button
              type="button"
              className="drawer-close"
              onClick={onClose}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </header>

        <div className="drawer-body">
          {/* ---- Screenshot ---- */}
          <div className="dd-shot">
            {imgSrc && !imgError ? (
              <a href={url} target="_blank" rel="noreferrer noopener">
                <img
                  src={imgSrc}
                  alt={`Screenshot of ${host.host}`}
                  className="dd-shot-img"
                  onError={() => setImgError(true)}
                />
              </a>
            ) : (
              <div className="dd-shot-empty">
                <span>No screenshot captured</span>
                <span className="muted">Run a Screenshot scan for this scope</span>
              </div>
            )}
            {captured.length > 1 && (
              <div className="dd-shot-nav">
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setShotIdx((i) => Math.max(0, i - 1))}
                  disabled={shotIdx === 0}
                >
                  ‹
                </button>
                <span className="muted">
                  {activeShot?.url} · {shotIdx + 1}/{captured.length}
                </span>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setShotIdx((i) => Math.min(captured.length - 1, i + 1))}
                  disabled={shotIdx >= captured.length - 1}
                >
                  ›
                </button>
              </div>
            )}
          </div>

          {/* ---- URL ---- */}
          <div className="dd-url">
            <a href={url} target="_blank" rel="noreferrer noopener" className="cell-mono">
              {url}
            </a>
          </div>

          {/* ---- Counts ---- */}
          <div className="dd-stats">
            <Stat label="URLs" value={host.url_count} />
            <Stat label="JS files" value={host.js_count} />
            <Stat label="Endpoints" value={host.endpoint_count} />
            <Stat label="Secrets" value={host.secret_count} />
            <Stat label="Screenshots" value={host.screenshot_count} />
            <Stat label="Technologies" value={technologies.length} />
            <Stat label="DNS records" value={dnsRecords.length} />
            <Stat label="HTTP resp." value={httpResponses.length} />
          </div>

          {/* ---- Host details ---- */}
          <section className="dd-section">
            <h3 className="dd-section-title">Host</h3>
            <div className="kv-list">
              <Field label="IP" value={host.ip} mono />
              <Field label="Scheme" value={host.scheme} />
              <Field label="Port" value={host.port} mono />
              <Field label="Content length" value={host.content_length} mono />
              <Field
                label="Response time"
                value={host.response_time != null ? `${host.response_time} ms` : null}
                mono
              />
              <Field label="CDN" value={host.cdn ? 'yes' : 'no'} />
              <Field label="WAF" value={host.waf ? 'yes' : 'no'} />
              <Field label="First seen" value={formatDate(host.first_seen)} />
              <Field label="Last seen" value={formatDate(host.last_seen)} />
            </div>
          </section>

          {/* ---- Technologies ---- */}
          {technologies.length > 0 && (
            <section className="dd-section">
              <h3 className="dd-section-title">Technologies ({technologies.length})</h3>
              <div className="flag-tags wrap">
                {technologies.map((t) => (
                  <span key={t.id} className="badge badge-type">
                    {t.technology}
                    {t.version ? ` ${t.version}` : ''}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* ---- DNS records ---- */}
          {dnsRecords.length > 0 && (
            <section className="dd-section">
              <h3 className="dd-section-title">DNS records ({dnsRecords.length})</h3>
              <table className="data-table compact">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Value</th>
                  </tr>
                </thead>
                <tbody>
                  {dnsRecords.map((d) => (
                    <tr key={d.id}>
                      <td className="cell-mono">{d.record_type}</td>
                      <td className="cell-mono">{d.record_value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </div>
      </aside>
    </div>
  )
}

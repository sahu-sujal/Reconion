import { useState } from 'react'
import { Link } from 'react-router-dom'

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

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

function Field({ label, value, mono }) {
  return (
    <div className="kv">
      <span className="kv-label">{label}</span>
      <span className={`kv-value${mono ? ' mono' : ''}`}>{value ?? '—'}</span>
    </div>
  )
}

// `data` = { subdomain, host, httpResponses[], dnsRecords[], technologies[] }
export default function SubdomainDrawer({ data, onClose }) {
  const [tab, setTab] = useState('host')
  if (!data) return null

  const { subdomain, host, httpResponses = [], dnsRecords = [], technologies = [] } = data

  const tabs = [
    { id: 'host', label: 'Host' },
    { id: 'http', label: `HTTP (${httpResponses.length})` },
    { id: 'dns', label: `DNS (${dnsRecords.length})` },
    { id: 'tech', label: `Tech (${technologies.length})` },
  ]

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-header">
          <div>
            <h2 className="drawer-title">{subdomain.subdomain}</h2>
            <p className="subtitle">
              {host?.status_code != null ? (
                <StatusPill code={host.status_code} />
              ) : (
                <span className="badge badge-archived">no host</span>
              )}
              {host?.ip && <span className="muted">{host.ip}</span>}
            </p>
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="drawer-tabs">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`drawer-tab${tab === t.id ? ' active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="drawer-body">
          {tab === 'host' && (
            <div className="kv-list">
              <Field label="Subdomain" value={subdomain.subdomain} mono />
              <Field label="Source tools" value={subdomain.source} />
              <Field
                label="Endpoints"
                value={
                  subdomain.endpoint_count > 0 ? (
                    <Link
                      className="endpoint-count-link"
                      to={`/scopes/${subdomain.scope_id}/endpoints?subdomain_id=${subdomain.id}&subdomain=${encodeURIComponent(subdomain.subdomain)}`}
                      onClick={onClose}
                      title="Open Endpoint Explorer filtered for this subdomain"
                    >
                      {subdomain.endpoint_count.toLocaleString()} →
                    </Link>
                  ) : (
                    <span className="muted">0</span>
                  )
                }
              />
              <Field label="First seen" value={formatDate(subdomain.first_seen)} />
              <Field label="Last seen" value={formatDate(subdomain.last_seen)} />
              {host ? (
                <>
                  <div className="kv-divider" />
                  <Field label="IP" value={host.ip} mono />
                  <Field
                    label="Status"
                    value={host.status_code != null ? <StatusPill code={host.status_code} /> : '—'}
                  />
                  <Field label="Title" value={host.title} />
                  <Field
                    label="Scheme / Port"
                    value={host.scheme ? `${host.scheme}${host.port ? `:${host.port}` : ''}` : '—'}
                  />
                  <Field label="Content length" value={host.content_length} />
                  <Field
                    label="Response time"
                    value={host.response_time != null ? `${host.response_time}s` : '—'}
                  />
                  <Field
                    label="Flags"
                    value={
                      <span className="flag-tags">
                        {host.cdn && <span className="badge badge-type">CDN</span>}
                        {host.waf && <span className="badge badge-pending">WAF</span>}
                        {!host.cdn && !host.waf && '—'}
                      </span>
                    }
                  />
                </>
              ) : (
                <p className="muted drawer-empty">
                  No resolved host yet. Run DNS + HTTP scans to populate this.
                </p>
              )}
            </div>
          )}

          {tab === 'http' && (
            httpResponses.length === 0 ? (
              <p className="muted drawer-empty">No HTTP responses recorded.</p>
            ) : (
              <div className="kv-stack">
                {httpResponses.map((r) => (
                  <div key={r.id} className="kv-card">
                    <div className="kv-card-head">
                      <StatusPill code={r.status_code} />
                      <span className="cell-mono">{r.url}</span>
                    </div>
                    <div className="kv-list compact">
                      <Field label="Title" value={r.title} />
                      <Field label="Server" value={r.server} />
                      <Field label="Content length" value={r.content_length} />
                      {r.technologies?.length > 0 && (
                        <Field
                          label="Technologies"
                          value={
                            <span className="flag-tags wrap">
                              {r.technologies.map((t) => (
                                <span key={t} className="badge badge-type">{t}</span>
                              ))}
                            </span>
                          }
                        />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )
          )}

          {tab === 'dns' && (
            dnsRecords.length === 0 ? (
              <p className="muted drawer-empty">No DNS records recorded.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Value</th>
                    <th>TTL</th>
                  </tr>
                </thead>
                <tbody>
                  {dnsRecords.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <span className="badge badge-type">{d.record_type}</span>
                      </td>
                      <td className="cell-mono">{d.record_value}</td>
                      <td className="muted">{d.ttl ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          )}

          {tab === 'tech' && (
            technologies.length === 0 ? (
              <p className="muted drawer-empty">No technologies detected.</p>
            ) : (
              <div className="tech-chips">
                {technologies.map((t) => (
                  <span key={t.id} className="tech-chip">
                    <strong>{t.technology}</strong>
                    {t.version && <span className="muted"> {t.version}</span>}
                    {t.confidence != null && (
                      <span className="tech-conf">{t.confidence}%</span>
                    )}
                  </span>
                ))}
              </div>
            )
          )}
        </div>
      </aside>
    </div>
  )
}

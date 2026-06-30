import { useEffect, useState } from 'react'
import { scansApi } from '../api/scans'

// Inline scan report — fetched per scan from GET /scans/{id}/report.
// Shows pipeline metrics + a per-tool execution breakdown.

function Metric({ label, value }) {
  if (value === undefined || value === null || value === 0) return null
  return (
    <div className="metric">
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  )
}

function ToolStatusBadge({ status }) {
  const s = (status || '').toUpperCase()
  const map = {
    COMPLETED: 'badge-active',
    RUNNING: 'badge-running',
    PENDING: 'badge-pending',
    FAILED: 'badge-failed',
  }
  return <span className={`badge ${map[s] || 'badge-archived'}`}>{s.toLowerCase()}</span>
}

export default function ScanReport({ scanId }) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    scansApi
      .report(scanId)
      .then((data) => active && setReport(data))
      .catch((err) => active && setError(err.message))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [scanId])

  if (loading) {
    return <div className="scan-report muted">Loading report…</div>
  }
  if (error) {
    return <div className="scan-report alert alert-error">{error}</div>
  }
  if (!report) return null

  const metrics = [
    ['Subfinder', report.subfinder_count],
    ['Assetfinder', report.assetfinder_count],
    ['Merged', report.merged_count],
    ['Unique', report.unique_count],
    ['New', report.new_count],
    ['Existing', report.existing_count],
    ['dnsx', report.dnsx_count],
    ['Resolved', report.resolved_count],
    ['New hosts', report.new_hosts_count],
    ['httpx', report.httpx_count],
    ['Live', report.live_count],
    ['New live', report.new_live_count],
  ]
  const hasMetrics = metrics.some(([, v]) => v)

  return (
    <div className="scan-report">
      {report.summary && <p className="scan-summary">{report.summary}</p>}

      {hasMetrics && (
        <div className="metric-grid">
          {metrics.map(([label, value]) => (
            <Metric key={label} label={label} value={value} />
          ))}
        </div>
      )}

      {report.duration_seconds != null && (
        <p className="muted scan-duration">
          Duration: {report.duration_seconds.toFixed(1)}s
        </p>
      )}

      {report.tools?.length > 0 && (
        <table className="tool-table">
          <thead>
            <tr>
              <th>Tool</th>
              <th>Status</th>
              <th>Raw</th>
              <th>In-scope</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {report.tools.map((t) => (
              <tr key={t.id}>
                <td className="tool-name">{t.tool_name}</td>
                <td>
                  <ToolStatusBadge status={t.status} />
                </td>
                <td>{t.raw_records_found}</td>
                <td>{t.records_found}</td>
                <td>
                  {t.duration_seconds != null ? `${t.duration_seconds.toFixed(1)}s` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

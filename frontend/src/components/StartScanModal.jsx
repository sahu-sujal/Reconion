import { useState } from 'react'
import { GlobeIcon, RadarIcon, PulseIcon, SearchIcon } from './icons'

// The pipeline runs sequentially: SUBDOMAIN → DNS → HTTP → CONTENT_DISCOVERY →
// JS_ENDPOINT. Each stage chains the next on the backend, so picking an earlier
// stage runs everything after it too.
const STAGES = [
  {
    type: 'SUBDOMAIN',
    label: 'Subdomain enumeration',
    desc: 'Discover subdomains (subfinder, assetfinder, crtsh…). Chains DNS + HTTP after.',
    Icon: GlobeIcon,
    step: 1,
  },
  {
    type: 'DNS',
    label: 'DNS resolution',
    desc: 'Resolve known subdomains to hosts/records (dnsx). Chains HTTP after.',
    Icon: RadarIcon,
    step: 2,
  },
  {
    type: 'HTTP',
    label: 'HTTP probing',
    desc: 'Probe resolved hosts for live services & tech (httpx). Chains content discovery after.',
    Icon: PulseIcon,
    step: 3,
  },
  {
    type: 'CONTENT_DISCOVERY',
    label: 'Content discovery',
    desc: 'Discover URLs & JS from history + crawling (gau, waybackurls, katana, hakrawler). Chains JS endpoint discovery after.',
    Icon: RadarIcon,
    step: 4,
  },
  {
    type: 'JS_ENDPOINT',
    label: 'JS endpoint discovery',
    desc: 'Extract endpoints from discovered JS files (LinkFinder, XNLinkFinder, JSluice). Reprocesses stored JS files. Final stage.',
    Icon: SearchIcon,
    step: 5,
  },
]

export default function StartScanModal({ target, busy, activeScan, onStart, onClose }) {
  const [selected, setSelected] = useState('SUBDOMAIN')

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal start-scan-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Start a scan</h2>
        <p className="modal-sub">
          Pick the stage to run for <strong>{target}</strong>. Scans run one at a
          time and each stage automatically chains the next.
        </p>

        {activeScan && (
          <div className="alert alert-warning">
            A {activeScan.scan_type} scan is already{' '}
            {activeScan.status.toLowerCase()}. Wait for it to finish before
            starting another.
          </div>
        )}

        <div className="stage-list">
          {STAGES.map(({ type, label, desc, Icon, step }) => (
            <button
              key={type}
              type="button"
              className={`stage-option${selected === type ? ' selected' : ''}`}
              onClick={() => setSelected(type)}
              aria-pressed={selected === type}
            >
              <span className="stage-step">{step}</span>
              <span className="stage-icon">
                <Icon width={18} height={18} />
              </span>
              <span className="stage-text">
                <span className="stage-label">{label}</span>
                <span className="stage-desc">{desc}</span>
              </span>
              <span className="stage-radio" />
            </button>
          ))}
        </div>

        <div className="form-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || Boolean(activeScan)}
            onClick={() => onStart(selected)}
          >
            {busy ? 'Starting…' : `Start ${selected} scan`}
          </button>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

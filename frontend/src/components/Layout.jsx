import { useEffect, useState } from 'react'
import { NavLink, Outlet, useMatch } from 'react-router-dom'
import { healthApi } from '../api/stats'
import { GridIcon, RadarIcon, GaugeIcon, GlobeIcon, PulseIcon, LayersIcon, SearchIcon } from './icons'

const GLOBAL_ITEMS = [{ to: '/', label: 'Programs', Icon: GridIcon, end: true }]

export default function Layout() {
  const [health, setHealth] = useState(null) // null = checking, true/false

  // When inside a scope, show scope-context nav in the sidebar.
  const scopeMatch = useMatch('/scopes/:scopeId/*')
  const scopeId = scopeMatch?.params?.scopeId

  useEffect(() => {
    let active = true
    async function check() {
      try {
        const res = await healthApi.check()
        if (active) setHealth(res?.status === 'ok')
      } catch {
        if (active) setHealth(false)
      }
    }
    check()
    const id = setInterval(check, 15000)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [])

  const scopeItems = scopeId
    ? [
        { to: `/scopes/${scopeId}`, label: 'Overview', Icon: GaugeIcon, end: true },
        { to: `/scopes/${scopeId}/subdomains`, label: 'Subdomains', Icon: GlobeIcon },
        { to: `/scopes/${scopeId}/content`, label: 'Content Discovery', Icon: LayersIcon },
        { to: `/scopes/${scopeId}/endpoints`, label: 'Endpoints', Icon: SearchIcon },
        { to: `/scopes/${scopeId}/secrets`, label: 'Secrets', Icon: RadarIcon },
        { to: `/scopes/${scopeId}/scans`, label: 'Scans', Icon: PulseIcon },
      ]
    : []

  return (
    <div className="layout">
      <header className="navbar">
        <div className="navbar-brand">
          <span className="brand-mark">
            <RadarIcon width={20} height={20} />
          </span>
          <span className="brand-text">Recon Platform</span>
        </div>
        <div className="navbar-right">
          <span className="api-status">
            <span
              className={`health-dot ${
                health === null ? 'unknown' : health ? 'up' : 'down'
              }`}
            />
            API {health === null ? 'checking…' : health ? 'online' : 'offline'}
          </span>
        </div>
      </header>

      <div className="layout-body">
        <aside className="sidebar">
          <nav className="sidebar-nav-wrap">
            <SidebarGroup label="Manage" items={GLOBAL_ITEMS} />
            {scopeId && <SidebarGroup label="Scope" items={scopeItems} />}
          </nav>
        </aside>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function SidebarGroup({ label, items }) {
  return (
    <div className="sidebar-group">
      <div className="sidebar-section">{label}</div>
      <ul className="sidebar-nav">
        {items.map(({ to, label: itemLabel, Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}
            >
              <Icon className="sidebar-icon" />
              <span>{itemLabel}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { scopesApi } from '../api/scopes'
import { HUNT_CATEGORIES, categorize } from '../lib/huntCategories'

const PAGE_SIZE = 25
// Max rows pulled for client-side hunting categorization (API hard cap).
const HUNT_SAMPLE_LIMIT = 10000

// Multi-part public suffixes where the registrable domain is the last 3 labels
// (e.g. example.co.uk → co.uk). Small practical list — not the full PSL.
const MULTI_PART_TLDS = new Set([
  'co.uk', 'org.uk', 'gov.uk', 'ac.uk', 'co.in', 'co.jp', 'com.au',
  'net.au', 'org.au', 'com.br', 'com.sg', 'co.nz', 'co.za',
])

// Collapse a host (e.g. "help.ortto.com") to its root domain ("ortto.com").
function rootDomain(host) {
  if (!host) return host
  const labels = host.split('.').filter(Boolean)
  if (labels.length <= 2) return host
  const lastTwo = labels.slice(-2).join('.')
  if (MULTI_PART_TLDS.has(lastTwo)) {
    return labels.slice(-3).join('.')
  }
  return lastTwo
}

function SourceBadges({ source }) {
  if (!source) return null
  const parts = source.split(',').filter(Boolean)
  return (
    <span className="src-badges">
      {parts.map((p) => (
        <span key={p} className="badge badge-type src-badge">
          {p}
        </span>
      ))}
    </span>
  )
}

export default function ContentDiscoveryPanel({ scopeId, stats }) {
  const [tab, setTab] = useState('urls') // 'urls' | 'js'
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [domainFilter, setDomainFilter] = useState('') // '' = all domains
  const [page, setPage] = useState(0)
  const [data, setData] = useState({ total: 0, items: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

  // ---- Hunt (category) state ----
  const [showHunt, setShowHunt] = useState(true)
  const [activeCat, setActiveCat] = useState('') // '' = no category filter
  const [sample, setSample] = useState([]) // broad slice for client-side categorization
  const [sampleLoading, setSampleLoading] = useState(false)
  const [sampleTruncated, setSampleTruncated] = useState(false)

  // ---- Root-domain list (fetched once, collapsed + deduped client-side) ----
  const [allDomains, setAllDomains] = useState([])
  const [domainQuery, setDomainQuery] = useState('')

  useEffect(() => {
    let active = true
    scopesApi
      .urlHosts(scopeId)
      .then((list) => {
        if (!active) return
        // Collapse each host to its root domain, then dedupe + sort — so the
        // dropdown shows "ortto.com", not every "x.ortto.com" subdomain.
        const domains = Array.from(
          new Set((list || []).filter(Boolean).map(rootDomain)),
        ).sort((a, b) => a.localeCompare(b))
        setAllDomains(domains)
      })
      .catch(() => active && setAllDomains([]))
    return () => {
      active = false
    }
  }, [scopeId])

  // Domains shown in the dropdown, narrowed by what the user types.
  const visibleDomains = useMemo(() => {
    const q = domainQuery.trim().toLowerCase()
    const list = q ? allDomains.filter((d) => d.toLowerCase().includes(q)) : allDomains
    return list.slice(0, 500) // cap rendered <option>s for very large scopes
  }, [allDomains, domainQuery])

  // Debounce search input.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setDebounced(search.trim())
      setPage(0)
    }, 350)
    return () => clearTimeout(debounceRef.current)
  }, [search])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // Domain and text search are independent server-side filters (ANDed):
      // `host` matches the selected root domain + all its subdomains, while
      // `search` substring-matches the URL. Both can be active at once.
      const opts = {
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: debounced || undefined,
        host: domainFilter || undefined,
      }
      const res =
        tab === 'urls'
          ? await scopesApi.urls(scopeId, opts)
          : await scopesApi.jsFiles(scopeId, opts)
      setData(res || { total: 0, items: [] })
    } catch (err) {
      setError(err.message)
      setData({ total: 0, items: [] })
    } finally {
      setLoading(false)
    }
  }, [scopeId, tab, debounced, domainFilter, page])

  useEffect(() => {
    load()
  }, [load])

  // Reset paging when the domain filter changes.
  useEffect(() => {
    setPage(0)
  }, [domainFilter])

  // ---- Load a broad sample for client-side hunting categorization ----
  // Reloads whenever the scope/tab/domain/search changes (NOT on page change,
  // since categorization is over the whole result set, not one page).
  useEffect(() => {
    let active = true
    setSampleLoading(true)
    const opts = {
      offset: 0,
      limit: HUNT_SAMPLE_LIMIT,
      search: debounced || undefined,
      host: domainFilter || undefined,
    }
    const req = tab === 'urls' ? scopesApi.urls(scopeId, opts) : scopesApi.jsFiles(scopeId, opts)
    req
      .then((res) => {
        if (!active) return
        const items = res?.items || []
        setSample(items)
        setSampleTruncated((res?.total || 0) > items.length)
      })
      .catch(() => {
        if (active) {
          setSample([])
          setSampleTruncated(false)
        }
      })
      .finally(() => active && setSampleLoading(false))
    return () => {
      active = false
    }
  }, [scopeId, tab, debounced, domainFilter])

  // Categorize the sample once → counts per category + a matcher for the active one.
  const { counts, matches } = useMemo(
    () => categorize(sample, { isJs: tab === 'js' }),
    [sample, tab],
  )

  // Categories that actually have matches, ordered by count desc (most useful first).
  const presentCategories = useMemo(
    () =>
      HUNT_CATEGORIES.filter((c) => counts[c.id] > 0).sort(
        (a, b) => counts[b.id] - counts[a.id],
      ),
    [counts],
  )

  // When a category is active, results are filtered + paginated client-side over
  // the sample. Otherwise we use the server-paginated `data`.
  const catMatches = useMemo(
    () => (activeCat ? matches(activeCat) : null),
    [activeCat, matches],
  )

  // Clear the active category when switching tabs or filters invalidate it.
  useEffect(() => {
    if (activeCat && counts[activeCat] === 0) setActiveCat('')
  }, [counts, activeCat])

  // Reset paging when switching tabs (keep the host filter — it applies to both).
  const switchTab = (next) => {
    if (next === tab) return
    setTab(next)
    setPage(0)
    setSearch('')
    setDebounced('')
    setActiveCat('')
  }

  // Reset paging when the active category changes.
  useEffect(() => {
    setPage(0)
  }, [activeCat])

  // When a category is active, page over the client-filtered matches; otherwise
  // use the server-paginated data.
  const catActive = Boolean(activeCat) && Array.isArray(catMatches)
  const total = catActive ? catMatches.length : data.total || 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rows = catActive
    ? catMatches.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
    : data.items

  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="section-title">Content discovery</h2>
        <div className="tab-switch">
          <button
            type="button"
            className={`tab-btn${tab === 'urls' ? ' active' : ''}`}
            onClick={() => switchTab('urls')}
          >
            URLs {stats?.urls_count != null && <span className="muted">({stats.urls_count})</span>}
          </button>
          <button
            type="button"
            className={`tab-btn${tab === 'js' ? ' active' : ''}`}
            onClick={() => switchTab('js')}
          >
            JS files {stats?.js_count != null && <span className="muted">({stats.js_count})</span>}
          </button>
        </div>
      </header>

      <div className="cd-toolbar">
        <input
          type="search"
          className="input"
          placeholder={tab === 'urls' ? 'Search URLs…' : 'Search JS files…'}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        {/* Domain filter: type to narrow the root-domain dropdown.
            Picking a domain matches that domain AND all its subdomains. */}
        <div className="cd-host-filter">
          <input
            type="search"
            className="input cd-host-search"
            placeholder="Filter domains…"
            value={domainQuery}
            onChange={(e) => setDomainQuery(e.target.value)}
            disabled={allDomains.length === 0}
          />
          <select
            className="input cd-host-select"
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            disabled={allDomains.length === 0}
          >
            <option value="">All domains ({allDomains.length})</option>
            {/* Keep the currently-selected domain visible even if filtered out */}
            {domainFilter && !visibleDomains.includes(domainFilter) && (
              <option value={domainFilter}>{domainFilter}</option>
            )}
            {visibleDomains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>

        {domainFilter && (
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => {
              setDomainFilter('')
              setDomainQuery('')
            }}
          >
            Clear domain
          </button>
        )}

        <span className="muted cd-count">
          {total.toLocaleString()} {tab === 'urls' ? 'URLs' : 'JS files'}
          {domainFilter && <span className="muted"> · {domainFilter} (+subdomains)</span>}
          {catActive && (
            <span className="muted">
              {' '}· {HUNT_CATEGORIES.find((c) => c.id === activeCat)?.label}
            </span>
          )}
        </span>
      </div>

      {/* ---- Hunt: category suggestion chips (computed from loaded data) ---- */}
      <div className="cd-hunt">
        <button
          type="button"
          className="cd-hunt-toggle"
          onClick={() => setShowHunt((s) => !s)}
          aria-expanded={showHunt}
        >
          🎯 Hunt {showHunt ? '▾' : '▸'}
          {sampleTruncated && (
            <span className="muted cd-hunt-note"> (first {HUNT_SAMPLE_LIMIT.toLocaleString()})</span>
          )}
        </button>
        {showHunt && (
          <div className="cd-chips">
            {sampleLoading && presentCategories.length === 0 ? (
              <span className="muted">Analyzing…</span>
            ) : presentCategories.length === 0 ? (
              <span className="muted">No category matches in the loaded data.</span>
            ) : (
              <>
                {activeCat && (
                  <button
                    type="button"
                    className="cd-chip cd-chip-clear"
                    onClick={() => setActiveCat('')}
                  >
                    ✕ Clear
                  </button>
                )}
                {presentCategories.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    title={c.hint}
                    className={`cd-chip${activeCat === c.id ? ' active' : ''}`}
                    onClick={() => setActiveCat((cur) => (cur === c.id ? '' : c.id))}
                  >
                    {c.label}
                    <span className="cd-chip-count">{counts[c.id].toLocaleString()}</span>
                  </button>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {(catActive ? sampleLoading : loading) ? (
        <p className="muted panel-empty">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted panel-empty">
          {catActive
            ? 'No URLs match this category.'
            : debounced
              ? 'No matches.'
              : 'No content discovered yet. Run a content discovery scan.'}
        </p>
      ) : (
        <ul className="cd-list">
          {rows.map((item) => (
            <li key={item.id} className="cd-row">
              <a
                href={tab === 'urls' ? item.normalized_url : item.url}
                target="_blank"
                rel="noreferrer"
                className="cd-url"
                title={tab === 'urls' ? item.normalized_url : item.url}
              >
                {tab === 'urls' ? item.normalized_url : item.url}
              </a>
              <SourceBadges source={item.source} />
            </li>
          ))}
        </ul>
      )}

      {total > PAGE_SIZE && (
        <div className="cd-pager">
          <button
            type="button"
            className="btn btn-sm"
            disabled={page === 0 || (catActive ? sampleLoading : loading)}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            ← Prev
          </button>
          <span className="muted">
            Page {page + 1} of {totalPages}
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={page >= totalPages - 1 || (catActive ? sampleLoading : loading)}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </button>
        </div>
      )}
    </section>
  )
}

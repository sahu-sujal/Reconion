// Endpoint inventory API (Phase 6.1) — mirrors backend/api/endpoint_routes.py
import { api } from './client'

export const endpointsApi = {
  // All endpoints for a scope. Returns { total, offset, limit, items }.
  byScope: (
    scopeId,
    { offset = 0, limit = 100, search, host, tool, sourceJs, sortBy, sortDir } = {},
  ) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (search) params.set('search', search)
    if (host) params.set('host', host)
    if (tool) params.set('tool', tool)
    if (sourceJs) params.set('source_js', sourceJs)
    if (sortBy) params.set('sort_by', sortBy)
    if (sortDir) params.set('sort_dir', sortDir)
    return api.get(`/scopes/${scopeId}/endpoints?${params.toString()}`)
  },

  // Endpoints for a single subdomain FQDN. Returns { total, offset, limit, items }.
  bySubdomain: (
    subdomainId,
    { offset = 0, limit = 100, search, tool, sourceJs, sortBy, sortDir } = {},
  ) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (search) params.set('search', search)
    if (tool) params.set('tool', tool)
    if (sourceJs) params.set('source_js', sourceJs)
    if (sortBy) params.set('sort_by', sortBy)
    if (sortDir) params.set('sort_dir', sortDir)
    return api.get(`/subdomains/${subdomainId}/endpoints?${params.toString()}`)
  },

  // Dashboard counters: { total_endpoints, new_endpoints, endpoints_per_host, endpoints_per_subdomain }.
  stats: (scopeId) => api.get(`/scopes/${scopeId}/endpoint-stats`),

  // Unique hosts that have at least one endpoint — for the host filter dropdown.
  hosts: (scopeId) => api.get(`/scopes/${scopeId}/endpoint-hosts`),
}

// Discovery tools available for the tool filter (Phase 6.1).
export const ENDPOINT_TOOLS = ['LINKFINDER', 'XNLINKFINDER', 'JSLUICE']

// Parameter Inventory API (Phase 6.4) — mirrors backend/api/parameter_routes.py
import { api } from './client'

function listParams({
  offset = 0,
  limit = 100,
  search,
  host,
  tool,
  parameterType,
  assetType,
  sortBy,
  sortDir,
} = {}) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (search) params.set('search', search)
  if (host) params.set('host', host)
  if (tool) params.set('tool', tool)
  if (parameterType) params.set('parameter_type', parameterType)
  if (assetType) params.set('asset_type', assetType)
  if (sortBy) params.set('sort_by', sortBy)
  if (sortDir) params.set('sort_dir', sortDir)
  return params.toString()
}

export const parametersApi = {
  // Parameters for a scope. Returns { total, offset, limit, items }.
  listByScope: (scopeId, opts = {}) =>
    api.get(`/scopes/${scopeId}/parameters?${listParams(opts)}`),

  listByProgram: (programId, opts = {}) =>
    api.get(`/programs/${programId}/parameters?${listParams(opts)}`),

  listByHost: (hostId, opts = {}) =>
    api.get(`/hosts/${hostId}/parameters?${listParams(opts)}`),

  // Parameters discovered on a single asset (url/endpoint row) — Explorer drill-down.
  listByAsset: (assetId, opts = {}) =>
    api.get(`/assets/${assetId}/parameters?${listParams(opts)}`),

  // Dashboard counters.
  scopeStats: (scopeId) => api.get(`/scopes/${scopeId}/parameter-stats`),
  programStats: (programId) => api.get(`/programs/${programId}/parameter-stats`),

  // Parameter-type taxonomy (stable legend order). Not scope-specific.
  types: () => api.get('/parameter-types'),
}

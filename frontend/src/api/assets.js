// Asset Explorer API (Phase 6.3) — mirrors backend/api/asset_routes.py
import { api } from './client'

export const assetsApi = {
  // Classified assets for a scope. Returns { total, offset, limit, items }.
  list: (
    scopeId,
    {
      offset = 0,
      limit = 50,
      category,
      search,
      host,
      extension,
      sourceKind,
      discoverySource,
      trait,
      sortBy,
      sortDir,
    } = {},
  ) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (category) params.set('category', category)
    if (search) params.set('search', search)
    if (host) params.set('host', host)
    if (extension) params.set('extension', extension)
    if (sourceKind) params.set('source_kind', sourceKind)
    if (discoverySource) params.set('discovery_source', discoverySource)
    if (trait) params.set('trait', trait)
    if (sortBy) params.set('sort_by', sortBy)
    if (sortDir) params.set('sort_dir', sortDir)
    return api.get(`/scopes/${scopeId}/assets?${params.toString()}`)
  },

  // { total_assets, by_category: {CAT: n}, categories: [{category,label,group,...}] }
  stats: (scopeId) => api.get(`/scopes/${scopeId}/asset-stats`),

  // Filter facets.
  hosts: (scopeId) => api.get(`/scopes/${scopeId}/asset-hosts`),
  extensions: (scopeId) => api.get(`/scopes/${scopeId}/asset-extensions`),

  // Taxonomy metadata (stable sidebar order). Not scope-specific.
  categories: () => api.get('/asset-categories'),
}

// GF Intelligence endpoints — mirrors backend/api/gf_routes.py
import { api, API_BASE_URL } from './client'

// Append a repeated query param for each value of a multi-select filter.
function appendAll(params, key, values) {
  if (!values) return
  const list = Array.isArray(values) ? values : [values]
  list.filter(Boolean).forEach((v) => params.append(key, String(v)))
}

// Shared filter → querystring builder used by list, export and count calls.
function buildParams({
  programId,
  scopeId,
  host,
  assetType,
  category,
  matchAll,
  onlyMatched,
  search,
  sortBy,
  sortDir,
  offset,
  limit,
} = {}) {
  const params = new URLSearchParams()
  appendAll(params, 'program_id', programId)
  appendAll(params, 'scope_id', scopeId)
  appendAll(params, 'host', host)
  appendAll(params, 'asset_type', assetType)
  appendAll(params, 'category', category)
  if (matchAll) params.set('match_all', 'true')
  if (onlyMatched === false) params.set('only_matched', 'false')
  if (search) params.set('search', search)
  if (sortBy) params.set('sort_by', sortBy)
  if (sortDir) params.set('sort_dir', sortDir)
  if (offset != null) params.set('offset', String(offset))
  if (limit != null) params.set('limit', String(limit))
  return params
}

export const gfApi = {
  // Every GF category present in the data (dynamic — never hardcoded).
  categories: ({ programId, scopeId, includeEmpty } = {}) => {
    const params = buildParams({ programId, scopeId })
    if (includeEmpty) params.set('include_empty', 'true')
    return api.get(`/gf/categories?${params.toString()}`)
  },

  // Assets for one category. Returns { total, offset, limit, items }.
  categoryAssets: (category, opts = {}) =>
    api.get(`/gf/categories/${encodeURIComponent(category)}?${buildParams(opts).toString()}`),

  // Browse all GF-classified assets with server-side filter/sort/paginate.
  assets: (opts = {}) => api.get(`/gf/assets?${buildParams(opts).toString()}`),

  asset: (id) => api.get(`/gf/assets/${id}`),

  hosts: ({ programId, scopeId } = {}) =>
    api.get(`/gf/hosts?${buildParams({ programId, scopeId }).toString()}`),

  statistics: ({ programId, scopeId, top } = {}) => {
    const params = buildParams({ programId, scopeId })
    if (top) params.set('top', String(top))
    return api.get(`/gf/statistics?${params.toString()}`)
  },

  // Direct download URL — the browser streams it, nothing buffers in JS.
  exportUrl: (fmt, opts = {}) => {
    const params = buildParams(opts)
    params.set('fmt', fmt)
    return `${API_BASE_URL}/gf/export?${params.toString()}`
  },

  queueScan: ({ assetIds, tool, notes }) =>
    api.post('/gf/scan-queue', { asset_ids: assetIds, tool, notes }),

  scanQueue: () => api.get('/gf/scan-queue'),
}

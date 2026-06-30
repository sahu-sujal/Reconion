// Scope endpoints — mirrors backend/api/scope_routes.py
import { api } from './client'

export const scopesApi = {
  // List scopes, optionally filtered by program.
  list: (programId) =>
    api.get(programId ? `/scopes?program_id=${programId}` : '/scopes'),
  get: (id) => api.get(`/scopes/${id}`),
  create: (payload) => api.post('/scopes', payload),
  update: (id, payload) => api.patch(`/scopes/${id}`, payload),
  remove: (id) => api.del(`/scopes/${id}`),
  stats: (id) => api.get(`/scopes/${id}/stats`),
  subdomains: (id, { offset = 0, limit = 100 } = {}) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    return api.get(`/scopes/${id}/subdomains?${params.toString()}`)
  },
  // Resolved hosts; live_only returns only hosts with an HTTP status code.
  hosts: (id, { offset = 0, limit = 100, liveOnly = false } = {}) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (liveOnly) params.set('live_only', 'true')
    return api.get(`/scopes/${id}/hosts?${params.toString()}`)
  },
  dnsRecords: (id, { offset = 0, limit = 5000, recordType } = {}) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (recordType) params.set('record_type', recordType)
    return api.get(`/scopes/${id}/dns-records?${params.toString()}`)
  },
  httpResponses: (id, { offset = 0, limit = 5000, statusCode } = {}) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (statusCode != null) params.set('status_code', String(statusCode))
    return api.get(`/scopes/${id}/http-responses?${params.toString()}`)
  },
  technologies: (id, { offset = 0, limit = 5000 } = {}) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    return api.get(`/scopes/${id}/technologies?${params.toString()}`)
  },
  // Discovered URLs (Phase 5). Returns { total, offset, limit, items }.
  urls: (id, { offset = 0, limit = 100, search, source, host, sortBy, sortDir } = {}) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (search) params.set('search', search)
    if (source) params.set('source', source)
    if (host) params.set('host', host)
    if (sortBy) params.set('sort_by', sortBy)
    if (sortDir) params.set('sort_dir', sortDir)
    return api.get(`/scopes/${id}/urls?${params.toString()}`)
  },
  // Discovered JS files (Phase 5). Returns { total, offset, limit, items }.
  jsFiles: (id, { offset = 0, limit = 100, search, host, sortBy, sortDir } = {}) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (search) params.set('search', search)
    if (host) params.set('host', host)
    if (sortBy) params.set('sort_by', sortBy)
    if (sortDir) params.set('sort_dir', sortDir)
    return api.get(`/scopes/${id}/js-files?${params.toString()}`)
  },
  // Unique hosts that have discovered URLs — for the host filter dropdown.
  urlHosts: (id) => api.get(`/scopes/${id}/url-hosts`),
}

export const SCOPE_TYPES = [
  'ROOT_DOMAIN',
  'WILDCARD_DOMAIN',
  'SUBDOMAIN',
  'URL',
  'CIDR',
  'IP_RANGE',
]

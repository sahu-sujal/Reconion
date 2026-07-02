// Secret inventory API (Phase 6.2) — mirrors backend/api/secret_routes.py
import { api } from './client'

function qs(params) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  return p.toString()
}

export const secretsApi = {
  byScope: (scopeId, opts = {}) =>
    api.get(`/scopes/${scopeId}/secrets?${qs({ offset: 0, limit: 100, ...opts })}`),
  byProgram: (programId, opts = {}) =>
    api.get(`/programs/${programId}/secrets?${qs({ offset: 0, limit: 100, ...opts })}`),
  bySubdomain: (subdomainId, opts = {}) =>
    api.get(`/subdomains/${subdomainId}/secrets?${qs({ offset: 0, limit: 100, ...opts })}`),
  byHost: (hostId, opts = {}) =>
    api.get(`/hosts/${hostId}/secrets?${qs({ offset: 0, limit: 100, ...opts })}`),
  byJsFile: (jsFileId, opts = {}) =>
    api.get(`/js-files/${jsFileId}/secrets?${qs({ offset: 0, limit: 100, ...opts })}`),
  scopeStats: (scopeId) => api.get(`/scopes/${scopeId}/secret-stats`),
  programStats: (programId) => api.get(`/programs/${programId}/secret-stats`),
}

export const SECRET_SEVERITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
export const SECRET_TOOLS = ['SECRETFINDER', 'MANTRA', 'NUCLEI_EXPOSURES']

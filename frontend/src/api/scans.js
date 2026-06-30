// Scan endpoints — mirrors backend/api/scan_routes.py
import { api } from './client'

export const scansApi = {
  // List scan runs, optionally filtered by program and/or scope.
  list: ({ programId, scopeId } = {}) => {
    const params = new URLSearchParams()
    if (programId) params.set('program_id', programId)
    if (scopeId) params.set('scope_id', scopeId)
    const qs = params.toString()
    return api.get(qs ? `/scans?${qs}` : '/scans')
  },
  get: (id) => api.get(`/scans/${id}`),
  start: (payload) => api.post('/scans/start', payload),
  report: (id) => api.get(`/scans/${id}/report`),
  remove: (id) => api.del(`/scans/${id}`),
}

// Scan run statuses (mirrors database/models/enums.py ScanStatus).
export const ACTIVE_SCAN_STATUSES = ['PENDING', 'RUNNING']

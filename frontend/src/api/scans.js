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
  // Scan control (pause / resume / stop).
  pause: (id) => api.post(`/scans/${id}/pause`),
  resume: (id) => api.post(`/scans/${id}/resume`),
  stop: (id) => api.post(`/scans/${id}/stop`),
}

// Scan run statuses (mirrors database/models/enums.py ScanStatus).
export const ACTIVE_SCAN_STATUSES = ['PENDING', 'RUNNING']
// A scan is controllable (pausable/stoppable) while active; resumable when paused.
export const PAUSABLE_SCAN_STATUSES = ['PENDING', 'RUNNING']
export const RESUMABLE_SCAN_STATUSES = ['PAUSED']

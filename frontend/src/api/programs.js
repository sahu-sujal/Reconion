// Program endpoints — mirrors backend/api/program_routes.py
import { api } from './client'

export const programsApi = {
  list: () => api.get('/programs'),
  get: (id) => api.get(`/programs/${id}`),
  create: (payload) => api.post('/programs', payload),
  update: (id, payload) => api.patch(`/programs/${id}`, payload),
  remove: (id) => api.del(`/programs/${id}`),
  stats: (id) => api.get(`/programs/${id}/stats`),
}

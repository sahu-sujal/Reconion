// Global stats + health — mirrors backend/api/stats_routes.py and health_routes.py
import { api } from './client'

export const statsApi = {
  // Aggregate dashboard counts.
  global: () => api.get('/stats'),
}

export const healthApi = {
  check: () => api.get('/health'),
}

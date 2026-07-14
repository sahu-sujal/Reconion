// Thin fetch wrapper around the Recon Platform backend.
// Override the base URL with VITE_API_BASE_URL in a .env file if needed.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path, { method = 'GET', body } = {}) {
  const options = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body !== undefined) {
    options.body = JSON.stringify(body)
  }

  const res = await fetch(`${API_BASE_URL}${path}`, options)

  // 204 No Content (e.g. DELETE) has no body to parse.
  if (res.status === 204) {
    return null
  }

  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }

  if (!res.ok) {
    const detail =
      (data && (data.detail || data.message)) || `Request failed (${res.status})`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }

  return data
}

export const api = {
  get: (path) => request(path, { method: 'GET' }),
  post: (path, body) => request(path, { method: 'POST', body }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
  del: (path) => request(path, { method: 'DELETE' }),
}

// Build an absolute URL for a stored artifact (screenshot, etc.) served by the
// backend's /storage static mount. `relPath` is stored relative to the storage
// root, e.g. "programs/<id>/scopes/<id>/screenshots/foo.jpeg".
export function storageUrl(relPath) {
  if (!relPath) return null
  const clean = String(relPath).replace(/^\/+/, '')
  return `${API_BASE_URL}/storage/${clean}`
}

export { API_BASE_URL }

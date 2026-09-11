/**
 * Thin fetch wrapper around the FastAPI backend.
 *
 * Centralised so error handling is uniform: FastAPI reports problems as
 * `{ detail: ... }`, and `detail` is either a string we can show the user
 * directly or a Pydantic validation array we have to flatten. Getting this
 * wrong is how you end up rendering "[object Object]" in a toast.
 */

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function readDetail(payload, fallback) {
  const detail = payload?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
        return field ? `${field}: ${item.msg}` : item.msg
      })
      .join('; ')
  }
  return fallback
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, options)
  } catch {
    // fetch only rejects on network-level failure, which almost always means
    // the backend is not running - worth saying so explicitly.
    throw new ApiError(
      `Cannot reach the API at ${BASE}. Is the backend running?`,
      0,
    )
  }

  if (response.status === 204) return null

  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    throw new ApiError(
      readDetail(payload, `${response.status} ${response.statusText}`),
      response.status,
    )
  }
  return payload
}

const json = (method) => (path, body) =>
  request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const api = {
  get: (path) => request(path),
  post: json('POST'),
  patch: json('PATCH'),
  del: (path) => request(path, { method: 'DELETE' }),

  upload: (path, file, fields = {}) => {
    const form = new FormData()
    form.append('file', file)
    Object.entries(fields).forEach(([key, value]) => {
      if (value != null) form.append(key, value)
    })
    // No Content-Type header: the browser must set the multipart boundary.
    return request(path, { method: 'POST', body: form })
  },
}

export const endpoints = {
  complaints: '/complaints',
  stats: '/complaints/stats',
  metadata: '/complaints/metadata',
  aiHealth: '/ai/health',
  intakeText: '/ai/intake/text',
  intakeFile: '/ai/intake/file',
  reassess: '/ai/reassess',
  chat: '/ai/chat',
  chatGreeting: '/ai/chat/greeting',
  chatUpload: '/ai/chat/upload',
}

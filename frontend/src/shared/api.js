/**
 * Thin fetch wrapper. Always uses the relative API base so the loopback-only
 * guarantee and the Flask-served production build both keep working.
 */

import { API_BASE } from './constants.js'

export class ApiError extends Error {
  constructor(code, message, status, details = null) {
    super(message || code || 'Request failed')
    this.name = 'ApiError'
    this.code = code || 'REQUEST_FAILED'
    this.status = status
    this.details = details
  }
}

async function parseBody(response) {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function api(path, options = {}) {
  const url = path.startsWith('http')
    ? path
    : `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`

  const headers = { ...(options.headers || {}) }
  let body = options.body
  if (body != null && !(body instanceof FormData) && typeof body !== 'string') {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
    body = JSON.stringify(body)
  }

  const response = await fetch(url, { ...options, headers, body })
  const payload = await parseBody(response)

  if (!response.ok) {
    const err = payload && payload.error
    throw new ApiError(
      err?.code || `HTTP_${response.status}`,
      err?.message || response.statusText || 'Request failed',
      response.status,
      err?.details ?? null,
    )
  }
  return payload
}

export function apiGet(path, query) {
  let url = path
  if (query && typeof query === 'object') {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      params.set(key, String(value))
    }
    const qs = params.toString()
    if (qs) url = `${path}?${qs}`
  }
  return api(url, { method: 'GET' })
}

export function apiPost(path, body) {
  return api(path, { method: 'POST', body })
}

export function apiPut(path, body) {
  return api(path, { method: 'PUT', body })
}

export function apiDelete(path, query) {
  let url = path
  if (query && typeof query === 'object') {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      params.set(key, String(value))
    }
    const qs = params.toString()
    if (qs) url = `${path}?${qs}`
  }
  return api(url, { method: 'DELETE' })
}

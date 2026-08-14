/**
 * Typed API client wrapping fetch.
 * All backend calls go through this module.
 */

const BASE_URL = ''

async function request(method, path, { body, params } = {}) {
  const url = new URL(path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, v)
    })
  }

  const opts = {
    method,
    headers: {},
  }

  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }

  const res = await fetch(`${BASE_URL}${url.pathname}${url.search}`, opts)

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    // The backend answers failures with the standard {error:{code,message}}
    // envelope (contracts.md §6). Surface that message verbatim and attach
    // the stable code/status so callers can report the real reason instead
    // of a raw "METHOD path → status: body" string.
    let envelope = null
    try {
      const parsed = JSON.parse(text)
      if (parsed?.error && typeof parsed.error.message === 'string' && parsed.error.message) {
        envelope = parsed.error
      }
    } catch {
      /* non-envelope body (proxy error page, plain text) */
    }
    const err = new Error(
      envelope ? envelope.message : `${method} ${path} → ${res.status}: ${text}`,
    )
    err.status = res.status
    if (envelope && typeof envelope.code === 'string' && envelope.code) err.code = envelope.code
    if (envelope && envelope.details !== undefined) err.details = envelope.details
    throw err
  }

  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return res.json()
  }
  return res.text()
}

export const api = {
  get:    (path, opts) => request('GET', path, opts),
  post:   (path, opts) => request('POST', path, opts),
  put:    (path, opts) => request('PUT', path, opts),
  patch:  (path, opts) => request('PATCH', path, opts),
  delete: (path, opts) => request('DELETE', path, opts),
}

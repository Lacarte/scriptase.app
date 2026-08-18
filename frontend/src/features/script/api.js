import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/api.js'

export function listScripts(options = {}) {
  return apiGet('/scripts', {
    q: options.query,
    channel_id: options.channelId,
    origin: options.origin,
    limit: options.limit ?? 500,
  })
}

export function getScript(id) {
  return apiGet(`/scripts/${id}`)
}

export function createScript(script) {
  return apiPost('/scripts', { script })
}

export function updateScript(id, script, expectedVersion) {
  return apiPut(`/scripts/${id}`, {
    script,
    expected_version: expectedVersion,
  })
}

export function deleteScript(id, expectedVersion) {
  return apiDelete(`/scripts/${id}`, { expected_version: expectedVersion })
}

/**
 * Provider-backed generation stays on the existing script-provider seam.
 * Paste deliberately never calls this function.
 */
export function generateScript(options) {
  return apiPost('/story/generate', options)
}

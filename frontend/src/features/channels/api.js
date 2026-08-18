/**
 * Channel API client. Logo bytes never travel through these calls — upload
 * goes to the managed branding endpoint, then we store only the ref.
 */

import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/api.js'

export function listChannels(opts = {}) {
  return apiGet('/channels', {
    limit: opts.limit ?? 500,
    seed: opts.seed === false ? '0' : '1',
    starters_only: opts.startersOnly ? '1' : undefined,
  })
}

export function getChannel(id) {
  return apiGet(`/channels/${id}`)
}

export function createChannel(draft) {
  return apiPost('/channels', { channel: draft })
}

export function updateChannel(id, draft, expectedVersion) {
  return apiPut(`/channels/${id}`, {
    channel: draft,
    expected_version: expectedVersion,
  })
}

export function deleteChannel(id, expectedVersion) {
  return apiDelete(`/channels/${id}`, {
    expected_version: expectedVersion,
  })
}

export function seedChannels(force = false) {
  return apiPost('/channels/seed', { force })
}

export function getChannelDefaults() {
  return apiGet('/channels/defaults')
}

/** Uses the same backend composer as Scene Director and image providers. */
export function composeVisualPrompt(parts) {
  return apiPost('/channels/prompt-preview', parts)
}

/** Managed branding library (engine route — never a browser path). */
export function listBrandingAssets() {
  return apiGet('/workflow/branding')
}

export async function uploadBrandingLogo(file) {
  const body = new FormData()
  body.append('file', file)
  // Use raw fetch so Content-Type is the multipart boundary, not JSON.
  const response = await fetch('/api/workflow/branding', {
    method: 'POST',
    body,
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const err = payload?.error
    const error = new Error(err?.message || 'Logo upload failed')
    error.code = err?.code
    error.status = response.status
    throw error
  }
  return payload.asset
}

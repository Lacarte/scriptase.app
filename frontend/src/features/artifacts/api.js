/**
 * Artifact library + input-picker API (step 4.1 / §9.1).
 *
 * Browser-supplied filesystem paths are never accepted — uploads go through
 * the managed multipart endpoint and return artifact ids only.
 */

import { apiDelete, apiGet, apiPost } from '@/shared/api.js'

/** §9.1 input source vocabulary (mirrors backend INPUT_SOURCES). */
export const INPUT_SOURCES = [
  'current_job',
  'job',
  'library',
  'upload',
  'manual',
  'sample',
  'run_deps',
]

/**
 * @param {object} [opts]
 * @param {string} [opts.jobId]
 * @param {string} [opts.sceneId]
 * @param {string} [opts.kind]
 * @param {boolean} [opts.includeSuperseded]
 * @param {number} [opts.limit]
 */
export function listArtifacts(opts = {}) {
  return apiGet('/artifacts', {
    job_id: opts.jobId,
    scene_id: opts.sceneId,
    kind: opts.kind,
    include_superseded: opts.includeSuperseded === false ? '0' : '1',
    limit: opts.limit ?? 100,
  })
}

export function getArtifact(id) {
  return apiGet(`/artifacts/${id}`)
}

export function getArtifactPayload(id, portType) {
  return apiGet(`/artifacts/${id}/payload`, {
    port_type: portType,
  })
}

/**
 * Version chain + default side-by-side pair for one artifact (step 4.3).
 * @param {string} artifactId
 */
export function getArtifactHistory(artifactId) {
  return apiGet(`/artifacts/${encodeURIComponent(artifactId)}/history`)
}

/**
 * Attempt history for an explicit (job, kind, scene) chain.
 * @param {{ jobId: string, kind: string, sceneId?: string }} opts
 */
export function getChainHistory(opts) {
  return apiGet('/artifacts/history', {
    job_id: opts.jobId,
    kind: opts.kind,
    scene_id: opts.sceneId || undefined,
  })
}

/**
 * Side-by-side comparison of two artifact versions.
 * @param {string} leftId
 * @param {string} rightId
 */
export function compareArtifacts(leftId, rightId) {
  return apiGet('/artifacts/compare', {
    left: leftId,
    right: rightId,
  })
}

/**
 * Managed upload. Returns `{ artifact }`.
 * @param {File} file
 * @param {{ kind?: string, jobId?: string, sceneId?: string }} [opts]
 */
export async function uploadArtifact(file, opts = {}) {
  const body = new FormData()
  body.append('file', file)
  if (opts.kind) body.append('kind', opts.kind)
  if (opts.jobId) body.append('job_id', opts.jobId)
  if (opts.sceneId) body.append('scene_id', opts.sceneId)
  const response = await fetch('/api/artifacts/upload', {
    method: 'POST',
    body,
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const err = payload?.error
    const error = new Error(err?.message || `Upload failed (${response.status})`)
    error.code = err?.code
    error.status = response.status
    error.details = err?.details
    throw error
  }
  return payload
}

/**
 * Dry-run: bindings → input_overrides + source_artifact_ids.
 * @param {object} inputBindings
 * @param {{ currentJobId?: string, workflow?: object }} [opts]
 */
export function resolveInputBindings(inputBindings, opts = {}) {
  return apiPost('/artifacts/resolve-inputs', {
    input_bindings: inputBindings,
    current_job_id: opts.currentJobId,
    workflow: opts.workflow,
  })
}

/**
 * Build a single-port binding object for the picker UI.
 * @param {string} source
 * @param {object} [fields]
 */
export function makeBinding(source, fields = {}) {
  return { source, ...fields }
}

/**
 * Build the input_bindings body fragment for one node.
 * @param {string} nodeId
 * @param {Record<string, object>} portBindings  port_id → binding
 */
export function bindingsForNode(nodeId, portBindings) {
  return { [nodeId]: portBindings }
}

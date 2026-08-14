/**
 * Stage status aggregation — mirrors scriptase.jobs.stage_projection.
 *
 * Stage status is derived from member nodes' execution records. There is no
 * separate status store (contracts.md §10). Keep this in lockstep with the
 * backend _STATUS_PRIORITY / _aggregate_status helpers.
 */

// Lower rank wins (most severe). Queued/waiting collapse to "running" for
// the Production view so the step list never shows engine-internal states.
const STATUS_PRIORITY = {
  failed: 0,
  cancelled: 1,
  awaiting_approval: 2,
  running: 3,
  queued: 3,
  waiting: 3,
  invalid: 4,
  stale: 5,
  succeeded: 6,
  skipped: 6,
  idle: 7,
}

const DEFAULT_STATUS = 'idle'

const TERMINAL_EXECUTION_STATUSES = new Set([
  'succeeded',
  'failed',
  'cancelled',
  'partial',
])

/**
 * Aggregate member node statuses into a single Production stage status.
 * @param {string[]} nodeStatuses
 * @returns {string}
 */
export function aggregateStageStatus(nodeStatuses) {
  if (!Array.isArray(nodeStatuses) || nodeStatuses.length === 0) {
    return DEFAULT_STATUS
  }
  let best = DEFAULT_STATUS
  let bestRank = STATUS_PRIORITY[best] ?? 99
  for (const raw of nodeStatuses) {
    const status = String(raw || DEFAULT_STATUS)
    const rank = STATUS_PRIORITY[status] ?? 50
    if (rank < bestRank) {
      best = status
      bestRank = rank
    }
  }
  if (best === 'queued' || best === 'waiting') return 'running'
  return best
}

/**
 * Rebuild every stage's status (and optional artifacts) from a node-status map.
 * Does not invent stages — only mutates status/artifacts on the projection.
 *
 * @param {Array<object>} stages  StageProjection.stages
 * @param {Record<string, {status?: string, artifact_refs?: string[]}>} nodeRecords
 * @returns {Array<object>} new stages array (shallow-copied rows)
 */
export function recomputeStagesFromNodes(stages, nodeRecords = {}) {
  if (!Array.isArray(stages)) return []
  return stages.map((stage) => {
    const nodeIds = Array.isArray(stage.node_ids) ? stage.node_ids : []
    const statuses = nodeIds.map((id) => {
      const record = nodeRecords[id]
      if (!record) return 'idle'
      return String(record.status || 'idle')
    })
    const artifacts = []
    const seen = new Set()
    for (const id of nodeIds) {
      const refs = nodeRecords[id]?.artifact_refs
      if (!Array.isArray(refs)) continue
      for (const ref of refs) {
        if (typeof ref === 'string' && ref && !seen.has(ref)) {
          seen.add(ref)
          artifacts.push(ref)
        }
      }
    }
    return {
      ...stage,
      status: aggregateStageStatus(statuses),
      artifacts: artifacts.length ? artifacts : (stage.artifacts || []),
    }
  })
}

/**
 * Apply a single node-status event onto a nodeRecords map (mutates).
 * @param {Record<string, object>} nodeRecords
 * @param {{node_id?: string, status?: string, attempt?: number, duration_ms?: number, error?: object, artifact_refs?: string[]}} event
 */
export function applyNodeEvent(nodeRecords, event) {
  if (!event?.node_id) return nodeRecords
  const record = nodeRecords[event.node_id] || { status: 'idle' }
  if (event.status) record.status = event.status
  if (Number.isFinite(event.attempt)) record.attempts = event.attempt
  if (Number.isFinite(event.duration_ms)) record.duration_ms = event.duration_ms
  if (event.error) record.error = event.error
  if (Array.isArray(event.artifact_refs)) record.artifact_refs = event.artifact_refs
  nodeRecords[event.node_id] = record
  return nodeRecords
}

/**
 * Build a nodeRecords map from an execution snapshot (dict form).
 * @param {object|null|undefined} execution
 * @returns {Record<string, object>}
 */
export function nodeRecordsFromExecution(execution) {
  const out = {}
  const nodes = execution?.nodes
  if (!nodes || typeof nodes !== 'object') return out
  for (const [nodeId, record] of Object.entries(nodes)) {
    if (!record || typeof record !== 'object') continue
    out[nodeId] = {
      status: String(record.status || 'idle'),
      attempts: record.attempts,
      duration_ms: record.duration_ms,
      error: record.error ?? null,
      artifact_refs: Array.isArray(record.artifact_refs) ? [...record.artifact_refs] : [],
    }
  }
  return out
}

export function isTerminalExecutionStatus(status) {
  return TERMINAL_EXECUTION_STATUSES.has(String(status || ''))
}

/** Human labels for status badges (UI only — never invent stage names). */
export const STATUS_LABELS = {
  idle: 'Pending',
  running: 'Running',
  succeeded: 'Complete',
  failed: 'Failed',
  cancelled: 'Cancelled',
  awaiting_approval: 'Awaiting approval',
  invalid: 'Invalid',
  stale: 'Stale',
  skipped: 'Skipped',
}

export function statusLabel(status) {
  return STATUS_LABELS[status] || String(status || 'Pending')
}

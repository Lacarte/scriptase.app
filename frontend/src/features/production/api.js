/**
 * Production stage-projection API client.
 *
 * Stages are computed on the backend from the workflow graph (step 2.2).
 * This module never hardcodes a step array.
 */

import { apiGet, apiPost } from '@/shared/api.js'

/** Project a saved workflow into the ordered Production stage list. */
export function getWorkflowStages(workflowId, { summary = false } = {}) {
  return apiGet(`/workflows/${encodeURIComponent(workflowId)}/stages`, {
    summary: summary ? '1' : undefined,
  })
}

/** Project an inline workflow document (draft / template). */
export function projectWorkflowBody(workflow) {
  return apiPost('/workflow/stages', { workflow })
}

/**
 * Project the execution's workflow snapshot with live per-stage status.
 * Status and artifacts derive from member node execution records.
 */
export function getExecutionStages(executionId) {
  return apiGet(`/workflow/executions/${encodeURIComponent(executionId)}/stages`)
}

/** Workflow listing (shared with the canvas). */
export function listWorkflows({ limit = 200 } = {}) {
  return apiGet('/workflows', { limit })
}

/** Recent executions for a workflow, newest first. */
export function listExecutions({ workflowId, limit = 50 } = {}) {
  return apiGet('/workflow/executions', {
    workflow_id: workflowId,
    limit,
  })
}

/** Load a single execution record (reload hydrate). */
export function getExecution(executionId) {
  return apiGet(`/workflow/executions/${encodeURIComponent(executionId)}`)
}

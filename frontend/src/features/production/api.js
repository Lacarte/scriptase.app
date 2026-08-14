/**
 * Production stage-projection + step-action API client.
 *
 * Stages are computed on the backend from the workflow graph (step 2.2).
 * Step actions (step 2.4) post to the same /workflow/run endpoint the canvas
 * uses — never a second execution path. This module never hardcodes a step array.
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

/** Load a saved workflow document (for primary-node targeting). */
export function getWorkflow(workflowId) {
  return apiGet(`/workflows/${encodeURIComponent(workflowId)}`)
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

/**
 * Start a run through the same endpoint the Workflow canvas uses.
 *
 * Body shape matches store.runWorkflow:
 *   { workflow_id | workflow, run_mode, target_node_ids, force }
 *
 * @param {object} body
 * @returns {Promise<{ execution_id: string, project_id: string, status: string }>}
 */
export function runWorkflow(body) {
  return apiPost('/workflow/run', body)
}

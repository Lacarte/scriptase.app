/**
 * Production stage-projection, Job creation, and step-action API client.
 *
 * Stages are computed on the backend from the workflow graph (step 2.2).
 * Step actions (step 2.4) post to the same /workflow/run endpoint the canvas
 * uses — never a second execution path. Job create / start (step 2.5) go
 * through /api/jobs. This module never hardcodes a step array.
 */

import { apiDelete, apiGet, apiPost } from '@/shared/api.js'

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

// ---------------------------------------------------------------------------
// Jobs (step 2.5 — Step 0 creation + start)
// ---------------------------------------------------------------------------

/** Source / execution mode catalog for the Job creation form. */
export function getJobDefaults() {
  return apiGet('/jobs/defaults')
}

/** List jobs newest-first. */
export function listJobs({ channelId, status, limit = 50 } = {}) {
  return apiGet('/jobs', {
    channel_id: channelId || undefined,
    status: status || undefined,
    limit,
  })
}

/** Load a single Job document (snapshot is secret-free). */
export function getJob(jobId) {
  return apiGet(`/jobs/${encodeURIComponent(jobId)}`)
}

/**
 * Cost accounting report for a Job (step 9.3).
 * Totals + per-stage + per-provider-instance, reconciled with provenance.
 */
export function getJobCost(jobId) {
  return apiGet(`/jobs/${encodeURIComponent(jobId)}/cost`)
}

/**
 * Full repair sequence for a Job (step 11.4 reads the 8.4 endpoint).
 *
 * Read-only. Entries arrive in attempt order and carry the issue they
 * answered, the node type the Repair Router chose, what was retried, and
 * every superseded artifact version.
 *
 * @param {string} jobId
 * @returns {Promise<object>}
 */
export function getJobRepairHistory(jobId) {
  return apiGet(`/jobs/${encodeURIComponent(jobId)}/repair-history`)
}

/**
 * Create a Job from Channel + source + workflow + execution mode.
 * @param {object} draft
 */
export function createJob(draft) {
  return apiPost('/jobs', { job: draft })
}

/**
 * Start a Job through the ported engine (returns job + execution_id).
 * @param {string} jobId
 * @param {{ force?: boolean, wait?: boolean, timeout?: number }} [opts]
 */
export function startJob(jobId, opts = {}) {
  return apiPost(`/jobs/${encodeURIComponent(jobId)}/start`, {
    force: Boolean(opts.force),
    wait: Boolean(opts.wait),
    timeout: opts.timeout,
  })
}

/**
 * Test a node in isolation without advancing the Job (step 4.2).
 *
 * @param {string} jobId
 * @param {object} body
 * @param {string[]} body.target_node_ids
 * @param {object} [body.input_bindings]
 * @param {object} [body.input_overrides]
 * @param {string} [body.provider_instance_id] One-shot provider for this run
 *   only (step 13.2). Never written to the node's saved configuration.
 * @param {boolean} [body.force]
 * @param {boolean} [body.wait]
 * @param {number} [body.timeout]
 */
export function testJobNode(jobId, body) {
  return apiPost(`/jobs/${encodeURIComponent(jobId)}/test-node`, body)
}

export function deleteJob(jobId) {
  return apiDelete(`/jobs/${encodeURIComponent(jobId)}`)
}

/** Registry payload used by the Test Node panel for port definitions. */
export function getNodeTypes() {
  return apiGet('/workflow/node-types')
}

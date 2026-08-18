/**
 * Schema view API client (steps 1.2, 1.3).
 *
 * Every read is a projection of backend truth: the node registry supplies what
 * a node *is*, the workflow document supplies which nodes exist and how they
 * are wired, and the stage projection supplies which Production stage each one
 * belongs to. Step 1.3 adds the run reads — the Job, its execution record, and
 * the runs there are to choose between.
 *
 * **Every export here is a GET**, apart from the inline template projection,
 * which computes a projection and stores nothing. Schema watches a Job; it
 * cannot start, stop, approve or repair one. Freeze view issues no request at
 * all, because pausing production is the Production row's job.
 * `__tests__/schemaPage.test.js` asserts this export list, so a write cannot
 * be slipped in later without the guard failing.
 */

import { apiGet, apiPost } from '@/shared/api.js'

/** Registry payload — node definitions, categories, port vocabulary. */
export function getNodeTypes() {
  return apiGet('/workflow/node-types')
}

/** Saved workflows, newest first. */
export function listWorkflows({ limit = 200 } = {}) {
  return apiGet('/workflows', { limit })
}

/** One saved workflow document (nodes, edges, authored positions). */
export function getWorkflow(workflowId) {
  return apiGet(`/workflows/${encodeURIComponent(workflowId)}`)
}

/** Ordered stage projection for a saved workflow. */
export function getWorkflowStages(workflowId) {
  return apiGet(`/workflows/${encodeURIComponent(workflowId)}/stages`)
}

/**
 * Project an inline workflow document. Used for the built-in templates, which
 * have no `workflow_id` to address until someone saves one.
 */
export function projectWorkflowBody(workflow) {
  return apiPost('/workflow/stages', { workflow })
}

/** Built-in templates — the fallback graph on an install with nothing saved. */
export function listTemplates() {
  return apiGet('/workflow/templates')
}

// ---------------------------------------------------------------------------
// The running job (step 1.3)
// ---------------------------------------------------------------------------

/** Runs of one workflow, newest first — what the Run picker offers. */
export function listExecutions({ workflowId, limit = 50 } = {}) {
  return apiGet('/workflow/executions', { workflow_id: workflowId, limit })
}

/**
 * One execution record: per-node status, resolved inputs, outputs, errors, and
 * the workflow snapshot the run actually executed.
 *
 * The snapshot — not the saved workflow — is what Schema draws for a run. A
 * workflow edited since the run started would otherwise animate nodes that
 * this execution never had.
 */
export function getExecution(executionId) {
  return apiGet(`/workflow/executions/${encodeURIComponent(executionId)}`)
}

/** Stage projection for a run, so cards keep their stage labels live. */
export function getExecutionStages(executionId) {
  return apiGet(`/workflow/executions/${encodeURIComponent(executionId)}/stages`)
}

/**
 * The Job the graph is animating. Carries `execution_id` and `current_stage`,
 * which is what the live pill names. The document is secret-free by contract —
 * the snapshot holds provider **instance references**, never credentials.
 */
export function getJob(jobId) {
  return apiGet(`/jobs/${encodeURIComponent(jobId)}`)
}

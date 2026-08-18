/**
 * Schema view API client (step 1.2).
 *
 * Every read is a projection of backend truth: the node registry supplies what
 * a node *is*, the workflow document supplies which nodes exist and how they
 * are wired, and the stage projection supplies which Production stage each one
 * belongs to. Nothing here writes, and Schema owns no execution path.
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

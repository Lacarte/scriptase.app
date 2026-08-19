/**
 * Load the graph Schema draws (step 1.2).
 *
 * Three backend reads, and no fourth source of truth:
 *   - `GET /api/workflow/node-types`      what a node *is*
 *   - `GET /api/workflows/<id>`           which nodes exist and how they wire
 *   - `GET /api/workflows/<id>/stages`    which Production stage each reports to
 *
 * An install with nothing saved still gets a graph: the built-in templates are
 * fetched and projected through `POST /api/workflow/stages`, which is the same
 * projector the saved-workflow route runs.
 *
 * Step 1.3 adds a fourth source that is still the same truth: an execution's
 * `workflow_snapshot`, which is what a *run* is drawn from.
 *
 * Read-only throughout. Nothing in this module starts, advances or cancels an
 * execution — that is Production's job, and Schema watching the graph must
 * never become a second way to run it.
 */

import { computed, ref, shallowRef } from 'vue'

import {
  getExecution,
  getExecutionStages,
  getNodeTypes,
  getWorkflow,
  getWorkflowStages,
  listExecutions,
  listTemplates,
  listWorkflows,
  projectWorkflowBody,
} from '../api.js'
import { buildSchemaGraph } from '../graph.js'

export function useSchemaGraph() {
  const registry = shallowRef(null)
  const workflows = ref([])
  /** Runs of the selected workflow — what the Run picker offers (step 1.3). */
  const runs = ref([])
  const selectedWorkflowId = ref('')
  const workflowDocument = shallowRef(null)
  const projection = shallowRef(null)
  /** Set when the graph on screen is a built-in template rather than a save. */
  const templateId = ref('')
  /** Set when the graph on screen is a run's snapshot rather than a save. */
  const executionId = ref('')

  /**
   * Counted rather than boolean: `load` nests `selectWorkflow` inside itself,
   * and a boolean would clear on the inner call and flash the empty state
   * while the outer sequence was still running.
   */
  const pending = ref(0)
  const loading = computed(() => pending.value > 0)
  const error = ref('')
  /**
   * Projection failures are survivable. A graph with no production stages
   * answers 422, and the right response is a graph without stage labels — not
   * an empty canvas that hides the nodes the user came to look at.
   */
  const stageError = ref('')

  const graph = computed(() => buildSchemaGraph({
    workflow: workflowDocument.value,
    registry: registry.value,
    projection: projection.value,
  }))

  const nodes = computed(() => graph.value.nodes)
  const edges = computed(() => graph.value.edges)
  const hasGraph = computed(() => nodes.value.length > 0)

  const sourceLabel = computed(() => {
    if (templateId.value) {
      const name = workflowDocument.value?.name || templateId.value
      return `${name} · built-in template`
    }
    if (!selectedWorkflowId.value) return ''
    const match = workflows.value.find((w) => w.workflow_id === selectedWorkflowId.value)
    return match?.name || selectedWorkflowId.value
  })

  /**
   * Draw a run (step 1.3).
   *
   * The structure comes from the execution's `workflow_snapshot`, not from the
   * saved workflow: a workflow edited since the run started would otherwise
   * animate nodes this execution never had, and hide nodes it did.
   *
   * @param {object} execution  execution record
   * @param {object} [runProjection]  StageProjection for the same run
   */
  function showExecution(execution, runProjection = null) {
    if (!execution?.workflow_snapshot) return null
    templateId.value = ''
    error.value = ''
    workflowDocument.value = execution.workflow_snapshot
    executionId.value = execution.execution_id || ''
    if (execution.workflow_id) selectedWorkflowId.value = execution.workflow_id
    projection.value = runProjection || null
    stageError.value = runProjection ? '' : stageError.value
    return workflowDocument.value
  }

  /**
   * Fetch a run and draw it. Returns the execution record so the caller can
   * hand it to `useSchemaLive` — this composable owns structure, never status.
   */
  async function selectExecution(id) {
    if (!id) return null
    pending.value += 1
    error.value = ''
    try {
      const [executionData, stagesData] = await Promise.all([
        getExecution(id),
        // Same survivable failure as a saved workflow's projection: without it
        // the cards lose their stage label, not their place on the canvas.
        Promise.resolve(getExecutionStages(id)).catch((err) => {
          stageError.value = err?.message || String(err)
          return null
        }),
      ])
      const execution = executionData?.execution || executionData || null
      if (!execution?.workflow_snapshot) {
        throw new Error('That run has no workflow snapshot to draw')
      }
      showExecution(execution, stagesData?.projection || null)
      return execution
    } catch (err) {
      error.value = err?.message || String(err)
      throw err
    } finally {
      pending.value -= 1
    }
  }

  async function loadRegistry() {
    registry.value = await getNodeTypes()
    return registry.value
  }

  async function refreshWorkflows() {
    try {
      const data = await listWorkflows({ limit: 200 })
      workflows.value = data?.workflows || []
    } catch {
      // A missing listing costs the picker, not the canvas.
      workflows.value = []
    }
    return workflows.value
  }

  async function refreshRuns(workflowId) {
    if (!workflowId) {
      runs.value = []
      return runs.value
    }
    try {
      const data = await listExecutions({ workflowId })
      runs.value = data?.executions || []
    } catch {
      // No listing costs the Run picker, not the canvas.
      runs.value = []
    }
    return runs.value
  }

  async function loadProjection(loader) {
    stageError.value = ''
    try {
      const data = await loader()
      projection.value = data?.projection || null
    } catch (err) {
      projection.value = null
      stageError.value = err?.message || String(err)
    }
  }

  /** Show a saved workflow. */
  async function selectWorkflow(workflowId) {
    if (!workflowId) return null
    pending.value += 1
    error.value = ''
    templateId.value = ''
    executionId.value = ''
    try {
      const data = await getWorkflow(workflowId)
      workflowDocument.value = data?.workflow || data || null
      selectedWorkflowId.value = workflowId
      await loadProjection(() => getWorkflowStages(workflowId))
      return workflowDocument.value
    } catch (err) {
      error.value = err?.message || String(err)
      workflowDocument.value = null
      projection.value = null
      throw err
    } finally {
      pending.value -= 1
    }
  }

  /** Fall back to the first built-in template when nothing is saved yet. */
  async function loadTemplateGraph() {
    pending.value += 1
    error.value = ''
    try {
      const data = await listTemplates()
      const first = (data?.templates || [])[0]
      if (!first?.workflow) {
        workflowDocument.value = null
        projection.value = null
        return null
      }
      workflowDocument.value = first.workflow
      templateId.value = first.template_id || 'template'
      selectedWorkflowId.value = ''
      executionId.value = ''
      await loadProjection(() => projectWorkflowBody(first.workflow))
      return workflowDocument.value
    } catch (err) {
      error.value = err?.message || String(err)
      workflowDocument.value = null
      projection.value = null
      throw err
    } finally {
      pending.value -= 1
    }
  }

  /**
   * Open the requested workflow, else the newest saved one, else a template.
   *
   * @param {string} [preferredId]  usually the `?workflow=` deep link
   */
  async function load(preferredId = '') {
    pending.value += 1
    error.value = ''
    try {
      try {
        await loadRegistry()
      } catch (err) {
        error.value = err?.message || String(err)
        throw err
      }

      const list = await refreshWorkflows()
      const target = preferredId
        || (list.some((w) => w.workflow_id === selectedWorkflowId.value)
          ? selectedWorkflowId.value
          : '')
        || list[0]?.workflow_id
        || ''

      if (target) {
        try {
          return await selectWorkflow(target)
        } catch {
          // A deleted or unreadable workflow must not leave a blank canvas.
        }
      }
      return await loadTemplateGraph().catch(() => null)
    } finally {
      pending.value -= 1
    }
  }

  return {
    registry,
    workflows,
    runs,
    selectedWorkflowId,
    workflowDocument,
    projection,
    templateId,
    executionId,
    loading,
    error,
    stageError,
    nodes,
    edges,
    hasGraph,
    sourceLabel,
    load,
    loadRegistry,
    refreshWorkflows,
    refreshRuns,
    selectWorkflow,
    loadTemplateGraph,
    showExecution,
    selectExecution,
  }
}

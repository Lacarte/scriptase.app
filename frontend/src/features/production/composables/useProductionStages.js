/**
 * Production stage list driven by backend projection + the same SSE stream
 * the workflow canvas consumes (createExecutionEventStream).
 *
 * - No hardcoded step array
 * - No second polling mechanism — live updates arrive only via SSE
 * - Reload: GET stages (disk truth) then open EventSource (ring-buffer replay
 *   / reset-snapshot + Last-Event-ID resume on reconnect)
 */

import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'

import { createExecutionEventStream } from '@/features/workflow/composables/useExecutionEvents.js'
import {
  getExecution,
  getExecutionStages,
  getWorkflow,
  getWorkflowStages,
  runWorkflow,
} from '../api.js'
import { buildStageRunRequest, isExecutableAction } from '../stageActions.js'
import {
  applyNodeEvent,
  isTerminalExecutionStatus,
  nodeRecordsFromExecution,
  recomputeStagesFromNodes,
} from '../stageStatus.js'

/**
 * @param {object} [options]
 * @param {typeof EventSource} [options.EventSourceImpl]  inject for tests
 */
export function useProductionStages(options = {}) {
  const stages = ref([])
  const workflowId = ref(null)
  const workflowVersion = ref(null)
  /** Saved workflow document (nodes/edges) for primary-node targeting. */
  const workflowDocument = shallowRef(null)
  const executionId = ref(null)
  const executionStatus = ref(null)
  const loading = ref(false)
  const error = ref('')
  const streamError = ref('')
  const lastSequence = ref(0)
  const actionRunning = ref(false)
  const actionError = ref('')
  const actionMessage = ref('')

  /** node_id → { status, artifact_refs, ... } — local mirror for aggregation */
  const nodeRecords = shallowRef({})

  let stream = null
  let EventSourceImpl = options.EventSourceImpl || null

  const hasStages = computed(() => stages.value.length > 0)
  const active = computed(() => {
    const status = executionStatus.value
    return status === 'queued' || status === 'running' || status === 'cancelling'
  })

  function closeStream() {
    if (stream) {
      stream.close()
      stream = null
    }
  }

  function setProjection(projection) {
    if (!projection || typeof projection !== 'object') {
      stages.value = []
      return
    }
    stages.value = Array.isArray(projection.stages) ? projection.stages.map((s) => ({ ...s })) : []
    if (projection.workflow_id != null) workflowId.value = projection.workflow_id
    if (projection.workflow_version != null) workflowVersion.value = projection.workflow_version
    if (projection.execution_id != null) executionId.value = projection.execution_id
    if (projection.execution_status != null) executionStatus.value = projection.execution_status
  }

  function recompute() {
    stages.value = recomputeStagesFromNodes(stages.value, nodeRecords.value)
  }

  /**
   * Apply one sequenced SSE event. Handles reset snapshots the same way the
   * canvas store does so a mid-run reconnect never leaves stages stale.
   */
  function applyExecutionEvent(event) {
    if (!event || typeof event !== 'object') return

    // Ring-buffer reset: authoritative snapshot replaces node records.
    if (event.snapshot && typeof event.snapshot === 'object') {
      const snap = event.snapshot
      nodeRecords.value = nodeRecordsFromExecution(snap)
      if (snap.status) executionStatus.value = snap.status
      if (snap.execution_id) executionId.value = snap.execution_id
      recompute()
    }

    if (event.node_id) {
      const next = { ...nodeRecords.value }
      applyNodeEvent(next, event)
      nodeRecords.value = next
      recompute()
    } else if (event.status && event.status !== 'reset') {
      executionStatus.value = event.status
    }

    // Terminal execution: close the stream. Artifact refs on the final
    // record are not repeated in every SSE frame — re-hydrate stages once.
    if (
      !event.node_id
      && isTerminalExecutionStatus(event.status)
    ) {
      closeStream()
      const id = executionId.value
      if (id) {
        void hydrateFromExecution(id, { watch: false, quiet: true }).catch(() => {
          // Keep the last live-derived view if the follow-up GET fails.
        })
      }
    }
  }

  function watchExecution(id, { EventSourceImpl: impl } = {}) {
    if (!id) return null
    closeStream()
    streamError.value = ''
    executionId.value = id
    const Source = impl || EventSourceImpl || globalThis.EventSource
    stream = createExecutionEventStream(id, {
      onEvent: (event) => {
        lastSequence.value = Number(event.sequence) || lastSequence.value
        applyExecutionEvent(event)
      },
      onError: (err) => {
        // EventSource surfaces transient reconnects here too. State stays
        // visible; Last-Event-ID resume is owned by the browser transport.
        streamError.value = err?.message || 'Execution event stream interrupted'
      },
      ...(Source ? { EventSourceImpl: Source } : {}),
    })
    return stream
  }

  /**
   * Load stages for a saved workflow (idle statuses — no execution yet).
   */
  async function loadWorkflow(id) {
    loading.value = true
    error.value = ''
    closeStream()
    nodeRecords.value = {}
    executionId.value = null
    executionStatus.value = null
    lastSequence.value = 0
    actionError.value = ''
    actionMessage.value = ''
    try {
      const [stagesData, workflowData] = await Promise.all([
        getWorkflowStages(id),
        Promise.resolve(getWorkflow(id)).catch(() => null),
      ])
      setProjection(stagesData.projection)
      workflowId.value = id
      workflowDocument.value = workflowData?.workflow || workflowData || null
      return stagesData.projection
    } catch (err) {
      error.value = err?.message || String(err)
      stages.value = []
      workflowDocument.value = null
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * Start a stage action through the same /api/workflow/run path the canvas uses.
   * After queueing, opens the shared SSE stream so stages update live.
   *
   * @param {string} action  run | test | regenerate | run_from_here
   * @param {object} stage   StageProjection row
   * @param {object} [opts]
   * @param {typeof EventSource} [opts.EventSourceImpl]
   * @param {object} [opts.body]  pre-built request body (tests / panel)
   * @returns {Promise<{ execution_id: string, project_id: string, status: string, body: object }>}
   */
  async function runStageAction(action, stage, opts = {}) {
    if (!isExecutableAction(action)) {
      throw new Error(`Action "${action}" does not start a run`)
    }
    if (active.value) {
      throw new Error('A run is already in progress')
    }
    actionRunning.value = true
    actionError.value = ''
    actionMessage.value = ''
    try {
      const body = opts.body || buildStageRunRequest(action, stage, {
        workflowId: workflowId.value || undefined,
        workflow: workflowId.value
          ? undefined
          : (workflowDocument.value || opts.workflow || undefined),
      })
      if (!body.workflow_id && !body.workflow) {
        throw new Error('No workflow selected')
      }
      const data = await runWorkflow(body)
      executionStatus.value = data.status || 'queued'
      executionId.value = data.execution_id
      actionMessage.value = `Started ${action} → ${body.run_mode} on ${body.target_node_ids?.[0] || 'node'}`
      if (data.execution_id) {
        watchExecution(data.execution_id, {
          EventSourceImpl: opts.EventSourceImpl || EventSourceImpl,
        })
      }
      return { ...data, body }
    } catch (err) {
      actionError.value = err?.message || String(err)
      throw err
    } finally {
      actionRunning.value = false
    }
  }

  /**
   * Hydrate from an execution: GET stages + execution record (disk truth),
   * then open SSE for live updates. Survives mid-run page reload without a
   * second polling loop — EventSource owns Last-Event-ID resume on reconnect.
   */
  async function hydrateFromExecution(
    id,
    { watch = true, EventSourceImpl: impl, quiet = false } = {},
  ) {
    if (!quiet) loading.value = true
    error.value = ''
    lastSequence.value = 0
    try {
      // Stages give the ordered projection; the execution record gives the
      // per-node statuses the SSE stream will continue from.
      const [stagesData, executionData] = await Promise.all([
        getExecutionStages(id),
        getExecution(id).catch(() => null),
      ])
      setProjection(stagesData.projection)
      const execution = executionData?.execution || null
      if (execution) {
        nodeRecords.value = nodeRecordsFromExecution(execution)
        if (execution.status) executionStatus.value = execution.status
        // Snapshot on the execution is enough for primary-node targeting when
        // the saved workflow is not loaded yet.
        if (execution.workflow_snapshot && !workflowDocument.value) {
          workflowDocument.value = execution.workflow_snapshot
        }
        if (execution.workflow_id && !workflowId.value) {
          workflowId.value = execution.workflow_id
        }
        // Recompute so stage rows match the record even if the stages GET
        // raced a just-written node status.
        recompute()
      } else {
        nodeRecords.value = {}
      }
      // Prefer the live saved document when we know the workflow id.
      if (workflowId.value && !workflowDocument.value) {
        const wfData = await Promise.resolve(getWorkflow(workflowId.value)).catch(() => null)
        workflowDocument.value = wfData?.workflow || wfData || null
      }
      executionId.value = id
      if (watch && !isTerminalExecutionStatus(executionStatus.value)) {
        watchExecution(id, { EventSourceImpl: impl })
      } else {
        closeStream()
      }
      return stagesData.projection
    } catch (err) {
      error.value = err?.message || String(err)
      throw err
    } finally {
      if (!quiet) loading.value = false
    }
  }

  /**
   * Attach to a live execution after stages are already loaded (e.g. run
   * just started elsewhere). Opens the shared SSE endpoint.
   */
  function attachExecution(id, { EventSourceImpl: impl } = {}) {
    executionId.value = id
    if (!executionStatus.value || executionStatus.value === 'idle') {
      executionStatus.value = 'queued'
    }
    return watchExecution(id, { EventSourceImpl: impl })
  }

  function dispose() {
    closeStream()
  }

  onBeforeUnmount(dispose)

  return {
    stages,
    workflowId,
    workflowVersion,
    workflowDocument,
    executionId,
    executionStatus,
    loading,
    error,
    streamError,
    lastSequence,
    nodeRecords,
    actionRunning,
    actionError,
    actionMessage,
    hasStages,
    active,
    loadWorkflow,
    hydrateFromExecution,
    attachExecution,
    runStageAction,
    applyExecutionEvent,
    watchExecution,
    closeStream,
    dispose,
    recompute,
    setProjection,
  }
}

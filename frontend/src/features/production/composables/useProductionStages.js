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
  getWorkflowStages,
} from '../api.js'
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
  const executionId = ref(null)
  const executionStatus = ref(null)
  const loading = ref(false)
  const error = ref('')
  const streamError = ref('')
  const lastSequence = ref(0)

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
    try {
      const data = await getWorkflowStages(id)
      setProjection(data.projection)
      workflowId.value = id
      return data.projection
    } catch (err) {
      error.value = err?.message || String(err)
      stages.value = []
      throw err
    } finally {
      loading.value = false
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
        // Recompute so stage rows match the record even if the stages GET
        // raced a just-written node status.
        recompute()
      } else {
        nodeRecords.value = {}
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
    executionId,
    executionStatus,
    loading,
    error,
    streamError,
    lastSequence,
    nodeRecords,
    hasStages,
    active,
    loadWorkflow,
    hydrateFromExecution,
    attachExecution,
    applyExecutionEvent,
    watchExecution,
    closeStream,
    dispose,
    recompute,
    setProjection,
  }
}

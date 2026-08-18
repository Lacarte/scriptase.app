/**
 * Bind the Schema graph to a running Job (step 1.3).
 *
 * The picture is fed by the same SSE stream Production consumes — one run, two
 * projections. There is no polling loop here and no second execution model:
 * this composable receives node status, it never asks for any of it to change.
 *
 * ## Freeze view
 *
 * Freezing stops *this view* repainting. The stream stays open, events keep
 * arriving, and `liveRecords` keeps moving underneath — only `records`, what
 * the canvas and the inspector draw, is held still. Unfreezing shows the run
 * where it actually is, not where it was.
 *
 * That distinction is the whole point: pausing production is the Production
 * row's job, and this module has no endpoint that could do it even by mistake
 * (see `../api.js` — every export is a read).
 */

import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'

import { createExecutionEventStream } from '@/features/workflow/composables/useExecutionEvents.js'
// Status vocabulary and node-record shape are shared with Production on
// purpose. Two projections of one execution must not disagree about what
// "succeeded" means, and a second copy of the ladder is how they would.
import {
  applyNodeEvent,
  isTerminalExecutionStatus,
  nodeRecordsFromExecution,
} from '@/features/production/stageStatus.js'
import { getExecution, getJob } from '../api.js'

/**
 * @param {object} [options]
 * @param {typeof EventSource} [options.EventSourceImpl]  inject for tests
 */
export function useSchemaLive(options = {}) {
  const jobId = ref('')
  const job = shallowRef(null)
  const executionId = ref('')
  const executionStatus = ref('')
  const streamError = ref('')

  /** Everything the stream has said. Never stops moving while a run is live. */
  const liveRecords = shallowRef({})
  /** What the canvas and inspector draw. Held still while frozen. */
  const records = shallowRef({})

  const frozen = ref(false)
  /** Updates the run has made since the view was frozen — shown on the badge. */
  const behind = ref(0)

  const EventSourceImpl = options.EventSourceImpl || null
  let stream = null

  const watching = computed(() => stream !== null)
  const running = computed(
    () => Boolean(executionStatus.value) && !isTerminalExecutionStatus(executionStatus.value),
  )

  function closeStream() {
    if (stream) {
      stream.close()
      stream = null
    }
  }

  function publish() {
    if (frozen.value) return
    records.value = liveRecords.value
    behind.value = 0
  }

  function setFrozen(next) {
    frozen.value = Boolean(next)
    publish()
  }

  function toggleFreeze() {
    setFrozen(!frozen.value)
    return frozen.value
  }

  /**
   * Apply one sequenced SSE frame.
   *
   * Exported so the freeze guarantee is testable without a browser: feed
   * frames in, and assert the run moved while the view did not.
   */
  function applyEvent(event) {
    if (!event || typeof event !== 'object') return

    // Ring-buffer reset — the retained window no longer reaches back this far,
    // so the attached snapshot is the authority, not what we already had.
    if (event.snapshot && typeof event.snapshot === 'object') {
      liveRecords.value = nodeRecordsFromExecution(event.snapshot)
      if (event.snapshot.status) executionStatus.value = event.snapshot.status
    }

    if (event.node_id) {
      const next = { ...liveRecords.value }
      // `applyNodeEvent` updates the record in place. Replacing it with a copy
      // first is what makes a frozen view genuinely still: without this, the
      // held map would share record objects with the live one and mutate
      // underneath it, showing new status through an old snapshot.
      next[event.node_id] = { ...(next[event.node_id] || { status: 'idle' }) }
      applyNodeEvent(next, event)
      liveRecords.value = next
    } else if (event.status && event.status !== 'reset') {
      executionStatus.value = event.status
    }

    if (frozen.value) behind.value += 1
    publish()

    if (!event.node_id && isTerminalExecutionStatus(event.status)) {
      closeStream()
      // Outputs, cost and the resolved provider instance are on the record,
      // not repeated in every frame. One last read so the inspector shows the
      // finished truth rather than the last thing the stream mentioned.
      void refresh().catch(() => {})
    }
  }

  function watchExecution(id, { EventSourceImpl: impl } = {}) {
    if (!id) return null
    closeStream()
    streamError.value = ''
    const Source = impl || EventSourceImpl || globalThis.EventSource
    stream = createExecutionEventStream(id, {
      onEvent: applyEvent,
      onError: (err) => {
        // EventSource reports transient reconnects here too. The picture stays
        // on screen; Last-Event-ID resume belongs to the browser transport.
        streamError.value = err?.message || 'Execution event stream interrupted'
      },
      ...(Source ? { EventSourceImpl: Source } : {}),
    })
    return stream
  }

  /**
   * Show an execution record and follow it live.
   *
   * Binding a different run is a new picture, so it clears any freeze — the
   * held-still state belonged to the run you were watching before.
   *
   * @param {object} execution  execution record (contracts §1.5)
   * @param {object} [opts]
   * @param {typeof EventSource} [opts.EventSourceImpl]
   */
  function attach(execution, opts = {}) {
    if (!execution) return null
    executionId.value = execution.execution_id || executionId.value
    executionStatus.value = execution.status || ''
    liveRecords.value = nodeRecordsFromExecution(execution)
    frozen.value = false
    behind.value = 0
    publish()
    if (isTerminalExecutionStatus(executionStatus.value)) {
      closeStream()
      return null
    }
    return watchExecution(executionId.value, opts)
  }

  /** Re-read the bound execution without disturbing the stream. */
  async function refresh() {
    const id = executionId.value
    if (!id) return null
    const data = await getExecution(id)
    const execution = data?.execution || data
    if (!execution) return null
    liveRecords.value = nodeRecordsFromExecution(execution)
    if (execution.status) executionStatus.value = execution.status
    publish()
    return execution
  }

  /**
   * Load the Job the graph is animating, for the pill's job id and stage.
   *
   * Returns the Job so the caller can bind its execution; this composable does
   * not fetch the graph, because structure is `useSchemaGraph`'s to own.
   */
  async function loadJob(id) {
    jobId.value = id || ''
    if (!id) {
      job.value = null
      return null
    }
    const data = await getJob(id)
    job.value = data?.job || data || null
    return job.value
  }

  function detach() {
    closeStream()
    jobId.value = ''
    job.value = null
    executionId.value = ''
    executionStatus.value = ''
    streamError.value = ''
    liveRecords.value = {}
    frozen.value = false
    behind.value = 0
    records.value = {}
  }

  onBeforeUnmount(closeStream)

  return {
    jobId,
    job,
    executionId,
    executionStatus,
    streamError,
    records,
    liveRecords,
    frozen,
    behind,
    watching,
    running,
    applyEvent,
    attach,
    refresh,
    loadJob,
    watchExecution,
    setFrozen,
    toggleFreeze,
    closeStream,
    detach,
  }
}

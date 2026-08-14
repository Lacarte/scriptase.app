/**
 * Open a workflow SSE stream and discard replay/reconnect duplicates.
 * EventSource itself owns Last-Event-ID reconnect behavior; sequence is the
 * application-level guard against a replay being applied twice.
 */
export function createExecutionEventStream(executionId, {
  onEvent,
  onError = () => {},
  EventSourceImpl = globalThis.EventSource,
} = {}) {
  if (!EventSourceImpl) throw new Error('EventSource is unavailable')
  let lastSequence = 0
  const url = `/api/workflow/executions/${encodeURIComponent(executionId)}/events`
  const source = new EventSourceImpl(url)

  source.onmessage = (message) => {
    let event
    try {
      event = JSON.parse(message.data)
    } catch (error) {
      onError(error)
      return
    }
    const sequence = Number(event.sequence)
    if (!Number.isSafeInteger(sequence) || sequence < 0) {
      onError(new Error('Workflow event has an invalid sequence'))
      return
    }
    if (sequence <= lastSequence) return
    lastSequence = sequence
    onEvent?.(event)
  }
  source.onerror = onError

  return {
    close: () => source.close(),
    get lastSequence() { return lastSequence },
    source,
  }
}


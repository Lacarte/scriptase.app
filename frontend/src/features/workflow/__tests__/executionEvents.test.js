import { describe, expect, it, vi } from 'vitest'
import { createExecutionEventStream } from '../composables/useExecutionEvents.js'

class FakeEventSource {
  constructor(url) {
    this.url = url
    this.close = vi.fn()
  }
  send(event) {
    this.onmessage({ data: JSON.stringify(event) })
  }
}

describe('sequenced workflow events', () => {
  it('deduplicates replayed and out-of-order sequence values', () => {
    const received = []
    const stream = createExecutionEventStream('ex_ABC123', {
      onEvent: event => received.push(event.sequence),
      EventSourceImpl: FakeEventSource,
    })
    expect(stream.source.url).toBe('/api/workflow/executions/ex_ABC123/events')
    stream.source.send({ sequence: 1, status: 'running' })
    stream.source.send({ sequence: 1, status: 'running' })
    stream.source.send({ sequence: 3, status: 'succeeded' })
    stream.source.send({ sequence: 2, status: 'running' })
    expect(received).toEqual([1, 3])
    expect(stream.lastSequence).toBe(3)
    stream.close()
    expect(stream.source.close).toHaveBeenCalledOnce()
  })
})


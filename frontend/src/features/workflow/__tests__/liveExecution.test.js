import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/shared/api/client.js'
import { useWorkflowStore } from '../stores/workflow.js'

class FakeEventSource {
  static latest = null
  constructor(url) {
    this.url = url
    this.close = vi.fn()
    FakeEventSource.latest = this
  }
  send(event) {
    this.onmessage({ data: JSON.stringify(event) })
  }
}

const TYPES = {
  'stub.input': {
    type_version: 1, display_name: 'Sample Input', category: 'testing',
    inputs: [], outputs: [{ id: 'value', type: 'dynamic' }], config_schema: [],
  },
  'assemble.project': {
    type_version: 1, display_name: 'Assemble', category: 'assembly',
    inputs: [], outputs: [{ id: 'project', type: 'editor_project' }], config_schema: [],
  },
}

function seeded() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = TYPES
  store.addNode('stub.input', { x: 0, y: 0 })
  store.addNode('assemble.project', { x: 200, y: 0 })
  return store
}

describe('live workflow execution state', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('starts a run, applies live node states, and hydrates terminal summaries', async () => {
    const store = seeded()
    const [sample, assemble] = store.nodes
    vi.spyOn(api, 'post').mockResolvedValue({
      execution_id: 'ex_ABC123', project_id: 'pm_ABC123', status: 'queued',
    })
    vi.spyOn(api, 'get').mockResolvedValue({
      execution: {
        ...store.currentExecution,
        execution_id: 'ex_ABC123', project_id: 'pm_ABC123', status: 'succeeded',
        workflow_snapshot: store.toDocument(),
        nodes: {
          [sample.id]: { status: 'succeeded', duration_ms: 2, from_sample_data: true, outputs_summary: { value: { sample: true } } },
          [assemble.id]: { status: 'succeeded', duration_ms: 42, from_sample_data: true, outputs_summary: { project: { project_id: { chars: 9 } } } },
        },
      },
    })

    await store.runWorkflow({ EventSourceImpl: FakeEventSource })
    expect(store.currentExecution.status).toBe('queued')
    expect(store.nodeExecution(sample.id).status).toBe('queued')
    expect(FakeEventSource.latest.url).toBe('/api/workflow/executions/ex_ABC123/events')

    FakeEventSource.latest.send({ sequence: 1, type: 'node_status', node_id: sample.id, status: 'running', attempt: 1, duration_ms: 0, from_sample_data: true })
    expect(store.nodeExecution(sample.id)).toMatchObject({ status: 'running', attempts: 1, from_sample_data: true })
    FakeEventSource.latest.send({ sequence: 2, type: 'execution_finished', node_id: null, status: 'succeeded' })
    await vi.waitFor(() => expect(store.editorProjectId).toBe('pm_ABC123'))
    expect(store.nodeExecution(assemble.id).outputs_summary.project.project_id).toEqual({ chars: 9 })
    expect(FakeEventSource.latest.close).toHaveBeenCalled()
  })

  it('surfaces node errors, limits output selection to finished nodes, and stops', async () => {
    const store = seeded()
    const nodeId = store.nodes[0].id
    store.currentExecution = {
      execution_id: 'ex_ABC123', status: 'running', workflow_snapshot: store.toDocument(),
      nodes: { [nodeId]: { status: 'running', outputs_summary: {} } },
    }
    store.applyExecutionEvent({ node_id: nodeId, type: 'node_error', error: { code: 'FAILED', message: 'boom' } })
    expect(store.nodeExecution(nodeId).error.message).toBe('boom')
    store.selectExecutionNode(nodeId)
    expect(store.selectedExecutionNode).toBeNull()
    store.applyExecutionEvent({ node_id: nodeId, type: 'node_status', status: 'failed', duration_ms: 12 })
    store.selectExecutionNode(nodeId)
    expect(store.selectedExecutionNode.status).toBe('failed')

    store.currentExecution.status = 'running'
    vi.spyOn(api, 'post').mockResolvedValue({ execution_id: 'ex_ABC123', status: 'cancelling' })
    await store.stopExecution()
    expect(store.currentExecution.status).toBe('cancelling')
    expect(api.post).toHaveBeenCalledWith('/api/workflow/executions/ex_ABC123/stop', { body: {} })
  })

  it.each([
    ['selected', ['node_a', 'node_b']],
    ['from_node', ['node_a']],
    ['retry_failed', ['node_a']],
    ['retry_failed_desc', ['node_a']],
  ])('sends the %s partial-run request', async (runMode, targetNodeIds) => {
    const store = seeded()
    vi.spyOn(api, 'post').mockResolvedValue({
      execution_id: 'ex_ABC123', project_id: 'pm_ABC123', status: 'queued',
    })
    await store.runWorkflow({ runMode, targetNodeIds, EventSourceImpl: FakeEventSource })
    expect(api.post).toHaveBeenCalledWith('/api/workflow/run', {
      body: expect.objectContaining({
        run_mode: runMode,
        target_node_ids: targetNodeIds,
        force: false,
      }),
    })
    expect(store.currentExecution).toMatchObject({
      run_mode: runMode,
      scope_node_ids: targetNodeIds,
    })
  })

  it('loads newest-first history and inspects a persisted execution', async () => {
    const store = seeded()
    store.workflowId = 'wf_ABC123'
    const summaries = [{
      execution_id: 'ex_OLD001', workflow_id: 'wf_ABC123', project_id: 'pm_ABC123',
      run_mode: 'full', status: 'failed', started_at: '2026-08-04T12:00:00Z', finished_at: '2026-08-04T12:00:01Z',
    }]
    const detail = {
      ...summaries[0], workflow_snapshot: store.toDocument(),
      nodes: { [store.nodes[0].id]: { status: 'failed', attempts: 2, attempt_errors: [{ attempt: 1 }] } },
    }
    vi.spyOn(api, 'get').mockImplementation((path, options) => {
      if (path === '/api/workflow/executions') {
        expect(options).toEqual({ params: { workflow_id: 'wf_ABC123', limit: 100 } })
        return Promise.resolve({ executions: summaries, total: 1 })
      }
      return Promise.resolve({ execution: detail })
    })

    await store.refreshExecutionHistory()
    expect(store.executionHistory).toEqual(summaries)
    expect(store.executionHistoryTotal).toBe(1)
    await store.inspectExecution('ex_OLD001')
    expect(store.currentExecution.execution_id).toBe('ex_OLD001')
    expect(store.currentExecution.nodes[store.nodes[0].id].attempt_errors).toHaveLength(1)
  })

  it('does not replace an active run with a historical execution', async () => {
    const store = seeded()
    store.currentExecution = { execution_id: 'ex_LIVE01', status: 'running', nodes: {} }
    await expect(store.inspectExecution('ex_OLD001')).rejects.toThrow(
      'Wait for the current run to finish',
    )
  })

  it('loads the persisted queue and cancels a pending run', async () => {
    const store = seeded()
    store.workflowId = 'wf_ABC123'
    const pending = {
      execution_id: 'ex_QUEUE1', workflow_id: 'wf_ABC123', project_id: 'pm_ABC123',
      status: 'pending', source: 'manual', requested_run_mode: 'full',
      requested_at: '2026-08-05T12:00:00Z',
    }
    vi.spyOn(api, 'get').mockResolvedValue({ queue: [pending], total: 1 })
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      execution_id: 'ex_QUEUE1', status: 'cancelled',
    })

    await store.refreshRunQueue()
    expect(store.runQueue).toEqual([pending])
    expect(store.runQueueTotal).toBe(1)
    await store.cancelPendingRun('ex_QUEUE1')

    expect(post).toHaveBeenCalledWith('/api/workflow/queue/ex_QUEUE1/cancel', { body: {} })
    expect(store.runQueue[0].status).toBe('cancelled')
  })
})

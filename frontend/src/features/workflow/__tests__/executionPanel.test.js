import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { api } from '@/shared/api/client.js'
import ExecutionPanel from '../components/ExecutionPanel.vue'
import { useWorkflowStore } from '../stores/workflow.js'

class FakeEventSource {
  constructor() { this.close = vi.fn() }
}

function record(nodeId) {
  return {
    schema_version: 1,
    execution_id: 'ex_FAIL01',
    workflow_id: 'wf_ABC123',
    project_id: 'pm_ABC123',
    run_mode: 'full',
    status: 'failed',
    started_at: '2026-08-04T12:00:00Z',
    finished_at: '2026-08-04T12:00:02Z',
    workflow_snapshot: { nodes: [{ id: nodeId, type: 'trigger.manual', name: 'Broken step' }] },
    nodes: {
      [nodeId]: {
        status: 'failed', attempts: 2, duration_ms: 120,
        resolved_inputs_summary: { script: { chars: 20 } },
        outputs_summary: {}, artifact_refs: [],
        cache: { hit: false, reason: 'config_changed' },
        logs: [{ ts: '2026-08-04T12:00:01Z', level: 'error', message: 'provider failed' }],
        attempt_errors: [{ attempt: 1, code: 'PROVIDER_FAILED', message: 'first failure' }],
        error: { code: 'PROVIDER_FAILED', message: 'provider failed', attempt: 2, recovery_suggestion: 'Retry it.' },
      },
    },
  }
}

describe('ExecutionPanel deep inspection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('EventSource', FakeEventSource)
    window.localStorage.clear()
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('shows persisted diagnostics and starts a failed-only retry', async () => {
    const store = useWorkflowStore()
    store.workflowId = 'wf_ABC123'
    store.workflowName = 'Diagnostics'
    store.nodeTypes = {
      'trigger.manual': { type_version: 1, inputs: [], outputs: [{ id: 'control', type: 'control' }], config_schema: [] },
    }
    store.nodes = [{
      id: 'broken', type: 'trigger.manual', type_version: 1, name: 'Broken step',
      position: { x: 0, y: 0 }, configuration: {}, disabled: false,
    }]
    const execution = record('broken')
    store.currentExecution = execution
    store.executionHistory = [execution]

    vi.spyOn(api, 'get').mockResolvedValue({ executions: [execution], total: 1 })
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      execution_id: 'ex_RETRY1', project_id: 'pm_ABC123', status: 'queued',
    })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    const wrapper = mount(ExecutionPanel, { global: { plugins: [router] } })
    await vi.waitFor(() => expect(wrapper.text()).toContain('Broken step'))

    await wrapper.find('.execution-row').trigger('click')
    expect(wrapper.text()).toContain('PROVIDER_FAILED')
    expect(wrapper.text()).toContain('config changed')
    expect(wrapper.text()).toContain('provider failed')
    await wrapper.find('.retry-actions button').trigger('click')

    expect(post).toHaveBeenCalledWith('/api/workflow/run', {
      body: expect.objectContaining({
        workflow_id: 'wf_ABC123', run_mode: 'retry_failed', target_node_ids: ['broken'], force: false,
      }),
    })
  })

  it('shows the run queue and cancels a pending item', async () => {
    const store = useWorkflowStore()
    store.workflowId = 'wf_ABC123'
    const pending = {
      execution_id: 'ex_QUEUE1', workflow_id: 'wf_ABC123', project_id: 'pm_ABC123',
      status: 'pending', source: 'manual', requested_run_mode: 'full',
      requested_at: '2026-08-05T12:00:00Z',
    }
    vi.spyOn(api, 'get').mockImplementation((path) => Promise.resolve(
      path === '/api/workflow/queue'
        ? { queue: [pending], total: 1 }
        : { executions: [], total: 0 },
    ))
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      execution_id: 'ex_QUEUE1', status: 'cancelled',
    })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    const wrapper = mount(ExecutionPanel, { global: { plugins: [router] } })

    await vi.waitFor(() => expect(wrapper.find('.queue-item').exists()).toBe(true))
    expect(wrapper.text()).toContain('manual · full')
    await wrapper.find('.queue-item button').trigger('click')
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/workflow/queue/ex_QUEUE1/cancel', { body: {} },
    ))
    expect(store.runQueue[0].status).toBe('cancelled')
  })

  it('collapses without unmounting diagnostics and remembers the preference', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    const wrapper = mount(ExecutionPanel, { global: { plugins: [router] } })
    const toggle = wrapper.find('.execution-collapse-toggle')

    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.execution-content').exists()).toBe(true)

    await toggle.trigger('click')

    expect(wrapper.find('.execution-panel').classes()).toContain('collapsed')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('.execution-body').attributes('style')).toContain('display: none')
    expect(wrapper.find('.execution-content').exists()).toBe(true)
    expect(window.localStorage.getItem('sts.workflow.execution-panel-collapsed')).toBe('1')

    wrapper.unmount()
    const restored = mount(ExecutionPanel, { global: { plugins: [router] } })
    expect(restored.find('.execution-panel').classes()).toContain('collapsed')
    expect(restored.find('.execution-collapse-toggle').attributes('aria-expanded')).toBe('false')
  })
})

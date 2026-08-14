/**
 * Step 2.3 — Production page (live stages + shared SSE).
 * Step 2.4 — Step detail panel (actions → existing run modes).
 *
 * 2.3 done when: running one Job updates Production and the Workflow canvas
 * simultaneously from a single execution, and both survive a mid-run reload.
 *
 * 2.4 done when: each action on a step produces the same execution record a
 * canvas-initiated run would, proven by comparing request bodies field by
 * field (and the backend suite compares full records).
 *
 * Guards:
 * - Stages come from the projection API (no hardcoded step array)
 * - Live updates use the same SSE endpoint as the canvas
 * - No setInterval / polling client
 * - Ring-buffer reset snapshot rebuilds stage status
 * - Mid-run reload hydrates from GET stages + execution, then reopens SSE
 * - Step actions POST /api/workflow/run with the same body as the canvas
 * - No new run modes; Provider UI only on provider-capable stages
 * - -P never appears in stage names
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick, unref } from 'vue'

import {
  aggregateStageStatus,
  applyNodeEvent,
  nodeRecordsFromExecution,
  recomputeStagesFromNodes,
  statusLabel,
} from './stageStatus.js'
import {
  ACTION_RUN_MODES,
  actionRequiresProvider,
  buildStageRunRequest,
  isExecutableAction,
  runModeForAction,
  stagePrimaryTarget,
} from './stageActions.js'
import { useProductionStages } from './composables/useProductionStages.js'
import ProductionPage from './ProductionPage.vue'
import StepDetailPanel from './components/StepDetailPanel.vue'
import * as api from './api.js'
import { useWorkflowStore } from '@/features/workflow/stores/workflow.js'
import { api as workflowApi } from '@/shared/api/client.js'

vi.mock('./api.js', () => ({
  getWorkflowStages: vi.fn(),
  getExecutionStages: vi.fn(),
  getExecution: vi.fn(),
  getWorkflow: vi.fn(),
  projectWorkflowBody: vi.fn(),
  listWorkflows: vi.fn(),
  listExecutions: vi.fn(),
  runWorkflow: vi.fn(),
}))

class FakeEventSource {
  static instances = []
  constructor(url) {
    this.url = url
    this.close = vi.fn()
    this.onmessage = null
    this.onerror = null
    FakeEventSource.instances.push(this)
  }
  send(event) {
    this.onmessage?.({ data: JSON.stringify(event) })
  }
  static reset() {
    FakeEventSource.instances = []
  }
  static latest() {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1] || null
  }
}

const DEFAULT_STAGES = [
  {
    key: 'script',
    label: 'Script',
    ordinal: 0,
    node_ids: ['n_script'],
    status: 'idle',
    provider_capable: false,
    active_provider_instance_id: null,
    artifacts: [],
    issues: [],
  },
  {
    key: 'voice',
    label: 'Voice',
    ordinal: 1,
    node_ids: ['n_tts'],
    status: 'idle',
    provider_capable: true,
    active_provider_instance_id: 'elevenlabs',
    artifacts: [],
    issues: [],
  },
  {
    key: 'composer',
    label: 'Composer',
    ordinal: 2,
    node_ids: ['n_assemble', 'n_captions'],
    status: 'idle',
    provider_capable: false,
    active_provider_instance_id: null,
    artifacts: [],
    issues: [],
  },
]

function projection(overrides = {}) {
  return {
    workflow_id: 'wf_ABCDEF',
    workflow_version: 1,
    stages: DEFAULT_STAGES.map((s) => ({ ...s, node_ids: [...s.node_ids] })),
    ...overrides,
  }
}

describe('stageStatus aggregation', () => {
  it('mirrors backend severity (failed beats running beats succeeded)', () => {
    expect(aggregateStageStatus(['succeeded', 'running'])).toBe('running')
    expect(aggregateStageStatus(['running', 'failed'])).toBe('failed')
    expect(aggregateStageStatus(['queued'])).toBe('running')
    expect(aggregateStageStatus(['waiting', 'succeeded'])).toBe('running')
    expect(aggregateStageStatus([])).toBe('idle')
  })

  it('recomputes stage rows from a node-record map', () => {
    const stages = recomputeStagesFromNodes(DEFAULT_STAGES, {
      n_script: { status: 'succeeded' },
      n_tts: { status: 'running' },
      n_assemble: { status: 'idle' },
      n_captions: { status: 'idle' },
    })
    expect(stages.find((s) => s.key === 'script').status).toBe('succeeded')
    expect(stages.find((s) => s.key === 'voice').status).toBe('running')
    expect(stages.find((s) => s.key === 'composer').status).toBe('idle')
  })

  it('never invents stage labels — statusLabel is presentation only', () => {
    expect(statusLabel('succeeded')).toBe('Complete')
    expect(statusLabel('awaiting_approval')).toBe('Awaiting approval')
  })
})

describe('useProductionStages', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    FakeEventSource.reset()
    api.getWorkflow.mockResolvedValue({ workflow: { nodes: [], edges: [] } })
  })

  it('loads stages from the workflow projection API (no hardcoded list)', async () => {
    api.getWorkflowStages.mockResolvedValue({ projection: projection() })
    const host = mountHarness()
    await host.vm.api.loadWorkflow('wf_ABCDEF')
    expect(api.getWorkflowStages).toHaveBeenCalledWith('wf_ABCDEF')
    const stages = stageList(host)
    expect(stages.map((s) => s.label)).toEqual([
      'Script',
      'Voice',
      'Composer',
    ])
    // Labels came from the API payload, not a local constant.
    expect(stages.every((s) => typeof s.key === 'string')).toBe(true)
  })

  it('opens the same SSE endpoint the canvas uses and updates stages live', async () => {
    api.getExecutionStages.mockResolvedValue({
      projection: {
        ...projection(),
        execution_id: 'ex_LIVE01',
        execution_status: 'running',
      },
    })
    api.getExecution.mockResolvedValue({
      execution: {
        execution_id: 'ex_LIVE01',
        status: 'running',
        nodes: {
          n_script: { status: 'succeeded' },
          n_tts: { status: 'queued' },
        },
      },
    })

    const host = mountHarness()
    await host.vm.api.hydrateFromExecution('ex_LIVE01', {
      EventSourceImpl: FakeEventSource,
    })

    expect(FakeEventSource.latest().url).toBe(
      '/api/workflow/executions/ex_LIVE01/events',
    )
    expect(stageList(host).find((s) => s.key === 'script').status).toBe('succeeded')
    // queued collapses to running for Production.
    expect(stageList(host).find((s) => s.key === 'voice').status).toBe('running')

    FakeEventSource.latest().send({
      sequence: 1,
      node_id: 'n_tts',
      status: 'running',
      attempt: 1,
    })
    expect(stageList(host).find((s) => s.key === 'voice').status).toBe('running')

    FakeEventSource.latest().send({
      sequence: 2,
      node_id: 'n_tts',
      status: 'succeeded',
      attempt: 1,
    })
    expect(stageList(host).find((s) => s.key === 'voice').status).toBe('succeeded')
  })

  it('applies ring-buffer reset snapshots the same way the canvas does', async () => {
    api.getExecutionStages.mockResolvedValue({
      projection: {
        ...projection(),
        execution_id: 'ex_RESET1',
        execution_status: 'running',
      },
    })
    api.getExecution.mockResolvedValue({
      execution: {
        execution_id: 'ex_RESET1',
        status: 'running',
        nodes: { n_script: { status: 'running' } },
      },
    })

    const host = mountHarness()
    await host.vm.api.hydrateFromExecution('ex_RESET1', {
      EventSourceImpl: FakeEventSource,
    })

    FakeEventSource.latest().send({
      sequence: 99,
      status: 'reset',
      snapshot: {
        execution_id: 'ex_RESET1',
        status: 'running',
        nodes: {
          n_script: { status: 'succeeded' },
          n_tts: { status: 'failed', error: { code: 'TTS_FAIL', message: 'boom' } },
        },
      },
    })

    expect(stageList(host).find((s) => s.key === 'script').status).toBe('succeeded')
    expect(stageList(host).find((s) => s.key === 'voice').status).toBe('failed')
  })

  it('survives a mid-run reload by hydrating disk state then reopening SSE', async () => {
    api.getExecutionStages.mockResolvedValue({
      projection: {
        ...projection(),
        execution_id: 'ex_RELOAD',
        execution_status: 'running',
      },
    })
    api.getExecution.mockResolvedValue({
      execution: {
        execution_id: 'ex_RELOAD',
        status: 'running',
        nodes: {
          n_script: { status: 'succeeded' },
          n_tts: { status: 'running' },
        },
      },
    })

    // First mount (pre-reload).
    const first = mountHarness()
    await first.vm.api.hydrateFromExecution('ex_RELOAD', {
      EventSourceImpl: FakeEventSource,
    })
    expect(stageList(first).find((s) => s.key === 'voice').status).toBe('running')
    first.vm.api.dispose()
    first.unmount()

    // Second mount simulates page reload — same execution_id, fresh state.
    FakeEventSource.reset()
    const second = mountHarness()
    await second.vm.api.hydrateFromExecution('ex_RELOAD', {
      EventSourceImpl: FakeEventSource,
    })
    expect(stageList(second).find((s) => s.key === 'script').status).toBe('succeeded')
    expect(stageList(second).find((s) => s.key === 'voice').status).toBe('running')
    expect(FakeEventSource.latest().url).toBe(
      '/api/workflow/executions/ex_RELOAD/events',
    )

    // Live events continue after reload.
    FakeEventSource.latest().send({
      sequence: 5,
      node_id: 'n_tts',
      status: 'succeeded',
    })
    expect(stageList(second).find((s) => s.key === 'voice').status).toBe('succeeded')
  })

  it('does not install a polling timer', async () => {
    const setIntervalSpy = vi.spyOn(globalThis, 'setInterval')
    api.getWorkflowStages.mockResolvedValue({ projection: projection() })
    const host = mountHarness()
    await host.vm.api.loadWorkflow('wf_ABCDEF')
    expect(setIntervalSpy).not.toHaveBeenCalled()
    setIntervalSpy.mockRestore()
  })
})

describe('Production + Workflow share one execution', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    FakeEventSource.reset()
    api.getWorkflow.mockResolvedValue({ workflow: { nodes: [], edges: [] } })
  })

  it('updates Production stages and the Workflow store from the same event sequence', async () => {
    // Production side
    api.getExecutionStages.mockResolvedValue({
      projection: {
        ...projection(),
        execution_id: 'ex_BOTH01',
        execution_status: 'running',
      },
    })
    api.getExecution.mockResolvedValue({
      execution: {
        execution_id: 'ex_BOTH01',
        status: 'running',
        nodes: {
          n_script: { status: 'queued' },
          n_tts: { status: 'idle' },
        },
      },
    })

    const production = mountHarness()
    await production.vm.api.hydrateFromExecution('ex_BOTH01', {
      EventSourceImpl: FakeEventSource,
    })
    const productionSource = FakeEventSource.latest()

    // Canvas side — same endpoint, independent EventSource (two tabs / two views).
    const store = useWorkflowStore()
    store.currentExecution = {
      execution_id: 'ex_BOTH01',
      status: 'running',
      workflow_snapshot: { nodes: [], edges: [] },
      nodes: {
        n_script: { status: 'queued' },
        n_tts: { status: 'idle' },
      },
    }
    store.watchExecution('ex_BOTH01', { EventSourceImpl: FakeEventSource })
    const canvasSource = FakeEventSource.latest()
    expect(canvasSource.url).toBe('/api/workflow/executions/ex_BOTH01/events')
    expect(productionSource.url).toBe(canvasSource.url)

    // Fan the same logical events to both subscribers (what the broker does).
    const events = [
      { sequence: 1, node_id: 'n_script', status: 'running', attempt: 1 },
      { sequence: 2, node_id: 'n_script', status: 'succeeded', attempt: 1 },
      { sequence: 3, node_id: 'n_tts', status: 'running', attempt: 1 },
    ]
    for (const event of events) {
      productionSource.send(event)
      canvasSource.send(event)
    }

    expect(stageList(production).find((s) => s.key === 'script').status).toBe('succeeded')
    expect(stageList(production).find((s) => s.key === 'voice').status).toBe('running')
    expect(store.nodeExecution('n_script').status).toBe('succeeded')
    expect(store.nodeExecution('n_tts').status).toBe('running')
  })
})

describe('stageActions mapping (step 2.4)', () => {
  const voiceStage = {
    key: 'voice',
    label: 'Voice',
    node_ids: ['n_tts'],
    provider_capable: true,
    active_provider_instance_id: 'elevenlabs',
  }
  const composerStage = {
    key: 'composer',
    label: 'Composer',
    node_ids: ['n_assemble', 'n_captions'],
    provider_capable: false,
  }
  const workflow = {
    nodes: [
      { id: 'n_tts', type: 'tts.generate' },
      { id: 'n_assemble', type: 'assemble.project' },
      { id: 'n_captions', type: 'captions.generate' },
    ],
  }

  it('maps every executable action onto a ported run mode', () => {
    expect(ACTION_RUN_MODES).toEqual({
      run: 'node_with_deps',
      test: 'node_isolated',
      regenerate: 'retry_failed',
      run_from_here: 'from_node',
    })
    for (const [action, mode] of Object.entries(ACTION_RUN_MODES)) {
      expect(isExecutableAction(action)).toBe(true)
      expect(runModeForAction(action)).toBe(mode)
    }
    expect(isExecutableAction('view_input')).toBe(false)
    expect(isExecutableAction('approve')).toBe(false)
  })

  it('prefers primary assemble over captions for Composer', () => {
    expect(stagePrimaryTarget(composerStage, workflow)).toBe('n_assemble')
    expect(stagePrimaryTarget(voiceStage, workflow)).toBe('n_tts')
  })

  it('builds the same request body the canvas runWorkflow would send', () => {
    for (const [action, mode] of Object.entries(ACTION_RUN_MODES)) {
      const productionBody = buildStageRunRequest(action, voiceStage, {
        workflowId: 'wf_ABCDEF',
        workflow,
      })
      // Canvas store.runWorkflow posts exactly this shape.
      const canvasBody = {
        workflow_id: 'wf_ABCDEF',
        run_mode: mode,
        target_node_ids: ['n_tts'],
        force: false,
      }
      expect(productionBody).toEqual(canvasBody)
    }
  })

  it('shows provider requirement only on provider-capable executable actions', () => {
    expect(actionRequiresProvider('run', voiceStage)).toBe(true)
    expect(actionRequiresProvider('run', composerStage)).toBe(false)
    expect(actionRequiresProvider('view_input', voiceStage)).toBe(false)
  })
})

describe('useProductionStages.runStageAction', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    FakeEventSource.reset()
    api.getWorkflowStages.mockResolvedValue({ projection: projection() })
    api.getWorkflow.mockResolvedValue({
      workflow: {
        workflow_id: 'wf_ABCDEF',
        nodes: [
          { id: 'n_script', type: 'script.input' },
          { id: 'n_tts', type: 'tts.generate' },
          { id: 'n_assemble', type: 'assemble.project' },
          { id: 'n_captions', type: 'captions.generate' },
        ],
      },
    })
    api.runWorkflow.mockResolvedValue({
      execution_id: 'ex_STAGE1',
      project_id: 'pm_STAGE1',
      status: 'queued',
    })
  })

  it('posts the canvas-identical body and opens the shared SSE stream', async () => {
    const host = mountHarness()
    await host.vm.api.loadWorkflow('wf_ABCDEF')
    const stages = stageList(host)
    const voice = stages.find((s) => s.key === 'voice')
    const result = await host.vm.api.runStageAction('run', voice, {
      EventSourceImpl: FakeEventSource,
    })
    expect(api.runWorkflow).toHaveBeenCalledWith({
      workflow_id: 'wf_ABCDEF',
      run_mode: 'node_with_deps',
      target_node_ids: ['n_tts'],
      force: false,
    })
    expect(result.execution_id).toBe('ex_STAGE1')
    expect(result.body.run_mode).toBe('node_with_deps')
    expect(FakeEventSource.latest().url).toBe(
      '/api/workflow/executions/ex_STAGE1/events',
    )
  })

  it.each([
    ['test', 'node_isolated'],
    ['regenerate', 'retry_failed'],
    ['run_from_here', 'from_node'],
  ])('action %s sends run_mode %s', async (action, mode) => {
    const host = mountHarness()
    await host.vm.api.loadWorkflow('wf_ABCDEF')
    const voice = stageList(host).find((s) => s.key === 'voice')
    await host.vm.api.runStageAction(action, voice, {
      EventSourceImpl: FakeEventSource,
    })
    expect(api.runWorkflow).toHaveBeenCalledWith(
      expect.objectContaining({
        run_mode: mode,
        target_node_ids: ['n_tts'],
      }),
    )
  })
})

describe('StepDetailPanel', () => {
  it('renders §18 actions and hides Provider on non-capable stages', async () => {
    const stage = {
      key: 'composer',
      label: 'Composer',
      status: 'idle',
      node_ids: ['n_assemble', 'n_captions'],
      provider_capable: false,
      artifacts: [],
    }
    const wrapper = mount(StepDetailPanel, {
      props: {
        stage,
        workflowId: 'wf_ABCDEF',
        workflow: {
          nodes: [
            { id: 'n_assemble', type: 'assemble.project' },
            { id: 'n_captions', type: 'captions.generate' },
          ],
        },
        nodeRecords: {},
      },
    })
    const text = wrapper.text()
    expect(text).toContain('Run')
    expect(text).toContain('Test')
    expect(text).toContain('Regenerate')
    expect(text).toContain('Run From Here')
    expect(text).toContain('View Input')
    expect(text).toContain('View Output')
    expect(text).toContain('History')
    expect(text).toContain('Approve')
    // Provider button is omitted when the stage is not provider-capable.
    expect(wrapper.find('.action-provider').exists()).toBe(false)
    expect(text).toContain('Local (not provider-capable)')
    expect(text).not.toMatch(/Composer\s*-P/)
  })

  it('emits a canvas-shaped run payload when Run is clicked', async () => {
    const stage = {
      key: 'voice',
      label: 'Voice',
      status: 'idle',
      node_ids: ['n_tts'],
      provider_capable: true,
      active_provider_instance_id: 'elevenlabs',
      artifacts: [],
    }
    const wrapper = mount(StepDetailPanel, {
      props: {
        stage,
        workflowId: 'wf_ABCDEF',
        workflow: { nodes: [{ id: 'n_tts', type: 'tts.generate' }] },
        nodeRecords: {},
      },
    })
    await wrapper.get('.action-run').trigger('click')
    const events = wrapper.emitted('run')
    expect(events).toHaveLength(1)
    expect(events[0][0].body).toEqual({
      workflow_id: 'wf_ABCDEF',
      run_mode: 'node_with_deps',
      target_node_ids: ['n_tts'],
      force: false,
    })
    expect(events[0][0].requiresProvider).toBe(true)
  })
})

describe('ProductionPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    FakeEventSource.reset()
    api.listWorkflows.mockResolvedValue({
      workflows: [
        { workflow_id: 'wf_ABCDEF', name: 'Full video' },
      ],
      total: 1,
    })
    api.listExecutions.mockResolvedValue({ executions: [], total: 0 })
    api.getWorkflowStages.mockResolvedValue({ projection: projection() })
    api.getWorkflow.mockResolvedValue({
      workflow: {
        workflow_id: 'wf_ABCDEF',
        nodes: [
          { id: 'n_script', type: 'script.input' },
          { id: 'n_tts', type: 'tts.generate' },
          { id: 'n_assemble', type: 'assemble.project' },
          { id: 'n_captions', type: 'captions.generate' },
        ],
      },
    })
  })

  it('renders projected stage labels from the API', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/production', name: 'production', component: ProductionPage },
        { path: '/workflow', name: 'workflow', component: { template: '<div />' } },
      ],
    })
    await router.push({ name: 'production', query: { workflow_id: 'wf_ABCDEF' } })
    await router.isReady()

    const wrapper = mount(ProductionPage, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(api.getWorkflowStages).toHaveBeenCalledWith('wf_ABCDEF')
    const text = wrapper.text()
    expect(text).toContain('Script')
    expect(text).toContain('Voice')
    expect(text).toContain('Composer')
    // Provider capability is metadata, not a "-P" suffix on the name.
    expect(text).not.toMatch(/Script\s*-P/)
    expect(text).not.toMatch(/Voice-P/)
  })

  it('binds an execution from the query string and shows live status', async () => {
    api.getExecutionStages.mockResolvedValue({
      projection: {
        ...projection(),
        execution_id: 'ex_PAGE01',
        execution_status: 'running',
      },
    })
    api.getExecution.mockResolvedValue({
      execution: {
        execution_id: 'ex_PAGE01',
        status: 'running',
        nodes: {
          n_script: { status: 'succeeded' },
          n_tts: { status: 'running' },
        },
      },
    })
    api.listExecutions.mockResolvedValue({
      executions: [{ execution_id: 'ex_PAGE01', status: 'running' }],
      total: 1,
    })

    // Force the composable's EventSource via global stub.
    const Original = globalThis.EventSource
    globalThis.EventSource = FakeEventSource

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/production', name: 'production', component: ProductionPage },
        { path: '/workflow', name: 'workflow', component: { template: '<div />' } },
      ],
    })
    await router.push({
      name: 'production',
      query: { workflow_id: 'wf_ABCDEF', execution_id: 'ex_PAGE01' },
    })
    await router.isReady()

    const wrapper = mount(ProductionPage, {
      global: { plugins: [router] },
    })
    await flushPromises()
    await nextTick()

    expect(api.getExecutionStages).toHaveBeenCalledWith('ex_PAGE01')
    expect(wrapper.text()).toContain('Complete') // script succeeded
    expect(wrapper.text()).toContain('Running')
    expect(wrapper.text()).toContain('Live')
    expect(FakeEventSource.latest()?.url).toBe(
      '/api/workflow/executions/ex_PAGE01/events',
    )

    globalThis.EventSource = Original
  })

  it('shows step detail actions when a stage is selected', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/production', name: 'production', component: ProductionPage },
        { path: '/workflow', name: 'workflow', component: { template: '<div />' } },
      ],
    })
    await router.push({ name: 'production', query: { workflow_id: 'wf_ABCDEF' } })
    await router.isReady()

    const wrapper = mount(ProductionPage, {
      global: { plugins: [router] },
    })
    await flushPromises()

    // Click the Voice stage row.
    const rows = wrapper.findAll('.stage-row')
    const voiceRow = rows.find((r) => r.text().includes('Voice'))
    expect(voiceRow).toBeTruthy()
    await voiceRow.trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('Run From Here')
    expect(wrapper.text()).toContain('View Input')
    expect(wrapper.find('.action-run').exists()).toBe(true)
    expect(wrapper.find('.action-provider').exists()).toBe(true)
  })
})

describe('nodeRecords helpers', () => {
  it('round-trips an execution snapshot into a records map', () => {
    const records = nodeRecordsFromExecution({
      nodes: {
        a: { status: 'succeeded', artifact_refs: ['stories/x.json'] },
        b: { status: 'failed' },
      },
    })
    applyNodeEvent(records, { node_id: 'b', status: 'running' })
    expect(records.a.status).toBe('succeeded')
    expect(records.b.status).toBe('running')
    expect(records.a.artifact_refs).toEqual(['stories/x.json'])
  })
})

/** Nested refs on vm.api are not auto-unwrapped — always unref. */
function stageList(host) {
  return unref(host.vm.api.stages) || []
}

/** Mount a tiny host so the composable can use onBeforeUnmount. */
function mountHarness() {
  const Comp = defineComponent({
    setup() {
      const apiHandle = useProductionStages({ EventSourceImpl: FakeEventSource })
      return { api: apiHandle }
    },
    render() {
      return h('div')
    },
  })
  return mount(Comp)
}

// workflowApi imported for the dual-view parity surface; keep the module edge.
void workflowApi

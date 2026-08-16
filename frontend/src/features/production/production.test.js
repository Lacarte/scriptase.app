/**
 * Step 2.3 — Production page (live stages + shared SSE).
 * Step 2.4 — Step detail panel (actions → existing run modes).
 * Step 2.5 — Job creation and Script stage modes.
 *
 * 2.3 done when: running one Job updates Production and the Workflow canvas
 * simultaneously from a single execution, and both survive a mid-run reload.
 *
 * 2.4 done when: each action on a step produces the same execution record a
 * canvas-initiated run would, proven by comparing request bodies field by
 * field (and the backend suite compares full records).
 *
 * 2.5 done when: a Job created with Paste Script runs to export with no
 * script provider (backend). Frontend: Step 0 form + provider UI only for
 * modes that need one.
 *
 * Guards:
 * - Stages come from the projection API (no hardcoded step array)
 * - Live updates use the same SSE endpoint as the canvas
 * - No setInterval / polling client
 * - Ring-buffer reset snapshot rebuilds stage status
 * - Mid-run reload hydrates from GET stages + execution, then reopens SSE
 * - Step actions POST /api/workflow/run with the same body as the canvas
 * - No new run modes; Provider UI only on provider-capable stages / modes
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
import {
  sourceModeRequiresProvider,
  validateJobSource,
  SOURCE_MODE_CATALOG,
} from './sourceModes.js'
import { useProductionStages } from './composables/useProductionStages.js'
import ProductionPage from './ProductionPage.vue'
import StepDetailPanel from './components/StepDetailPanel.vue'
import JobCreatePanel from './components/JobCreatePanel.vue'
import * as api from './api.js'
import * as channelsApi from '@/features/channels/api.js'
import { useWorkflowStore } from '@/features/workflow/stores/workflow.js'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
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
  getJobDefaults: vi.fn(),
  listJobs: vi.fn(),
  getJob: vi.fn(),
  getJobCost: vi.fn(),
  getJobRepairHistory: vi.fn(),
  createJob: vi.fn(),
  startJob: vi.fn(),
  testJobNode: vi.fn(),
  getNodeTypes: vi.fn(),
  deleteJob: vi.fn(),
}))

vi.mock('@/features/channels/api.js', () => ({
  listChannels: vi.fn(),
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

  it('shows its queue position and moves up when the run ahead finishes', async () => {
    // Step 13.1: Jobs run one at a time, so a queued run is waiting on a
    // known number of runs ahead of it.
    api.getExecutionStages.mockResolvedValue({
      projection: {
        ...projection(),
        execution_id: 'ex_WAIT01',
        execution_status: 'queued',
        queue_position: 2,
        queue_waiting: 2,
      },
    })
    api.getExecution.mockResolvedValue({
      execution: { execution_id: 'ex_WAIT01', status: 'queued', nodes: {} },
    })

    const host = mountHarness()
    await host.vm.api.hydrateFromExecution('ex_WAIT01', {
      EventSourceImpl: FakeEventSource,
    })
    expect(unref(host.vm.api.queuePosition)).toBe(2)
    expect(unref(host.vm.api.queueWaiting)).toBe(2)

    // The run ahead finished — this run moves up without acting itself.
    FakeEventSource.latest().send({
      sequence: 1,
      type: 'queue_position',
      node_id: null,
      status: 'queued',
      queue_position: 1,
      queue_waiting: 1,
    })
    expect(unref(host.vm.api.queuePosition)).toBe(1)

    // Admitted to the pool: no longer behind anyone.
    FakeEventSource.latest().send({ sequence: 2, node_id: null, status: 'running' })
    expect(unref(host.vm.api.queuePosition)).toBe(null)
    expect(unref(host.vm.api.executionStatus)).toBe('running')
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

describe('sourceModes (step 2.5)', () => {
  it('marks paste/manual as no-provider and topic/idea/automatic as provider', () => {
    expect(sourceModeRequiresProvider('paste')).toBe(false)
    expect(sourceModeRequiresProvider('manual')).toBe(false)
    expect(sourceModeRequiresProvider('topic')).toBe(true)
    expect(sourceModeRequiresProvider('idea')).toBe(true)
    expect(sourceModeRequiresProvider('automatic')).toBe(true)
    expect(SOURCE_MODE_CATALOG.map((m) => m.mode)).toEqual([
      'automatic',
      'topic',
      'idea',
      'paste',
      'manual',
    ])
  })

  it('validates paste requires text and topic requires topic', () => {
    expect(validateJobSource({ mode: 'paste', pasted_script: '' }).length).toBeGreaterThan(0)
    expect(validateJobSource({ mode: 'paste', pasted_script: 'Hello.' })).toEqual([])
    expect(validateJobSource({ mode: 'topic', topic: '' }).length).toBeGreaterThan(0)
    expect(validateJobSource({ mode: 'topic', topic: 'stoicism' })).toEqual([])
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

  it('opens the Test Node panel on Test click (step 4.2)', async () => {
    const stage = {
      key: 'videos',
      label: 'Video Generator',
      status: 'idle',
      node_ids: ['n_animator'],
      provider_capable: true,
      active_provider_instance_id: 'wavespeed_main',
      artifacts: [],
    }
    const wrapper = mount(StepDetailPanel, {
      props: {
        stage,
        workflowId: 'wf_ABCDEF',
        workflow: {
          nodes: [{ id: 'n_animator', type: 'animator.generate' }],
        },
        nodeRecords: {},
        jobId: 'job_TEST01',
        nodeTypes: {
          'animator.generate': {
            inputs: [
              { id: 'scenes', type: 'scenes', required: true },
              { id: 'storyboard', type: 'storyboard_images', required: true },
            ],
          },
        },
      },
    })
    expect(wrapper.find('.test-node-panel').exists()).toBe(false)
    await wrapper.find('.action-test').trigger('click')
    expect(wrapper.find('.test-node-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('Video Generator — Test Node')
    expect(wrapper.text()).toContain('will not advance')
    expect(wrapper.text()).toContain('Test Node')
  })

  it('History pane shows side-by-side image versions (step 4.3)', async () => {
    const stage = {
      key: 'images',
      label: 'Image Generator',
      status: 'succeeded',
      node_ids: ['n_storyboard'],
      provider_capable: true,
      active_provider_instance_id: 'wavespeed_main',
      artifacts: [],
    }
    const attemptHistory = {
      attempt_count: 2,
      attempts: [
        {
          artifact_id: 'art_AAAAAA',
          version: 1,
          provider_instance_id: 'wavespeed_main',
          seed: 42,
          prompt_revision: 'flux-v1',
          is_superseded: true,
          path: 'storyboard/a_v1.png',
        },
        {
          artifact_id: 'art_BBBBBB',
          version: 2,
          provider_instance_id: 'wavespeed_fallback',
          seed: 99,
          prompt_revision: 'flux-v2',
          is_superseded: false,
          path: 'storyboard/a_v2.png',
        },
      ],
      comparison: {
        left: {
          artifact_id: 'art_AAAAAA',
          version: 1,
          provider_instance_id: 'wavespeed_main',
          seed: 42,
          prompt_revision: 'flux-v1',
          path: 'storyboard/a_v1.png',
        },
        right: {
          artifact_id: 'art_BBBBBB',
          version: 2,
          provider_instance_id: 'wavespeed_fallback',
          seed: 99,
          prompt_revision: 'flux-v2',
          path: 'storyboard/a_v2.png',
        },
        axes: {
          provider_instance_id: {
            left: 'wavespeed_main',
            right: 'wavespeed_fallback',
            changed: true,
          },
          seed: { left: 42, right: 99, changed: true },
          prompt_revision: { left: 'flux-v1', right: 'flux-v2', changed: true },
        },
        changed_axes: ['provider_instance_id', 'seed', 'prompt_revision'],
      },
    }
    const wrapper = mount(StepDetailPanel, {
      props: {
        stage,
        workflowId: 'wf_ABCDEF',
        workflow: {
          nodes: [{ id: 'n_storyboard', type: 'storyboard.generate' }],
        },
        nodeRecords: {
          n_storyboard: { status: 'succeeded', attempts: 1 },
        },
        jobId: 'job_IMG001',
        attemptHistory,
      },
    })
    await wrapper.find('.action-history').trigger('click')
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('Side-by-side comparison')
    expect(text).toContain('wavespeed_main')
    expect(text).toContain('wavespeed_fallback')
    expect(text).toContain('42')
    expect(text).toContain('99')
    expect(text).toContain('flux-v1')
    expect(text).toContain('flux-v2')
  })

  it('renders stage.issues and the repair that answered them (step 11.4)', async () => {
    const stage = {
      key: 'images',
      label: 'Image Generator',
      status: 'succeeded',
      node_ids: ['n_storyboard'],
      provider_capable: true,
      active_provider_instance_id: 'wavespeed_main',
      artifacts: [],
      issues: ['iss_AAAAAA'],
    }
    const repairHistory = {
      job_id: 'job_REP001',
      entry_count: 1,
      entries: [
        {
          id: 'rph_AAAAAA',
          issue_id: 'iss_AAAAAA',
          scene_id: 'scene_003',
          routed_to_node_type: 'storyboard.generate',
          provider_instance_id: 'wavespeed_main',
          action: 'regenerate',
          instruction: 'Regenerate scene 3 with a tighter framing',
          reason: 'Technical validator flagged a blank frame',
          prompt_revision: 'flux-v2',
          input_artifact_ids: ['art_OLD001'],
          output_artifact_ids: ['art_NEW001'],
          result: 'resolved',
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      superseded_artifact_versions: [
        {
          artifact_id: 'art_OLD001',
          version: 1,
          is_superseded: true,
          superseded_by: 'art_NEW001',
        },
      ],
    }
    const wrapper = mount(StepDetailPanel, {
      props: {
        stage,
        workflowId: 'wf_ABCDEF',
        workflow: { nodes: [{ id: 'n_storyboard', type: 'storyboard.generate' }] },
        nodeRecords: { n_storyboard: { status: 'succeeded', attempts: 2 } },
        jobId: 'job_REP001',
        repairHistory,
      },
    })

    // The projection's issue ids render without opening any pane.
    expect(wrapper.find('[data-testid="stage-issues"]').text()).toContain('iss_AAAAAA')

    await wrapper.find('.action-history').trigger('click')
    await flushPromises()

    const pane = wrapper.find('[data-testid="repair-history"]')
    expect(pane.exists()).toBe(true)
    const text = pane.text()
    // The issue, the node it was routed to, and what was retried.
    expect(text).toContain('iss_AAAAAA')
    expect(text).toContain('storyboard.generate')
    expect(text).toContain('regenerate')
    expect(text).toContain('Technical validator flagged a blank frame')
    expect(text).toContain('Regenerate scene 3 with a tighter framing')
    // Superseded evidence is never erased.
    expect(wrapper.find('[data-testid="superseded-versions"]').text()).toContain('art_OLD001')
    expect(wrapper.find('[data-testid="superseded-versions"]').text()).toContain('art_NEW001')
  })

  it('loads repair history from the read-only Job endpoint when not preloaded', async () => {
    api.getJobRepairHistory.mockResolvedValue({
      job_id: 'job_REP002',
      entry_count: 0,
      entries: [],
      superseded_artifact_versions: [],
    })
    const stage = {
      key: 'videos',
      label: 'Video Generator',
      status: 'succeeded',
      node_ids: ['n_animator'],
      provider_capable: true,
      artifacts: [],
      issues: [],
    }
    const wrapper = mount(StepDetailPanel, {
      props: {
        stage,
        workflowId: 'wf_ABCDEF',
        workflow: { nodes: [{ id: 'n_animator', type: 'animator.generate' }] },
        nodeRecords: {},
        jobId: 'job_REP002',
      },
    })
    await wrapper.find('.action-history').trigger('click')
    await flushPromises()

    expect(api.getJobRepairHistory).toHaveBeenCalledWith('job_REP002')
    expect(wrapper.find('[data-testid="repair-history"]').text()).toContain(
      'No repair has run for this Job',
    )
  })

  it('hides Provider on Script stage for Paste mode even if graph is provider-capable', () => {
    const stage = {
      key: 'script',
      label: 'Script',
      status: 'idle',
      node_ids: ['n_story'],
      provider_capable: true,
      active_provider_instance_id: 'gemini',
      artifacts: [],
    }
    const wrapper = mount(StepDetailPanel, {
      props: {
        stage,
        workflowId: 'wf_ABCDEF',
        workflow: { nodes: [{ id: 'n_story', type: 'story.generate' }] },
        scriptSourceMode: 'paste',
        scriptProviderRequired: false,
      },
    })
    expect(wrapper.find('.action-provider').exists()).toBe(false)
    expect(wrapper.text()).toContain('Paste Script')
    expect(wrapper.text()).toContain('Not required for this Script mode')
    expect(wrapper.text()).not.toMatch(/Script\s*-P/)
  })

  it('shows Provider on Script stage for Idea mode', () => {
    const stage = {
      key: 'script',
      label: 'Script',
      status: 'idle',
      node_ids: ['n_story'],
      provider_capable: true,
      active_provider_instance_id: 'gemini',
      artifacts: [],
    }
    const wrapper = mount(StepDetailPanel, {
      props: {
        stage,
        workflowId: 'wf_ABCDEF',
        workflow: { nodes: [{ id: 'n_story', type: 'story.generate' }] },
        scriptSourceMode: 'idea',
        scriptProviderRequired: true,
      },
    })
    expect(wrapper.find('.action-provider').exists()).toBe(true)
    expect(wrapper.text()).toContain('Idea → Script')
    expect(wrapper.text()).toContain('gemini')
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

describe('JobCreatePanel (step 2.5)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getJobDefaults.mockResolvedValue({
      source_modes: SOURCE_MODE_CATALOG,
      execution_modes: [
        { mode: 'manual', label: 'Manual', description: 'Manual' },
        { mode: 'assisted', label: 'Assisted', description: 'Assisted' },
        { mode: 'automatic', label: 'Automatic', description: 'Automatic' },
      ],
      defaults: {
        execution_mode: 'manual',
        source: { mode: 'paste', topic: '', idea: '', pasted_script: '', references: [] },
      },
    })
    channelsApi.listChannels.mockResolvedValue({
      channels: [{ id: 'ch_AAAAAA', name: 'Philosophy Daily' }],
      total: 1,
    })
    api.listWorkflows.mockResolvedValue({
      workflows: [{ workflow_id: 'wf_ABCDEF', name: 'Full video' }],
      total: 1,
    })
    api.createJob.mockResolvedValue({
      job: {
        id: 'job_PASTE1',
        channel_id: 'ch_AAAAAA',
        workflow_id: 'wf_ABCDEF',
        execution_mode: 'manual',
        source: { mode: 'paste', pasted_script: 'Hello narration.' },
        status: 'queued',
      },
    })
    api.startJob.mockResolvedValue({
      job: {
        id: 'job_PASTE1',
        channel_id: 'ch_AAAAAA',
        workflow_id: 'wf_ABCDEF',
        execution_mode: 'manual',
        source: { mode: 'paste', pasted_script: 'Hello narration.' },
        status: 'running',
        execution_id: 'ex_PASTE1',
      },
      execution_id: 'ex_PASTE1',
      status: 'running',
    })
  })

  it('creates a paste Job without requiring a script provider', async () => {
    const wrapper = mount(JobCreatePanel, {
      props: { autoStart: true },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Create Job')
    expect(wrapper.text()).toContain('Paste Script')
    expect(wrapper.text()).toContain('No provider')

    await wrapper.get('select').setValue('ch_AAAAAA')
    // Paste mode is default — fill script textarea.
    const textarea = wrapper.find('textarea')
    expect(textarea.exists()).toBe(true)
    await textarea.setValue('What Marcus Aurelius teaches about control.')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(api.createJob).toHaveBeenCalledWith(
      expect.objectContaining({
        channel_id: 'ch_AAAAAA',
        source: expect.objectContaining({
          mode: 'paste',
          pasted_script: 'What Marcus Aurelius teaches about control.',
        }),
      }),
    )
    expect(api.startJob).toHaveBeenCalledWith('job_PASTE1', expect.any(Object))
    expect(wrapper.emitted('started')).toBeTruthy()
  })

  it('shows provider note for idea mode and hides for paste', async () => {
    const wrapper = mount(JobCreatePanel, { props: { autoStart: false } })
    await flushPromises()

    // Default paste — local note.
    expect(wrapper.text()).toMatch(/no script provider/i)

    // Switch to Idea → Script.
    const ideaRadio = wrapper.findAll('input[type="radio"]').find(
      (r) => r.element.value === 'idea',
    )
    expect(ideaRadio).toBeTruthy()
    await ideaRadio.setValue('idea')
    await flushPromises()
    expect(wrapper.text()).toMatch(/uses a script provider/i)
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
    api.getJobDefaults.mockResolvedValue({
      source_modes: SOURCE_MODE_CATALOG,
      execution_modes: [{ mode: 'manual', label: 'Manual', description: '' }],
      defaults: { execution_mode: 'manual', source: { mode: 'paste' } },
    })
    channelsApi.listChannels.mockResolvedValue({ channels: [], total: 0 })
    api.getNodeTypes.mockResolvedValue({ node_types: {} })
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

  it('surfaces the projection issue count on the stage row (step 11.4)', async () => {
    api.getWorkflowStages.mockResolvedValue({
      projection: {
        ...projection(),
        stages: DEFAULT_STAGES.map((s) => ({
          ...s,
          node_ids: [...s.node_ids],
          issues: s.key === 'voice' ? ['iss_AAAAAA'] : [],
        })),
      },
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/production', name: 'production', component: ProductionPage },
        { path: '/workflow', name: 'workflow', component: { template: '<div />' } },
      ],
    })
    await router.push({ name: 'production', query: { workflow_id: 'wf_ABCDEF' } })
    await router.isReady()

    const wrapper = mount(ProductionPage, { global: { plugins: [router] } })
    await flushPromises()

    const voiceRow = wrapper.findAll('.stage-row').find((r) => r.text().includes('Voice'))
    expect(voiceRow.find('.issue-count').text()).toBe('1 issue')

    await voiceRow.trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="stage-issues"]').text()).toContain('iss_AAAAAA')
  })

  it('sends the Test Node provider choice as a one-shot override (step 13.3)', async () => {
    api.getJob.mockResolvedValue({
      job: { id: 'job_TEST01', workflow_id: 'wf_ABCDEF', source: { mode: 'paste' } },
    })
    api.getJobCost.mockResolvedValue({ cost: null })
    api.getNodeTypes.mockResolvedValue({
      node_types: {
        'tts.generate': {
          inputs: [{ id: 'script', type: 'script', required: true, multiple: false }],
        },
      },
    })
    api.testJobNode.mockResolvedValue({ execution_id: 'ex_TEST01', status: 'queued' })
    api.getExecution.mockResolvedValue({
      execution: { execution_id: 'ex_TEST01', status: 'succeeded', nodes: {} },
    })

    // Two instances of one provider type is the case the override exists for.
    const catalog = useProviderCatalogStore()
    catalog.catalogVersion = 1
    catalog.domains = {
      tts: {
        label: 'Voice',
        selected_instance_id: 'elevenlabs',
        default_provider: 'elevenlabs',
        capability_vocabulary: [],
        providers: [{
          id: 'elevenlabs', label: 'ElevenLabs',
          availability: 'available', capabilities: {}, aliases: [],
        }],
        instances: [
          {
            instance_id: 'elevenlabs', provider_type: 'elevenlabs', label: 'ElevenLabs',
            availability: 'available', selected: true,
          },
          {
            instance_id: 'elevenlabs_alt', provider_type: 'elevenlabs', label: 'ElevenLabs Alt',
            availability: 'available', selected: false,
          },
        ],
        excluded: [],
      },
    }

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/production', name: 'production', component: ProductionPage },
        { path: '/workflow', name: 'workflow', component: { template: '<div />' } },
      ],
    })
    await router.push({
      name: 'production',
      query: { workflow_id: 'wf_ABCDEF', job_id: 'job_TEST01' },
    })
    await router.isReady()

    const wrapper = mount(ProductionPage, { global: { plugins: [router] } })
    await flushPromises()

    const voiceRow = wrapper.findAll('.stage-row').find((r) => r.text().includes('Voice'))
    await voiceRow.trigger('click')
    await nextTick()
    await wrapper.find('.action-test').trigger('click')
    await nextTick()

    const select = wrapper.find('.tn-provider-select')
    expect(select.exists()).toBe(true)
    expect(select.text()).toContain('ElevenLabs Alt')
    await select.setValue('elevenlabs_alt')
    await wrapper.find('.tn-run').trigger('click')
    await flushPromises()

    // The bound Job's own endpoint, so the Job cannot advance, carrying the
    // 13.2 one-shot instance.
    expect(api.testJobNode).toHaveBeenCalledWith(
      'job_TEST01',
      expect.objectContaining({
        target_node_ids: ['n_tts'],
        provider_instance_id: 'elevenlabs_alt',
      }),
    )
    wrapper.unmount()
  })

  it('opens the editor and exports in their own windows, keeping the run bound (step 14.4)', async () => {
    // Production owns a live SSE stream; a route change would tear it down.
    // The bound execution's project travels in the URL so the popup survives
    // its own reload and stays pasteable.
    api.getExecutionStages.mockResolvedValue({
      projection: {
        ...projection(),
        execution_id: 'ex_WIN001',
        execution_status: 'succeeded',
      },
    })
    api.getExecution.mockResolvedValue({
      execution: {
        execution_id: 'ex_WIN001',
        project_id: 'pm_ABC123',
        status: 'succeeded',
        nodes: { n_script: { status: 'succeeded' } },
      },
    })
    api.listExecutions.mockResolvedValue({
      executions: [{ execution_id: 'ex_WIN001', status: 'succeeded' }],
      total: 1,
    })
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/production', name: 'production', component: ProductionPage },
        { path: '/workflow', name: 'workflow', component: { template: '<div />' } },
      ],
    })
    await router.push({
      name: 'production',
      query: { workflow_id: 'wf_ABCDEF', execution_id: 'ex_WIN001' },
    })
    await router.isReady()

    const wrapper = mount(ProductionPage, { global: { plugins: [router] } })
    await flushPromises()

    const buttons = wrapper.findAll('.page-header .actions button')
    const editorButton = buttons.find((b) => b.text().includes('Timeline Editor'))
    const exportsButton = buttons.find((b) => b.text().includes('Exports'))
    await editorButton.trigger('click')
    await exportsButton.trigger('click')

    expect(open.mock.calls.map((call) => call.slice(0, 2))).toEqual([
      ['/editor?project=pm_ABC123', 'scriptase-editor-pm_ABC123'],
      ['/exports?project=pm_ABC123', 'scriptase-exports-pm_ABC123'],
    ])
    expect(open.mock.calls[0][2]).toContain('popup=yes')
    // Production is still on Production, still bound to the same run.
    expect(router.currentRoute.value.path).toBe('/production')
    expect(router.currentRoute.value.query.execution_id).toBe('ex_WIN001')
    wrapper.unmount()
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

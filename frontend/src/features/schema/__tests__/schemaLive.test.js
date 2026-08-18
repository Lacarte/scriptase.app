/**
 * Step 1.3 — live animation and the node inspector.
 *
 * Done when: a running job animates the graph live, the inspector stays in
 * sync as stages advance, and Freeze view demonstrably leaves the job running.
 *
 * Guards:
 * - Every card's look is derived from an execution record; no status, stage or
 *   node is authored in the frontend
 * - Freeze holds the *view* still: the stream stays open, the run keeps
 *   moving, and unfreezing shows where it actually got to
 * - The inspector reports the resolved provider **instance**, never a secret
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, unref } from 'vue'
import { mount } from '@vue/test-utils'

import {
  buildNodeStates,
  currentStageLabel,
  flowingEdgeIds,
  formatDuration,
  inspectorModel,
  runProgress,
  visualForStatus,
} from '../live.js'
import { useSchemaLive } from '../composables/useSchemaLive.js'
import * as api from '../api.js'

vi.mock('../api.js', () => ({
  getNodeTypes: vi.fn(),
  listWorkflows: vi.fn(),
  getWorkflow: vi.fn(),
  getWorkflowStages: vi.fn(),
  projectWorkflowBody: vi.fn(),
  listTemplates: vi.fn(),
  listExecutions: vi.fn(),
  getExecution: vi.fn(),
  getExecutionStages: vi.fn(),
  getJob: vi.fn(),
}))

const NODES = [
  { id: 'n_one', name: 'One', stageKey: 'alpha', stageLabel: 'Alpha', subtitle: 'Alpha' },
  { id: 'n_two', name: 'Two', stageKey: 'beta', stageLabel: 'Beta', subtitle: 'Beta' },
  { id: 'n_three', name: 'Three', stageKey: null, stageLabel: null, subtitle: 'Infrastructure' },
]

const EDGES = [
  { id: 'e1', source: 'n_one', target: 'n_two' },
  { id: 'e2', source: 'n_two', target: 'n_three' },
]

class FakeEventSource {
  static instances = []
  constructor(url) {
    this.url = url
    this.closed = false
    this.close = vi.fn(() => { this.closed = true })
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

function execution(overrides = {}) {
  return {
    execution_id: 'ex_LIVE01',
    workflow_id: 'wf_AAA111',
    status: 'running',
    workflow_snapshot: { nodes: [], edges: [] },
    nodes: {
      n_one: { status: 'succeeded', artifact_refs: ['a/1'] },
      n_two: { status: 'running' },
    },
    ...overrides,
  }
}

/** The composable registers onBeforeUnmount, so it needs a component to live in. */
function mountLive() {
  return mount(defineComponent({
    setup() {
      return { live: useSchemaLive({ EventSourceImpl: FakeEventSource }) }
    },
    render: () => null,
  }))
}

let sequence = 0
function frame(event) {
  sequence += 1
  return { sequence, execution_id: 'ex_LIVE01', ...event }
}

describe('live model (step 1.3)', () => {
  it('maps engine status onto the five looks, and never loses a node', () => {
    expect(visualForStatus('idle')).toBe('pending')
    expect(visualForStatus('running')).toBe('active')
    expect(visualForStatus('succeeded')).toBe('done')
    expect(visualForStatus('failed')).toBe('failed')
    expect(visualForStatus('skipped')).toBe('skipped')
    // A status this frontend has never heard of still draws, the same way an
    // unknown node type does.
    expect(visualForStatus('teleported')).toBe('pending')
    expect(visualForStatus(undefined)).toBe('pending')
  })

  it('keys card state off the graph, not off the record map', () => {
    const states = buildNodeStates(NODES, {
      n_one: { status: 'succeeded' },
      n_ghost: { status: 'running' },
    })
    expect(Object.keys(states)).toEqual(['n_one', 'n_two', 'n_three'])
    expect(states.n_one.visual).toBe('done')
    // Never reached by this run: pending, not missing.
    expect(states.n_two.visual).toBe('pending')
    // A record for a node this graph does not contain is ignored, not drawn.
    expect(states.n_ghost).toBeUndefined()
  })

  it('flows the edges into an active node and no others', () => {
    const states = buildNodeStates(NODES, {
      n_one: { status: 'succeeded' },
      n_two: { status: 'running' },
    })
    const flowing = flowingEdgeIds(EDGES, states)
    expect(flowing.has('e1')).toBe(true)
    // Out of the active node: nothing has left it yet.
    expect(flowing.has('e2')).toBe(false)
  })

  it('flows nothing when nothing is running', () => {
    const states = buildNodeStates(NODES, { n_one: { status: 'succeeded' } })
    expect(flowingEdgeIds(EDGES, states).size).toBe(0)
  })

  it('reports the run percent from settled nodes', () => {
    const idle = runProgress(NODES, buildNodeStates(NODES, {}))
    expect(idle).toMatchObject({ settled: 0, total: 3, percent: 0 })

    const midway = runProgress(NODES, buildNodeStates(NODES, {
      n_one: { status: 'succeeded' },
      n_two: { status: 'running' },
    }))
    expect(midway).toMatchObject({ settled: 1, active: 1, total: 3, percent: 33 })

    const done = runProgress(NODES, buildNodeStates(NODES, {
      n_one: { status: 'succeeded' },
      n_two: { status: 'skipped' },
      n_three: { status: 'failed' },
    }))
    expect(done.percent).toBe(100)
  })

  it('names the current stage from the projection, never from itself', () => {
    const running = buildNodeStates(NODES, {
      n_one: { status: 'succeeded' },
      n_two: { status: 'running' },
    })
    expect(currentStageLabel(NODES, running)).toBe('Beta')
    // Nothing active: the last stage to settle is where the run stands.
    const settled = buildNodeStates(NODES, { n_one: { status: 'succeeded' } })
    expect(currentStageLabel(NODES, settled)).toBe('Alpha')
    expect(currentStageLabel(NODES, buildNodeStates(NODES, {}))).toBeNull()
  })

  it('builds the inspector from the record, provider instance included', () => {
    const model = inspectorModel(NODES[1], {
      status: 'succeeded',
      attempts: 2,
      duration_ms: 4200,
      resolved_inputs_summary: { text: '…' },
      outputs_summary: { audio: 'voice.wav' },
      artifact_refs: ['tts/pm_X/voice.wav'],
      cost: {
        provider_instance_id: 'inst_main',
        provider_id: 'kokoro',
        selection_reason: 'request',
        // A secret has no business here, and never arrives — but if one ever
        // did, the panel reads named fields only and would not surface it.
      },
    })
    expect(model).toMatchObject({
      id: 'n_two',
      status: 'succeeded',
      visual: 'done',
      attempts: 2,
      empty: false,
      stageLabel: 'Beta',
    })
    expect(model.provider).toEqual({
      instanceId: 'inst_main',
      providerId: 'kokoro',
      reason: 'request',
    })
    expect(model.output).toEqual({ audio: 'voice.wav' })
  })

  it('says so when the run has not reached the node', () => {
    const model = inspectorModel(NODES[0], null)
    expect(model.empty).toBe(true)
    expect(model.status).toBe('idle')
    expect(model.provider).toBeNull()
    expect(inspectorModel(null, null)).toBeNull()
  })

  it('formats a duration without inventing precision', () => {
    expect(formatDuration(420)).toBe('420 ms')
    expect(formatDuration(4200)).toBe('4.2 s')
    expect(formatDuration(90000)).toBe('1m 30s')
    expect(formatDuration(undefined)).toBe('')
  })
})

describe('useSchemaLive (step 1.3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    FakeEventSource.reset()
    sequence = 0
    api.getExecution.mockResolvedValue({ execution: execution() })
    api.getJob.mockResolvedValue({ job: { id: 'job_AAA111', execution_id: 'ex_LIVE01' } })
  })

  it('seeds from the execution record and follows the shared stream', () => {
    const host = mountLive()
    host.vm.live.attach(execution())
    expect(FakeEventSource.latest().url).toBe('/api/workflow/executions/ex_LIVE01/events')
    expect(unref(host.vm.live.records).n_one.status).toBe('succeeded')
    expect(unref(host.vm.live.records).n_two.status).toBe('running')
  })

  it('moves the picture as the run advances', () => {
    const host = mountLive()
    host.vm.live.attach(execution())
    FakeEventSource.latest().send(frame({ node_id: 'n_two', status: 'succeeded' }))
    expect(unref(host.vm.live.records).n_two.status).toBe('succeeded')
  })

  it('opens no stream for a run that has already finished', () => {
    const host = mountLive()
    host.vm.live.attach(execution({ status: 'succeeded' }))
    expect(FakeEventSource.instances).toHaveLength(0)
    expect(unref(host.vm.live.records).n_one.status).toBe('succeeded')
  })

  it('freezes the view and leaves the job running', async () => {
    const host = mountLive()
    host.vm.live.attach(execution())
    const source = FakeEventSource.latest()

    host.vm.live.setFrozen(true)
    const held = unref(host.vm.live.records)

    source.send(frame({ node_id: 'n_two', status: 'succeeded' }))
    source.send(frame({ node_id: 'n_three', status: 'running' }))

    // The view is exactly where it was left...
    expect(unref(host.vm.live.records)).toBe(held)
    expect(unref(host.vm.live.records).n_two.status).toBe('running')
    expect(unref(host.vm.live.records).n_three).toBeUndefined()

    // ...while the run kept going underneath it, on an open stream.
    expect(unref(host.vm.live.liveRecords).n_two.status).toBe('succeeded')
    expect(unref(host.vm.live.liveRecords).n_three.status).toBe('running')
    expect(source.closed).toBe(false)
    expect(source.close).not.toHaveBeenCalled()
    expect(unref(host.vm.live.behind)).toBe(2)

    // Nothing was asked of the backend: freezing is a view state, and this
    // module has no endpoint that could stop, pause or cancel a run.
    expect(api.getExecution).not.toHaveBeenCalled()

    // Unfreezing shows where the run actually got to, not where it was.
    host.vm.live.setFrozen(false)
    expect(unref(host.vm.live.records).n_two.status).toBe('succeeded')
    expect(unref(host.vm.live.records).n_three.status).toBe('running')
    expect(unref(host.vm.live.behind)).toBe(0)
  })

  it('replaces state from a ring-buffer reset snapshot', () => {
    const host = mountLive()
    host.vm.live.attach(execution())
    FakeEventSource.latest().send(frame({
      node_id: null,
      status: 'reset',
      snapshot: execution({ nodes: { n_three: { status: 'failed' } } }),
    }))
    expect(unref(host.vm.live.records).n_one).toBeUndefined()
    expect(unref(host.vm.live.records).n_three.status).toBe('failed')
  })

  it('closes the stream and re-reads the record when the run ends', async () => {
    api.getExecution.mockResolvedValue({
      execution: execution({
        status: 'succeeded',
        nodes: {
          n_one: { status: 'succeeded' },
          n_two: { status: 'succeeded', cost: { provider_instance_id: 'inst_main' } },
        },
      }),
    })
    const host = mountLive()
    host.vm.live.attach(execution())
    const source = FakeEventSource.latest()
    source.send(frame({ node_id: null, status: 'succeeded' }))
    await Promise.resolve()
    await Promise.resolve()

    expect(source.close).toHaveBeenCalled()
    // Cost and outputs are on the record, not in every frame — the follow-up
    // read is what lets the inspector name the provider that ran.
    expect(api.getExecution).toHaveBeenCalledWith('ex_LIVE01')
    expect(unref(host.vm.live.records).n_two.cost.provider_instance_id).toBe('inst_main')
  })

  it('detaches without leaving a stream open', () => {
    const host = mountLive()
    host.vm.live.attach(execution())
    const source = FakeEventSource.latest()
    host.vm.live.detach()
    expect(source.close).toHaveBeenCalled()
    expect(unref(host.vm.live.records)).toEqual({})
    expect(unref(host.vm.live.executionId)).toBe('')
  })
})

/**
 * Step 6.6 — the prototype's `sch-*` family, and the rule that keeps it honest:
 * every card, edge and state on screen is still the backend's answer.
 *
 * The prototype hardcodes one graph with fixed positions, roles and accents.
 * Nothing here does. The registry says what a node *is*, the workflow document
 * says which nodes exist, the projection says which stage claims them, and the
 * execution record says what state they are in — so the same stylesheet draws
 * whatever the backend happens to return.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

import SchemaPage from '../SchemaPage.vue'
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
  listFailedJobs: vi.fn(),
  listJobs: vi.fn(),
  testJobNode: vi.fn(),
  runWorkflow: vi.fn(),
}))

/**
 * A registry with a branching node in it, so `role-branch` is exercised by the
 * registry's own `conditional` output flag rather than by a type name.
 */
const REGISTRY = {
  registry_version: 5,
  categories: {
    input: { label: 'Input', color: '#4ECDC4' },
    audio: { label: 'Audio', color: '#A78BFA' },
    utility: { label: 'Utility', color: '#9CA3AF' },
  },
  node_types: {
    'demo.start': { display_name: 'Start', category: 'input', icon: 'play' },
    'demo.speak': {
      display_name: 'Speak',
      category: 'audio',
      icon: 'mic',
      config_schema: [{ name: 'provider', type: 'provider', provider_domain: 'tts' }],
    },
    'demo.branch': {
      display_name: 'Condition',
      category: 'utility',
      icon: 'git-branch',
      outputs: [
        { id: 'true', type: 'generic_json', conditional: true },
        { id: 'false', type: 'generic_json', conditional: true },
      ],
    },
    'demo.finish': { display_name: 'Finish', category: 'utility', icon: 'flag' },
  },
}

const WORKFLOW = {
  workflow_id: 'wf_FID001',
  name: 'Fidelity',
  nodes: [
    { id: 'n_start', type: 'demo.start', name: 'Start', position: { x: 0, y: 80 } },
    {
      id: 'n_speak',
      type: 'demo.speak',
      name: 'Narrate',
      position: { x: 200, y: 80 },
      configuration: { remove_silence: true, speed: 1.2 },
    },
    { id: 'n_pick', type: 'demo.branch', name: 'Route', position: { x: 400, y: 80 } },
    { id: 'n_end', type: 'demo.finish', name: 'Output', position: { x: 600, y: 80 } },
  ],
  edges: [
    { id: 'e1', source_node: 'n_start', target_node: 'n_speak', edge_type: 'data' },
    { id: 'e2', source_node: 'n_speak', target_node: 'n_pick', edge_type: 'data' },
    { id: 'e3', source_node: 'n_pick', target_node: 'n_end', edge_type: 'data' },
  ],
}

const PROJECTION = {
  projection: {
    workflow_id: 'wf_FID001',
    stages: [
      { key: 'script', label: 'Script', ordinal: 0, node_ids: ['n_start'] },
      { key: 'voice', label: 'Voice', ordinal: 1, node_ids: ['n_speak'] },
    ],
  },
}

/** One run touching every state the prototype styles. */
function execution(overrides = {}) {
  return {
    execution_id: 'ex_FID001',
    workflow_id: 'wf_FID001',
    status: 'running',
    workflow_snapshot: WORKFLOW,
    nodes: {
      n_start: { status: 'succeeded' },
      n_speak: { status: 'running' },
      n_pick: { status: 'skipped' },
    },
    ...overrides,
  }
}

class FakeEventSource {
  constructor(url) {
    this.url = url
    this.close = vi.fn()
    this.onmessage = null
    this.onerror = null
  }
}

function readSource(relative) {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')
}

async function mountPage(path = '/schema') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/schema', name: 'schema', component: SchemaPage }],
  })
  const pinia = createPinia()
  setActivePinia(pinia)
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SchemaPage, { global: { plugins: [router, pinia] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  globalThis.EventSource = FakeEventSource
  api.getNodeTypes.mockResolvedValue(REGISTRY)
  api.listWorkflows.mockResolvedValue({ workflows: [{ workflow_id: 'wf_FID001', name: 'Fidelity' }] })
  api.getWorkflow.mockResolvedValue({ workflow: WORKFLOW })
  api.getWorkflowStages.mockResolvedValue(PROJECTION)
  api.listTemplates.mockResolvedValue({ templates: [] })
  api.projectWorkflowBody.mockResolvedValue(PROJECTION)
  api.listExecutions.mockResolvedValue({ executions: [{ execution_id: 'ex_FID001', status: 'running' }] })
  api.getExecution.mockResolvedValue({ execution: execution() })
  api.getExecutionStages.mockResolvedValue(PROJECTION)
  api.listFailedJobs.mockResolvedValue({ jobs: [] })
  api.listJobs.mockResolvedValue({ jobs: [], total: 0 })
  api.getJob.mockResolvedValue({ job: {} })
})

describe('schema fidelity (step 6.6)', () => {
  it('draws the prototype topbar, canvas and status legend', async () => {
    const wrapper = await mountPage()

    expect(wrapper.find('.schema-view').exists()).toBe(true)
    expect(wrapper.find('.sch-topbar .sch-title h1').text()).toBe('Workflow Schema')
    expect(wrapper.find('.sch-title svg').exists()).toBe(true)
    expect(wrapper.find('.sch-sub').text()).toBe('Read-only overview · nodes animate live as a job runs')
    expect(wrapper.find('.sch-topbar .spacer').exists()).toBe(true)
    expect(wrapper.find('.sch-live').exists()).toBe(true)
    expect(wrapper.find('.sch-pause').text()).toContain('Freeze view')
    expect(wrapper.findAll('.sch-zoom .sch-zbtn')).toHaveLength(3)

    expect(wrapper.find('.sch-canvas .sch-world .sch-edges').exists()).toBe(true)
    expect(wrapper.find('.sch-canvas .sch-world .sch-nodes').exists()).toBe(true)

    // The legend is the prototype's five states, in its order.
    expect(wrapper.findAll('.sch-legend .sl').map((s) => s.text())).toEqual([
      'Pending', 'Active', 'Done', 'Failed', 'Skipped',
    ])
    expect(wrapper.findAll('.sch-legend .sd').map((d) => d.classes()[1])).toEqual([
      'd-pending', 'd-active', 'd-done', 'd-failed', 'd-skip',
    ])
  })

  it('builds each card from the prototype parts, and none of it from a table', async () => {
    const wrapper = await mountPage()
    const card = wrapper.find('[data-node-id="n_start"]')

    expect(card.find('.sch-ic').exists()).toBe(true)
    expect(card.find('.sch-nt .nm').text()).toBe('Start')
    // The subtitle is the projection's stage label, not a string in this repo.
    expect(card.find('.sch-nt .sb').text()).toBe('Script')
    expect(card.find('.sch-io.in').exists()).toBe(true)
    expect(card.find('.sch-io.out').exists()).toBe(true)
    expect(card.find('.sch-state').exists()).toBe(true)
    // The category colour is the registry's, carried onto the icon plate.
    expect(card.attributes('style')).toContain('#4ECDC4')
  })

  it('roles a card from the registry, never from its type name', async () => {
    const wrapper = await mountPage()

    // Claimed by a stage.
    expect(wrapper.find('[data-node-id="n_start"]').classes()).toContain('role-stage')
    // Claimed by nothing: graph infrastructure.
    expect(wrapper.find('[data-node-id="n_end"]').classes()).toContain('role-flow')
    // Declares conditional outputs, so it routes control.
    expect(wrapper.find('[data-node-id="n_pick"]').classes()).toContain('role-branch')
  })

  it('paints the prototype status treatments and their corner pill', async () => {
    const wrapper = await mountPage('/schema?run=ex_FID001')

    const done = wrapper.find('[data-node-id="n_start"]')
    expect(done.classes()).toContain('s-done')
    expect(done.find('.sch-state').classes()).toContain('s-done')
    expect(done.find('.sch-state').text()).toBe('✓')

    const active = wrapper.find('[data-node-id="n_speak"]')
    expect(active.classes()).toContain('s-active')
    // The percent is the run's — the engine has no per-node progress. Two of
    // the four cards have settled, so the graph is half done.
    expect(active.find('.sch-state').text()).toBe('50%')

    const skipped = wrapper.find('[data-node-id="n_pick"]')
    expect(skipped.classes()).toContain('s-skip')
    expect(skipped.find('.sch-state').text()).toBe('skip')

    // Not reached by this run, and the pill has nothing to say about it.
    const pending = wrapper.find('[data-node-id="n_end"]')
    expect(pending.classes()).toContain('s-pending')
    expect(pending.find('.sch-state').text()).toBe('')
  })

  it('animates only the edge work is crossing, and reddens a failure', async () => {
    const wrapper = await mountPage('/schema?run=ex_FID001')
    const edges = wrapper.findAll('.sch-edge')

    expect(edges[0].classes()).toEqual(expect.arrayContaining(['e-done', 'e-active']))
    expect(edges[1].classes()).not.toContain('e-active')

    api.getExecution.mockResolvedValue({
      execution: execution({
        status: 'failed',
        nodes: {
          n_start: { status: 'succeeded' },
          n_speak: { status: 'failed', error: { code: 'VOICE_TIMEOUT', message: 'Provider timed out' } },
        },
      }),
    })
    const failed = await mountPage('/schema?run=ex_FID001')
    expect(failed.findAll('.sch-edge')[0].classes()).toContain('e-fail')
  })

  it('tags the narration settings the way the prototype does', async () => {
    const wrapper = await mountPage()
    const tags = wrapper.find('[data-node-id="n_speak"] .sch-tags')

    expect(tags.exists()).toBe(true)
    // Trim is a glyph; speed is the warn-toned chip.
    expect(tags.findAll('.sch-tag')).toHaveLength(2)
    expect(tags.find('.sch-tag.chip').text()).toBe('1.2×')
    // A card the registry gives no TTS domain carries no tag group at all.
    expect(wrapper.find('[data-node-id="n_end"] .sch-tags').exists()).toBe(false)
  })

  it('tooltips the failing card with the engine’s code and message', async () => {
    api.getExecution.mockResolvedValue({
      execution: execution({
        status: 'failed',
        nodes: {
          n_speak: { status: 'failed', error: { code: 'VOICE_TIMEOUT', message: 'Provider timed out' } },
        },
      }),
    })
    const wrapper = await mountPage('/schema?run=ex_FID001')

    const tip = wrapper.find('[data-node-id="n_speak"] .sch-node-err')
    expect(tip.classes()).toContain('show')
    expect(tip.find('.ne-h').text()).toContain('Narrate')
    expect(tip.find('.ne-msg').text()).toBe('Provider timed out')
    expect(tip.find('.ne-code').text()).toBe('VOICE_TIMEOUT')

    // Every other card keeps its tooltip hidden rather than absent.
    expect(wrapper.find('[data-node-id="n_end"] .sch-node-err').classes()).not.toContain('show')
  })

  it('opens the prototype error panel on the failure', async () => {
    api.getExecution.mockResolvedValue({
      execution: execution({
        status: 'failed',
        nodes: {
          n_speak: { status: 'failed', error: { code: 'VOICE_TIMEOUT', message: 'Provider timed out' } },
        },
      }),
    })
    const wrapper = await mountPage('/schema?run=ex_FID001')

    const panel = wrapper.find('.sch-err')
    expect(panel.classes()).toContain('show')
    expect(panel.find('.se-head .se-ic').exists()).toBe(true)
    expect(panel.find('.se-t .se-node').text()).toBe('Narrate')
    expect(panel.findAll('.se-body .se-row .k').map((k) => k.text())).toEqual([
      'Node', 'Stage', 'Job',
    ])
    expect(panel.find('.se-why').text()).toBe('Provider timed out')
    expect(panel.find('.se-code').text()).toBe('VOICE_TIMEOUT')
    expect(panel.findAll('.se-foot .btn')).toHaveLength(2)
  })

  it('opens the prototype inspector, coloured but never as markup', async () => {
    api.getExecution.mockResolvedValue({
      execution: execution({
        nodes: {
          n_speak: {
            status: 'running',
            resolved_inputs_summary: { text: 'Once upon a time', takes: 2 },
          },
        },
      }),
    })
    const wrapper = await mountPage('/schema?run=ex_FID001')

    // Mounted and hidden until a card is picked, exactly as the prototype does.
    expect(wrapper.find('.sch-inspect').classes()).not.toContain('show')

    const card = wrapper.find('[data-node-id="n_speak"]')
    await card.trigger('mousedown', { button: 0, clientX: 40, clientY: 40 })
    window.dispatchEvent(new MouseEvent('mouseup'))
    await flushPromises()

    const panel = wrapper.find('.sch-inspect')
    expect(panel.classes()).toContain('show')
    expect(card.classes()).toContain('picked')
    expect(panel.find('.si-head .si-ic').exists()).toBe(true)
    expect(panel.find('.si-t .nm').text()).toBe('Narrate')
    expect(panel.find('.si-badge').classes()).toContain('s-active')
    expect(panel.find('.si-x').exists()).toBe(true)
    expect(panel.find('.si-h.in .arrow').exists()).toBe(true)

    // Summaries are coloured by rendered elements, and the text survives intact.
    const pane = panel.find('.si-sec pre')
    expect(pane.find('.k').text()).toBe('"text":')
    expect(pane.find('.s').text()).toBe('"Once upon a time"')
    expect(pane.find('.n').text()).toBe('2')
    expect(pane.text()).toContain('Once upon a time')
  })

  it('holds no node, stage or accent of its own', () => {
    for (const file of ['../SchemaPage.vue', '../components/SchemaCanvas.vue', '../graph.js']) {
      const source = readSource(file)
      // The prototype hardcodes per-node accents; nothing here may.
      expect(source).not.toMatch(/#[0-9a-fA-F]{6}\s*['"]?\s*[,}]/)
      expect(source).not.toContain('demo.speak')
    }
  })
})

/**
 * Step 1.2 — the Schema graph, projected from the engine.
 *
 * Done when: the graph renders from the registry, all navigation and realign
 * actions work, and no frontend file contains a hardcoded node or edge list.
 *
 * Guards:
 * - Every card and edge on screen came from a backend response; change the
 *   response and the picture changes with it
 * - Stage labels come from the stage projection, and a projection failure
 *   degrades to categories instead of blanking the canvas
 * - Realign is cosmetic: it never issues a write
 * - Schema starts nothing — no run, save or delete endpoint is reachable here
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

import SchemaPage from '../SchemaPage.vue'
import SchemaCanvas from '../components/SchemaCanvas.vue'
import SchemaContextMenu from '../components/SchemaContextMenu.vue'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
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
  testJobNode: vi.fn(),
  runWorkflow: vi.fn(),
}))

const REGISTRY = {
  registry_version: 5,
  categories: {
    input: { label: 'Input', color: '#4ECDC4' },
    audio: { label: 'Audio', color: '#A78BFA' },
    utility: { label: 'Utility', color: '#9CA3AF' },
  },
  node_types: {
    'demo.start': { display_name: 'Start', category: 'input', icon: 'play' },
    'demo.speak': { display_name: 'Speak', category: 'audio', icon: 'mic' },
    'demo.finish': { display_name: 'Finish', category: 'utility', icon: 'flag' },
  },
}

const WORKFLOW = {
  workflow_id: 'wf_AAA111',
  name: 'Demo',
  nodes: [
    { id: 'n_start', type: 'demo.start', name: 'Start', position: { x: 0, y: 80 } },
    { id: 'n_speak', type: 'demo.speak', name: 'Narrate', position: { x: 240, y: 80 } },
    { id: 'n_end', type: 'demo.finish', name: 'Output', position: { x: 480, y: 80 } },
  ],
  edges: [
    { id: 'e1', source_node: 'n_start', target_node: 'n_speak', edge_type: 'data' },
    { id: 'e2', source_node: 'n_speak', target_node: 'n_end', edge_type: 'data' },
  ],
}

const PROJECTION = {
  projection: {
    workflow_id: 'wf_AAA111',
    stages: [
      { key: 'script', label: 'Script', ordinal: 0, node_ids: ['n_start'] },
      { key: 'voice', label: 'Voice', ordinal: 1, node_ids: ['n_speak'] },
    ],
  },
}

/**
 * Read one of this feature's source files.
 *
 * The path goes through a parameter on purpose: Vite rewrites a *literal*
 * `new URL('./x', import.meta.url)` into an asset URL, which is no longer a
 * file path by the time `fileURLToPath` sees it.
 */
function readSource(relative) {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')
}

/** A run of the same graph: the snapshot is what a run is drawn from. */
function execution(overrides = {}) {
  return {
    execution_id: 'ex_LIVE01',
    workflow_id: 'wf_AAA111',
    status: 'running',
    workflow_snapshot: WORKFLOW,
    nodes: {
      n_start: { status: 'succeeded', artifact_refs: ['demo/one'] },
      n_speak: { status: 'running' },
    },
    ...overrides,
  }
}

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

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/schema', name: 'schema', component: SchemaPage },
    ],
  })
}

async function mountPage(path = '/schema') {
  const router = makeRouter()
  const pinia = createPinia()
  setActivePinia(pinia)
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SchemaPage, { global: { plugins: [router, pinia] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  FakeEventSource.reset()
  globalThis.EventSource = FakeEventSource
  api.getNodeTypes.mockResolvedValue(REGISTRY)
  api.listWorkflows.mockResolvedValue({ workflows: [{ workflow_id: 'wf_AAA111', name: 'Demo' }] })
  api.getWorkflow.mockResolvedValue({ workflow: WORKFLOW })
  api.getWorkflowStages.mockResolvedValue(PROJECTION)
  api.listTemplates.mockResolvedValue({ templates: [] })
  api.projectWorkflowBody.mockResolvedValue(PROJECTION)
  api.listExecutions.mockResolvedValue({ executions: [{ execution_id: 'ex_LIVE01', status: 'running' }] })
  api.getExecution.mockResolvedValue({ execution: execution() })
  api.getExecutionStages.mockResolvedValue(PROJECTION)
  api.getJob.mockResolvedValue({
    job: {
      id: 'job_AAA111',
      workflow_id: 'wf_AAA111',
      execution_id: 'ex_LIVE01',
      current_stage: 'voice',
      status: 'running',
    },
  })
  api.listFailedJobs.mockResolvedValue({ jobs: [] })
  api.testJobNode.mockResolvedValue({ execution_id: 'ex_TEST01', status: 'queued' })
  api.runWorkflow.mockResolvedValue({ execution_id: 'ex_RETRY1', status: 'queued' })
})

describe('Schema graph (step 1.2)', () => {
  it('renders one card per node the backend returned', async () => {
    const { wrapper } = await mountPage()
    const cards = wrapper.findAll('.sch-node')
    expect(cards).toHaveLength(3)
    expect(cards.map((c) => c.attributes('data-node-id'))).toEqual(['n_start', 'n_speak', 'n_end'])
    expect(cards[1].text()).toContain('Narrate')
  })

  it('renders one path per edge the backend returned', async () => {
    const { wrapper } = await mountPage()
    const paths = wrapper.findAll('.sch-edge')
    expect(paths).toHaveLength(2)
    for (const path of paths) {
      expect(path.attributes('d')).toMatch(/^M [\d.-]+ [\d.-]+ C /)
    }
  })

  it('follows the backend rather than a list of its own', async () => {
    // A completely different graph, with a node type nothing in the frontend
    // has ever heard of, must render just as faithfully.
    api.getWorkflow.mockResolvedValue({
      workflow: {
        workflow_id: 'wf_AAA111',
        nodes: [{ id: 'n_only', type: 'invented.thing', name: 'Invented', position: { x: 10, y: 10 } }],
        edges: [],
      },
    })
    api.getWorkflowStages.mockResolvedValue({ projection: { stages: [] } })
    const { wrapper } = await mountPage()
    const cards = wrapper.findAll('.sch-node')
    expect(cards).toHaveLength(1)
    expect(cards[0].text()).toContain('Invented')
    expect(wrapper.findAll('.sch-edge')).toHaveLength(0)
  })

  it('labels cards with the stage the projection assigned', async () => {
    const { wrapper } = await mountPage()
    const cards = wrapper.findAll('.sch-node')
    expect(cards[0].attributes('data-stage')).toBe('script')
    expect(cards[0].text()).toContain('Script')
    expect(cards[1].attributes('data-stage')).toBe('voice')
    // Claimed by no stage: infrastructure, drawn dashed, never named a step.
    expect(cards[2].attributes('data-stage')).toBe('')
    expect(cards[2].classes()).toContain('role-flow')
  })

  it('still draws the graph when stage projection fails', async () => {
    api.getWorkflowStages.mockRejectedValue(new Error('Workflow has no production stages'))
    const { wrapper } = await mountPage()
    expect(wrapper.findAll('.sch-node')).toHaveLength(3)
    expect(wrapper.text()).toContain('Stage projection unavailable')
  })

  it('falls back to a built-in template when nothing is saved', async () => {
    api.listWorkflows.mockResolvedValue({ workflows: [] })
    api.listTemplates.mockResolvedValue({
      templates: [{ template_id: 'full_video', workflow: { ...WORKFLOW, name: 'Full Video' } }],
    })
    const { wrapper } = await mountPage()
    expect(api.projectWorkflowBody).toHaveBeenCalled()
    expect(wrapper.findAll('.sch-node')).toHaveLength(3)
    expect(wrapper.text()).toContain('built-in template')
  })

  it('reports an unreachable registry instead of throwing', async () => {
    api.getNodeTypes.mockRejectedValue(new Error('Registry unavailable'))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('Registry unavailable')
    expect(wrapper.findAll('.sch-node')).toHaveLength(0)
  })

  it('opens the workflow named by the deep link', async () => {
    api.listWorkflows.mockResolvedValue({
      workflows: [
        { workflow_id: 'wf_AAA111', name: 'Demo' },
        { workflow_id: 'wf_BBB222', name: 'Other' },
      ],
    })
    const router = makeRouter()
    await router.push('/schema?workflow=wf_BBB222')
    await router.isReady()
    mount(SchemaPage, { global: { plugins: [router] } })
    await flushPromises()
    expect(api.getWorkflow).toHaveBeenCalledWith('wf_BBB222')
  })
})

describe('Schema navigation and realign (step 1.2)', () => {
  it('pans on a two-finger scroll', async () => {
    const { wrapper } = await mountPage()
    const canvas = wrapper.findComponent(SchemaCanvas)
    canvas.vm.view.zoom = 1
    const before = { ...canvas.vm.view }
    await wrapper.find('.sch-canvas').trigger('wheel', { deltaX: 40, deltaY: 25 })
    expect(canvas.vm.view.panX).toBe(before.panX - 40)
    expect(canvas.vm.view.panY).toBe(before.panY - 25)
    expect(canvas.vm.view.zoom).toBe(before.zoom)
  })

  it('zooms on Ctrl+wheel instead of panning', async () => {
    const { wrapper } = await mountPage()
    const canvas = wrapper.findComponent(SchemaCanvas)
    const before = canvas.vm.view.zoom
    // `ctrlKey` is read-only on a MouseEvent, so this one needs a real event
    // rather than test-utils' property assignment.
    wrapper.find('.sch-canvas').element.dispatchEvent(new WheelEvent('wheel', {
      deltaY: -40,
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    }))
    await flushPromises()
    expect(canvas.vm.view.zoom).toBeGreaterThan(before)
  })

  it('drives zoom in, zoom out and fit from the topbar', async () => {
    const { wrapper } = await mountPage()
    const canvas = wrapper.findComponent(SchemaCanvas)
    const buttons = wrapper.findAll('.sch-zbtn')
    expect(buttons).toHaveLength(3)
    const start = canvas.vm.view.zoom
    await buttons[2].trigger('click')
    expect(canvas.vm.view.zoom).toBeGreaterThan(start)
    await buttons[0].trigger('click')
    expect(canvas.vm.view.zoom).toBeCloseTo(start, 5)
    await buttons[1].trigger('click')
    expect(Number.isFinite(canvas.vm.view.zoom)).toBe(true)
  })

  it('drags a card to a new position without changing the graph', async () => {
    const { wrapper } = await mountPage()
    const canvas = wrapper.findComponent(SchemaCanvas)
    const card = wrapper.findAll('.sch-node')[1]
    await card.trigger('mousedown', { button: 0, clientX: 100, clientY: 100 })
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 160, clientY: 130 }))
    window.dispatchEvent(new MouseEvent('mouseup'))
    await flushPromises()
    expect(canvas.vm.positions.n_speak).toEqual({ x: 300, y: 110 })
    // Structure is untouched: same cards, same edges, no write.
    expect(wrapper.findAll('.sch-node')).toHaveLength(3)
    expect(wrapper.findAll('.sch-edge')).toHaveLength(2)
  })

  it('offers the realign menu on right-click and auto-aligns from it', async () => {
    const { wrapper } = await mountPage()
    const canvas = wrapper.findComponent(SchemaCanvas)
    canvas.vm.positions.n_start = { x: 900, y: 900 }
    await wrapper.find('.sch-canvas').trigger('contextmenu')
    const menu = wrapper.findComponent(SchemaContextMenu)
    expect(menu.props('open')).toBe(true)
    const labels = menu.findAll('.ctx-item').map((item) => item.text())
    expect(labels).toEqual([
      'Auto-align layout',
      'Snap all to grid',
      'Reset positions',
      'Fit & centre view',
    ])
    await menu.findAll('.ctx-item')[0].trigger('click')
    await flushPromises()
    expect(canvas.vm.positions.n_start.x).toBeLessThan(canvas.vm.positions.n_speak.x)
    expect(menu.props('open')).toBe(false)
  })

  it('adds the per-node entries when the menu opens on a card', async () => {
    const { wrapper } = await mountPage()
    await wrapper.findAll('.sch-node')[0].trigger('contextmenu')
    const labels = wrapper.findComponent(SchemaContextMenu).findAll('.ctx-item').map((i) => i.text())
    expect(labels.slice(0, 2)).toEqual(['Center on node', 'Reset this node'])
  })

  it('snaps to the grid and resets back to the authored layout', async () => {
    const { wrapper } = await mountPage()
    const canvas = wrapper.findComponent(SchemaCanvas)
    canvas.vm.positions = { ...canvas.vm.positions, n_start: { x: 33, y: 47 } }
    canvas.vm.onMenuSelect({ action: 'snap-grid', nodeId: null })
    expect(canvas.vm.positions.n_start).toEqual({ x: 40, y: 40 })
    canvas.vm.onMenuSelect({ action: 'reset-layout', nodeId: null })
    expect(canvas.vm.positions.n_start).toEqual({ x: 0, y: 80 })
  })

  it('resets and centres a single node', async () => {
    const { wrapper } = await mountPage()
    const canvas = wrapper.findComponent(SchemaCanvas)
    canvas.vm.positions = { ...canvas.vm.positions, n_end: { x: 5, y: 5 } }
    canvas.vm.onMenuSelect({ action: 'reset-node', nodeId: 'n_end' })
    expect(canvas.vm.positions.n_end).toEqual({ x: 480, y: 80 })
    canvas.vm.onMenuSelect({ action: 'center-node', nodeId: 'n_end' })
    expect(Number.isFinite(canvas.vm.view.panX)).toBe(true)
  })

  it('never writes while realigning — positions are cosmetic', async () => {
    const { wrapper } = await mountPage()
    const canvas = wrapper.findComponent(SchemaCanvas)
    for (const action of ['auto-align', 'snap-grid', 'reset-layout', 'fit']) {
      canvas.vm.onMenuSelect({ action, nodeId: null })
    }
    await flushPromises()
    expect(api.getWorkflow).toHaveBeenCalledTimes(1)
    expect(api.getWorkflowStages).toHaveBeenCalledTimes(1)
  })

  it('exposes only the projector and explicit step 1.4 node actions as writes', () => {
    // Read the real client, not the mock: the mock is whatever this file says
    // it is, and the guarantee is about the shipped module. Schema watches the
    // engine, so every call it can make is a GET — apart from the projector,
    // which computes a projection for an unsaved template and stores nothing.
    const source = readSource('../api.js')
    const posts = [...source.matchAll(/apiPost\(\s*'([^']+)'/g)].map((m) => m[1])
    expect(posts).toEqual(['/workflow/stages', '/workflow/run'])
    expect(source).toContain('/test-node')
    expect(source).not.toMatch(/apiPut|apiDelete/)
    // The endpoints that would start, stop or approve a run.
    for (const forbidden of ['/stop', '/approve', '/reject']) {
      expect(source, `api.js reaches ${forbidden}`).not.toContain(forbidden)
    }
  })
})

describe('the running job on the graph (step 1.3)', () => {
  async function mountLivePage(path = '/schema?run=ex_LIVE01') {
    const mounted = await mountPage(path)
    await flushPromises()
    return mounted
  }

  it('draws the run from its snapshot and reflects each node', async () => {
    const { wrapper } = await mountLivePage()
    expect(api.getExecution).toHaveBeenCalledWith('ex_LIVE01')
    const cards = wrapper.findAll('.sch-node')
    expect(cards[0].attributes('data-visual')).toBe('done')
    expect(cards[1].attributes('data-visual')).toBe('active')
    // Not reached by this run: pending, not missing.
    expect(cards[2].attributes('data-visual')).toBe('pending')
  })

  it('still asks the registry what a run’s nodes are', async () => {
    const { wrapper } = await mountLivePage()
    expect(api.getNodeTypes).toHaveBeenCalled()
    // Stage labels and category colours come from the registry and the
    // projection; arriving by run deep link must not cost a card its identity.
    const first = wrapper.findAll('.sch-node')[0]
    expect(first.attributes('data-stage')).toBe('script')
    expect(first.text()).toContain('Script')
  })

  it('flows the edges arriving at whatever is running', async () => {
    const { wrapper } = await mountLivePage()
    const edges = wrapper.findAll('.sch-edge')
    expect(edges[0].classes()).toContain('flowing')
    expect(edges[1].classes()).not.toContain('flowing')
  })

  it('shows job, stage and percent on the pill', async () => {
    const { wrapper } = await mountLivePage('/schema?job=job_AAA111')
    const pill = wrapper.find('.sch-live-pill')
    expect(pill.exists()).toBe(true)
    expect(pill.text()).toContain('Job job_AAA111')
    // Stage named by the projection, and the percent of the graph settled.
    expect(pill.text()).toContain('Voice')
    expect(pill.text()).toContain('33%')
  })

  it('animates as the run advances', async () => {
    const { wrapper } = await mountLivePage()
    FakeEventSource.latest().send({
      sequence: 1,
      execution_id: 'ex_LIVE01',
      node_id: 'n_speak',
      status: 'succeeded',
    })
    await flushPromises()
    expect(wrapper.findAll('.sch-node')[1].attributes('data-visual')).toBe('done')
    expect(wrapper.find('.sch-live-pill').text()).toContain('67%')
  })

  it('opens the inspector on a card and keeps it in sync', async () => {
    api.getExecution.mockResolvedValue({
      execution: execution({
        nodes: {
          n_start: { status: 'succeeded' },
          n_speak: {
            status: 'running',
            resolved_inputs_summary: { text: 'Once upon a time' },
            cost: { provider_instance_id: 'inst_main', selection_reason: 'default' },
          },
        },
      }),
    })
    const { wrapper } = await mountLivePage()
    const card = wrapper.findAll('.sch-node')[1]
    await card.trigger('mousedown', { button: 0, clientX: 50, clientY: 50 })
    window.dispatchEvent(new MouseEvent('mouseup'))
    await flushPromises()

    const panel = wrapper.find('.sch-inspector')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('Narrate')
    expect(panel.text()).toContain('Running')
    // The resolved provider is an instance reference — never a credential.
    expect(panel.text()).toContain('inst_main')
    expect(panel.text()).toContain('Once upon a time')

    FakeEventSource.latest().send({
      sequence: 1,
      execution_id: 'ex_LIVE01',
      node_id: 'n_speak',
      status: 'failed',
      error: { code: 'PROVIDER_FAILED', message: 'upstream refused' },
    })
    await flushPromises()
    expect(wrapper.find('.sch-inspector').text()).toContain('PROVIDER_FAILED')
    expect(wrapper.find('.sch-inspector').text()).toContain('upstream refused')
    expect(wrapper.find('.si-sec.err').element.children[1].className).toBe('si-err-msg')
    expect(wrapper.find('.si-sec.err').element.children[2].className).toBe('si-err-code')
  })

  it('freezes the view without touching the job', async () => {
    const { wrapper } = await mountLivePage()
    await wrapper.find('.sch-zbtn.freeze').trigger('click')
    await flushPromises()

    const source = FakeEventSource.latest()
    source.send({ sequence: 1, execution_id: 'ex_LIVE01', node_id: 'n_speak', status: 'succeeded' })
    await flushPromises()

    // The picture is held still...
    expect(wrapper.findAll('.sch-node')[1].attributes('data-visual')).toBe('active')
    // ...and the run was never asked to stop: the stream is still open, and
    // the badge counts what is waiting behind the freeze.
    expect(source.close).not.toHaveBeenCalled()
    expect(wrapper.find('.sch-zbtn.freeze').text()).toContain('Frozen · 1')
    expect(wrapper.text()).toContain('the job is still running')

    await wrapper.find('.sch-zbtn.freeze').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.sch-node')[1].attributes('data-visual')).toBe('done')
  })

  it('paints nothing live until a run is bound', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.find('.sch-live-pill').exists()).toBe(false)
    expect(wrapper.find('.sch-zbtn.freeze').exists()).toBe(false)
    for (const card of wrapper.findAll('.sch-node')) {
      expect(card.attributes('data-visual')).toBe('pending')
    }
  })
})

describe('Schema node actions and failure navigation (step 1.4)', () => {
  function providerRegistry() {
    return {
      ...REGISTRY,
      node_types: {
        ...REGISTRY.node_types,
        'demo.speak': {
          ...REGISTRY.node_types['demo.speak'],
          inputs: [{ id: 'text', type: 'text', required: true }],
          config_schema: [
            { name: 'provider_id', type: 'provider', provider_domain: 'voice' },
          ],
        },
      },
    }
  }

  function seedProviderCatalog() {
    const catalog = useProviderCatalogStore()
    catalog.catalogVersion = 1
    catalog.domains = {
      voice: {
        label: 'Voice',
        providers: [
          { id: 'voice_type', label: 'Voice Type', availability: 'available', aliases: [] },
        ],
        instances: [
          { instance_id: 'inst_main', provider_type: 'voice_type', label: 'Main', availability: 'available' },
          { instance_id: 'inst_alt', provider_type: 'voice_type', label: 'Alternate', availability: 'available' },
        ],
        excluded: [],
      },
    }
  }

  async function clickNode(wrapper, index = 1) {
    const card = wrapper.findAll('.sch-node')[index]
    await card.trigger('mousedown', { button: 0, clientX: 50, clientY: 50 })
    window.dispatchEvent(new MouseEvent('mouseup'))
    await flushPromises()
  }

  it('tests from the inspector with input bindings and a one-shot provider override', async () => {
    api.getNodeTypes.mockResolvedValue(providerRegistry())
    api.getExecution.mockResolvedValue({
      execution: execution({
        nodes: {
          n_start: { status: 'succeeded' },
          n_speak: {
            status: 'running',
            cost: { provider_instance_id: 'inst_main', selection_reason: 'default' },
          },
        },
      }),
    })
    api.testJobNode.mockResolvedValue({
      execution_id: 'ex_TEST01',
      status: 'succeeded',
      provider_instance_id: 'inst_alt',
      execution: {
        execution_id: 'ex_TEST01',
        status: 'succeeded',
        nodes: {
          n_speak: {
            status: 'succeeded',
            outputs_summary: { audio: 'test.wav' },
            cost: { provider_instance_id: 'inst_alt', selection_reason: 'request' },
          },
        },
      },
    })

    const { wrapper } = await mountPage('/schema?job=job_AAA111')
    seedProviderCatalog()
    await clickNode(wrapper)
    await wrapper.findAll('.si-action').find((button) => button.text() === 'Test').trigger('click')
    await flushPromises()

    const picker = wrapper.find('.tn-provider-select')
    expect(picker.exists()).toBe(true)
    await picker.setValue('inst_alt')
    await wrapper.find('.tn-run').trigger('click')
    await flushPromises()

    expect(api.testJobNode).toHaveBeenCalledWith('job_AAA111', expect.objectContaining({
      target_node_ids: ['n_speak'],
      input_bindings: {
        n_speak: { text: { source: 'sample', port_type: 'text' } },
      },
      provider_instance_id: 'inst_alt',
      wait: true,
    }))
    expect(api.runWorkflow).not.toHaveBeenCalled()
    expect(wrapper.find('.tn-result').text()).toContain('inst_alt')
    expect(wrapper.find('.tn-result').text()).toContain('one-shot override')
    expect(wrapper.find('.tn-hint').text()).toContain('will not advance')
  })

  it('counts failed Jobs and locates a failed node from the badge in one click', async () => {
    api.listFailedJobs.mockResolvedValue({
      jobs: [
        { id: 'job_BAD001', status: 'failed', execution_id: 'ex_BAD001' },
        { id: 'job_BAD002', status: 'failed', execution_id: 'ex_BAD002' },
      ],
    })
    api.getJob.mockImplementation(async (id) => ({
      job: {
        id,
        workflow_id: 'wf_AAA111',
        execution_id: 'ex_BAD001',
        current_stage: 'voice',
        status: 'failed',
      },
    }))
    api.getExecution.mockImplementation(async (id) => ({
      execution: execution({
        execution_id: id,
        status: 'failed',
        nodes: {
          n_start: { status: 'succeeded' },
          n_speak: {
            status: 'failed',
            error: { code: 'VOICE_TIMEOUT', message: 'Provider timed out' },
          },
        },
      }),
    }))

    const { wrapper } = await mountPage()
    const badge = wrapper.find('.sch-errbadge')
    expect(badge.text()).toContain('2 errors')
    await badge.trigger('click')
    await flushPromises()

    const failedCard = wrapper.find('[data-node-id="n_speak"]')
    expect(failedCard.classes()).toContain('flash')
    expect(failedCard.text()).toContain('VOICE_TIMEOUT')
    expect(wrapper.find('.sch-error-panel').text()).toContain('Provider timed out')
    expect(wrapper.find('.sch-error-panel').text()).toContain('job_BAD001')
    expect(wrapper.find('.sch-inspector').text()).toContain('VOICE_TIMEOUT')
  })

  it('retries only the selected failed node through the engine', async () => {
    api.getExecution.mockImplementation(async (id) => ({
      execution: execution({
        execution_id: id,
        status: id === 'ex_RETRY1' ? 'queued' : 'failed',
        nodes: id === 'ex_RETRY1'
          ? { n_speak: { status: 'queued' } }
          : { n_speak: { status: 'failed', error: { code: 'FAILED', message: 'No audio' } } },
      }),
    }))
    const { wrapper } = await mountPage('/schema?run=ex_LIVE01')
    await clickNode(wrapper)
    await wrapper.findAll('.si-action').find((button) => button.text() === 'Retry').trigger('click')
    await flushPromises()

    expect(api.runWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      run_mode: 'retry_failed',
      target_node_ids: ['n_speak'],
    }))
  })
})

describe('no hardcoded structure (steps 1.2, 1.3)', () => {
  const SOURCES = [
    '../graph.js',
    '../live.js',
    '../api.js',
    '../SchemaPage.vue',
    '../components/SchemaCanvas.vue',
    '../components/SchemaContextMenu.vue',
    '../components/SchemaInspector.vue',
    '../composables/useSchemaGraph.js',
    '../composables/useSchemaCanvas.js',
    '../composables/useSchemaLive.js',
  ]

  /** Registry keys and stage names a hardcoded list would have to name. */
  const FORBIDDEN = [
    'trigger.manual', 'project.setup', 'script.input', 'tts.generate',
    'timing.align', 'segment.run', 'scenes.blueprint', 'storyboard.generate',
    'animator.generate', 'captions.generate', 'music.select',
    'assemble.project', 'timeline.project', 'export.video', 'workflow.output',
  ]

  it.each(SOURCES)('%s names no node type and no stage key', (relative) => {
    const source = readSource(relative)
    for (const key of FORBIDDEN) {
      expect(source, `${relative} hardcodes ${key}`).not.toContain(key)
    }
    // A stage catalog would have to spell the spine out somewhere.
    expect(source).not.toMatch(/['"]script['"]\s*,\s*['"]voice['"]/)
  })
})

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

import SchemaPage from '../SchemaPage.vue'
import SchemaCanvas from '../components/SchemaCanvas.vue'
import SchemaContextMenu from '../components/SchemaContextMenu.vue'
import * as api from '../api.js'

vi.mock('../api.js', () => ({
  getNodeTypes: vi.fn(),
  listWorkflows: vi.fn(),
  getWorkflow: vi.fn(),
  getWorkflowStages: vi.fn(),
  projectWorkflowBody: vi.fn(),
  listTemplates: vi.fn(),
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

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/schema', name: 'schema', component: SchemaPage },
    ],
  })
}

async function mountPage() {
  const router = makeRouter()
  await router.push('/schema')
  await router.isReady()
  const wrapper = mount(SchemaPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getNodeTypes.mockResolvedValue(REGISTRY)
  api.listWorkflows.mockResolvedValue({ workflows: [{ workflow_id: 'wf_AAA111', name: 'Demo' }] })
  api.getWorkflow.mockResolvedValue({ workflow: WORKFLOW })
  api.getWorkflowStages.mockResolvedValue(PROJECTION)
  api.listTemplates.mockResolvedValue({ templates: [] })
  api.projectWorkflowBody.mockResolvedValue(PROJECTION)
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
    // The only calls the whole view is allowed to make are the three reads.
    expect(api.getWorkflow).toHaveBeenCalledTimes(1)
    expect(api.getWorkflowStages).toHaveBeenCalledTimes(1)
    expect(Object.keys(api)).toEqual([
      'getNodeTypes',
      'listWorkflows',
      'getWorkflow',
      'getWorkflowStages',
      'projectWorkflowBody',
      'listTemplates',
    ])
  })
})

describe('no hardcoded structure (step 1.2)', () => {
  const SOURCES = [
    '../graph.js',
    '../api.js',
    '../SchemaPage.vue',
    '../components/SchemaCanvas.vue',
    '../components/SchemaContextMenu.vue',
    '../composables/useSchemaGraph.js',
    '../composables/useSchemaCanvas.js',
  ]

  /** Registry keys and stage names a hardcoded list would have to name. */
  const FORBIDDEN = [
    'trigger.manual', 'project.setup', 'script.input', 'tts.generate',
    'timing.align', 'segment.run', 'scenes.blueprint', 'storyboard.generate',
    'animator.generate', 'captions.generate', 'music.select',
    'assemble.project', 'timeline.project', 'export.video', 'workflow.output',
  ]

  it.each(SOURCES)('%s names no node type and no stage key', (relative) => {
    const source = readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')
    for (const key of FORBIDDEN) {
      expect(source, `${relative} hardcodes ${key}`).not.toContain(key)
    }
    // A stage catalog would have to spell the spine out somewhere.
    expect(source).not.toMatch(/['"]script['"]\s*,\s*['"]voice['"]/)
  })
})

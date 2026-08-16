/**
 * Step 13.3 — testing any node from the canvas, with a provider picker.
 *
 * The node context menu used to offer three run items that fired immediately:
 * no input choice, no provider choice, no way to see what the node was fed.
 * They are replaced by the Production Test Node panel, which already owns
 * per-port binding and, since 13.2, the one-shot provider override.
 */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'

const { contextNode, apiPost } = vi.hoisted(() => ({
  contextNode: { id: '' },
  apiPost: vi.fn(async () => ({ execution_id: 'ex_TEST01', status: 'queued' })),
}))

vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn() }))
vi.mock('@/shared/api/client.js', () => ({
  api: {
    get: vi.fn(async (path) =>
      path === '/api/workflows'
        ? { workflows: [] }
        : path === '/api/workflow/templates'
          ? { templates: [] }
          : {}),
    post: apiPost,
  },
}))

vi.mock('@vue-flow/core', () => ({
  MarkerType: { ArrowClosed: 'arrow' },
  useVueFlow: () => ({
    screenToFlowCoordinate: (point) => point,
    fitView: vi.fn(),
    setViewport: vi.fn(async () => {}),
    setNodes: vi.fn(),
  }),
  VueFlow: defineComponent({
    name: 'VueFlow',
    emits: ['nodeContextMenu'],
    setup(_props, { emit, slots }) {
      return () => h('div', { class: 'vue-flow__pane' }, [
        h('button', {
          class: 'emit-node-menu',
          onContextmenu: (event) => emit('nodeContextMenu', { event, node: { id: contextNode.id } }),
        }),
        slots.default?.(),
      ])
    },
  }),
}))
vi.mock('@vue-flow/background', () => ({ Background: defineComponent(() => () => h('div')) }))
vi.mock('@vue-flow/controls', () => ({ Controls: defineComponent(() => () => h('div')) }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: defineComponent(() => () => h('div')) }))

import WorkflowPage from '../views/WorkflowPage.vue'
import { useWorkflowStore } from '../stores/workflow.js'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'

class FakeEventSource {
  constructor(url) {
    this.url = url
    this.close = vi.fn()
  }
}

const TYPES = {
  'image.generate': {
    type: 'image.generate',
    type_version: 1,
    display_name: 'Image Generator',
    category: 'media',
    inputs: [{ id: 'scenes', type: 'scenes', required: true, multiple: false }],
    outputs: [{ id: 'images', type: 'storyboard_images' }],
    config_schema: [
      { name: 'provider_id', type: 'provider', provider_domain: 'image', default: 'alpha' },
    ],
  },
}

// Two configured instances of one type: exactly the shape 13.2 exists for.
const DOMAINS = {
  image: {
    label: 'Image',
    selected_instance_id: 'alpha',
    default_provider: 'alpha',
    capability_vocabulary: [],
    providers: [
      { id: 'alpha', label: 'Alpha', availability: 'available', capabilities: {}, aliases: [] },
    ],
    instances: [
      {
        instance_id: 'alpha', provider_type: 'alpha', label: 'Alpha',
        availability: 'available', selected: true,
      },
      {
        instance_id: 'beta', provider_type: 'alpha', label: 'Beta',
        availability: 'available', selected: false,
      },
    ],
    excluded: [],
  },
}

function seed() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = TYPES
  store.portTypes = ['scenes', 'storyboard_images']
  store.settings = { on_error: 'stop', auto_attach_stubs: false }
  const node = store.addNode('image.generate', { x: 0, y: 0 })
  store.clearCommandHistory()

  const catalog = useProviderCatalogStore()
  catalog.catalogVersion = 1
  catalog.domains = DOMAINS

  contextNode.id = node.id
  return { store, catalog, node }
}

function mountPage() {
  return mount(WorkflowPage, {
    global: {
      stubs: {
        NodeLibrary: true,
        NodeInspector: true,
        NodeCard: true,
        ExecutionPanel: true,
      },
    },
  })
}

describe('step 13.3 canvas Test Node', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    apiPost.mockClear()
    globalThis.EventSource = FakeEventSource
  })

  afterEach(() => {
    delete globalThis.EventSource
  })

  it('opens the test panel from the node context menu instead of running blind', async () => {
    seed()
    const wrapper = mountPage()
    await wrapper.find('.emit-node-menu').trigger('contextmenu')

    // The three items that fired immediately are gone; the toolbar run-mode
    // select still offers every mode they covered.
    const items = wrapper.findAll('.wf-context-item').map((button) => button.text())
    expect(items).not.toContain('Run node in isolation')
    expect(items).not.toContain('Run node + dependencies')
    expect(items).not.toContain('Run from node downstream')
    expect(items).toContain('Test node…')
    expect(wrapper.find('.wf-run-select').text()).toContain('Node in isolation')

    expect(wrapper.find('.test-node-panel').exists()).toBe(false)
    await wrapper.findAll('.wf-context-item').find((b) => b.text() === 'Test node…').trigger('click')
    await nextTick()

    const panel = wrapper.find('.test-node-panel')
    expect(panel.exists()).toBe(true)
    // One input picker per data port, and a provider picker naming both
    // instances of the domain.
    expect(panel.findAll('.input-picker').length).toBe(1)
    const options = panel.find('.tn-provider-select').findAll('option').map((o) => o.text().trim())
    expect(options[0]).toContain("Node's provider")
    expect(options).toContain('Alpha')
    expect(options).toContain('Beta')
    wrapper.unmount()
  })

  it('sends the picked instance as a one-shot override and leaves the node config alone', async () => {
    const { store, node } = seed()
    const savedConfiguration = JSON.parse(JSON.stringify(node.configuration))
    const wrapper = mountPage()
    await wrapper.find('.emit-node-menu').trigger('contextmenu')
    await wrapper.findAll('.wf-context-item').find((b) => b.text() === 'Test node…').trigger('click')
    await nextTick()

    const select = wrapper.find('.tn-provider-select')
    await select.setValue('beta')
    const dirtyBefore = store.dirty
    await wrapper.find('.tn-run').trigger('click')
    await vi.waitFor(() => expect(apiPost).toHaveBeenCalled())

    const [url, options] = apiPost.mock.calls.at(-1)
    expect(url).toBe('/api/workflow/run')
    expect(options.body.provider_instance_id).toBe('beta')
    expect(options.body.run_mode).toBe('node_isolated')
    expect(options.body.target_node_ids).toEqual([node.id])
    // A canvas test is bound to no Job, so it cannot advance one.
    expect(options.body.current_job_id).toBeUndefined()
    // The override is a question, not an edit: no config write, no new
    // undoable command, no change to the document's dirty state.
    expect(store.nodeById(node.id).configuration).toEqual(savedConfiguration)
    expect(store.dirty).toBe(dirtyBefore)
    expect(store.undoLabel).toBe('')
    wrapper.unmount()
  })

  it('omits the override entirely when the node keeps its own provider', async () => {
    const { node } = seed()
    const wrapper = mountPage()
    await wrapper.find('.emit-node-menu').trigger('contextmenu')
    await wrapper.findAll('.wf-context-item').find((b) => b.text() === 'Test node…').trigger('click')
    await nextTick()

    await wrapper.find('.tn-run').trigger('click')
    await vi.waitFor(() => expect(apiPost).toHaveBeenCalled())

    const [, options] = apiPost.mock.calls.at(-1)
    expect('provider_instance_id' in options.body).toBe(false)
    expect(options.body.target_node_ids).toEqual([node.id])
    wrapper.unmount()
  })
})

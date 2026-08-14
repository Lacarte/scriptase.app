import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'

const { setNodesSpy } = vi.hoisted(() => ({ setNodesSpy: vi.fn() }))

vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn() }))
vi.mock('@/shared/api/client.js', () => ({
  api: {
    get: vi.fn(async (path) => path === '/api/workflows'
      ? { workflows: [] }
      : path === '/api/workflow/templates'
        ? { templates: [] }
        : {}),
    post: vi.fn(async () => ({})),
  },
}))

vi.mock('@vue-flow/core', () => ({
  MarkerType: { ArrowClosed: 'arrow' },
  useVueFlow: () => ({
    screenToFlowCoordinate: (point) => point,
    fitView: vi.fn(),
    setViewport: vi.fn(async () => {}),
    setNodes: setNodesSpy,
  }),
  VueFlow: defineComponent({
    name: 'VueFlow',
    emits: ['nodeContextMenu', 'edgeContextMenu', 'paneContextMenu', 'nodesChange', 'edgesChange'],
    setup(_props, { emit, slots }) {
      return () => h('div', { class: 'vue-flow__pane' }, [
        h('button', {
          class: 'emit-node-menu',
          onContextmenu: (event) => emit('nodeContextMenu', { event, node: { id: 'n_1' } }),
        }),
        h('button', {
          class: 'emit-edge-menu',
          onContextmenu: (event) => emit('edgeContextMenu', { event, edge: { id: 'e_1' } }),
        }),
        h('button', {
          class: 'emit-pane-menu',
          onContextmenu: (event) => emit('paneContextMenu', event),
        }),
        h('button', {
          class: 'emit-vue-flow-delete',
          onClick: () => {
            emit('edgesChange', [
              { id: 'e_1', type: 'remove' },
              { id: 'e_2', type: 'remove' },
            ])
            emit('nodesChange', [{ id: 'n_1', type: 'remove' }])
          },
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

const TYPES = {
  source: {
    type: 'source', type_version: 1, display_name: 'Source', category: 'input',
    inputs: [], outputs: [{ id: 'value', type: 'text' }], config_schema: [],
  },
  target: {
    type: 'target', type_version: 1, display_name: 'Target', category: 'output',
    inputs: [{ id: 'value', type: 'text', required: true, multiple: false }],
    outputs: [], config_schema: [],
  },
  'stub.input': {
    type: 'stub.input', type_version: 1, display_name: 'Sample Input', category: 'testing',
    inputs: [], outputs: [{ id: 'value', type: 'dynamic' }],
    config_schema: [
      { name: 'port_type', type: 'options', default: 'text' },
      { name: 'payload', type: 'json', default: '' },
    ],
  },
  'stub.output': {
    type: 'stub.output', type_version: 1, display_name: 'Result Viewer', category: 'testing',
    inputs: [{ id: 'value', type: 'dynamic', required: true, multiple: false }],
    outputs: [],
    config_schema: [
      { name: 'port_type', type: 'options', default: 'text' },
      { name: 'pinned', type: 'boolean', default: false },
      { name: 'payload', type: 'json', default: '' },
    ],
  },
}

describe('step 5.2 context menus', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    setNodesSpy.mockClear()
  })

  it('renders node, edge, and pane actions and dispatches duplicate undoably', async () => {
    const store = useWorkflowStore()
    store.registryVersion = 1
    store.nodeTypes = TYPES
    store.portTypes = ['text']
    store.settings = { on_error: 'stop', auto_attach_stubs: false }
    const source = store.addNode('source', { x: 0, y: 0 })
    const target = store.addNode('target', { x: 200, y: 0 })
    store.connectNodes({ sourceNode: source.id, sourcePort: 'value', targetNode: target.id, targetPort: 'value' })
    store.clearCommandHistory()

    const wrapper = mount(WorkflowPage, {
      global: {
        stubs: {
          NodeLibrary: true,
          NodeInspector: true,
          NodeCard: true,
          ExecutionPanel: true,
        },
      },
    })
    expect(wrapper.find('.wf-toolbar-actions').text()).not.toContain('Add note')
    const inspectorToggle = wrapper.find('.wf-inspector-toggle')
    expect(inspectorToggle.attributes('aria-expanded')).toBe('true')
    await inspectorToggle.trigger('click')
    await nextTick()
    expect(wrapper.find('.wf-inspector').classes()).toContain('collapsed')
    expect(wrapper.find('.wf-inspector-content').attributes('style')).toContain('display: none')
    expect(localStorage.getItem('sts.workflow.inspector-collapsed')).toBe('1')
    await inspectorToggle.trigger('click')
    await wrapper.find('.emit-node-menu').trigger('contextmenu')
    expect(wrapper.text()).toContain('Copy')
    expect(wrapper.text()).toContain('Replace with…')
    expect(wrapper.text()).toContain('Delete')
    const duplicate = wrapper.findAll('.wf-context-item').find((button) => button.text() === 'Duplicate')
    await duplicate.trigger('click')
    expect(store.nodes).toHaveLength(3)
    expect(store.undoLabel).toBe('Duplicate node')

    await wrapper.find('.emit-edge-menu').trigger('contextmenu')
    expect(wrapper.text()).toContain('Disconnect')
    await wrapper.find('.wf-context-backdrop').trigger('click')
    await nextTick()

    await wrapper.find('.emit-pane-menu').trigger('contextmenu')
    expect(wrapper.text()).toContain('Paste here')
    expect(wrapper.text()).toContain('Add note')
    expect(wrapper.text()).toContain('Auto arrange')
    wrapper.unmount()
  })

  it('deletes default sample nodes when Vue Flow removes edges before the main node', async () => {
    const store = useWorkflowStore()
    store.registryVersion = 1
    store.nodeTypes = TYPES
    store.portTypes = ['text']
    store.samplePayloads = { text: 'sample' }
    store.settings = { on_error: 'stop', auto_attach_stubs: true }
    store.addNodeWithStubs('target', { x: 200, y: 0 })
    store.clearCommandHistory()

    expect(store.nodes.map((node) => node.type).sort()).toEqual(['stub.input', 'target'])
    expect(store.edges).toHaveLength(1)

    const wrapper = mount(WorkflowPage, {
      global: {
        stubs: {
          NodeLibrary: true,
          NodeInspector: true,
          NodeCard: true,
          ExecutionPanel: true,
        },
      },
    })
    await wrapper.find('.emit-vue-flow-delete').trigger('click')
    await nextTick()

    expect(store.nodes).toEqual([])
    expect(store.edges).toEqual([])
    expect(store.undoLabel).toBe('Delete node')
    expect(setNodesSpy).toHaveBeenCalledWith([])
  })
})

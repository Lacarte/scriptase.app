import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import fixture from '../fixtures/large-workflow.json'
import { generateLargeWorkflow, LARGE_WORKFLOW_NODE_COUNT } from '../../../../scripts/generate-large-workflow.mjs'
import { createCanvasNodeProjector, LARGE_CANVAS_NODE_THRESHOLD } from '../canvasElements.js'

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
  }),
  VueFlow: defineComponent({
    name: 'VueFlow',
    props: {
      nodes: { type: Array, default: () => [] },
      edges: { type: Array, default: () => [] },
      onlyRenderVisibleElements: Boolean,
    },
    emits: ['nodeDragStop', 'viewportChangeEnd'],
    setup(props, { emit, slots }) {
      return () => h('div', { class: 'vue-flow__pane' }, [
        h('span', { class: 'rendered-node-count' }, String(props.nodes.length)),
        h('button', {
          class: 'emit-pan',
          onClick: () => emit('viewportChangeEnd', { x: -320, y: -180, zoom: 0.75 }),
        }),
        h('button', {
          class: 'emit-drag',
          onClick: () => emit('nodeDragStop', {
            node: { id: fixture.nodes[0].id, position: { x: 37, y: 53 } },
          }),
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
import { DRAFT_DEBOUNCE_MS, DRAFT_STORAGE_KEY, useWorkflowStore } from '../stores/workflow.js'

describe('step 9.5 large-canvas performance', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('keeps unchanged Vue Flow node objects stable across selection updates', () => {
    const project = createCanvasNodeProjector()
    const nodes = fixture.nodes.slice(0, 3)
    const initial = project(nodes, [], new Set())
    const selected = project(nodes, [], new Set([nodes[1].id]))

    expect(selected[0]).toBe(initial[0])
    expect(selected[1]).not.toBe(initial[1])
    expect(selected[2]).toBe(initial[2])
    expect(selected[1].selected).toBe(true)
  })

  it('generates the checked-in deterministic 150-node regression fixture', () => {
    expect(LARGE_WORKFLOW_NODE_COUNT).toBeGreaterThanOrEqual(150)
    expect(fixture).toEqual(generateLargeWorkflow())
    expect(fixture.nodes).toHaveLength(LARGE_WORKFLOW_NODE_COUNT)
    expect(new Set(fixture.nodes.map((node) => node.id)).size).toBe(fixture.nodes.length)
  })

  it('loads, culls, pans, drags, and defers draft persistence on the fixture', async () => {
    vi.useFakeTimers()
    const store = useWorkflowStore()
    store.registryVersion = 1
    store.nodeTypes = {
      'stub.input': {
        type: 'stub.input', type_version: 1, display_name: 'Sample Input', category: 'testing',
        inputs: [], outputs: [{ id: 'value', type: 'dynamic' }], config_schema: [],
      },
    }
    store.categories = { testing: { color: '#64748b' } }
    store.portTypes = ['text']
    store.applyDocument(fixture)

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
    const flow = wrapper.findComponent({ name: 'VueFlow' })
    expect(flow.props('nodes')).toHaveLength(LARGE_WORKFLOW_NODE_COUNT)
    expect(LARGE_WORKFLOW_NODE_COUNT).toBeGreaterThanOrEqual(LARGE_CANVAS_NODE_THRESHOLD)
    expect(flow.props('onlyRenderVisibleElements')).toBe(true)

    await wrapper.find('.emit-pan').trigger('click')
    expect(store.viewport).toEqual({ x: -320, y: -180, zoom: 0.75 })
    expect(store.dirty).toBe(false)

    await wrapper.find('.emit-drag').trigger('click')
    await nextTick()
    expect(store.nodeById(fixture.nodes[0].id).position).toEqual({ x: 37, y: 53 })
    expect(store.dirty).toBe(true)
    expect(localStorage.getItem(DRAFT_STORAGE_KEY)).toBeNull()

    await vi.advanceTimersByTimeAsync(DRAFT_DEBOUNCE_MS - 1)
    expect(localStorage.getItem(DRAFT_STORAGE_KEY)).toBeNull()
    await vi.advanceTimersByTimeAsync(1)
    const draft = JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY))
    expect(draft.document.nodes).toHaveLength(LARGE_WORKFLOW_NODE_COUNT)
    expect(draft.document.nodes[0].position).toEqual({ x: 37, y: 53 })

    wrapper.unmount()
    vi.useRealTimers()
  })
})

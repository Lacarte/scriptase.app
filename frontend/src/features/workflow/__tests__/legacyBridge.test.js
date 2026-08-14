import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

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
    setup(_props, { slots }) {
      return () => h('div', { class: 'vue-flow__pane' }, slots.default?.())
    },
  }),
}))
vi.mock('@vue-flow/background', () => ({ Background: defineComponent(() => () => h('div')) }))
vi.mock('@vue-flow/controls', () => ({ Controls: defineComponent(() => () => h('div')) }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: defineComponent(() => () => h('div')) }))

import WorkflowPage from '../views/WorkflowPage.vue'
import { useWorkflowStore } from '../stores/workflow.js'

describe('Scriptase workflow surface — no legacy pipeline bridge', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('does not link to the retired V2 pipeline dashboard', () => {
    const store = useWorkflowStore()
    store.settings = { on_error: 'stop', auto_attach_stubs: false }

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
    expect(wrapper.find('a.wf-legacy-link').exists()).toBe(false)
    expect(wrapper.find('a[href="#/pipeline"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('pipeline dashboard')
    wrapper.unmount()
  })
})

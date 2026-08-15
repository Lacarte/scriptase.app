import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { useWorkflowStore, SHOW_ALL_NODES_KEY } from '../stores/workflow.js'
import NodeLibrary from '../components/NodeLibrary.vue'

/** Step 12.1: the palette shows the Full Video stages until asked for the rest. */

const TYPES = {
  'script.input': {
    type: 'script.input', type_version: 1, display_name: 'Script Input',
    description: 'Enter a script', category: 'input', icon: 'file-text',
    config_schema: [], hidden: false,
  },
  'workflow.output': {
    type: 'workflow.output', type_version: 1, display_name: 'Workflow Output',
    description: 'Record a result', category: 'utility', icon: 'flag',
    config_schema: [], hidden: false,
  },
  'utility.wait': {
    type: 'utility.wait', type_version: 1, display_name: 'Wait',
    description: 'Delay a branch', category: 'utility', icon: 'clock',
    config_schema: [], hidden: true,
  },
  'stub.input': {
    type: 'stub.input', type_version: 1, display_name: 'Sample Input',
    description: 'Testing sample data', category: 'testing', icon: 'flask',
    config_schema: [], hidden: true,
  },
  // A category the library's sort hint has never heard of. It used to vanish.
  'dev.hot_node': {
    type: 'dev.hot_node', type_version: 1, display_name: 'Hot Node',
    description: 'Scaffolded node', category: 'experimental', icon: 'flask',
    config_schema: [], hidden: false,
  },
}

function seededStore() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = TYPES
  store.categories = {
    input: { label: 'Input', color: '#60a5fa' },
    utility: { label: 'Utility', color: '#9ca3af' },
    testing: { label: 'Testing', color: '#78716c' },
  }
  return store
}

describe('node library visibility', () => {
  let pinia
  beforeEach(() => {
    localStorage.clear()
    pinia = createPinia()
    setActivePinia(pinia)
  })

  it('hides flagged nodes by default and keeps visible ones in the same category', () => {
    seededStore()
    const wrapper = mount(NodeLibrary, { global: { plugins: [pinia] } })
    const text = wrapper.text()

    expect(text).toContain('Script Input')
    expect(text).toContain('Workflow Output')
    expect(text).not.toContain('Wait')
    expect(text).not.toContain('Sample Input')
  })

  it('shows a node whose category is missing from the sort order, last', () => {
    seededStore()
    const wrapper = mount(NodeLibrary, { global: { plugins: [pinia] } })

    const labels = wrapper.findAll('.library-group-header').map((header) => header.text())
    expect(labels).toContain('experimental')
    expect(labels.at(-1)).toBe('experimental')
    expect(wrapper.text()).toContain('Hot Node')
  })

  it('reveals every node through the toggle and remembers the choice', async () => {
    const store = seededStore()
    const wrapper = mount(NodeLibrary, { global: { plugins: [pinia] } })

    expect(wrapper.get('.library-toggle').text()).toContain('2 hidden')
    await wrapper.get('.library-toggle-input').setValue(true)

    expect(store.showAllNodes).toBe(true)
    expect(localStorage.getItem(SHOW_ALL_NODES_KEY)).toBe('1')
    expect(wrapper.text()).toContain('Wait')
    expect(wrapper.text()).toContain('Sample Input')

    await wrapper.get('.library-toggle-input').setValue(false)
    expect(store.showAllNodes).toBe(false)
    expect(localStorage.getItem(SHOW_ALL_NODES_KEY)).toBeNull()
    expect(wrapper.text()).not.toContain('Sample Input')
  })

  it('leaves a hidden node searchable once the toggle is on', async () => {
    const store = seededStore()
    store.setShowAllNodes(true)
    const wrapper = mount(NodeLibrary, { global: { plugins: [pinia] } })

    await wrapper.get('.library-search-input').setValue('sample')
    expect(wrapper.text()).toContain('Sample Input')
    expect(wrapper.text()).not.toContain('Script Input')
  })
})

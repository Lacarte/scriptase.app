import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { shouldDisplayField, nodeIssues } from '../schema.js'
import { useWorkflowStore } from '../stores/workflow.js'
import NodeInspector from '../components/NodeInspector.vue'

const LOGO_FIELDS = [
  { name: 'logo_enabled', label: 'Show logo', type: 'boolean', default: false },
  { name: 'logo_position', label: 'Position', type: 'options', options: ['top_left', 'top_right'],
    default: 'top_right', display_options: { show: { logo_enabled: [true] } } },
]

describe('shouldDisplayField', () => {
  it('always shows fields without display_options', () => {
    expect(shouldDisplayField(LOGO_FIELDS[0], {})).toBe(true)
  })

  it('honours show conditions', () => {
    expect(shouldDisplayField(LOGO_FIELDS[1], { logo_enabled: false })).toBe(false)
    expect(shouldDisplayField(LOGO_FIELDS[1], { logo_enabled: true })).toBe(true)
  })

  it('honours hide conditions', () => {
    const field = { name: 'x', type: 'string', display_options: { hide: { mode: ['auto'] } } }
    expect(shouldDisplayField(field, { mode: 'auto' })).toBe(false)
    expect(shouldDisplayField(field, { mode: 'manual' })).toBe(true)
  })
})

const DEF = {
  display_name: 'Text to Speech',
  category: 'audio',
  icon: 'mic',
  config_schema: [
    { name: 'text', label: 'Script', type: 'textarea', default: '', required: true },
    { name: 'secret', label: 'Secret', type: 'string', default: '', required: true,
      display_options: { show: { text: ['unlock'] } } },
  ],
  inputs: [
    { id: 'trigger', type: 'control', required: false, multiple: false },
    { id: 'script', type: 'script', required: true, multiple: false },
  ],
  outputs: [],
}

describe('nodeIssues', () => {
  const node = (configuration) => ({
    id: 'n_1', type: 'x.y', name: 'X', configuration, disabled: false,
  })

  it('flags empty required fields and unconnected required inputs', () => {
    const issues = nodeIssues(node({ text: '' }), DEF, [])
    expect(issues.map((i) => i.name)).toEqual(['text', 'script'])
  })

  it('ignores hidden required fields and connected inputs', () => {
    const edges = [{ target_node: 'n_1', target_port: 'script', source_node: 'a', source_port: 's' }]
    const issues = nodeIssues(node({ text: 'hello' }), DEF, edges)
    expect(issues).toEqual([])
  })

  it('flags hidden fields once their show condition activates', () => {
    const issues = nodeIssues(node({ text: 'unlock', secret: '' }), DEF, [])
    expect(issues.map((i) => i.name)).toContain('secret')
  })

  it('reports unknown node types', () => {
    const issues = nodeIssues(node({}), undefined, [])
    expect(issues[0].message).toMatch(/Unknown node type/)
  })

  it('reports graph issues even when the configuration container is invalid', () => {
    const issues = nodeIssues(node([]), DEF, [])
    expect(issues.map((issue) => issue.name)).toEqual(expect.arrayContaining([
      'configuration', 'text', 'script',
    ]))
  })

  it('mirrors server config constraints and unknown-field rejection', () => {
    const constrained = {
      ...DEF,
      type_version: 1,
      config_schema: [
        { name: 'name', label: 'Name', type: 'string', default: '', min_length: 2, max_length: 5 },
        { name: 'count', label: 'Count', type: 'number', default: 2, min: 1, max: 3 },
        { name: 'mode', label: 'Mode', type: 'options', default: 'a', options: ['a', 'b'] },
        { name: 'enabled', label: 'Enabled', type: 'boolean', default: false },
        { name: 'data', label: 'Data', type: 'json', default: {} },
      ],
      inputs: [],
    }
    const invalid = node({
      name: 'x', count: 9, mode: 'c', enabled: 'yes', data: { value: Infinity }, surprise: true,
    })
    invalid.type_version = 2
    const messages = nodeIssues(invalid, constrained, []).map((issue) => issue.message)
    expect(messages).toEqual(expect.arrayContaining([
      expect.stringMatching(/Unsupported version/),
      expect.stringMatching(/Unknown configuration field/),
      expect.stringMatching(/invalid length/),
      expect.stringMatching(/allowed range/),
      expect.stringMatching(/allowed option/),
      expect.stringMatching(/boolean/),
      expect.stringMatching(/finite JSON/),
    ]))
  })

  it('rejects fractional values for integer number fields', () => {
    const definition = {
      ...DEF,
      type_version: 1,
      inputs: [],
      config_schema: [
        { name: 'delay', label: 'Delay', type: 'number', default: 0, min: 0, max: 100, integer: true },
      ],
    }
    const messages = nodeIssues(node({ delay: 1.5 }), definition, []).map((issue) => issue.message)
    expect(messages).toContain('Delay must be an integer')
  })
})

describe('inspector conditional rendering + issue badges', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('reveals conditional fields when their condition flips', async () => {
    const store = useWorkflowStore()
    store.registryVersion = 1
    store.nodeTypes = {
      'project.setup': {
        type_version: 1,
        display_name: 'Channel',
        category: 'input',
        icon: 'briefcase',
        inputs: [],
        outputs: [],
        config_schema: LOGO_FIELDS,
      },
    }
    store.categories = { input: { label: 'Input', color: '#4ECDC4' } }
    const node = store.addNode('project.setup', { x: 0, y: 0 })
    store.selectNode(node.id)

    const wrapper = mount(NodeInspector)
    expect(wrapper.findAll('select')).toHaveLength(0)

    store.updateNodeConfig(node.id, 'logo_enabled', true)
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('select')).toHaveLength(1)
  })

  it('issuesByNode drives the inspector issue list', () => {
    const store = useWorkflowStore()
    store.registryVersion = 1
    store.nodeTypes = { 'x.y': DEF }
    store.categories = { audio: { label: 'Audio', color: '#A78BFA' } }
    const node = store.addNode('x.y', { x: 0, y: 0 })
    store.selectNode(node.id)

    const wrapper = mount(NodeInspector)
    expect(store.issuesByNode[node.id].length).toBe(2)
    expect(wrapper.text()).toContain('is required')
    expect(wrapper.text()).toContain('needs a connection')
  })
})

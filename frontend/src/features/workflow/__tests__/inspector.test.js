import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import ConfigField from '../components/ConfigField.vue'
import NodeInspector from '../components/NodeInspector.vue'
import { useWorkflowStore } from '../stores/workflow.js'
import { clearOptionSourceCache } from '@/shared/composables/useOptionSources.js'
import { api } from '@/shared/api/client.js'

function mountField(field, value) {
  return mount(ConfigField, { props: { field, value } })
}

describe('ConfigField widgets', () => {
  it('renders string input and emits updates', async () => {
    const wrapper = mountField({ name: 'channel_name', label: 'Channel', type: 'string', default: '' }, 'Acme')
    const input = wrapper.get('input[type="text"]')
    expect(input.element.value).toBe('Acme')
    await input.setValue('New name')
    expect(wrapper.emitted('update').at(-1)).toEqual(['New name'])
  })

  it('renders textarea', async () => {
    const wrapper = mountField({ name: 'text', label: 'Script', type: 'textarea', default: '' }, 'hello')
    const area = wrapper.get('textarea')
    await area.setValue('changed')
    expect(wrapper.emitted('update').at(-1)).toEqual(['changed'])
  })

  it('renders number with clamping to min/max', async () => {
    const wrapper = mountField(
      { name: 'speed', label: 'Speed', type: 'number', default: 1, min: 0.5, max: 2, step: 0.1 },
      1.0,
    )
    const input = wrapper.get('input[type="number"]')
    input.element.value = '5'
    await input.trigger('change')
    expect(wrapper.emitted('update').at(-1)).toEqual([2])
    expect(wrapper.find('input[type="range"]').exists()).toBe(true)
  })

  it('renders boolean checkbox', async () => {
    const wrapper = mountField({ name: 'enabled', label: 'On', type: 'boolean', default: false }, false)
    const box = wrapper.get('input[type="checkbox"]')
    await box.setValue(true)
    expect(wrapper.emitted('update').at(-1)).toEqual([true])
  })

  it('renders static options select', async () => {
    const wrapper = mountField(
      { name: 'mode', label: 'Mode', type: 'options', options: ['video', 'image'], default: 'video' },
      'video',
    )
    const select = wrapper.get('select')
    await select.setValue('image')
    expect(wrapper.emitted('update').at(-1)).toEqual(['image'])
  })

  it('loads async options through the backend allowlist', async () => {
    clearOptionSourceCache()
    vi.spyOn(api, 'get').mockResolvedValue({
      source: 'tts_voices',
      options: [
        { value: 'af_heart', label: 'af_heart' },
        { value: 'bm_fable', label: 'bm_fable' },
      ],
    })
    const wrapper = mountField(
      { name: 'voice', label: 'Voice', type: 'options', options_source: 'tts_voices', default: 'af_heart' },
      'af_heart',
    )
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/api/workflow/options/tts_voices')
    const select = wrapper.get('select')
    expect(select.element.disabled).toBe(false)
    const values = wrapper.findAll('option').map((o) => o.element.value)
    expect(values).toEqual(['af_heart', 'bm_fable'])
    await select.setValue('bm_fable')
    expect(wrapper.emitted('update').at(-1)).toEqual(['bm_fable'])
    vi.restoreAllMocks()
  })

  it('scopes an option source to the node provider it declares a context for', async () => {
    // Step 15.2: the `voice` dropdown used to resolve context-free, so it
    // always answered with the default engine's voices however the node's
    // provider was set. Step 3.2 also sends `instance` so two bindings of one
    // type resolve their own catalogs. `options_context` comes from the
    // registry, which reads it off the source's own spec.
    clearOptionSourceCache()
    vi.spyOn(api, 'get').mockResolvedValue({
      source: 'tts_voices',
      options: [{ value: 'Ashley', label: 'Ashley' }],
    })
    const wrapper = mount(ConfigField, {
      props: {
        field: {
          name: 'voice',
          label: 'Voice',
          type: 'options',
          options_source: 'tts_voices',
          options_context: ['domain', 'provider', 'instance'],
          default: 'Ashley',
        },
        value: 'Ashley',
        providerId: 'inworld',
        providerDomain: 'tts',
      },
    })
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith(
      '/api/workflow/options/tts_voices?domain=tts&instance=inworld&provider=inworld',
    )

    // Switching the node's instance re-resolves rather than reusing the answer.
    api.get.mockResolvedValue({
      source: 'tts_voices',
      options: [{ value: 'af_heart', label: 'af_heart' }],
    })
    await wrapper.setProps({ providerId: 'kokoro' })
    await flushPromises()
    expect(api.get).toHaveBeenLastCalledWith(
      '/api/workflow/options/tts_voices?domain=tts&instance=kokoro&provider=kokoro',
    )
    expect(wrapper.findAll('option').map((o) => o.element.value)).toContain('af_heart')
    vi.restoreAllMocks()
  })

  it('sends no context to a source that declares none', async () => {
    clearOptionSourceCache()
    vi.spyOn(api, 'get').mockResolvedValue({ source: 'tts_providers', options: [] })
    mount(ConfigField, {
      props: {
        field: {
          name: 'provider_id',
          label: 'Provider',
          type: 'provider',
          provider_domain: 'tts',
          options_source: 'tts_providers',
          default: 'kokoro',
        },
        value: 'kokoro',
        providerId: 'kokoro',
        providerDomain: 'tts',
      },
    })
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/api/workflow/options/tts_providers')
    vi.restoreAllMocks()
  })

  it('keeps an unavailable stored value visible instead of showing option 0', async () => {
    clearOptionSourceCache()
    vi.spyOn(api, 'get').mockResolvedValue({
      source: 'tts_voices',
      options: [{ value: 'af_heart', label: 'af_heart' }],
    })
    const wrapper = mountField(
      { name: 'voice', label: 'Voice', type: 'options', options_source: 'tts_voices', default: 'af_heart' },
      'retired_voice',
    )
    await flushPromises()
    const labels = wrapper.findAll('option').map((o) => o.text())
    expect(labels[0]).toContain('retired_voice (unavailable)')
    expect(wrapper.get('select').element.value).toBe('retired_voice')
    vi.restoreAllMocks()
  })

  it('media_asset renders the managed picker and emits removal', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ assets: [] })
    const wrapper = mountField(
      { name: 'logo', label: 'Logo', type: 'media_asset', accept: ['png'], default: null },
      { ref: 'branding/logo_ab12.png', filename: 'logo.png', url: '/output/branding/logo_ab12.png' },
    )
    await flushPromises()
    expect(wrapper.get('img').attributes('src')).toBe('/output/branding/logo_ab12.png')
    await wrapper.get('.media-btn.danger').trigger('click')
    expect(wrapper.emitted('update').at(-1)).toEqual([null])
    vi.restoreAllMocks()
  })

  it('json widget validates before emitting', async () => {
    const wrapper = mountField({ name: 'opts', label: 'Opts', type: 'json', default: {} }, { a: 1 })
    const area = wrapper.get('textarea')
    await area.setValue('{ bad json')
    await area.trigger('blur')
    expect(wrapper.text()).toContain('Invalid JSON')
    expect(wrapper.emitted('update')).toBeUndefined()
    await area.setValue('{"b": 2}')
    await area.trigger('blur')
    expect(wrapper.emitted('update').at(-1)).toEqual([{ b: 2 }])
  })
})

const TYPES = {
  'tts.generate': {
    type_version: 1,
    display_name: 'Text to Speech',
    description: 'Generate narration audio.',
    category: 'audio',
    icon: 'mic',
    inputs: [],
    outputs: [],
    config_schema: [
      { name: 'engine', label: 'Engine', type: 'options', options: ['kokoro', 'inworld'], default: 'kokoro' },
      { name: 'speed', label: 'Speed', type: 'number', default: 1, min: 0.5, max: 2, step: 0.1 },
      { name: 'provider_options', label: 'Options', type: 'json', default: {} },
    ],
  },
}

describe('NodeInspector', () => {
  beforeEach(() => setActivePinia(createPinia()))

  function seeded() {
    const store = useWorkflowStore()
    store.registryVersion = 1
    store.nodeTypes = TYPES
    store.categories = { audio: { label: 'Audio', color: '#A78BFA' } }
    const node = store.addNode('tts.generate', { x: 0, y: 0 })
    store.selectNode(node.id)
    return { store, node }
  }

  it('shows the empty state without a selection', () => {
    const store = useWorkflowStore()
    store.nodeTypes = TYPES
    const wrapper = mount(NodeInspector)
    expect(wrapper.text()).toContain('Select a node')
  })

  it('renders every schema field generically and writes config updates', async () => {
    const { store, node } = seeded()
    const wrapper = mount(NodeInspector)
    expect(wrapper.findAllComponents(ConfigField)).toHaveLength(3)
    const select = wrapper.get('select')
    await select.setValue('inworld')
    expect(store.nodeById(node.id).configuration.engine).toBe('inworld')
    expect(store.dirty).toBe(true)
  })

  it('renders capability-gated retry controls and persists the node policy', async () => {
    const { store, node } = seeded()
    store.nodeTypes['tts.generate'].capabilities = {
      retry: true, error_output: true, skip_optional: true,
    }
    const wrapper = mount(NodeInspector)
    const policy = wrapper.get('.error-policy select')
    expect(policy.findAll('option').map((option) => option.element.value)).toEqual([
      'stop', 'retry', 'continue_error', 'skip_optional',
    ])
    await policy.setValue('retry')
    const inputs = wrapper.findAll('.retry-grid input')
    await inputs[0].setValue(4)
    await inputs[0].trigger('change')
    await inputs[1].setValue(250)
    await inputs[1].trigger('change')
    expect(store.nodeById(node.id).on_error).toMatchObject({
      policy: 'retry', max_attempts: 4, delay_ms: 250,
    })
    expect(store.toDocument().nodes[0].on_error.policy).toBe('retry')
  })

  it('rename, disable, duplicate, delete actions work', async () => {
    const { store, node } = seeded()
    const wrapper = mount(NodeInspector)

    const name = wrapper.get('.inspector-name')
    await name.setValue('Narration A')
    await name.trigger('change')
    expect(store.nodeById(node.id).name).toBe('Narration A')

    const buttons = wrapper.findAll('.ins-btn')
    await buttons[0].trigger('click') // disable
    expect(store.nodeById(node.id).disabled).toBe(true)

    await buttons[1].trigger('click') // duplicate
    expect(store.nodes).toHaveLength(2)
    expect(store.selectedNodeId).not.toBe(node.id)

    store.selectNode(node.id)
    const del = mount(NodeInspector).findAll('.ins-btn')[2]
    await del.trigger('click')
    expect(store.nodeById(node.id)).toBeNull()
    expect(store.selectedNodeId).toBeNull()
  })

  it('clears stale selection when a node is removed or a document is replaced', () => {
    const { store, node } = seeded()
    store.removeNodes([node.id])
    expect(store.selectedNodeId).toBeNull()

    const replacement = store.addNode('tts.generate', { x: 0, y: 0 })
    store.selectNode(replacement.id)
    store.applyDocument({
      schema_version: 1,
      name: 'Replacement',
      nodes: [{ ...replacement, name: 'Same ID, different document' }],
      edges: [],
      variables: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      settings: { on_error: 'stop' },
      extensions: {},
    })
    expect(store.selectedNodeId).toBeNull()
  })

  it('preserves selection only when reapplying the same saved graph', () => {
    const { store, node } = seeded()
    const saved = store.toDocument()
    store.applyDocument(saved, { preserveSelection: true })
    expect(store.selectedNodeId).toBe(node.id)

    saved.nodes = []
    store.applyDocument(saved, { preserveSelection: true })
    expect(store.selectedNodeId).toBeNull()
  })

  it('duplicates bounded node data without dropping extensions', () => {
    const { store, node } = seeded()
    node.name = 'N'.repeat(120)
    node.position = { x: 999_990, y: 999_990 }
    node.extensions = { plugin: { value: 1 } }

    const copy = store.duplicateNode(node.id)
    expect(copy.name).toHaveLength(120)
    expect(copy.name.endsWith(' copy')).toBe(true)
    expect(copy.position).toEqual({ x: 1_000_000, y: 1_000_000 })
    expect(copy.extensions).toEqual(node.extensions)
    expect(copy.extensions).not.toBe(node.extensions)
  })
})

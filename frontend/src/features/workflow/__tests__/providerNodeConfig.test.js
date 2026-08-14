import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import NodeInspector from '../components/NodeInspector.vue'
import ProviderOptionsField from '../components/ProviderOptionsField.vue'
import ProviderSettingsForm from '@/features/providers/components/ProviderSettingsForm.vue'
import { useWorkflowStore } from '../stores/workflow.js'
import { clearOptionSourceCache } from '@/shared/composables/useOptionSources.js'
import { api } from '@/shared/api/client.js'

/**
 * Step 12.5 — configuring a provider-backed node from metadata alone.
 *
 * Step 12.3 converted five nodes to the `provider_id` + `provider_options`
 * pair, but nothing rendered either widget: `ConfigField` fell through to
 * "Unsupported field type: provider" and those nodes could not be configured
 * at all. This covers the half that closes it.
 *
 * Every provider here is invented. Nothing in the fixtures matches a shipped
 * provider, which is the assertion: the inspector draws a provider it has
 * never heard of, from `<domain>_providers` and the provider's own settings
 * schema (contracts.md §22, §26).
 */

const DOMAIN = 'script'

const NODE_TYPES = {
  'story.generate': {
    type_version: 1,
    display_name: 'Story Generator',
    description: 'Generate a script.',
    category: 'ai',
    icon: 'sparkles',
    inputs: [],
    outputs: [],
    config_schema: [
      {
        name: 'provider_id',
        label: 'Provider',
        type: 'provider',
        provider_domain: DOMAIN,
        options_source: `${DOMAIN}_providers`,
        default: 'alpha_writer',
        required: true,
      },
      { name: 'duration', label: 'Duration', type: 'number', default: 45, min: 15, max: 180 },
      {
        name: 'provider_options',
        label: 'Provider options',
        type: 'provider_options',
        provider_domain: DOMAIN,
        default: {},
        description: 'Credentials belong in provider settings.',
      },
    ],
  },
}

const PROVIDER_OPTIONS = [
  { value: 'alpha_writer', label: 'Alpha Writer' },
  { value: 'beta_scribe', label: 'Beta Scribe' },
]

const SCHEMAS = {
  alpha_writer: {
    type: 'object',
    properties: {
      // A secret must never be offered on a node: the value would be
      // persisted into the workflow document (§22.6).
      api_key: { type: 'string', label: 'API key', ui: { type: 'password' } },
      voice_of: {
        type: 'string',
        label: 'Narrative voice',
        default: 'narrator',
        ui: { type: 'dropdown', options: ['narrator', 'chorus'] },
      },
      chaptered: { type: 'boolean', label: 'Chapters', default: false, ui: { type: 'toggle' } },
      chapter_count: {
        type: 'integer',
        label: 'How many',
        default: 3,
        minimum: 2,
        maximum: 9,
        ui: { type: 'number', show_if: { chaptered: true } },
      },
    },
    required: ['api_key'],
  },
  beta_scribe: {
    type: 'object',
    properties: {
      register: {
        type: 'string',
        label: 'Register',
        default: 'formal',
        ui: { type: 'dropdown', options: ['formal', 'casual'] },
      },
    },
    required: [],
  },
}

function mockApi() {
  return vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url.startsWith(`/api/workflow/options/${DOMAIN}_providers`)) {
      return Promise.resolve({ source: `${DOMAIN}_providers`, options: PROVIDER_OPTIONS })
    }
    const settings = url.match(/^\/api\/providers\/([^/]+)\/([^/]+)\/settings$/)
    if (settings) {
      const [, domain, providerId] = settings
      return Promise.resolve({
        domain,
        provider_id: providerId,
        // The server always redacts; the node form must not show it either way.
        settings: { api_key: '***' },
        schema: SCHEMAS[providerId] ?? null,
      })
    }
    return Promise.reject(new Error(`unexpected request: ${url}`))
  })
}

async function mountInspector(configuration = {}) {
  const store = useWorkflowStore()
  store.registryVersion = 4
  store.nodeTypes = NODE_TYPES
  store.categories = { ai: { label: 'AI', color: '#F472B6' } }
  const node = store.addNode('story.generate', { x: 0, y: 0 })
  Object.assign(node.configuration, configuration)
  store.selectNode(node.id)
  const wrapper = mount(NodeInspector)
  await flushPromises()
  return { store, node, wrapper }
}

describe('provider-backed node configuration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    clearOptionSourceCache()
    mockApi()
  })

  afterEach(() => vi.restoreAllMocks())

  it('renders the provider field as a dropdown over the domain option source', async () => {
    const { wrapper } = await mountInspector()
    expect(api.get).toHaveBeenCalledWith(`/api/workflow/options/${DOMAIN}_providers`)
    const select = wrapper.get('.cfg-select')
    const labels = select.findAll('option').map((option) => option.text())
    expect(labels).toEqual(['Alpha Writer', 'Beta Scribe'])
  })

  it('no longer reports the widget as unsupported', async () => {
    const { wrapper } = await mountInspector()
    expect(wrapper.text()).not.toContain('Unsupported field type')
  })

  it('renders the selected provider’s own settings as the per-run sub-form', async () => {
    const { wrapper } = await mountInspector({ provider_id: 'alpha_writer' })
    expect(api.get).toHaveBeenCalledWith('/api/providers/script/alpha_writer/settings')
    const form = wrapper.getComponent(ProviderSettingsForm)
    const labels = form.findAll('.field-label').map((label) => label.text())
    expect(labels).toContain('Narrative voice')
    expect(labels).toContain('Chapters')
  })

  it('never offers a credential as a per-run node option', async () => {
    const { wrapper } = await mountInspector({ provider_id: 'alpha_writer' })
    const form = wrapper.getComponent(ProviderSettingsForm)
    expect(form.find('input[type="password"]').exists()).toBe(false)
    expect(form.text()).not.toContain('API key')
  })

  it('honours the provider’s conditional visibility', async () => {
    const { wrapper } = await mountInspector({ provider_id: 'alpha_writer' })
    const labels = () =>
      wrapper.getComponent(ProviderSettingsForm).findAll('.field-label').map((l) => l.text())
    expect(labels()).not.toContain('How many')

    await wrapper.getComponent(ProviderSettingsForm).get('input[type="checkbox"]').setValue(true)
    await flushPromises()
    expect(labels()).toContain('How many')
  })

  it('writes an edited option back into the node configuration', async () => {
    const { store, node, wrapper } = await mountInspector({ provider_id: 'alpha_writer' })
    const form = wrapper.getComponent(ProviderSettingsForm)
    await form.get('select').setValue('chorus')
    await flushPromises()
    expect(store.nodeById(node.id).configuration.provider_options).toEqual({
      voice_of: 'chorus',
    })
  })

  it('swaps the sub-form when the node selects a different provider', async () => {
    const { store, node, wrapper } = await mountInspector({ provider_id: 'alpha_writer' })
    store.updateNodeConfig(node.id, 'provider_id', 'beta_scribe')
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/api/providers/script/beta_scribe/settings')
    const labels = wrapper
      .getComponent(ProviderSettingsForm)
      .findAll('.field-label')
      .map((label) => label.text())
    expect(labels).toEqual(['Register'])
  })

  it('falls back to the schema default for a document saved before the conversion', async () => {
    // M4: a pre-12.3 workflow carries no `provider_id`, and must still show the
    // options of the provider it will actually run.
    const { wrapper } = await mountInspector()
    expect(api.get).toHaveBeenCalledWith('/api/providers/script/alpha_writer/settings')
    expect(wrapper.findComponent(ProviderOptionsField).exists()).toBe(true)
  })

  it('renders a provider with no schema as having no per-run options', async () => {
    const { wrapper } = await mountInspector({ provider_id: 'gamma_unknown' })
    expect(wrapper.getComponent(ProviderOptionsField).text()).toContain(
      'no per-run options',
    )
  })

  it('fetches each schema once however many fields ask for it', async () => {
    await mountInspector({ provider_id: 'alpha_writer' })
    const calls = api.get.mock.calls
      .map(([url]) => url)
      .filter((url) => url === '/api/providers/script/alpha_writer/settings')
    expect(calls).toHaveLength(1)
  })
})

describe('no provider id in the node provider widgets', () => {
  // The 12.2/12.4 guard, extended to the two files 12.5 added or changed.
  const src = resolve(process.cwd(), 'src')
  const SHIPPED_PROVIDER_IDS = [
    'kokoro', 'inworld', 'gemini_ws', 'wavespeed_webhook', 'wavespeed_direct',
    'grok_automa', 'kie_ai', 'kie-ai',
  ]
  const FILES = [
    join(src, 'features', 'workflow', 'components', 'ProviderOptionsField.vue'),
    join(src, 'features', 'workflow', 'components', 'ConfigField.vue'),
    join(src, 'features', 'workflow', 'components', 'NodeInspector.vue'),
  ]

  it.each(FILES)('%s names no provider', (path) => {
    const source = readFileSync(path, 'utf8').toLowerCase()
    for (const id of SHIPPED_PROVIDER_IDS) {
      expect(source, `${path} mentions ${id}`).not.toContain(id)
    }
  })

  it('names no domain either — the field carries its own', () => {
    const source = readFileSync(FILES[0], 'utf8')
    // `provider_domain` is read, never compared against a literal domain id.
    // Domain ids rename with packages (image/video/scene_director). The field
    // must not hardcode either the V2 or Scriptase spellings.
    for (const domain of [
      'storyboard', 'animator', 'scene_blueprint',
      'image', 'video', 'scene_director',
    ]) {
      expect(source).not.toContain(`'${domain}'`)
    }
  })
})

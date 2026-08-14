import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { h } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import ProviderSettingsModal from '../components/ProviderSettingsModal.vue'
import ProviderSettingsForm from '../components/ProviderSettingsForm.vue'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import { api } from '@/shared/api/client.js'
import {
  clearOptionSourceCache,
  useOptionSource,
} from '@/shared/composables/useOptionSources.js'

// Step 12.2 — the modal renders capability badges, provider links, health
// actions, and validation feedback from public metadata only, and it never
// discards a provider's unsaved draft when the operator looks at another one.

const SCHEMA = {
  type: 'object',
  properties: {
    api_key: { type: 'string', label: 'API Key', ui: { type: 'password' } },
    model: { type: 'string', label: 'Model' },
  },
  required: ['api_key'],
}

function settingsPayload(providerId, overrides = {}) {
  return {
    provider_id: providerId,
    domain: 'demo',
    settings: { api_key: '***', model: 'base', ...(overrides.settings || {}) },
    schema: SCHEMA,
    manifest: {
      id: providerId,
      label: providerId.toUpperCase(),
      description: 'A fixture provider.',
      docs_url: 'https://example.test/docs',
      open_url: null,
      capabilities: { batch: true, streaming: false, test_connection: true },
      availability: 'available',
      ...(overrides.manifest || {}),
    },
  }
}

// The real form in the real slot: the modal owns the data and the form owns the
// widgets, and the draft rules only hold if both halves are wired together.
function mountModal(props = {}) {
  return mount(ProviderSettingsModal, {
    props: { domain: 'demo', providerId: 'alpha', visible: true, ...props },
    global: { stubs: { Teleport: true } },
    slots: {
      form: (params) =>
        h(ProviderSettingsForm, {
          modelValue: params.formData,
          schema: params.schema,
          errors: params.errors,
          domain: params.domain,
          providerId: params.providerId,
          'onUpdate:modelValue': (value) => Object.assign(params.formData, value),
        }),
    },
  })
}

describe('provider settings modal', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    clearOptionSourceCache()
  })
  afterEach(() => vi.restoreAllMocks())

  it('renders capabilities, description, and links from the manifest', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(settingsPayload('alpha'))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.text()).toContain('Configure ALPHA')
    expect(wrapper.text()).toContain('A fixture provider.')
    // Only capabilities the manifest declares true, and never `streaming: false`.
    const badges = wrapper.findAll('.badge').map((el) => el.text())
    expect(badges).toEqual(['batch', 'test_connection'])
    expect(wrapper.find('a[href="https://example.test/docs"]').exists()).toBe(true)
  })

  it('names the provider in validation feedback', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(settingsPayload('alpha'))
    vi.spyOn(api, 'post').mockResolvedValue({
      valid: false,
      issues: [{ field: 'api_key', severity: 'error', message: 'API Key is required' }],
    })
    const wrapper = mountModal()
    await flushPromises()

    await wrapper.findAll('.btn').at(-1).trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('ALPHA needs configuration')
  })

  it('names the provider in health feedback', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(settingsPayload('alpha'))
    vi.spyOn(api, 'post').mockResolvedValue({ health: { status: 'fail', message: 'no key' } })
    const wrapper = mountModal()
    await flushPromises()

    await wrapper.findAll('.btn').at(1).trigger('click')
    await flushPromises()

    expect(wrapper.find('.test-result').text()).toContain('ALPHA: no key')
  })

  it('keeps each provider unsaved non-secret draft independently', async () => {
    const store = useProviderCatalogStore()
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      settingsPayload(url.includes('/beta/') ? 'beta' : 'alpha'),
    )

    const wrapper = mountModal()
    await flushPromises()

    // Edit alpha, then look at beta.
    await wrapper.find('#field-model').setValue('alpha-draft')
    await wrapper.setProps({ providerId: 'beta' })
    await flushPromises()

    expect(store.draftFor('demo', 'alpha')).toEqual({ model: 'alpha-draft' })
    expect(wrapper.find('#field-model').element.value).toBe('base')

    // Edit beta too, then come back: alpha's draft is still there.
    await wrapper.find('#field-model').setValue('beta-draft')
    await wrapper.setProps({ providerId: 'alpha' })
    await flushPromises()

    expect(store.draftFor('demo', 'beta')).toEqual({ model: 'beta-draft' })
    expect(wrapper.find('#field-model').element.value).toBe('alpha-draft')
  })

  it('never keeps a secret in a draft', async () => {
    const store = useProviderCatalogStore()
    vi.spyOn(api, 'get').mockResolvedValue(settingsPayload('alpha'))
    const wrapper = mountModal()
    await flushPromises()

    await wrapper.find('.link-btn').trigger('click') // replace the secret
    await wrapper.find('#field-api_key').setValue('super-secret')
    await wrapper.setProps({ visible: false })
    await flushPromises()

    const draft = store.draftFor('demo', 'alpha')
    expect(JSON.stringify(draft)).not.toContain('super-secret')
    expect(draft).not.toHaveProperty('api_key')
  })

  it('drops the draft once the settings save', async () => {
    const store = useProviderCatalogStore()
    vi.spyOn(api, 'get').mockResolvedValue(settingsPayload('alpha'))
    vi.spyOn(api, 'post').mockResolvedValue({ valid: true, issues: [] })
    vi.spyOn(api, 'put').mockResolvedValue({ ok: true, issues: [] })

    const wrapper = mountModal()
    await flushPromises()
    await wrapper.find('#field-model').setValue('changed')
    await wrapper.findAll('.btn').at(-1).trigger('click')
    await flushPromises()

    expect(store.draftFor('demo', 'alpha')).toBeNull()
  })

  it('invalidates option sources for the domain after a settings save', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.startsWith('/api/workflow/options')
        ? { options: [{ value: 'one', label: 'One' }], context: { domain: 'demo' } }
        : settingsPayload('alpha'),
    )
    vi.spyOn(api, 'post').mockResolvedValue({ valid: true, issues: [] })
    vi.spyOn(api, 'put').mockResolvedValue({ ok: true, issues: [] })

    useOptionSource('fixture_voices', { domain: 'demo' })
    await flushPromises()

    const store = useProviderCatalogStore()
    await store.saveProviderSettings('demo', 'alpha', {})
    useOptionSource('fixture_voices', { domain: 'demo' })
    await flushPromises()

    expect(api.get.mock.calls.filter((c) => c[0].startsWith('/api/workflow/options')))
      .toHaveLength(2)
  })
})

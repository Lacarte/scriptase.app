import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/shared/api/client.js'
import ProvidersSettingsPage from '../ProvidersSettingsPage.vue'

const CATALOG = {
  catalog_version: 'settings-v1',
  dev_reload_enabled: false,
  domains: {
    tts: {
      domain: 'tts',
      label: 'Text to Speech',
      selected_instance_id: 'inworld',
      providers: [{ id: 'inworld', label: 'Inworld', availability: 'available' }],
      instances: [{
        instance_id: 'inworld', provider_type: 'inworld', label: 'Primary',
        selected: true, availability: 'available',
      }],
      excluded: [],
    },
  },
}

describe('provider settings page', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.spyOn(api, 'get').mockResolvedValue(structuredClone(CATALOG))
  })
  afterEach(() => vi.restoreAllMocks())

  it('lists named instances and creates a second one for configuration', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ instance_id: 'inworld_2' })
    const wrapper = shallowMount(ProvidersSettingsPage)
    await flushPromises()

    expect(wrapper.text()).toContain('Providers')
    expect(wrapper.text()).toContain('Primary')
    await wrapper.get('.instance-tools .ghost').trigger('click')
    await wrapper.get('.create-form input').setValue('Client account')
    await wrapper.get('.create-form .primary').trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/api/providers/tts/instances', {
      body: { provider_type: 'inworld', label: 'Client account' },
    })
    expect(wrapper.findComponent({ name: 'ProviderSettingsModal' }).exists()).toBe(true)
  })

  it('never renders a credential value from the catalog', async () => {
    const payload = structuredClone(CATALOG)
    payload.domains.tts.instances[0].api_key = 'must-not-render'
    api.get.mockResolvedValue(payload)
    const wrapper = shallowMount(ProvidersSettingsPage)
    await flushPromises()

    expect(wrapper.text()).not.toContain('must-not-render')
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/shared/api/client.js'
import ProviderSimulationConsole from '../components/ProviderSimulationConsole.vue'

describe('provider simulation console', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('renders a dummy request and response from the simulation endpoint', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({
      simulated: true,
      transport: 'extension://simulated/gemini_ws',
      operation: 'generate_image',
      elapsed_ms: 0,
      request: { prompt: 'A cinematic sample frame' },
      response: { status: 'ok', artifact: 'simulated/frame.png' },
      steps: ['Build dummy command', 'Mock extension hand-off'],
    })
    const wrapper = mount(ProviderSimulationConsole, {
      props: { domain: 'image', instanceId: 'gemini_ws', providerName: 'Gemini' },
    })

    await wrapper.get('.simulate-button').trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith(
      '/api/providers/image/instances/gemini_ws/simulate', { body: {} },
    )
    expect(wrapper.text()).toContain('A cinematic sample frame')
    expect(wrapper.text()).toContain('simulated/frame.png')
    expect(wrapper.text()).toContain('No configured endpoint is contacted')
  })
})

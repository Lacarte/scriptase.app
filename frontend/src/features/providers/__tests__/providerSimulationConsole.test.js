import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/shared/api/client.js'
import ProviderSimulationConsole from '../components/ProviderSimulationConsole.vue'

const FIXTURE = {
  simulated: true,
  transport: 'extension://simulated/gemini_ws',
  operation: 'generate_image',
  elapsed_ms: 0,
  request: { prompt: 'A cinematic sample frame', aspect: '9:16' },
  response: { request_id: 'sim_abc', status: 'ok', artifact: 'simulated/frame.png', width: 1080 },
  steps: ['Build dummy command', 'Mock extension hand-off'],
}

function mountConsole() {
  return mount(ProviderSimulationConsole, {
    props: { domain: 'image', instanceId: 'gemini_ws', providerName: 'Gemini' },
  })
}

describe('provider simulation console', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('renders a dummy request and response from the simulation endpoint', async () => {
    vi.spyOn(api, 'post').mockResolvedValue(structuredClone(FIXTURE))
    const wrapper = mountConsole()

    // The button lives in the detail pane's `pv-foot` (step 6.5), so the console
    // is driven through what it exposes rather than through markup of its own.
    await wrapper.vm.simulate()
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith(
      '/api/providers/image/instances/gemini_ws/simulate', { body: {} },
    )
    // The prototype's console: a head, two panes, the steps, the artifact.
    expect(wrapper.find('.pv-sim').classes()).toContain('show')
    expect(wrapper.find('.pv-sim-head .badge2').classes()).toContain('ok')
    expect(wrapper.find('.pv-sim-head .transport').text()).toBe('extension://simulated/gemini_ws')

    const panes = wrapper.findAll('.pv-sim-body .pv-sim-col')
    expect(panes).toHaveLength(2)
    expect(panes[0].find('.cl').text()).toContain('Request · generate_image')
    expect(panes[0].find('pre').text()).toContain('A cinematic sample frame')
    expect(panes[1].find('pre').text()).toContain('simulated/frame.png')

    expect(wrapper.findAll('.pv-sim-step.done')).toHaveLength(2)
    expect(wrapper.find('.pv-sim-artifact .t').text()).toBe('simulated/frame.png')
    expect(wrapper.find('.pv-sim-artifact .d').text()).toContain('width 1080')
  })

  /**
   * The prototype colours its JSON by assigning a rewritten string to
   * `innerHTML`. Tokens are elements here instead: a response body must never
   * reach `v-html`, whatever the endpoint behind it is.
   */
  it('colours the payload with elements, never with raw markup', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({
      ...structuredClone(FIXTURE),
      response: { note: '<img src=x onerror=alert(1)>', width: 1080 },
    })
    const wrapper = mountConsole()
    await wrapper.vm.simulate()
    await flushPromises()

    const response = wrapper.findAll('.pv-sim-col')[1]
    expect(response.find('pre .k').text()).toBe('"note"')
    expect(response.findAll('pre .n').at(-1).text()).toBe('1080')
    expect(response.find('pre').text()).toContain('<img src=x onerror=alert(1)>')
    expect(response.find('img').exists()).toBe(false)
  })

  it('reports a failed round trip without a response pane', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(new Error('simulation unavailable'))
    const wrapper = mountConsole()
    await wrapper.vm.simulate()
    await flushPromises()

    expect(wrapper.find('.pv-sim-head .badge2').classes()).toContain('err')
    expect(wrapper.find('.pv-sim-body').exists()).toBe(false)
    expect(wrapper.find('.sim-error').text()).toContain('simulation unavailable')
  })
})

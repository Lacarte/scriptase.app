/**
 * Step 6.5 — the prototype's `pv-*` family, and the rule that keeps it honest:
 * every value it draws comes from `GET /api/providers`, and the two the catalog
 * has no field for (plate colour, glyph) are derived from ids it does own.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/shared/api/client.js'
import ProvidersSettingsPage from '../ProvidersSettingsPage.vue'

const CATALOG = {
  catalog_version: 'pv-v1',
  dev_reload_enabled: false,
  domains: {
    tts: {
      domain: 'tts',
      label: 'Voice',
      selected_instance_id: 'inworld',
      capability_vocabulary: ['streaming', 'voice_listing'],
      providers: [{
        id: 'inworld',
        label: 'Inworld',
        kind: 'cloud',
        version: '1.2.0',
        description: 'Neural text-to-speech for all narration.',
        capabilities: { streaming: true, voice_listing: true },
        availability: 'available',
      }],
      instances: [{
        instance_id: 'inworld', provider_type: 'inworld', label: 'Primary',
        selected: true, availability: 'available',
      }],
      excluded: [],
    },
    image: {
      domain: 'image',
      label: 'Image',
      selected_instance_id: 'gemini_ws',
      capability_vocabulary: ['aspect_ratio'],
      providers: [{
        id: 'gemini_ws',
        label: 'Gemini',
        kind: 'extension',
        version: '0.4.2',
        description: 'Generates storyboard art from scene blueprints.',
        capabilities: { aspect_ratio: true },
        availability: 'needs_configuration',
      }],
      instances: [{
        instance_id: 'gemini_ws', provider_type: 'gemini_ws', label: 'Gemini',
        selected: true, availability: 'needs_configuration',
      }],
      excluded: [],
    },
  },
}

function mountPage() {
  return mount(ProvidersSettingsPage, {
    global: { stubs: { ProviderSettingsModal: true, ProviderSettingsForm: true } },
  })
}

describe('providers fidelity (step 6.5)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.spyOn(api, 'get').mockImplementation((url) =>
      url === '/api/providers'
        ? Promise.resolve(structuredClone(CATALOG))
        : Promise.resolve({}),
    )
  })
  afterEach(() => vi.restoreAllMocks())

  it('renders the prototype rail beside the prototype detail', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('.pvview').exists()).toBe(true)
    expect(wrapper.find('.pv-rail .pv-rail-head h2').text()).toBe('Providers')
    expect(wrapper.find('.pv-rail-sub').text()).toContain('Capability is metadata')
    expect(wrapper.findAll('.pv-list .pv-litem')).toHaveLength(2)
    // One of the two is `available`; the foot counts that axis, not a probe.
    expect(wrapper.find('.pv-rail-foot').text()).toContain('1 of 2 available')

    expect(wrapper.find('.pv-detail .pv-hero').exists()).toBe(true)
    expect(wrapper.find('.pv-hero-cap').text()).toBe('Image')
    expect(wrapper.find('.pv-hero-name').text()).toContain('Gemini')
    expect(wrapper.find('.pv-hero-tag').text()).toBe('Generates storyboard art from scene blueprints.')
    expect(wrapper.find('.pv-body').exists()).toBe(true)
    expect(wrapper.find('.pv-link .stage-pill').text()).toBe('image')
    expect(wrapper.findAll('.pv-meta .cell')).toHaveLength(4)
    expect(wrapper.find('.pv-foot').exists()).toBe(true)
  })

  it('draws each rail row from the catalog, not from a table of providers', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const rows = wrapper.findAll('.pv-litem')
    // Domains are sorted, so `image` leads `tts`.
    expect(rows[0].find('.cap').text()).toBe('Image')
    expect(rows[0].find('.pn .kind').text()).toBe('Extension')
    expect(rows[1].find('.cap').text()).toBe('Voice')
    expect(rows[1].find('.pn .kind').text()).toBe('API key')

    // Availability is the resting status axis: a probe was never requested.
    expect(rows[0].find('.pv-status-dot').classes()).toContain('st-disconnected')
    expect(rows[1].find('.pv-status-dot').classes()).toContain('st-connected')
    expect(wrapper.find('.pv-badge').classes()).toContain('disconnected')
  })

  it('derives a stable plate per domain rather than storing one', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const plates = wrapper.findAll('.pv-litem .pv-ic')
    expect(plates.map((p) => p.text())).toEqual(['I', 'V'])
    // Two domains must not collapse onto one colour by accident.
    expect(plates[0].attributes('style')).not.toBe(plates[1].attributes('style'))
    // The hero repeats the selected row's plate exactly — same domain, same
    // derivation, so a colour can never disagree between rail and detail.
    expect(wrapper.find('.pv-hero-ic').attributes('style')).toBe(plates[0].attributes('style'))
  })

  it('chips only the capabilities the domain vocabulary declares', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.findAll('.pv-litem')[1].trigger('click')
    expect(wrapper.findAll('.pv-caps .kind').map((c) => c.text())).toEqual([
      'streaming', 'voice listing',
    ])
    expect(wrapper.find('.pv-meta .cell:nth-child(3) .n').text()).toBe('2')
  })

  it('shows a probe result in the prototype test readout', async () => {
    api.get.mockImplementation((url) =>
      url === '/api/providers'
        ? Promise.resolve(structuredClone(CATALOG))
        : Promise.resolve({ health: { status: 'ok', latency_ms: 42, message: 'Key valid' } }),
    )
    const wrapper = mountPage()
    await flushPromises()

    // The readout is in the DOM from the start and hidden until it has a result.
    expect(wrapper.find('.pv-test-out').classes()).not.toContain('show')

    await wrapper.findAll('.pv-foot .btn')[1].trigger('click')
    await flushPromises()

    const readout = wrapper.find('.pv-test-out')
    expect(readout.classes()).toEqual(expect.arrayContaining(['show', 'ok']))
    expect(readout.text()).toContain('Key valid')
    expect(readout.text()).toContain('42ms')
    expect(wrapper.find('.pv-badge').classes()).toContain('connected')
  })

  it('never renders a credential the catalog leaked', async () => {
    const payload = structuredClone(CATALOG)
    payload.domains.tts.instances[0].api_key = 'must-not-render'
    api.get.mockResolvedValue(payload)
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).not.toContain('must-not-render')
    expect(wrapper.find('.pv-static').text()).toContain('write-only')
  })
})

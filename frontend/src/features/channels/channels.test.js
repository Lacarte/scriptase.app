import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

import ChannelsPage from './ChannelsPage.vue'
import ChannelEditor from './ChannelEditor.vue'
import * as api from './api.js'

vi.mock('./api.js', () => ({
  listChannels: vi.fn(),
  createChannel: vi.fn(),
  deleteChannel: vi.fn(),
  seedChannels: vi.fn(),
  getChannel: vi.fn(),
  updateChannel: vi.fn(),
  listBrandingAssets: vi.fn(),
  uploadBrandingLogo: vi.fn(),
  getChannelDefaults: vi.fn(),
}))

function makeRouter(routes) {
  return createRouter({
    history: createMemoryHistory(),
    routes,
  })
}

describe('ChannelsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listChannels.mockResolvedValue({
      channels: [
        {
          id: 'ch_AAAAAA',
          name: 'Cinematic Stoicism',
          version: 1,
          niche: 'stoicism',
          style: 'cinematic',
        },
        {
          id: 'ch_BBBBBB',
          name: 'Custom Brand',
          version: 2,
          niche: 'brand',
          style: 'noir',
        },
      ],
      total: 2,
      starter_mappings: { stoicism_cinematic: 'ch_AAAAAA' },
      seed: { created: 0, skipped: 81, total_presets: 81 },
    })
  })

  it('lists channels and marks starters', async () => {
    const router = makeRouter([
      { path: '/', name: 'channels', component: ChannelsPage },
      { path: '/channels/:id', name: 'channel-edit', component: { template: '<div />' } },
    ])
    router.push('/')
    await router.isReady()

    const wrapper = mount(ChannelsPage, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(api.listChannels).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Cinematic Stoicism')
    expect(wrapper.text()).toContain('Custom Brand')
    expect(wrapper.text()).toContain('starter')
    expect(wrapper.text()).toContain('81 presets')
  })

  it('creates a channel and navigates to the editor', async () => {
    api.createChannel.mockResolvedValue({
      channel: { id: 'ch_NEWNEW', name: 'New Channel', version: 1 },
    })
    const router = makeRouter([
      { path: '/', name: 'channels', component: ChannelsPage },
      { path: '/channels/:id', name: 'channel-edit', component: { template: '<div>edit</div>' } },
    ])
    router.push('/')
    await router.isReady()
    const pushSpy = vi.spyOn(router, 'push')

    const wrapper = mount(ChannelsPage, {
      global: { plugins: [router] },
    })
    await flushPromises()

    await wrapper.get('button.primary').trigger('click')
    await flushPromises()

    expect(api.createChannel).toHaveBeenCalled()
    expect(pushSpy).toHaveBeenCalledWith({
      name: 'channel-edit',
      params: { id: 'ch_NEWNEW' },
    })
  })
})

describe('ChannelEditor', () => {
  const sample = {
    id: 'ch_AAAAAA',
    name: 'Cinematic Stoicism',
    version: 1,
    schema_version: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    branding: {
      logo_asset_id: null,
      enabled: false,
      position: 'bottom-right',
      size: 0.12,
      opacity: 1,
      margin: 0.04,
    },
    content: {
      niche: 'stoicism',
      language: 'en',
      audience: 'philosophy',
      script_style: '',
      tone: 'educational',
      mood: '',
      hook_style: '',
      cta_style: '',
      duration_target: 60,
    },
    visual_direction: {
      style: 'cinematic',
      pattern: [
        { narrative_role: 'hook', shot: 'extreme close-up' },
        { narrative_role: 'ending', shot: 'symbolic visual' },
      ],
      palette: '',
      lighting: '',
      camera: '',
      character_style: '',
      continuity: '',
      negative_prompt: '',
      references: [],
    },
    audio_defaults: {
      tts_provider_instance_id: null,
      voice: 'am_michael',
      speed: 0.9,
      music_profile: '',
      loudness: null,
      ducking: null,
    },
    captions: { preset: '', position: '', font_treatment: '', animation: '' },
    provider_defaults: {
      script: null,
      tts: null,
      scene_director: null,
      image: null,
      video: null,
      review: null,
    },
    fallback_policies: {},
    review_policy: {
      thresholds: {},
      max_repairs: 3,
      escalation: '',
      human_checkpoints: [],
    },
    budget: { max_generations: null, max_cost: null, currency: 'USD' },
    export_defaults: {
      aspect_ratio: '9:16',
      resolution: '',
      fps: null,
      profile: '',
    },
    default_workflow_id: null,
  }

  beforeEach(() => {
    vi.clearAllMocks()
    api.getChannel.mockResolvedValue({ channel: structuredClone(sample) })
    api.listBrandingAssets.mockResolvedValue({ assets: [] })
    api.updateChannel.mockImplementation(async (_id, draft, version) => ({
      channel: {
        ...sample,
        ...draft,
        version: version + 1,
        name: draft.name,
      },
    }))
  })

  it('loads a channel and saves edits with expected_version', async () => {
    const router = makeRouter([
      { path: '/channels', name: 'channels', component: { template: '<div />' } },
      {
        path: '/channels/:id',
        name: 'channel-edit',
        component: ChannelEditor,
      },
    ])
    router.push('/channels/ch_AAAAAA')
    await router.isReady()

    const wrapper = mount(ChannelEditor, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(api.getChannel).toHaveBeenCalledWith('ch_AAAAAA')
    expect(wrapper.text()).toContain('Cinematic Stoicism')

    const textInputs = wrapper.findAll('input[type="text"]')
    const values = textInputs.map((input) => input.element.value)
    expect(values).toContain('extreme close-up')
    expect(values).toContain('hook')

    // First text input is the channel name.
    await textInputs[0].setValue('Stoicism Nightly')
    await wrapper.get('button.primary').trigger('click')
    await flushPromises()

    expect(api.updateChannel).toHaveBeenCalled()
    const [id, draft, expected] = api.updateChannel.mock.calls[0]
    expect(id).toBe('ch_AAAAAA')
    expect(expected).toBe(1)
    expect(draft.name).toBe('Stoicism Nightly')
    expect(draft.visual_direction.pattern[0]).toEqual({
      narrative_role: 'hook',
      shot: 'extreme close-up',
    })
    // Provider defaults must remain instance-id slots (null / empty), never secrets.
    expect(draft.provider_defaults).toEqual({
      script: null,
      tts: null,
      scene_director: null,
      image: null,
      video: null,
      review: null,
    })
    expect(wrapper.text()).toContain('Saved')
  })
})

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
  listMusicAssets: vi.fn(),
  uploadBrandingLogo: vi.fn(),
  uploadChannelThumbnail: vi.fn(),
  uploadMusicTrack: vi.fn(),
  getChannelDefaults: vi.fn(),
  composeVisualPrompt: vi.fn(),
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

  /**
   * Step 0.3 — delete offers Undo instead of a confirm dialog. The row leaves
   * the list at once and the DELETE is deferred, so Undo is exact rather than
   * a best-effort restore.
   */
  describe('delete', () => {
    async function mountList() {
      const router = makeRouter([
        { path: '/', name: 'channels', component: ChannelsPage },
        { path: '/channels/:id', name: 'channel-edit', component: { template: '<div />' } },
      ])
      router.push('/')
      await router.isReady()
      const wrapper = mount(ChannelsPage, { global: { plugins: [router] } })
      await flushPromises()
      return wrapper
    }

    it('never asks for confirmation and hides the row immediately', async () => {
      vi.useFakeTimers()
      const confirmSpy = vi.spyOn(window, 'confirm')
      const wrapper = await mountList()

      await wrapper.get('button.danger').trigger('click')

      expect(confirmSpy).not.toHaveBeenCalled()
      expect(wrapper.text()).not.toContain('Cinematic Stoicism')
      expect(wrapper.text()).toContain('Custom Brand')
      // Nothing has reached the backend while the window is open.
      expect(api.deleteChannel).not.toHaveBeenCalled()

      confirmSpy.mockRestore()
      vi.useRealTimers()
      wrapper.unmount()
    })

    it('commits the delete once the five-second window closes', async () => {
      vi.useFakeTimers()
      api.deleteChannel.mockResolvedValue({})
      const wrapper = await mountList()

      await wrapper.get('button.danger').trigger('click')
      vi.advanceTimersByTime(5000)
      await flushPromises()

      expect(api.deleteChannel).toHaveBeenCalledWith('ch_AAAAAA', 1)

      vi.useRealTimers()
      wrapper.unmount()
    })

    it('puts the row back when the deferred delete fails', async () => {
      vi.useFakeTimers()
      api.deleteChannel.mockRejectedValue(new Error('409 stale version'))
      const wrapper = await mountList()

      await wrapper.get('button.danger').trigger('click')
      vi.advanceTimersByTime(5000)
      await flushPromises()

      expect(wrapper.text()).toContain('Cinematic Stoicism')
      expect(wrapper.text()).toContain('409 stale version')

      vi.useRealTimers()
      wrapper.unmount()
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
      thumbnail_asset_id: null,
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
    script_template: {
      brief: 'Hook the viewer, turn the premise, explain it, then land cleanly.',
      sections: ['Hook', 'Turn', 'Why', 'Reframe', 'Landing'],
    },
    visual_direction: {
      style: 'cinematic',
      style_prompt: 'Painterly chiaroscuro with restrained bronze highlights',
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
    music_library: {
      folder: 'Cinematic beds',
      tracks: ['musics/bed_12345678.mp3'],
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
    api.listMusicAssets.mockResolvedValue([
      { filename: 'bed.mp3', ref: 'musics/bed_12345678.mp3', category: 'uploads' },
    ])
    api.composeVisualPrompt.mockResolvedValue({
      prompt: 'A lone traveler finds a glowing door in the rain. Painterly chiaroscuro with restrained bronze highlights. Aspect ratio: 9:16.',
    })
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
    expect(wrapper.text()).toContain('Painterly chiaroscuro')
    expect(api.composeVisualPrompt).toHaveBeenCalled()

    const textInputs = wrapper.findAll('input[type="text"]')
    const values = textInputs.map((input) => input.element.value)
    expect(values).toContain('extreme close-up')
    expect(values).toContain('hook')
    expect(wrapper.findAll('.section-chip')).toHaveLength(5)
    expect(wrapper.findAll('.watermark-position')).toHaveLength(9)
    expect(
      wrapper.findAll('.section-chip input').map((input) => input.element.value),
    ).toEqual(['Hook', 'Turn', 'Why', 'Reframe', 'Landing'])

    const turnChip = wrapper.findAll('.section-chip')[1]
    await turnChip.find('button[aria-label="Move Turn down"]').trigger('click')

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
    expect(draft.script_template).toEqual({
      brief: 'Hook the viewer, turn the premise, explain it, then land cleanly.',
      sections: ['Hook', 'Why', 'Turn', 'Reframe', 'Landing'],
    })
    expect(draft.music_library).toEqual({
      folder: 'Cinematic beds',
      tracks: ['musics/bed_12345678.mp3'],
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

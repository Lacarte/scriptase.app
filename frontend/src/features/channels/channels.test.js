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
    // Step 6.4 — the prototype's rail rows, and its empty detail beside them.
    expect(wrapper.findAll('.ch-litem')).toHaveLength(2)
    expect(wrapper.find('.ch-empty').exists()).toBe(true)
  })

  /**
   * Step 6.4 — the avatar is derived, not stored: `ChannelProfile` carries no
   * colour or code, and inventing them would be a second source of truth.
   */
  it('draws each rail row with a stable derived avatar', async () => {
    const router = makeRouter([
      { path: '/', name: 'channels', component: ChannelsPage },
      { path: '/channels/:id', name: 'channel-edit', component: { template: '<div />' } },
    ])
    router.push('/')
    await router.isReady()

    const wrapper = mount(ChannelsPage, { global: { plugins: [router] } })
    await flushPromises()

    const avatars = wrapper.findAll('.ch-litem .ch-avatar')
    expect(avatars).toHaveLength(2)
    expect(avatars[0].text()).toBe('CS')
    expect(avatars[1].text()).toBe('CB')
    // Two different ids must not collapse onto one plate colour by accident.
    expect(avatars[0].attributes('style')).not.toBe(avatars[1].attributes('style'))
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
    // The editor renders the same rail as the index (step 6.4).
    api.listChannels.mockResolvedValue({ channels: [], starter_mappings: {}, seed: null })
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
    // The name is the hero's own input, as in the prototype — not a heading.
    expect(wrapper.get('.ch-name-input').element.value).toBe('Cinematic Stoicism')
    expect(wrapper.text()).toContain('Painterly chiaroscuro')
    expect(api.composeVisualPrompt).toHaveBeenCalled()
    expect(wrapper.find('.ch-dirty').classes()).not.toContain('show')

    const textInputs = wrapper.findAll('input[type="text"]')
    const values = textInputs.map((input) => input.element.value)
    expect(values).toContain('extreme close-up')
    expect(values).toContain('hook')
    // Step 6.4 — the prototype's numbered section rows and 3x3 picker.
    expect(wrapper.findAll('.ch-tpl-sec')).toHaveLength(5)
    expect(wrapper.findAll('.ch-wm-cell')).toHaveLength(9)
    expect(
      wrapper.findAll('.ch-tpl-sec input').map((input) => input.element.value),
    ).toEqual(['Hook', 'Turn', 'Why', 'Reframe', 'Landing'])

    const turnRow = wrapper.findAll('.ch-tpl-sec')[1]
    await turnRow.find('button[aria-label="Move Turn down"]').trigger('click')

    // First text input is the channel name, in the hero.
    expect(textInputs[0].classes()).toContain('ch-name-input')
    await textInputs[0].setValue('Stoicism Nightly')
    await wrapper.get('[data-testid="channel-save"]').trigger('click')
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

  /**
   * Step 6.4 — the picker writes `WATERMARK_POSITIONS` values straight through.
   * The prototype spells its cells `tl`…`br`; translating them here would put a
   * second vocabulary between the control and the field it validates against.
   */
  it('writes the backend watermark position the picker cell names', async () => {
    const router = makeRouter([
      { path: '/channels', name: 'channels', component: { template: '<div />' } },
      { path: '/channels/:id', name: 'channel-edit', component: ChannelEditor },
    ])
    router.push('/channels/ch_AAAAAA')
    await router.isReady()

    const wrapper = mount(ChannelEditor, { global: { plugins: [router] } })
    await flushPromises()

    const cells = wrapper.findAll('.ch-wm-cell')
    expect(cells.map((cell) => cell.attributes('aria-label'))).toEqual([
      'Top left', 'Top center', 'Top right',
      'Left', 'Center', 'Right',
      'Bottom left', 'Bottom center', 'Bottom right',
    ])
    expect(cells[8].attributes('aria-checked')).toBe('true')

    await cells[4].trigger('click')
    expect(cells[4].attributes('aria-checked')).toBe('true')
    expect(wrapper.find('.ch-dirty').classes()).toContain('show')

    await wrapper.get('[data-testid="channel-save"]').trigger('click')
    await flushPromises()

    const [, draft] = api.updateChannel.mock.calls[0]
    expect(draft.branding.position).toBe('center')
  })

  /**
   * Step 6.4 — neither block has a control in this editor, and both used to be
   * flattened on every save: cadence was never sent, fallbacks were sent empty.
   */
  it('carries cadence and fallback policies through an unrelated save', async () => {
    const scheduled = structuredClone(sample)
    scheduled.cadence = { enabled: true, cron: '0 9 * * 1' }
    scheduled.fallback_policies = {
      image: { primary: 'inst_image_1', fallbacks: ['inst_image_2'] },
    }
    api.getChannel.mockResolvedValue({ channel: scheduled })

    const router = makeRouter([
      { path: '/channels', name: 'channels', component: { template: '<div />' } },
      { path: '/channels/:id', name: 'channel-edit', component: ChannelEditor },
    ])
    router.push('/channels/ch_AAAAAA')
    await router.isReady()

    const wrapper = mount(ChannelEditor, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.get('[data-testid="channel-save"]').trigger('click')
    await flushPromises()

    const [, draft] = api.updateChannel.mock.calls[0]
    expect(draft.cadence).toEqual({ enabled: true, cron: '0 9 * * 1' })
    expect(draft.fallback_policies).toEqual({
      image: { primary: 'inst_image_1', fallbacks: ['inst_image_2'] },
    })
  })

  /**
   * The rail sits beside the editor. Saving must bump the list row's version
   * or a later Undo-delete still holds the pre-save token and 409s.
   */
  it('keeps the rail version in sync after save', async () => {
    api.listChannels.mockResolvedValue({
      channels: [
        {
          id: 'ch_AAAAAA',
          name: 'Cinematic Stoicism',
          version: 1,
          niche: 'stoicism',
          style: 'cinematic',
        },
      ],
      starter_mappings: {},
      seed: null,
    })
    api.updateChannel.mockResolvedValue({
      channel: {
        ...structuredClone(sample),
        name: 'Stoicism Nightly',
        version: 2,
      },
    })

    const router = makeRouter([
      { path: '/channels', name: 'channels', component: { template: '<div />' } },
      { path: '/channels/:id', name: 'channel-edit', component: ChannelEditor },
    ])
    router.push('/channels/ch_AAAAAA')
    await router.isReady()

    const wrapper = mount(ChannelEditor, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.get('.ch-litem .lrow').text()).toContain('v1')

    await wrapper.get('.ch-name-input').setValue('Stoicism Nightly')
    await wrapper.get('[data-testid="channel-save"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('.ch-litem .lrow').text()).toContain('v2')
    expect(wrapper.get('.ch-litem .lname').text()).toBe('Stoicism Nightly')
  })

  /**
   * Creating while already on the editor reuses ChannelRail — onMounted does
   * not re-run — so the new row has to be inserted by onCreate itself.
   */
  it('shows a channel created from the editor rail immediately', async () => {
    api.listChannels.mockResolvedValue({
      channels: [
        {
          id: 'ch_AAAAAA',
          name: 'Cinematic Stoicism',
          version: 1,
          niche: 'stoicism',
          style: 'cinematic',
        },
      ],
      starter_mappings: {},
      seed: null,
    })
    api.createChannel.mockResolvedValue({
      channel: {
        id: 'ch_NEWNEW',
        name: 'New Channel',
        version: 1,
        content: {},
        visual_direction: {},
        branding: {},
        music_library: { folder: '', tracks: [] },
      },
    })
    api.getChannel.mockImplementation(async (id) => ({
      channel: {
        ...structuredClone(sample),
        id,
        name: id === 'ch_NEWNEW' ? 'New Channel' : sample.name,
      },
    }))

    const router = makeRouter([
      { path: '/channels', name: 'channels', component: { template: '<div />' } },
      { path: '/channels/:id', name: 'channel-edit', component: ChannelEditor },
    ])
    router.push('/channels/ch_AAAAAA')
    await router.isReady()

    const wrapper = mount(ChannelEditor, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.findAll('.ch-litem')).toHaveLength(1)

    await wrapper.get('.ch-rail-title button.primary').trigger('click')
    await flushPromises()

    expect(api.createChannel).toHaveBeenCalled()
    expect(wrapper.findAll('.ch-litem')).toHaveLength(2)
    expect(wrapper.text()).toContain('New Channel')
    expect(router.currentRoute.value.params.id).toBe('ch_NEWNEW')
  })

  /**
   * Rapid rail clicks reuse this component. A slow response for A must not
   * overwrite the document already shown for B.
   */
  it('ignores a stale load when the route has already moved on', async () => {
    let resolveA
    const pendingA = new Promise((resolve) => {
      resolveA = resolve
    })
    api.getChannel.mockImplementation((id) => {
      if (id === 'ch_AAAAAA') {
        return pendingA.then(() => ({
          channel: { ...structuredClone(sample), id: 'ch_AAAAAA', name: 'Slow A' },
        }))
      }
      return Promise.resolve({
        channel: {
          ...structuredClone(sample),
          id: 'ch_BBBBBB',
          name: 'Fast B',
          version: 3,
        },
      })
    })
    api.listChannels.mockResolvedValue({
      channels: [
        { id: 'ch_AAAAAA', name: 'Cinematic Stoicism', version: 1 },
        { id: 'ch_BBBBBB', name: 'Custom Brand', version: 3 },
      ],
      starter_mappings: {},
      seed: null,
    })

    const router = makeRouter([
      { path: '/channels', name: 'channels', component: { template: '<div />' } },
      { path: '/channels/:id', name: 'channel-edit', component: ChannelEditor },
    ])
    router.push('/channels/ch_AAAAAA')
    await router.isReady()

    const wrapper = mount(ChannelEditor, { global: { plugins: [router] } })
    // First load is still pending — switch to B before A resolves.
    await router.push('/channels/ch_BBBBBB')
    await flushPromises()

    expect(wrapper.get('.ch-name-input').element.value).toBe('Fast B')

    resolveA()
    await flushPromises()

    expect(wrapper.get('.ch-name-input').element.value).toBe('Fast B')
    expect(router.currentRoute.value.params.id).toBe('ch_BBBBBB')
  })
})

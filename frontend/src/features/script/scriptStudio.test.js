import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import ScriptPage from './ScriptPage.vue'
import { applyTemplateOutline } from './generation.js'
import * as scriptApi from './api.js'
import * as channelApi from '@/features/channels/api.js'

vi.mock('./api.js', () => ({
  listScripts: vi.fn(),
  getScript: vi.fn(),
  createScript: vi.fn(),
  updateScript: vi.fn(),
  deleteScript: vi.fn(),
  generateScript: vi.fn(),
  generateNarration: vi.fn(),
  scoreScript: vi.fn(),
  listNarrationVoices: vi.fn(),
  narrationAudioUrl: vi.fn((id, artifactId) => `/api/scripts/${id}/narration/audio?artifact_id=${artifactId}`),
}))

vi.mock('@/features/channels/api.js', () => ({
  listChannels: vi.fn(),
  getChannel: vi.fn(),
}))

const CHANNEL_SUMMARY = {
  id: 'ch_AAAAAA',
  name: 'Philosophy Daily',
  niche: 'philosophy',
  style: 'cinematic',
}

const CHANNEL = {
  ...CHANNEL_SUMMARY,
  content: {
    niche: 'philosophy',
    script_style: 'cinematic',
    language: 'english',
  },
  script_template: {
    brief: 'Open with a reversal and land on one memorable thought.',
    sections: ['Hook', 'Turn', 'Why', 'Landing'],
  },
  audio_defaults: {
    voice: 'Alex',
    remove_silence: true,
    speed: 1.1,
  },
  provider_defaults: { tts: 'inworld' },
}

const SUMMARY = {
  id: 'scr_AAAAAA',
  title: 'Silence changes a room',
  channel_id: CHANNEL.id,
  origin: 'manual',
  version: 1,
  created_at: '2026-08-18T12:00:00Z',
  updated_at: '2026-08-18T12:00:00Z',
  word_count: 4,
  estimated_duration_s: 2,
  narration: { state: 'none', voice: '', duration_s: null, audio_artifact_id: null },
}

const DOCUMENT = {
  ...SUMMARY,
  schema_version: 1,
  body: 'Silence changes every crowded room.',
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/script', component: ScriptPage },
      { path: '/channels/:id', component: { template: '<div />' } },
      { path: '/production', name: 'production', component: { template: '<div />' } },
    ],
  })
}

async function mountPage({ withScript = true } = {}) {
  scriptApi.listScripts.mockResolvedValue({
    scripts: withScript ? [SUMMARY] : [],
    total: withScript ? 1 : 0,
  })
  const router = makeRouter()
  await router.push('/script')
  await router.isReady()
  const wrapper = mount(ScriptPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  channelApi.listChannels.mockResolvedValue({ channels: [CHANNEL_SUMMARY], total: 1 })
  channelApi.getChannel.mockResolvedValue({ channel: CHANNEL })
  scriptApi.getScript.mockResolvedValue({ script: DOCUMENT, narration_audio: null })
  scriptApi.listNarrationVoices.mockResolvedValue([
    { id: 'Alex', label: 'Alex' },
    { id: 'Ashley', label: 'Ashley' },
  ])
  scriptApi.generateScript.mockResolvedValue({
    story_text: 'The room goes quiet. Everyone reaches for a word. Silence removes the performance. The pause says enough.',
  })
})

describe('Script Studio step 3.2', () => {
  it('browses, opens and edits a saved script', async () => {
    scriptApi.updateScript.mockResolvedValue({
      script: { ...DOCUMENT, version: 2, title: 'A quieter room', body: 'A hand-written revision.' },
    })
    const wrapper = await mountPage()

    expect(scriptApi.getScript).toHaveBeenCalledWith('scr_AAAAAA')
    expect(wrapper.get('[aria-label="Script title"]').element.value).toBe('Silence changes a room')

    await wrapper.get('[aria-label="Script title"]').setValue('A quieter room')
    await wrapper.get('#script-body').setValue('A hand-written revision.')
    expect(wrapper.get('.s1-dirty-note').classes()).toContain('show')
    await wrapper.get('.s1-doc-foot .primary').trigger('click')
    await flushPromises()

    expect(scriptApi.updateScript).toHaveBeenCalledWith(
      'scr_AAAAAA',
      expect.objectContaining({
        title: 'A quieter room',
        body: 'A hand-written revision.',
        origin: 'manual',
      }),
      1,
    )
  })

  it('uses the selected Channel template for Auto generation', async () => {
    scriptApi.createScript.mockImplementation(async ({ title, body, channel_id, origin, narration }) => ({
      script: { ...DOCUMENT, title, body, channel_id, origin, narration },
    }))
    const wrapper = await mountPage({ withScript: false })

    await wrapper.get('.s1-rail-title .primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain("Using Philosophy Daily's template")
    for (const section of CHANNEL.script_template.sections) {
      expect(wrapper.text()).toContain(section)
    }

    await wrapper.get('.s1-create-go').trigger('click')
    await flushPromises()

    expect(scriptApi.generateScript).toHaveBeenCalledTimes(1)
    const saved = scriptApi.createScript.mock.calls[0][0]
    expect(saved.origin).toBe('auto')
    expect(saved.body).toContain('Hook\n')
    expect(saved.body).toContain('Turn\n')
    expect(saved.body).toContain('Why\n')
    expect(saved.body).toContain('Landing\n')
  })

  it('generates Topic to Idea through the script provider', async () => {
    scriptApi.createScript.mockImplementation(async draft => ({ script: { ...DOCUMENT, ...draft } }))
    const wrapper = await mountPage({ withScript: false })
    await wrapper.get('.s1-rail-title .primary').trigger('click')
    await flushPromises()

    const ideaTab = wrapper.findAll('[role="tab"]').find(button => button.text().includes('Idea'))
    await ideaTab.trigger('click')
    await wrapper.get('#idea-input').setValue('Why old arguments replay in our heads')
    await wrapper.get('.s1-create-go').trigger('click')
    await flushPromises()

    expect(scriptApi.generateScript).toHaveBeenCalledWith(expect.objectContaining({
      idea: 'Why old arguments replay in our heads',
      template_sections: CHANNEL.script_template.sections,
    }))
    expect(scriptApi.createScript).toHaveBeenCalledWith(expect.objectContaining({ origin: 'idea' }))
  })

  it('saves Paste verbatim without touching a script provider', async () => {
    const pasted = 'My exact opening.\n\nMy exact landing — unchanged.'
    scriptApi.createScript.mockImplementation(async draft => ({ script: { ...DOCUMENT, ...draft } }))
    const wrapper = await mountPage({ withScript: false })
    await wrapper.get('.s1-rail-title .primary').trigger('click')
    await flushPromises()

    const pasteTab = wrapper.findAll('[role="tab"]').find(button => button.text().includes('Paste'))
    await pasteTab.trigger('click')
    await wrapper.get('#paste-script').setValue(pasted)
    await wrapper.get('.s1-create-go').trigger('click')
    await flushPromises()

    expect(scriptApi.generateScript).not.toHaveBeenCalled()
    expect(scriptApi.createScript).toHaveBeenCalledWith(expect.objectContaining({
      body: pasted,
      origin: 'paste',
    }))
  })
})

describe('Script Studio step 3.3 narration', () => {
  it('defaults to Channel voice and marks processing values inherited', async () => {
    const wrapper = await mountPage()

    expect(wrapper.get('[aria-label="Narration voice"]').element.value).toBe('Alex')
    // Inheritance shows as the effective value plus an `s1-inh` badge, and the
    // reset affordance stays hidden while nothing is overridden.
    expect(wrapper.get('[aria-label="Remove silence override"]').attributes('aria-checked')).toBe('true')
    expect(wrapper.get('[aria-label="Narration speed override"]').element.value).toBe('1.1')
    expect(wrapper.findAll('.s1-inh')).toHaveLength(2)
    expect(wrapper.get('.s1-proc-src').text()).toBe('inherited from Philosophy Daily')
    expect(wrapper.find('.s1-proc-reset').exists()).toBe(false)
  })

  it('overrides processing through the toggle and restores the Channel default', async () => {
    const wrapper = await mountPage()

    await wrapper.get('[aria-label="Remove silence override"]').trigger('click')
    expect(wrapper.get('[aria-label="Remove silence override"]').attributes('aria-checked')).toBe('false')
    expect(wrapper.findAll('.s1-inh')).toHaveLength(1)
    expect(wrapper.get('.s1-proc-src').text()).toBe('overridden for this script')

    await wrapper.get('.s1-proc-reset').trigger('click')
    expect(wrapper.get('[aria-label="Remove silence override"]').attributes('aria-checked')).toBe('true')
    expect(wrapper.findAll('.s1-inh')).toHaveLength(2)
  })

  it('generates with explicit overrides and renders the returned take', async () => {
    const ready = {
      ...DOCUMENT,
      version: 3,
      narration: {
        state: 'ready', voice: 'Ashley', remove_silence: false, speed: 1.25,
        duration_s: 12.4, audio_artifact_id: 'art_AAAAAA',
      },
    }
    scriptApi.generateNarration.mockResolvedValue({
      script: ready,
      narration_audio: { mime: 'audio/mpeg' },
    })
    const wrapper = await mountPage()

    await wrapper.get('[aria-label="Narration voice"]').setValue('Ashley')
    await wrapper.get('[aria-label="Remove silence override"]').trigger('click')
    await wrapper.get('[aria-label="Narration speed override"]').setValue('1.25')
    await wrapper.get('[data-testid="narration-generate"]').trigger('click')
    await flushPromises()

    expect(scriptApi.generateNarration).toHaveBeenCalledWith('scr_AAAAAA', {
      voice: 'Ashley', remove_silence: false, speed: 1.25, expected_version: 1,
    })
    expect(wrapper.get('audio').attributes('src')).toContain('art_AAAAAA')
    expect(wrapper.findAll('.s1-inh')).toHaveLength(0)
    expect(wrapper.text()).toContain('Regenerate narration')

    // The player replaces the browser's default controls: a play button, the
    // 48-bar progress track and the elapsed/total readout.
    expect(wrapper.get('[data-testid="narration-status"]').classes()).toContain('ready')
    expect(wrapper.find('[data-testid="narration-play"]').exists()).toBe(true)
    expect(wrapper.findAll('.s1-wave-track i')).toHaveLength(48)
    expect(wrapper.get('.s1-player .time').text()).toBe('0:00 / 0:12')
    expect(wrapper.get('.s1-kv .mono').text()).toBe('0:12')
    expect(wrapper.text()).toContain('48kHz · mp3')
  })

  it('names the Channel provider instance without hardcoding a provider', async () => {
    channelApi.getChannel.mockResolvedValue({
      channel: {
        ...CHANNEL,
        audio_defaults: { ...CHANNEL.audio_defaults, tts_provider_instance_id: 'voice_house#2' },
      },
    })
    const wrapper = await mountPage()

    expect(wrapper.get('[data-testid="narration-provider"]').text()).toBe('voice_house#2')
  })

  it('resets voice and processing when create follows an open script', async () => {
    scriptApi.createScript.mockImplementation(async draft => ({
      script: {
        ...DOCUMENT,
        id: 'scr_NEWNEW',
        title: draft.title,
        body: draft.body,
        channel_id: draft.channel_id,
        origin: draft.origin,
        narration: { state: 'none', voice: '', remove_silence: null, speed: null },
      },
      narration_audio: null,
    }))
    const wrapper = await mountPage()

    await wrapper.get('[aria-label="Narration voice"]').setValue('Ashley')
    await wrapper.get('[aria-label="Remove silence override"]').trigger('click')
    await wrapper.get('[aria-label="Narration speed override"]').setValue('1.25')
    expect(wrapper.findAll('.s1-inh')).toHaveLength(0)

    await wrapper.get('.s1-rail-title .primary').trigger('click')
    await flushPromises()
    const pasteTab = wrapper.findAll('[role="tab"]').find(button => button.text().includes('Paste'))
    await pasteTab.trigger('click')
    await wrapper.get('#paste-script').setValue('A fresh pasted script.')
    await wrapper.get('.s1-create-go').trigger('click')
    await flushPromises()

    expect(wrapper.get('[aria-label="Narration voice"]').element.value).toBe('Alex')
    expect(wrapper.get('[aria-label="Remove silence override"]').attributes('aria-checked')).toBe('true')
    expect(wrapper.get('[aria-label="Narration speed override"]').element.value).toBe('1.1')
    expect(wrapper.findAll('.s1-inh')).toHaveLength(2)
    expect(scriptApi.listNarrationVoices).toHaveBeenCalled()
  })

  it('keeps an out-of-range Channel speed inherited instead of posting it as an override', async () => {
    channelApi.getChannel.mockResolvedValue({
      channel: {
        ...CHANNEL,
        audio_defaults: { ...CHANNEL.audio_defaults, speed: 3 },
      },
    })
    scriptApi.generateNarration.mockResolvedValue({
      script: {
        ...DOCUMENT,
        version: 2,
        narration: {
          state: 'ready', voice: 'Alex', remove_silence: null, speed: null,
          duration_s: 8, audio_artifact_id: 'art_SPEED',
        },
      },
      narration_audio: { mime: 'audio/mpeg' },
    })
    const wrapper = await mountPage()

    expect(wrapper.get('[aria-label="Narration speed override"]').element.value).toBe('3')
    expect(wrapper.findAll('.s1-inh')).toHaveLength(2)

    // Re-selecting the Channel default must stay null (inherit), not 3.0 —
    // narration overrides only accept 0.5–2.0.
    await wrapper.get('[aria-label="Narration speed override"]').setValue('3')
    await wrapper.get('[data-testid="narration-generate"]').trigger('click')
    await flushPromises()

    expect(scriptApi.generateNarration).toHaveBeenCalledWith('scr_AAAAAA', expect.objectContaining({
      speed: null,
    }))
  })
})

describe('Script Studio step 3.4 virality panel', () => {
  const VIRALITY = {
    score: 68,
    band: 'solid',
    scorer: 'deterministic',
    scorer_version: 1,
    dimensions: [
      { id: 'hook', score: 0.8, reasons: [{ code: 'hook_present', impact: 'positive' }] },
      { id: 'open_loops', score: 0.25, reasons: [{ code: 'open_loops_sparse', impact: 'negative' }] },
    ],
  }

  it('runs from the Check Virality header button and renders the gauge detail', async () => {
    scriptApi.scoreScript.mockResolvedValue({ virality: VIRALITY, cached: false })
    const wrapper = await mountPage()

    // The not-yet-run panel is copy only; Check Virality above the editor is
    // the affordance, as in the prototype.
    expect(wrapper.get('[data-testid="virality-panel"]').text()).toContain('Virality score not run')
    expect(wrapper.find('[data-testid="virality-panel"] button').exists()).toBe(false)

    await wrapper.get('[data-testid="check-virality"]').trigger('click')
    await flushPromises()

    expect(scriptApi.scoreScript).toHaveBeenCalledWith(DOCUMENT.id, DOCUMENT.body)
    expect(wrapper.get('[data-testid="virality-panel"]').text()).toContain('68')
    expect(wrapper.get('[data-testid="virality-panel"]').text()).toContain('solid')
    expect(wrapper.get('.s1-vir-gauge').attributes('data-band')).toBe('solid')
    expect(wrapper.get('[data-testid="virality-dimensions"]').text()).toContain('Hook')
    expect(wrapper.get('[data-testid="virality-dimensions"]').text()).toContain('Open loops')
    expect(wrapper.get('[data-testid="virality-dimensions"]').text()).toContain('Open loops sparse')

    // A run turns the panel head into the Re-check control.
    expect(wrapper.get('.s1-vir-recheck').text()).toContain('Re-check')
    expect(wrapper.findAll('.s1-vir-dim')).toHaveLength(2)
    expect(wrapper.get('.s1-vir-dim .s1-vir-bar .fill').attributes('style')).toContain('width: 80%')
  })

  it('scores unsaved text without disabling Save', async () => {
    scriptApi.scoreScript.mockResolvedValue({ virality: VIRALITY, cached: false })
    const wrapper = await mountPage()
    await wrapper.get('#script-body').setValue('Unsaved text can still be analyzed.')

    expect(wrapper.get('.s1-doc-foot .primary').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="check-virality"]').trigger('click')
    await flushPromises()

    expect(scriptApi.scoreScript).toHaveBeenCalledWith(DOCUMENT.id, 'Unsaved text can still be analyzed.')
    expect(scriptApi.updateScript).not.toHaveBeenCalled()
  })

  it('offers Check current text once the body has moved on from the score', async () => {
    scriptApi.scoreScript.mockResolvedValue({ virality: VIRALITY, cached: false })
    const wrapper = await mountPage()
    await wrapper.get('[data-testid="check-virality"]').trigger('click')
    await flushPromises()

    await wrapper.get('#script-body').setValue('Rewritten opening.')
    expect(wrapper.get('.s1-vir-recheck').text()).toContain('Check current text')
  })
})

describe('Script Studio step 6.3 library filter chips', () => {
  const NARRATED = {
    ...SUMMARY,
    id: 'scr_BBBBBB',
    title: 'The pause before an answer',
    narration: { state: 'ready', voice: 'Alex', duration_s: 31, audio_artifact_id: 'art_BBBBBB' },
  }

  async function mountLibrary() {
    scriptApi.listScripts.mockResolvedValue({ scripts: [SUMMARY, NARRATED], total: 2 })
    const router = makeRouter()
    await router.push('/script')
    await router.isReady()
    const wrapper = mount(ScriptPage, { global: { plugins: [router] } })
    await flushPromises()
    return wrapper
  }

  it('counts each narration state and filters the list without a second request', async () => {
    const wrapper = await mountLibrary()

    expect(wrapper.get('[data-testid="narration-filter-all"]').text()).toBe('All · 2')
    expect(wrapper.get('[data-testid="narration-filter-ready"]').text()).toBe('TTS Ready · 1')
    expect(wrapper.get('[data-testid="narration-filter-only"]').text()).toBe('Script Only · 1')
    expect(wrapper.get('[data-testid="narration-filter-all"]').classes()).toContain('sel')
    expect(wrapper.findAll('.s1-card')).toHaveLength(2)

    const requests = scriptApi.listScripts.mock.calls.length
    await wrapper.get('[data-testid="narration-filter-ready"]').trigger('click')

    expect(scriptApi.listScripts).toHaveBeenCalledTimes(requests)
    expect(wrapper.findAll('.s1-card')).toHaveLength(1)
    expect(wrapper.get('.s1-card .ctitle').text()).toBe('The pause before an answer')
    expect(wrapper.get('[data-testid="narration-filter-ready"]').classes()).toContain('sel')

    await wrapper.get('[data-testid="narration-filter-only"]').trigger('click')
    expect(wrapper.findAll('.s1-card')).toHaveLength(1)
    expect(wrapper.get('.s1-card .ctitle').text()).toBe('Silence changes a room')
  })

  it('tags each card with its narration state and totals them in the rail foot', async () => {
    const wrapper = await mountLibrary()
    const tags = wrapper.findAll('.s1-card .tts-tag')

    expect(tags.map(tag => tag.text())).toEqual(['Script Only', 'TTS Ready'])
    expect(tags[0].classes()).toContain('tts-only')
    expect(tags[1].classes()).toContain('tts-ready')
    expect(wrapper.get('.s1-rail-foot').text()).toContain('1 with narration')
    expect(wrapper.get('.s1-rail-foot').text()).toContain('2 total')
  })

  it('says so when a filter empties a library that is not itself empty', async () => {
    scriptApi.listScripts.mockResolvedValue({ scripts: [SUMMARY], total: 1 })
    const router = makeRouter()
    await router.push('/script')
    await router.isReady()
    const wrapper = mount(ScriptPage, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.get('[data-testid="narration-filter-ready"]').trigger('click')
    expect(wrapper.findAll('.s1-card')).toHaveLength(0)
    expect(wrapper.get('[data-testid="script-library"]').text()).toBe('No scripts match.')
  })
})

describe('applyTemplateOutline', () => {
  it('distributes provider prose across every ordered section', () => {
    const result = applyTemplateOutline(
      'First thought. Second thought. Third thought. Fourth thought.',
      ['Hook', 'Turn', 'Why', 'Landing'],
    )
    expect(result.split('\n\n').map(section => section.split('\n')[0]))
      .toEqual(['Hook', 'Turn', 'Why', 'Landing'])
  })

  it('returns untemplated text unchanged when no outline exists', () => {
    expect(applyTemplateOutline('Hand written.', [])).toBe('Hand written.')
  })
})

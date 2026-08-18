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
    await wrapper.get('article .document-foot .primary').trigger('click')
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

    await wrapper.get('.rail-title .primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain("Using Philosophy Daily's template")
    for (const section of CHANNEL.script_template.sections) {
      expect(wrapper.text()).toContain(section)
    }

    await wrapper.get('.document-foot .primary').trigger('click')
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
    await wrapper.get('.rail-title .primary').trigger('click')
    await flushPromises()

    const ideaTab = wrapper.findAll('[role="tab"]').find(button => button.text().includes('Topic to Idea'))
    await ideaTab.trigger('click')
    await wrapper.get('#idea-input').setValue('Why old arguments replay in our heads')
    await wrapper.get('.document-foot .primary').trigger('click')
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
    await wrapper.get('.rail-title .primary').trigger('click')
    await flushPromises()

    const pasteTab = wrapper.findAll('[role="tab"]').find(button => button.text().includes('Paste'))
    await pasteTab.trigger('click')
    await wrapper.get('#paste-script').setValue(pasted)
    await wrapper.get('.document-foot .primary').trigger('click')
    await flushPromises()

    expect(scriptApi.generateScript).not.toHaveBeenCalled()
    expect(scriptApi.createScript).toHaveBeenCalledWith(expect.objectContaining({
      body: pasted,
      origin: 'paste',
    }))
  })
})

describe('Script Studio step 3.3 narration', () => {
  it('defaults to Channel voice and shows processing values as inherited', async () => {
    const wrapper = await mountPage()

    expect(wrapper.get('[aria-label="Narration voice"]').element.value).toBe('Alex')
    expect(wrapper.get('[aria-label="Remove silence override"]').classes()).toContain('inherited')
    expect(wrapper.get('[aria-label="Narration speed override"]').classes()).toContain('inherited')
    expect(wrapper.text()).toContain('Inherited · On')
    expect(wrapper.text()).toContain('Inherited · 1.10×')
  })

  it('generates with explicit overrides and renders the returned audio player', async () => {
    const ready = {
      ...DOCUMENT,
      version: 3,
      narration: {
        state: 'ready', voice: 'Ashley', remove_silence: false, speed: 1.25,
        duration_s: 12.4, audio_artifact_id: 'art_AAAAAA',
      },
    }
    scriptApi.generateNarration.mockResolvedValue({ script: ready, narration_audio: {} })
    const wrapper = await mountPage()

    await wrapper.get('[aria-label="Narration voice"]').setValue('Ashley')
    await wrapper.get('[aria-label="Remove silence override"]').setValue(false)
    await wrapper.get('[aria-label="Narration speed override"]').setValue(1.25)
    await wrapper.get('.narration-button').trigger('click')
    await flushPromises()

    expect(scriptApi.generateNarration).toHaveBeenCalledWith('scr_AAAAAA', {
      voice: 'Ashley', remove_silence: false, speed: 1.25, expected_version: 1,
    })
    expect(wrapper.get('audio').attributes('src')).toContain('art_AAAAAA')
    expect(wrapper.get('[aria-label="Remove silence override"]').classes()).not.toContain('inherited')
    expect(wrapper.text()).toContain('Regenerate narration')
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

  it('runs on demand and renders the overall grade and dimension detail', async () => {
    scriptApi.scoreScript.mockResolvedValue({ virality: VIRALITY, cached: false })
    const wrapper = await mountPage()

    expect(wrapper.get('[data-testid="virality-panel"]').text()).toContain('Virality score not run')
    await wrapper.get('[data-testid="virality-panel"] button').trigger('click')
    await flushPromises()

    expect(scriptApi.scoreScript).toHaveBeenCalledWith(DOCUMENT.id, DOCUMENT.body)
    expect(wrapper.get('[data-testid="virality-panel"]').text()).toContain('68')
    expect(wrapper.get('[data-testid="virality-panel"]').text()).toContain('solid')
    expect(wrapper.get('[data-testid="virality-dimensions"]').text()).toContain('Hook')
    expect(wrapper.get('[data-testid="virality-dimensions"]').text()).toContain('Open loops')
    expect(wrapper.get('[data-testid="virality-dimensions"]').text()).toContain('Open loops sparse')
  })

  it('scores unsaved text without disabling Save', async () => {
    scriptApi.scoreScript.mockResolvedValue({ virality: VIRALITY, cached: false })
    const wrapper = await mountPage()
    await wrapper.get('#script-body').setValue('Unsaved text can still be analyzed.')

    expect(wrapper.get('article .document-foot .primary').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="virality-panel"] button').trigger('click')
    await flushPromises()

    expect(scriptApi.scoreScript).toHaveBeenCalledWith(DOCUMENT.id, 'Unsaved text can still be analyzed.')
    expect(scriptApi.updateScript).not.toHaveBeenCalled()
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

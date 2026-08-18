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

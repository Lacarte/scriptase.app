/**
 * Step 6.7 — the prototype's `lib-*` and `exp-*` families, and the rule that
 * keeps them honest: the gallery is still whatever the backend returned.
 *
 * The prototype hardcodes a fixture of finished jobs with channel colours and
 * logos baked in. Nothing here does. Every figure in the stat run is counted
 * off the rows `/api/export/library` handed back, every card is one of those
 * rows, and the 48-hour line is the shared calendar's — the same component
 * Production draws its rows with.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'

const { apiGet, apiPost } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

vi.mock('@/shared/api/client.js', () => ({
  api: { get: apiGet, post: apiPost },
}))

const ExportCard = (await import('../components/ExportCard.vue')).default
const ExportDetailModal = (await import('../components/ExportDetailModal.vue')).default
const LibrarySearch = (await import('../components/LibrarySearch.vue')).default
const ExportLibraryPage = (await import('../views/ExportLibraryPage.vue')).default

// The modal teleports; without this, one test's overlay is still in the body
// when the next one queries it.
enableAutoUnmount(afterEach)

const HOUR = 3600000

function makeItem(overrides = {}) {
  return {
    project_id: 'pm_ONE',
    project_name: 'One',
    channel_id: 'ch_A',
    channel_name: 'Alpha Channel',
    video_name: 'one.mp4',
    video_relpath: 'pm_ONE/one.mp4',
    size_bytes: 1024,
    duration: 20,
    width: 1080,
    height: 1920,
    modified_at: new Date(Date.now() - HOUR).toISOString(),
    style: 'anime_manga',
    video_ratio: '1080:1920',
    scene_count: 4,
    audio_track_count: 2,
    caption_count: 12,
    media_counts: { image: 3, video: 1 },
    source_folder: 'pm_ONE',
    pipeline_timing: { tts: 12, scenes: 40, assemble: 8, total: 60 },
    preview_url: '/api/export/library/preview/pm_ONE/one.mp4',
    video_download_url: '/api/export/library/download/pm_ONE/one.mp4',
    zip_download_url: '/api/export/library/download/pm_ONE/one.zip',
    zip_source: 'file',
    ...overrides,
  }
}

const ITEMS = [
  makeItem(),
  makeItem({
    project_id: 'pm_TWO',
    channel_id: 'ch_B',
    channel_name: 'Beta Channel',
    video_name: 'two.mp4',
    video_relpath: 'pm_TWO/two.mp4',
    size_bytes: 4096,
    duration: 200,
    modified_at: new Date(Date.now() - 72 * HOUR).toISOString(),
    style: 'cyberpunk_neon',
    video_ratio: '1920:1080',
  }),
]

function readSource(relative) {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')
}

async function mountPage(query = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/library', name: 'library', component: ExportLibraryPage }],
  })
  await router.push({ path: '/library', query })
  await router.isReady()
  const wrapper = mount(ExportLibraryPage, { global: { plugins: [router] } })
  await flushPromises()
  await nextTick()
  return wrapper
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
  apiGet.mockResolvedValue({ items: ITEMS.map(item => ({ ...item })) })
  apiPost.mockResolvedValue({ ok: true })
})

describe('library fidelity — the lib-* family (step 6.7)', () => {
  it('draws the prototype shell, head and naked stat run', async () => {
    const wrapper = await mountPage()

    expect(wrapper.find('.lib-view .lib-inner').exists()).toBe(true)
    expect(wrapper.find('.lib-head h1').text()).toBe('Library')
    expect(wrapper.find('.lib-head .sub').exists()).toBe(true)
    expect(wrapper.find('.lib-head .spacer').exists()).toBe(true)

    // Each figure is a `.n` over its `.l`, and no panel or divider around them.
    const stats = wrapper.findAll('.lib-stats .lib-stat')
    expect(stats.length).toBeGreaterThan(3)
    expect(stats.map(stat => stat.find('.l').text()).slice(0, 4)).toEqual([
      'Videos', 'Channels', 'Total runtime', 'Archived',
    ])
    // Counted off the two rows the backend returned, not authored here.
    expect(stats[0].find('.n').text()).toBe('2')
    expect(stats[1].find('.n').text()).toBe('2')
    expect(stats[3].find('.n').text()).toBe('1')
  })

  it('puts the search and every filter in one lib-toolbar', async () => {
    const wrapper = await mountPage()
    const toolbar = wrapper.find('.lib-toolbar')

    expect(toolbar.exists()).toBe(true)
    expect(toolbar.find('.search-input').exists()).toBe(true)
    expect(toolbar.findAll('.f-select')).toHaveLength(5)
    expect(toolbar.find('.search-count').text()).toContain('2 videos')
  })

  it('builds each card from the prototype parts', async () => {
    const wrapper = await mountPage()
    const card = wrapper.findComponent(ExportCard)

    expect(card.classes()).toContain('lib-card')
    expect(card.find('.lib-thumb .cap').text()).toBe('pm_ONE')
    expect(card.find('.lib-thumb .dur').text()).toBe('0:20')
    expect(card.find('.lib-thumb .play').exists()).toBe(true)
    expect(card.find('.lib-body .t').text()).toBe('pm_ONE')
    // The avatar is the channel's own initials — the export row carries no art.
    expect(card.find('.lib-body .m .cav').text()).toBe('AC')
    expect(card.find('.lib-body .m').text()).toContain('Alpha Channel')
    expect(card.findAll('.lib-actions .btn').map(button => button.text())).toEqual(['Editor', 'Export'])
  })

  it('badges a card the calendar calls archived, and only that one', async () => {
    const wrapper = await mountPage()
    await wrapper.find('.search-input').setValue('two.mp4')
    await flushPromises()

    const archived = wrapper.findComponent(ExportCard)
    expect(archived.find('.lib-badge-arch').text()).toBe('archived')

    await wrapper.find('.search-input').setValue('one.mp4')
    await flushPromises()
    expect(wrapper.findComponent(ExportCard).find('.lib-badge-arch').exists()).toBe(false)
  })

  it('flashes the card named by ?project= rather than pulsing it forever', async () => {
    const wrapper = await mountPage({ project: 'pm_ONE' })

    const flashed = wrapper.findAll('.lib-card.lib-flash')
    expect(flashed).toHaveLength(1)
    expect(flashed[0].text()).toContain('pm_ONE')
  })

  it('lays the gallery out on lib-grid, inside the shared calendar', async () => {
    const wrapper = await mountPage()

    // The track is the Library's; the markup and the 48-hour line are the
    // calendar's, which is what Production draws its rows with.
    expect(wrapper.find('.archive-calendar .archive-items.lib-grid').exists()).toBe(true)
    expect(wrapper.find('.archive-strip .calendar-cell').exists()).toBe(true)
    // Older than 48h, so it is behind a date cell rather than in the gallery.
    expect(wrapper.findAllComponents(ExportCard)).toHaveLength(1)
  })

  it('says the prototype’s empty state instead of drawing an empty grid', async () => {
    apiGet.mockResolvedValueOnce({ items: [] })
    const wrapper = await mountPage()

    expect(wrapper.find('.lib-empty h3').text()).toBe('No videos found')
    expect(wrapper.find('.archive-calendar').exists()).toBe(false)
  })
})

/* The modal teleports to the body, so it is read there rather than through the
   wrapper's own subtree — the same way the delete dialog is. */
function one(selector) {
  return document.querySelector(selector)
}

function all(selector) {
  return [...document.querySelectorAll(selector)].map(el => el.textContent.trim())
}

describe('library fidelity — the exp-* family (step 6.7)', () => {
  function mountModal(item = makeItem()) {
    return mount(ExportDetailModal, { props: { item } })
  }

  it('opens the prototype export modal from a card, and closes again', async () => {
    const wrapper = await mountPage()
    expect(one('.export-modal')).toBeNull()

    await wrapper.find('.lib-card').trigger('click')
    await nextTick()

    expect(one('.exp-head .et .t').textContent.trim()).toBe('Library · pm_ONE')
    one('.exp-close').click()
    await nextTick()
    expect(one('.export-modal')).toBeNull()
    wrapper.unmount()
  })

  it('builds the head, preview and configuration from the prototype parts', async () => {
    const wrapper = mountModal()
    await nextTick()

    expect(one('.exp-head .ei')).not.toBeNull()
    expect(one('.exp-head .et .s').textContent).toContain('one.mp4')
    expect(one('.exp-close')).not.toBeNull()

    expect(one('.exp-body .exp-preview .exp-thumb .cap').textContent.trim()).toBe('pm_ONE')
    expect(one('.exp-thumb .dur').textContent.trim()).toBe('0:20')
    expect(one('.exp-thumb .play')).not.toBeNull()
    // The preview keeps the export's own shape, reduced from its pixel size.
    expect(one('.exp-thumb').getAttribute('style')).toContain('9 / 16')
    expect(one('.exp-thumb-note').textContent.trim()).toBe('FINAL RENDER · 9:16')

    expect(all('.exp-cfg .exp-sec .h')).toEqual(['Output', 'Pipeline timing', 'Destination'])
    expect(all('.exp-cfg .exp-sec:first-child .exp-kv .k')).toEqual([
      'Resolution', 'Ratio', 'Duration', 'Style', 'Scenes', 'Media', 'Audio', 'Captions', 'Exported',
    ])
    expect(one('.exp-kv .v.mono').textContent.trim()).toBe('1080x1920')

    wrapper.unmount()
  })

  it('hands over the play overlay to real controls', async () => {
    const wrapper = mountModal()
    await nextTick()

    expect(one('video').hasAttribute('controls')).toBe(false)
    one('.exp-thumb .play').click()
    await nextTick()

    expect(one('.exp-thumb .play')).toBeNull()
    expect(one('video').hasAttribute('controls')).toBe(true)
    wrapper.unmount()
  })

  it('names the managed relative path, never an absolute one', async () => {
    const wrapper = mountModal()
    await nextTick()

    expect(one('.exp-path .p').textContent.trim()).toBe('pm_ONE/one.mp4')
    expect(one('.exp-size-note b').textContent.trim()).toBe('1.0 KB')
    wrapper.unmount()
  })

  it('carries every action the card gave up, in the prototype foot', async () => {
    const wrapper = mountModal()
    await nextTick()

    expect(one('.exp-foot .spacer')).not.toBeNull()
    expect(all('.exp-foot .btn')).toEqual([
      'Open in Editor', 'Project ZIP', 'Delete', 'Close', 'Download',
    ])

    const [editor, zip, trash, , download] = document.querySelectorAll('.exp-foot .btn')
    editor.click()
    zip.click()
    trash.click()
    download.click()
    await nextTick()

    expect(wrapper.emitted('editor')).toHaveLength(1)
    expect(wrapper.emitted('download-zip')).toHaveLength(1)
    expect(wrapper.emitted('trash')).toHaveLength(1)
    expect(wrapper.emitted('export')).toHaveLength(1)
    wrapper.unmount()
  })

  it('drops the ZIP action when the export has none', async () => {
    const wrapper = mountModal(makeItem({ zip_download_url: '' }))
    await nextTick()

    expect(all('.exp-foot .btn')).toEqual(['Open in Editor', 'Delete', 'Close', 'Download'])
    wrapper.unmount()
  })

  it('draws the pipeline the run reported, in one tone', async () => {
    const wrapper = mountModal()
    await nextTick()

    expect(all('.timing-step .timing-label')).toEqual(['TTS', 'Scenes', 'Assemble'])
    // The longest step fills the track; the rest are read against it.
    const bars = document.querySelectorAll('.timing-step .timing-bar-fill')
    expect(bars[1].getAttribute('style')).toContain('width: 100%')
    expect(one('.timing-total .v').textContent.trim()).toBe('1m 0s')
    wrapper.unmount()
  })

  it('omits the pipeline section when the export recorded no timing', async () => {
    const wrapper = mountModal(makeItem({ pipeline_timing: null }))
    await nextTick()

    expect(all('.exp-sec .h')).toEqual(['Output', 'Destination'])
    wrapper.unmount()
  })
})

describe('library fidelity — no palette and no fixture of its own', () => {
  it('holds no hardcoded colour', () => {
    for (const file of [
      '../views/ExportLibraryPage.vue',
      '../components/ExportCard.vue',
      '../components/ExportDetailModal.vue',
      '../components/LibrarySearch.vue',
    ]) {
      const source = readSource(file)
      // White and pure black over a video frame are the prototype's own, and
      // are the only literals it uses outside the token set.
      const literals = source.match(/#[0-9a-fA-F]{3,8}\b/g) || []
      expect(literals.filter(value => value.toLowerCase() !== '#fff')).toEqual([])
    }
  })

  it('leaves the 48-hour line to the shared calendar', () => {
    const page = readSource('../views/ExportLibraryPage.vue')
    expect(page).toContain('ArchiveCalendar')
    // No second copy of the archive threshold, and no local date grouping.
    expect(page).not.toMatch(/archive-?after-?hours/i)
    expect(page).not.toContain('openDates')
  })

  it('keeps the calendar ignorant of the Library’s vocabulary', () => {
    const calendar = readSource('../../../shared/components/ArchiveCalendar.vue')
    // It renders the Library's track by name from a prop, and knows nothing
    // about exports — which is what lets Production draw rows with it.
    expect(calendar).toContain('itemsClass')
    expect(calendar).not.toContain('lib-')
    expect(calendar).not.toContain('video_relpath')
  })
})

describe('LibrarySearch is still controlled by the page', () => {
  it('emits rather than filtering anything itself', async () => {
    const wrapper = mount(LibrarySearch, {
      props: { items: ITEMS, styleOptions: ['', 'anime_manga'], filteredCount: 2 },
    })

    await wrapper.findAll('.f-select')[2].setValue('anime_manga')
    expect(wrapper.emitted('update:filterStyle').at(-1)).toEqual(['anime_manga'])
  })
})

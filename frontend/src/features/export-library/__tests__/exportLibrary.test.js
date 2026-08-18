import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'

// Step 14.3 — the library is idiomatic Vue with no legacy bridge, so the parts
// worth pinning are the ones that decide what the user sees: the filter/sort
// projection, the SSE folder sync state machine, and the trash round trip.

const { apiGet, apiPost } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

vi.mock('@/shared/api/client.js', () => ({
  api: { get: apiGet, post: apiPost },
}))

const { useExportLibrary, aspectRatioFromDimensions } = await import(
  '../composables/useExportLibrary.js'
)
const ExportCard = (await import('../components/ExportCard.vue')).default
const LibrarySearch = (await import('../components/LibrarySearch.vue')).default
const DeleteExportDialog = (await import('../components/DeleteExportDialog.vue')).default
const ExportLibraryPage = (await import('../views/ExportLibraryPage.vue')).default

const HOUR = 3600000

function makeItem(overrides = {}) {
  return {
    project_id: 'pm_ONE',
    project_name: 'One',
    video_name: 'one.mp4',
    video_relpath: 'pm_ONE/one.mp4',
    size_bytes: 1024,
    duration: 20,
    modified_at: new Date(Date.now() - HOUR).toISOString(),
    style: 'anime_manga',
    video_ratio: '1080:1920',
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
    video_name: 'two.mp4',
    video_relpath: 'pm_TWO/two.mp4',
    size_bytes: 4096,
    duration: 200,
    modified_at: new Date(Date.now() - 48 * HOUR).toISOString(),
    style: 'cyberpunk_neon',
    video_ratio: '1920:1080',
  }),
  makeItem({
    project_id: 'pm_THREE',
    video_name: 'three.mp4',
    video_relpath: 'pm_THREE/three.mp4',
    size_bytes: 2048,
    duration: 5,
    modified_at: new Date(Date.now() - 4 * HOUR).toISOString(),
    style: '',
    video_ratio: '1080:1080',
  }),
]

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
  apiGet.mockResolvedValue({ items: ITEMS.map(i => ({ ...i })) })
  apiPost.mockResolvedValue({ ok: true })
})

describe('aspect ratio from pixel dimensions', () => {
  it('reduces dimensions by their greatest common divisor', () => {
    expect(aspectRatioFromDimensions('1920:1080')).toBe('16:9')
    expect(aspectRatioFromDimensions('1080:1920')).toBe('9:16')
    expect(aspectRatioFromDimensions('1080:1080')).toBe('1:1')
  })

  it('returns empty for anything it cannot parse', () => {
    expect(aspectRatioFromDimensions('')).toBe('')
    expect(aspectRatioFromDimensions('1920')).toBe('')
    expect(aspectRatioFromDimensions('0:1080')).toBe('')
  })
})

describe('library projection', () => {
  it('loads the library and derives the filter option lists', async () => {
    const lib = useExportLibrary()
    await lib.fetchLibrary()

    expect(apiGet).toHaveBeenCalledWith('/api/export/library')
    expect(lib.items.value).toHaveLength(3)
    // A leading '' is the "all" option; the rest are the values actually present.
    expect(lib.styleOptions.value).toEqual(['', 'anime_manga', 'cyberpunk_neon'])
    expect(lib.ratioOptions.value).toEqual(['', '1080:1080', '1080:1920', '1920:1080'])
  })

  it('sorts newest first by default and honours every other sort', async () => {
    const lib = useExportLibrary()
    await lib.fetchLibrary()

    expect(lib.filteredItems.value.map(i => i.project_id)).toEqual(['pm_ONE', 'pm_THREE', 'pm_TWO'])

    lib.sortBy.value = 'longest'
    expect(lib.filteredItems.value.map(i => i.project_id)).toEqual(['pm_TWO', 'pm_ONE', 'pm_THREE'])

    lib.sortBy.value = 'smallest'
    expect(lib.filteredItems.value.map(i => i.project_id)).toEqual(['pm_ONE', 'pm_THREE', 'pm_TWO'])
  })

  it('filters by style, ratio, duration bucket, and free text', async () => {
    const lib = useExportLibrary()
    await lib.fetchLibrary()

    lib.filterStyle.value = 'cyberpunk_neon'
    expect(lib.filteredItems.value.map(i => i.project_id)).toEqual(['pm_TWO'])
    lib.filterStyle.value = ''

    lib.filterRatio.value = '1080:1080'
    expect(lib.filteredItems.value.map(i => i.project_id)).toEqual(['pm_THREE'])
    lib.filterRatio.value = ''

    lib.filterDuration.value = '0-15'
    expect(lib.filteredItems.value.map(i => i.project_id)).toEqual(['pm_THREE'])
    lib.filterDuration.value = '180+'
    expect(lib.filteredItems.value.map(i => i.project_id)).toEqual(['pm_TWO'])
    lib.filterDuration.value = ''

    lib.searchQuery.value = 'two'
    expect(lib.filteredItems.value.map(i => i.project_id)).toEqual(['pm_TWO'])
  })

  it('surfaces a fetch failure without wiping the previous list', async () => {
    const lib = useExportLibrary()
    await lib.fetchLibrary()

    apiGet.mockRejectedValueOnce(new Error('backend down'))
    await lib.fetchLibrary()

    expect(lib.error.value).toBe('backend down')
    expect(lib.loading.value).toBe(false)
    expect(lib.items.value).toHaveLength(3)
  })
})

describe('trash', () => {
  it('posts the relative path and drops the row on success', async () => {
    const lib = useExportLibrary()
    await lib.fetchLibrary()

    const deleted = await lib.trashVideo(lib.items.value[1])

    expect(deleted).toBe(true)
    expect(apiPost).toHaveBeenCalledWith('/api/export/library/trash', {
      body: { video_relpath: 'pm_TWO/two.mp4' },
    })
    expect(lib.items.value.map(i => i.project_id)).toEqual(['pm_ONE', 'pm_THREE'])
  })

  it('keeps the row when the backend refuses', async () => {
    const lib = useExportLibrary()
    await lib.fetchLibrary()
    apiPost.mockRejectedValueOnce(new Error('locked'))

    expect(await lib.trashVideo(lib.items.value[0])).toBe(false)
    expect(lib.items.value).toHaveLength(3)
  })

  it('refuses an item with no relative path rather than guessing', async () => {
    const lib = useExportLibrary()

    expect(await lib.trashVideo({ video_name: 'orphan.mp4' })).toBe(false)
    expect(apiPost).not.toHaveBeenCalled()
  })
})

describe('folder sync', () => {
  let opened

  beforeEach(() => {
    opened = []
    vi.stubGlobal('EventSource', class {
      constructor(url) {
        this.url = url
        this.onmessage = null
        this.onerror = null
        this.closed = false
        opened.push(this)
      }
      send(payload) { this.onmessage?.({ data: JSON.stringify(payload) }) }
      close() { this.closed = true }
    })
  })

  it('counts copies and skips, then reports the outcome', async () => {
    const lib = useExportLibrary()
    lib.syncToFolder()

    const es = opened[0]
    expect(es.url).toBe('/api/export/library/sync')
    expect(lib.syncing.value).toBe(true)

    es.send({ phase: 'copying', file: 'one.mp4', index: 1, total: 2, size: 1024 })
    expect(lib.syncProgress.value).toMatchObject({ phase: 'copying', file: 'one.mp4', size: 1024 })

    es.send({ phase: 'copied', file: 'one.mp4', index: 1, total: 2 })
    es.send({ phase: 'skip', file: 'two.mp4', index: 2, total: 2 })
    expect(lib.syncProgress.value).toMatchObject({ copied: 1, skipped: 1 })

    es.send({ phase: 'done', copied: 1, skipped: 1, total: 2 })
    expect(lib.syncing.value).toBe(false)
    expect(es.closed).toBe(true)
    expect(lib.syncProgress.value).toMatchObject({ done: true, doneResult: 'copied' })
  })

  it('calls a skip-only run up to date, and an empty run empty', () => {
    const uptodate = useExportLibrary()
    uptodate.syncToFolder()
    opened[0].send({ phase: 'done', copied: 0, skipped: 3, total: 3 })
    expect(uptodate.syncProgress.value.doneResult).toBe('uptodate')

    const empty = useExportLibrary()
    empty.syncToFolder()
    opened[1].send({ phase: 'done', copied: 0, skipped: 0, total: 0 })
    expect(empty.syncProgress.value.doneResult).toBe('empty')
  })

  it('closes the stream and clears progress on a backend error', () => {
    const lib = useExportLibrary()
    lib.syncToFolder()

    opened[0].send({ phase: 'error', message: 'No sync folder configured. Set it in Settings.' })

    expect(opened[0].closed).toBe(true)
    expect(lib.syncing.value).toBe(false)
    expect(lib.syncProgress.value).toBeNull()
  })

  it('refuses to open a second stream while one is running', () => {
    const lib = useExportLibrary()
    lib.syncToFolder()
    lib.syncToFolder()

    expect(opened).toHaveLength(1)
  })
})

describe('ExportCard', () => {
  it('shows the metadata the library promises, and both downloads', async () => {
    const wrapper = mount(ExportCard, { props: { item: makeItem() } })
    await nextTick()

    const text = wrapper.text()
    expect(text).toContain('pm_ONE')
    expect(text).toContain('one.mp4')
    expect(text).toContain('Anime Manga')
    expect(text).toContain('1.0 KB')
    // 1080:1920 pixels reduced to its aspect ratio.
    expect(text).toContain('9:16')
    expect(text).toContain('0:20')

    const labels = wrapper.findAll('.dl-btn').map(b => b.text())
    expect(labels).toEqual(['Video', 'Project ZIP', 'Delete'])
  })

  it('hides the ZIP button when the export has none', () => {
    const wrapper = mount(ExportCard, { props: { item: makeItem({ zip_download_url: '' }) } })
    expect(wrapper.findAll('.dl-btn').map(b => b.text())).toEqual(['Video', 'Delete'])
  })

  it('emits the item for each action', async () => {
    const wrapper = mount(ExportCard, { props: { item: makeItem() } })
    const [video, zip, del] = wrapper.findAll('.dl-btn')

    await video.trigger('click')
    await zip.trigger('click')
    await del.trigger('click')

    expect(wrapper.emitted('download-video')[0][0].project_id).toBe('pm_ONE')
    expect(wrapper.emitted('download-zip')).toHaveLength(1)
    expect(wrapper.emitted('trash')).toHaveLength(1)
  })
})

describe('LibrarySearch', () => {
  it('debounces the blur so a suggestion click still lands', async () => {
    vi.useFakeTimers()
    const wrapper = mount(LibrarySearch, {
      props: { items: ITEMS, styleOptions: ['', 'anime_manga'], filteredCount: 3 },
    })

    const input = wrapper.find('.search-input')
    await input.setValue('anime')
    await input.trigger('focus')
    await nextTick()
    expect(wrapper.find('.search-suggestions').exists()).toBe(true)

    await input.trigger('blur')
    await nextTick()
    // Still open on the tick after blur — this is the bug V2 shipped, where an
    // inline setTimeout in the template resolved against the component.
    expect(wrapper.find('.search-suggestions').exists()).toBe(true)

    vi.advanceTimersByTime(250)
    await nextTick()
    expect(wrapper.find('.search-suggestions').exists()).toBe(false)
    vi.useRealTimers()
  })

  it('promotes a style suggestion to a filter and clears everything on demand', async () => {
    const wrapper = mount(LibrarySearch, {
      props: { items: ITEMS, styleOptions: ['', 'anime_manga'], filteredCount: 3 },
    })

    const input = wrapper.find('.search-input')
    await input.setValue('anime')
    await input.trigger('focus')
    await nextTick()

    await wrapper.find('.search-sug-item').trigger('mousedown')
    expect(wrapper.emitted('update:filterStyle').at(-1)).toEqual(['anime_manga'])

    // The filters are controlled props, so the parent owns the round trip.
    await wrapper.setProps({ filterStyle: 'anime_manga' })
    await wrapper.find('.clear-all-btn').trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })
})

describe('ExportLibraryPage', () => {
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

  it('lists every export with its stats bar', async () => {
    const wrapper = await mountPage()

    expect(wrapper.findAllComponents(ExportCard)).toHaveLength(2)
    expect(wrapper.find('.calendar-cell').exists()).toBe(true)
    const stats = wrapper.find('.stats-bar').text()
    expect(stats).toContain('3')
    expect(stats).toContain('Exports')
    // 20 + 200 + 5 seconds of finished video.
    expect(stats).toContain('3:45')
  })

  it('says so when the library is empty rather than rendering an empty grid', async () => {
    apiGet.mockResolvedValueOnce({ items: [] })
    const wrapper = await mountPage()

    expect(wrapper.find('.export-grid').exists()).toBe(false)
    expect(wrapper.text()).toContain('No exported videos found yet')
    expect(wrapper.find('.sync-btn').attributes('disabled')).toBeDefined()
  })

  it('reports a backend failure in place of the grid', async () => {
    apiGet.mockRejectedValueOnce(new Error('exports unreadable'))
    const wrapper = await mountPage()

    expect(wrapper.find('.state-error').text()).toBe('exports unreadable')
  })

  it('highlights the export named by ?project=', async () => {
    const wrapper = await mountPage({ project: 'pm_TWO' })

    const highlighted = wrapper.findAll('.export-card.highlighted')
    expect(highlighted).toHaveLength(1)
    expect(highlighted[0].text()).toContain('pm_TWO')
  })

  it('finds a collapsed archived video by name before its date is opened', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).not.toContain('two.mp4')

    await wrapper.find('.search-input').setValue('two.mp4')
    await flushPromises()

    expect(wrapper.find('.archive-strip').exists()).toBe(false)
    expect(wrapper.findComponent(ExportCard).text()).toContain('two.mp4')
    expect(wrapper.text()).toContain('Found in archive · 1')
  })

  it('opens the delete dialog before trashing anything', async () => {
    const wrapper = await mountPage()

    await wrapper.findAllComponents(ExportCard)[0].find('.dl-btn--danger').trigger('click')
    await nextTick()
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.findComponent(DeleteExportDialog).props('visible')).toBe(true)

    wrapper.findComponent(DeleteExportDialog).vm.$emit('confirm')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/export/library/trash', {
      body: { video_relpath: 'pm_ONE/one.mp4' },
    })
    expect(wrapper.findAllComponents(ExportCard)).toHaveLength(1)
    expect(wrapper.find('.calendar-cell').exists()).toBe(true)
  })
})

describe('DeleteExportDialog', () => {
  it('names the files at risk and confirms only on the danger button', async () => {
    const wrapper = mount(DeleteExportDialog, {
      props: { visible: true, item: makeItem(), deleting: false },
      attachTo: document.body,
    })
    await flushPromises()

    const text = document.body.textContent
    expect(text).toContain('one.mp4')
    expect(text).toContain('Project ZIP')

    await document.querySelector('.btn-danger').click()
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    wrapper.unmount()
  })

  it('stays put while a delete is in flight', async () => {
    const wrapper = mount(DeleteExportDialog, {
      props: { visible: true, item: makeItem(), deleting: true },
      attachTo: document.body,
    })
    await flushPromises()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(document.querySelector('.btn-danger').disabled).toBe(true)
    wrapper.unmount()
  })
})

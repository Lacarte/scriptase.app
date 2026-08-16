import { ref, readonly, computed } from 'vue'
import { api } from '@/shared/api/client.js'
import { useToast } from '@/shared/composables/useToast.js'

/* ── Helpers ───────────────────────────────────────── */

export function ratioLabel(ratio) {
  if (!ratio) return ''
  const map = {
    '16:9': '16:9', '9:16': '9:16', '1:1': '1:1',
    '4:3': '4:3', '3:4': '3:4', '4:5': '4:5',
    '21:9': '21:9',
  }
  return map[ratio] || ratio
}

/**
 * Convert pixel dimensions string (e.g. "1920:1080") to simplified aspect ratio (e.g. "16:9").
 * Returns '' if input is invalid.
 */
export function aspectRatioFromDimensions(dimStr) {
  if (!dimStr) return ''
  const parts = dimStr.split(':')
  if (parts.length !== 2) return ''
  const w = parseInt(parts[0], 10)
  const h = parseInt(parts[1], 10)
  if (!w || !h) return ''
  // GCD to simplify
  let a = w, b = h
  while (b) { [a, b] = [b, a % b] }
  return `${w / a}:${h / a}`
}

/* ── Duration filter buckets ───────────────────────── */

const DURATION_FILTERS = [
  { label: 'All durations', value: '' },
  { label: 'Under 15s',     value: '0-15' },
  { label: '15s – 30s',     value: '15-30' },
  { label: '30s – 1m',      value: '30-60' },
  { label: '1m – 3m',       value: '60-180' },
  { label: 'Over 3m',       value: '180+' },
]

/* ── Sort options ──────────────────────────────────── */

const SORT_OPTIONS = [
  { label: 'Newest first',   value: 'newest' },
  { label: 'Oldest first',   value: 'oldest' },
  { label: 'Longest first',  value: 'longest' },
  { label: 'Shortest first', value: 'shortest' },
  { label: 'Largest first',  value: 'largest' },
  { label: 'Smallest first', value: 'smallest' },
]

/* ── Composable ────────────────────────────────────── */

export function useExportLibrary() {
  const toast = useToast()

  const items = ref([])
  const loading = ref(false)
  const error = ref(null)

  // Filters
  const sortBy = ref('newest')
  const filterStyle = ref('')
  const filterRatio = ref('')
  const filterDuration = ref('')
  const searchQuery = ref('')

  /* ── Derived option lists from data ──────────────── */

  const styleOptions = computed(() => {
    const set = new Set()
    for (const item of items.value) {
      if (item.style) set.add(item.style)
    }
    return ['', ...Array.from(set).sort()]
  })

  const ratioOptions = computed(() => {
    const set = new Set()
    for (const item of items.value) {
      const r = item.video_ratio || item.ratio
      if (r) set.add(r)
    }
    return ['', ...Array.from(set).sort()]
  })

  /* ── Filtered + sorted items ─────────────────────── */

  const filteredItems = computed(() => {
    let list = [...items.value]

    // Text search
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      list = list.filter(i =>
        (i.project_id || '').toLowerCase().includes(q) ||
        (i.project_name || '').toLowerCase().includes(q) ||
        (i.video_name || '').toLowerCase().includes(q) ||
        (i.style || '').toLowerCase().includes(q)
      )
    }

    // Style filter
    if (filterStyle.value) {
      list = list.filter(i => i.style === filterStyle.value)
    }

    // Ratio filter
    if (filterRatio.value) {
      list = list.filter(i => (i.video_ratio || i.ratio) === filterRatio.value)
    }

    // Duration filter
    if (filterDuration.value) {
      const f = filterDuration.value
      list = list.filter(i => {
        const d = i.duration ?? 0
        if (f === '0-15')   return d < 15
        if (f === '15-30')  return d >= 15 && d < 30
        if (f === '30-60')  return d >= 30 && d < 60
        if (f === '60-180') return d >= 60 && d < 180
        if (f === '180+')   return d >= 180
        return true
      })
    }

    // Sort
    const s = sortBy.value
    list.sort((a, b) => {
      if (s === 'newest')   return new Date(b.modified_at) - new Date(a.modified_at)
      if (s === 'oldest')   return new Date(a.modified_at) - new Date(b.modified_at)
      if (s === 'longest')  return (b.duration ?? 0) - (a.duration ?? 0)
      if (s === 'shortest') return (a.duration ?? 0) - (b.duration ?? 0)
      if (s === 'largest')  return (b.size_bytes ?? 0) - (a.size_bytes ?? 0)
      if (s === 'smallest') return (a.size_bytes ?? 0) - (b.size_bytes ?? 0)
      return 0
    })

    return list
  })

  /* ── Fetch ───────────────────────────────────────── */

  async function fetchLibrary() {
    loading.value = true
    error.value = null
    try {
      const data = await api.get('/api/export/library')
      items.value = data.items || []
    } catch (e) {
      error.value = e.message || 'Failed to load export library'
      toast.error('Failed to load export library')
    } finally {
      loading.value = false
    }
  }

  /* ── Download helpers ────────────────────────────── */

  async function downloadFile(url, filename) {
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(`Download failed: ${res.status}`)
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = filename
      document.body.appendChild(a)
      a.click()
      setTimeout(() => {
        URL.revokeObjectURL(a.href)
        document.body.removeChild(a)
      }, 100)
      toast.success(`Downloaded ${filename}`)
    } catch (e) {
      toast.error(`Download failed: ${e.message}`)
    }
  }

  function downloadVideo(item) {
    if (!item.video_download_url) {
      toast.error('No video download URL available')
      return
    }
    const name = item.video_name || 'video.mp4'
    downloadFile(item.video_download_url, name)
  }

  function downloadZip(item) {
    const url = item.zip_download_url
    if (!url) {
      toast.error('No ZIP download available for this export')
      return
    }
    const name = (item.video_name || 'project').replace(/\.[^.]+$/, '') + '.zip'
    downloadFile(url, name)
  }

  /* ── Folder sync ─────────────────────────────────── */

  const syncing = ref(false)
  const syncProgress = ref(null)
  // syncProgress shape: { file, index, total, phase, copied, skipped, size, done, doneResult }

  function syncToFolder() {
    if (syncing.value) return
    syncing.value = true
    syncProgress.value = { file: '', index: 0, total: 0, phase: 'connecting', copied: 0, skipped: 0, size: 0, done: false, doneResult: null }
    let finished = false
    let copiedCount = 0
    let skippedCount = 0

    const es = new EventSource('/api/export/library/sync')

    es.onmessage = (e) => {
      const d = JSON.parse(e.data)

      if (d.phase === 'copying') {
        syncProgress.value = { ...syncProgress.value, file: d.file, index: d.index, total: d.total, phase: 'copying', size: d.size || 0, copied: copiedCount, skipped: skippedCount, done: false }
      } else if (d.phase === 'copied') {
        copiedCount++
        syncProgress.value = { ...syncProgress.value, file: d.file, index: d.index, total: d.total, phase: 'copied', copied: copiedCount, skipped: skippedCount, done: false }
      } else if (d.phase === 'skip') {
        skippedCount++
        syncProgress.value = { ...syncProgress.value, file: d.file, index: d.index, total: d.total, phase: 'skip', copied: copiedCount, skipped: skippedCount, done: false }
      } else if (d.phase === 'error') {
        finished = true
        es.close()
        syncing.value = false
        syncProgress.value = null
        toast.error(d.message || 'Sync failed')
      } else if (d.phase === 'done') {
        finished = true
        es.close()
        syncing.value = false
        syncProgress.value = { ...syncProgress.value, phase: 'done', done: true, copied: d.copied, skipped: d.skipped, total: d.total, doneResult: d.copied > 0 ? 'copied' : d.skipped > 0 ? 'uptodate' : 'empty' }
        setTimeout(() => { syncProgress.value = null }, 4000)
      }
    }

    es.onerror = () => {
      es.close()
      if (!finished) {
        syncing.value = false
        syncProgress.value = null
        toast.error('Sync connection lost')
      }
    }
  }

  /* ── Trash ───────────────────────────────────────── */

  async function trashVideo(item) {
    if (!item.video_relpath) {
      toast.error('Cannot identify file to delete')
      return false
    }
    try {
      await api.post('/api/export/library/trash', { body: { video_relpath: item.video_relpath } })
      // Remove from local list
      const idx = items.value.findIndex(i => i.video_relpath === item.video_relpath)
      if (idx !== -1) items.value.splice(idx, 1)
      toast.success(`Moved "${item.video_name}" to trash`)
      return true
    } catch (e) {
      toast.error(`Failed to trash: ${e.message}`)
      return false
    }
  }

  return {
    // State
    items: readonly(items),
    loading: readonly(loading),
    error: readonly(error),

    // Filters
    sortBy,
    filterStyle,
    filterRatio,
    filterDuration,
    searchQuery,
    filteredItems,

    // Options
    SORT_OPTIONS,
    DURATION_FILTERS,
    styleOptions,
    ratioOptions,

    // Sync
    syncing: readonly(syncing),
    syncProgress: readonly(syncProgress),
    syncToFolder,

    // Actions
    fetchLibrary,
    downloadVideo,
    downloadZip,
    trashVideo,
  }
}

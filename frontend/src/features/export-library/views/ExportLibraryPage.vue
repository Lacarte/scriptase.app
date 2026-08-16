<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ExportCard from '../components/ExportCard.vue'
import DeleteExportDialog from '../components/DeleteExportDialog.vue'
import LibraryAnalytics from '../components/LibraryAnalytics.vue'
import LibrarySearch from '../components/LibrarySearch.vue'
import { useExportLibrary, aspectRatioFromDimensions } from '../composables/useExportLibrary.js'
import { formatBytes, fmtDuration } from '@/shared/utils/format.js'

defineOptions({ name: 'ExportLibraryPage' })

const route = useRoute()
const router = useRouter()

const {
  items,
  loading,
  error,
  sortBy,
  filterStyle,
  filterRatio,
  filterDuration,
  searchQuery,
  filteredItems,
  SORT_OPTIONS,
  DURATION_FILTERS,
  styleOptions,
  ratioOptions,
  fetchLibrary,
  downloadVideo,
  downloadZip,
  trashVideo,
  syncing,
  syncProgress,
  syncToFolder,
} = useExportLibrary()

const cardRefs = ref([])
const highlightedItemKey = ref('')
const focusedQueryKey = ref('')
const pendingTrashItem = ref(null)
const trashing = ref(false)
let highlightTimer = null

function setCardRef(el, idx) {
  cardRefs.value[idx] = el || null
}

function handlePlay(videoEl) {
  for (const card of cardRefs.value) {
    if (card && card.videoEl !== videoEl) card.stopPlayback()
  }
}

function handleTrash(item) {
  pendingTrashItem.value = item
}

function closeTrashDialog() {
  if (trashing.value) return
  pendingTrashItem.value = null
}

async function confirmTrash() {
  if (!pendingTrashItem.value || trashing.value) return

  trashing.value = true
  const item = pendingTrashItem.value
  const deleted = await trashVideo(item)
  trashing.value = false
  if (!deleted) return

  const key = itemKey(item)
  if (highlightedItemKey.value === key) {
    highlightedItemKey.value = ''
  }
  pendingTrashItem.value = null
}

function clearFilters() {
  filterStyle.value = ''
  filterRatio.value = ''
  filterDuration.value = ''
}

function itemKey(item) {
  return item?.video_relpath || `${item?.project_id || ''}::${item?.video_name || ''}`
}

function clearHighlightLater(key) {
  if (highlightTimer) window.clearTimeout(highlightTimer)
  highlightTimer = window.setTimeout(() => {
    if (highlightedItemKey.value === key) highlightedItemKey.value = ''
  }, 5000)
}

async function focusRequestedExport() {
  const projectId = typeof route.query.project === 'string' ? route.query.project : ''
  const exportName = typeof route.query.export === 'string' ? route.query.export : ''
  const queryKey = `${projectId}::${exportName}`
  if ((!projectId && !exportName) || !filteredItems.value.length || focusedQueryKey.value === queryKey) return

  let index = -1
  if (exportName) index = filteredItems.value.findIndex(item => item.video_name === exportName)
  if (index < 0 && projectId) index = filteredItems.value.findIndex(item => item.project_id === projectId)
  if (index < 0) return

  await nextTick()
  const card = cardRefs.value[index]
  const rootEl = card?.cardRootEl?.value || card?.cardRootEl
  if (!rootEl) return

  const key = itemKey(filteredItems.value[index])
  focusedQueryKey.value = queryKey
  highlightedItemKey.value = key
  if (typeof rootEl.scrollIntoView === 'function') rootEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
  if (typeof rootEl.focus === 'function') rootEl.focus({ preventScroll: true })
  clearHighlightLater(key)

  const nextQuery = { ...route.query }
  delete nextQuery.project
  delete nextQuery.export
  router.replace({ query: nextQuery }).catch(() => {})
}

watch(
  [filteredItems, () => route.query.project, () => route.query.export],
  () => { void focusRequestedExport() },
  { flush: 'post' }
)

onMounted(async () => {
  await fetchLibrary()
  await focusRequestedExport()
})

onBeforeUnmount(() => {
  if (highlightTimer) window.clearTimeout(highlightTimer)
})

// --- Style helpers ---
function styleLabel(id) {
  if (!id) return ''
  return id.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function styleColor(id) {
  if (!id) return 'var(--text-muted)'
  const map = {
    cinematic_realistic: '#4ECDC4', anime_manga: '#FF6B6B',
    watercolor_dreamy: '#A78BFA', pop_art_bold: '#FFB347', minimalist_clean: '#56CCF2',
  }
  return map[id] || 'var(--text-muted)'
}

// --- Extended stats ---
const extendedStats = computed(() => {
  const all = items.value
  const now = Date.now()
  const DAY = 86400000

  const totalDur = all.reduce((s, i) => s + (i.duration || 0), 0)
  const totalSize = all.reduce((s, i) => s + (i.size_bytes || 0), 0)
  const today = all.filter(i => i.modified_at && (now - new Date(i.modified_at).getTime()) < DAY).length
  const week = all.filter(i => i.modified_at && (now - new Date(i.modified_at).getTime()) < 7 * DAY).length

  const styleCounts = {}
  all.forEach(i => { if (i.style) styleCounts[i.style] = (styleCounts[i.style] || 0) + 1 })
  const topStyle = Object.entries(styleCounts).sort((a, b) => b[1] - a[1])[0]

  const ratioCounts = {}
  all.forEach(i => {
    const r = i.video_ratio || i.ratio
    if (r) ratioCounts[r] = (ratioCounts[r] || 0) + 1
  })
  const topRatio = Object.entries(ratioCounts).sort((a, b) => b[1] - a[1])[0]

  return { total: all.length, today, week, totalDur, totalSize, topStyle, topRatio }
})
</script>

<template>
  <div class="export-page">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h2 class="page-title">Export Library</h2>
        <p class="page-subtitle">Browse exported videos and download</p>
      </div>
      <div class="header-actions">
        <button class="sync-btn" :class="{ 'sync-btn--active': syncing }" :disabled="syncing || items.length === 0" @click="syncToFolder" title="Sync all exported videos to the configured folder. Duplicates are skipped.">
          <span class="sync-btn-icon" :class="{ spinning: syncing }">
            <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 014-4h14"/>
              <path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 01-4 4H3"/>
            </svg>
          </span>
          {{ syncing ? 'Syncing...' : 'Sync to Folder' }}
        </button>
        <button class="refresh-btn" :disabled="loading" @click="fetchLibrary">
          <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" :class="{ spinning: loading }">
            <path d="M23 4v6h-6" /><path d="M1 20v-6h6" />
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
          </svg>
          Refresh
        </button>
      </div>
    </div>

    <!-- Sync progress panel -->
    <Transition name="sync-panel">
      <div v-if="syncProgress" class="sync-panel" :class="{ 'sync-panel--done': syncProgress.done }">
        <!-- Left: icon + status -->
        <div class="sync-panel-left">
          <div class="sync-panel-icon" :class="[syncProgress.done ? 'sync-panel-icon--done' : 'sync-panel-icon--active']">
            <svg v-if="syncProgress.done && syncProgress.doneResult === 'copied'" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
            <svg v-else-if="syncProgress.done && syncProgress.doneResult === 'uptodate'" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            <svg v-else-if="syncProgress.done" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><line x1="5" y1="12" x2="19" y2="12"/></svg>
            <svg v-else width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" class="spinning">
              <path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 014-4h14"/>
              <path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 01-4 4H3"/>
            </svg>
          </div>
          <div class="sync-panel-status">
            <div class="sync-panel-title">
              <template v-if="syncProgress.done && syncProgress.doneResult === 'copied'">Sync complete</template>
              <template v-else-if="syncProgress.done && syncProgress.doneResult === 'uptodate'">Already up to date</template>
              <template v-else-if="syncProgress.done">Nothing to sync</template>
              <template v-else-if="syncProgress.phase === 'connecting'">Preparing sync...</template>
              <template v-else-if="syncProgress.phase === 'copying'">Copying file...</template>
              <template v-else-if="syncProgress.phase === 'copied'">Copied</template>
              <template v-else-if="syncProgress.phase === 'skip'">Skipped (exists)</template>
            </div>
            <div v-if="syncProgress.file" class="sync-panel-file">{{ syncProgress.file }}</div>
          </div>
        </div>

        <!-- Center: progress bar -->
        <div v-if="syncProgress.total > 0" class="sync-panel-center">
          <div class="sync-panel-bar-track">
            <div class="sync-panel-bar-fill" :class="{ 'sync-panel-bar-fill--done': syncProgress.done }" :style="{ width: (syncProgress.index / syncProgress.total * 100) + '%' }" />
          </div>
          <div class="sync-panel-meta">
            <span class="sync-panel-counter">{{ syncProgress.index }}<span class="sync-panel-counter-sep">/</span>{{ syncProgress.total }}</span>
            <span v-if="!syncProgress.done" class="sync-panel-size">{{ syncProgress.size ? formatBytes(syncProgress.size) : '' }}</span>
            <span v-if="syncProgress.done" class="sync-panel-summary">
              <template v-if="syncProgress.copied">{{ syncProgress.copied }} copied</template>
              <template v-if="syncProgress.copied && syncProgress.skipped"> · </template>
              <template v-if="syncProgress.skipped">{{ syncProgress.skipped }} skipped</template>
            </span>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Stats bar (compact) -->
    <div v-if="items.length" class="stats-bar">
      <div class="stat">
        <span class="stat-num" style="color: var(--accent)">{{ extendedStats.total }}</span>
        <span class="stat-lbl">Exports</span>
      </div>
      <span class="stat-divider"></span>
      <div class="stat">
        <span class="stat-num" :style="{ color: extendedStats.today > 0 ? '#26DE81' : 'var(--text-muted)' }">{{ extendedStats.today }}</span>
        <span class="stat-lbl">Today</span>
      </div>
      <span class="stat-divider"></span>
      <div class="stat">
        <span class="stat-num" style="color: #FFB347">{{ extendedStats.week }}</span>
        <span class="stat-lbl">This Week</span>
      </div>
      <span class="stat-divider"></span>
      <div class="stat">
        <span class="stat-num" style="color: #A78BFA">{{ fmtDuration(extendedStats.totalDur) }}</span>
        <span class="stat-lbl">Duration</span>
      </div>
      <span class="stat-divider"></span>
      <div class="stat">
        <span class="stat-num" style="color: var(--text-secondary)">{{ formatBytes(extendedStats.totalSize) }}</span>
        <span class="stat-lbl">Size</span>
      </div>
      <template v-if="extendedStats.topStyle">
        <span class="stat-divider"></span>
        <div class="stat">
          <span class="stat-num" :style="{ color: styleColor(extendedStats.topStyle[0]) }">{{ styleLabel(extendedStats.topStyle[0]) }}</span>
          <span class="stat-lbl">Top Style</span>
        </div>
      </template>
      <template v-if="extendedStats.topRatio">
        <span class="stat-divider"></span>
        <div class="stat">
          <span class="stat-num" style="color: #A78BFA">{{ aspectRatioFromDimensions(extendedStats.topRatio[0]) || extendedStats.topRatio[0] }}</span>
          <span class="stat-lbl">Top Ratio</span>
        </div>
      </template>
    </div>

    <!-- Analytics dashboard -->
    <LibraryAnalytics v-if="items.length" :items="items" />

    <!-- Search & Filter -->
    <LibrarySearch
      v-if="items.length"
      :items="items"
      :sort-by="sortBy"
      :filter-style="filterStyle"
      :filter-ratio="filterRatio"
      :filter-duration="filterDuration"
      :sort-options="SORT_OPTIONS"
      :duration-filters="DURATION_FILTERS"
      :style-options="styleOptions"
      :ratio-options="ratioOptions"
      :filtered-count="filteredItems.length"
      @update:sort-by="sortBy = $event"
      @update:filter-style="filterStyle = $event"
      @update:filter-ratio="filterRatio = $event"
      @update:filter-duration="filterDuration = $event"
      @search="searchQuery = $event"
      @clear="clearFilters"
    />

    <!-- States -->
    <div v-if="loading && items.length === 0" class="state-msg">Loading export library...</div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="!loading && items.length === 0" class="state-msg">No exported videos found yet.</div>
    <div v-else-if="items.length > 0 && filteredItems.length === 0" class="state-msg">No videos match the current filters.</div>

    <!-- Grid -->
    <div v-else class="export-grid">
      <ExportCard
        v-for="(item, idx) in filteredItems"
        :key="item.project_id + (item.video_relpath || idx)"
        :item="item"
        :highlighted="highlightedItemKey === itemKey(item)"
        :ref="(el) => setCardRef(el, idx)"
        @play="handlePlay"
        @download-video="downloadVideo"
        @download-zip="downloadZip"
        @trash="handleTrash"
      />
    </div>

    <DeleteExportDialog
      :visible="!!pendingTrashItem"
      :item="pendingTrashItem"
      :deleting="trashing"
      @close="closeTrashDialog"
      @confirm="confirmTrash"
    />
  </div>
</template>

<style scoped>
.export-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
}

/* ---- Header ---- */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text);
  margin: 0;
}

.page-subtitle {
  font-size: 12px;
  color: var(--text-muted);
  margin: 4px 0 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sync-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 15px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  border: 1px solid rgba(78, 205, 196, 0.3);
  border-radius: 8px;
  background: rgba(78, 205, 196, 0.06);
  color: var(--accent);
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  overflow: hidden;
}

.sync-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(78, 205, 196, 0.12), transparent 60%);
  opacity: 0;
  transition: opacity 0.2s;
}

.sync-btn:hover:not(:disabled)::before {
  opacity: 1;
}

.sync-btn:hover:not(:disabled) {
  border-color: var(--accent);
  box-shadow: 0 0 12px rgba(78, 205, 196, 0.12);
}

.sync-btn--active {
  border-color: var(--accent);
  background: rgba(78, 205, 196, 0.10);
}

.sync-btn-icon {
  display: flex;
  align-items: center;
}

.sync-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.refresh-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinning {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ---- Sync Panel ---- */
.sync-panel {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 18px;
  background: var(--bg-surface);
  border: 1px solid rgba(78, 205, 196, 0.2);
  border-radius: 10px;
  margin-bottom: 12px;
  position: relative;
  overflow: hidden;
}

.sync-panel::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--accent);
  border-radius: 3px 0 0 3px;
}

.sync-panel--done::before {
  background: var(--accent-ready);
}

/* Transition */
.sync-panel-enter-active {
  animation: sync-slide-in 0.25s ease-out;
}
.sync-panel-leave-active {
  animation: sync-slide-out 0.2s ease-in forwards;
}
@keyframes sync-slide-in {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes sync-slide-out {
  from { opacity: 1; transform: translateY(0); }
  to   { opacity: 0; transform: translateY(-6px); }
}

/* Left: icon + status */
.sync-panel-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  min-width: 0;
}

.sync-panel-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.sync-panel-icon--active {
  background: rgba(78, 205, 196, 0.1);
  color: var(--accent);
}

.sync-panel-icon--done {
  background: rgba(38, 222, 129, 0.1);
  color: var(--accent-ready);
}

.sync-panel-status {
  min-width: 0;
}

.sync-panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.2;
}

.sync-panel-file {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
  margin-top: 2px;
}

/* Center: progress */
.sync-panel-center {
  flex: 1;
  min-width: 0;
}

.sync-panel-bar-track {
  height: 3px;
  background: var(--bg-darkest);
  border-radius: 2px;
  overflow: hidden;
}

.sync-panel-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.sync-panel-bar-fill::after {
  content: '';
  position: absolute;
  right: 0;
  top: -1px;
  bottom: -1px;
  width: 20px;
  background: linear-gradient(90deg, transparent, rgba(78, 205, 196, 0.4));
  border-radius: 0 2px 2px 0;
  animation: sync-bar-pulse 1.5s ease-in-out infinite;
}

.sync-panel-bar-fill--done {
  background: var(--accent-ready);
}

.sync-panel-bar-fill--done::after {
  display: none;
}

@keyframes sync-bar-pulse {
  0%, 100% { opacity: 0.4; }
  50%      { opacity: 1; }
}

.sync-panel-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}

.sync-panel-counter {
  font-size: 11px;
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--accent);
  letter-spacing: -0.02em;
}

.sync-panel-counter-sep {
  color: var(--text-muted);
  opacity: 0.4;
  margin: 0 1px;
}

.sync-panel-size {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.sync-panel-summary {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--accent-ready);
  font-weight: 500;
}

/* ---- Stats Bar ---- */
.stats-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 12px;
  overflow-x: auto;
  flex-wrap: wrap;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 50px;
}

.stat-num {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
}

.stat-lbl {
  font-family: var(--font-mono);
  font-size: 8px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.stat-divider {
  width: 1px;
  height: 24px;
  background: var(--border);
  flex-shrink: 0;
}

/* (Filter bar moved to LibrarySearch component) */

/* ---- States ---- */
.state-msg {
  text-align: center;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
  padding: 48px 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.state-error {
  color: var(--coral);
  border-color: rgba(255, 107, 107, 0.3);
}

/* ---- Grid ---- */
.export-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
</style>

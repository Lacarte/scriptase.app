<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ExportCard from '../components/ExportCard.vue'
import DeleteExportDialog from '../components/DeleteExportDialog.vue'
import LibraryAnalytics from '../components/LibraryAnalytics.vue'
import LibrarySearch from '../components/LibrarySearch.vue'
import { useExportLibrary, aspectRatioFromDimensions } from '../composables/useExportLibrary.js'
import { formatBytes, fmtDuration } from '@/shared/utils/format.js'
import ArchiveCalendar from '@/shared/components/ArchiveCalendar.vue'
import { openAppWindow } from '@/shared/utils/openWindow.js'

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
  filterChannel,
  searchQuery,
  filteredItems,
  SORT_OPTIONS,
  DURATION_FILTERS,
  styleOptions,
  ratioOptions,
  channelOptions,
  fetchLibrary,
  downloadVideo,
  downloadZip,
  trashVideo,
  syncing,
  syncProgress,
  syncToFolder,
} = useExportLibrary()

const cardRefs = ref({})
const archiveCalendarRef = ref(null)
const highlightedItemKey = ref('')
const focusedQueryKey = ref('')
const pendingTrashItem = ref(null)
const trashing = ref(false)
let highlightTimer = null

function setCardRef(el, item) {
  const key = itemKey(item)
  if (el) cardRefs.value[key] = el
  else delete cardRefs.value[key]
}

function handlePlay(videoEl) {
  for (const card of Object.values(cardRefs.value)) {
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
  filterChannel.value = ''
  filterStyle.value = ''
  filterRatio.value = ''
  filterDuration.value = ''
}

function openEditor(item) {
  openAppWindow('editor', { query: { project: item.project_id || '' } })
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

  const item = filteredItems.value[index]
  archiveCalendarRef.value?.revealItem(item)
  await nextTick()
  const card = cardRefs.value[itemKey(item)]
  const rootEl = card?.cardRootEl?.value || card?.cardRootEl
  if (!rootEl) return

  const key = itemKey(item)
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
        <h2 class="page-title">Library</h2>
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
      <div class="stat-item">
        <span class="stat-num" style="color: var(--accent)">{{ extendedStats.total }}</span>
        <span class="stat-lbl">Exports</span>
      </div>
      <span class="stat-divider"></span>
      <div class="stat-item">
        <span class="stat-num" :style="{ color: extendedStats.today > 0 ? '#26DE81' : 'var(--text-muted)' }">{{ extendedStats.today }}</span>
        <span class="stat-lbl">Today</span>
      </div>
      <span class="stat-divider"></span>
      <div class="stat-item">
        <span class="stat-num" style="color: #FFB347">{{ extendedStats.week }}</span>
        <span class="stat-lbl">This Week</span>
      </div>
      <span class="stat-divider"></span>
      <div class="stat-item">
        <span class="stat-num" style="color: #A78BFA">{{ fmtDuration(extendedStats.totalDur) }}</span>
        <span class="stat-lbl">Duration</span>
      </div>
      <span class="stat-divider"></span>
      <div class="stat-item">
        <span class="stat-num" style="color: var(--text-secondary)">{{ formatBytes(extendedStats.totalSize) }}</span>
        <span class="stat-lbl">Size</span>
      </div>
      <template v-if="extendedStats.topStyle">
        <span class="stat-divider"></span>
        <div class="stat-item">
          <span class="stat-num" :style="{ color: styleColor(extendedStats.topStyle[0]) }">{{ styleLabel(extendedStats.topStyle[0]) }}</span>
          <span class="stat-lbl">Top Style</span>
        </div>
      </template>
      <template v-if="extendedStats.topRatio">
        <span class="stat-divider"></span>
        <div class="stat-item">
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
      :filter-channel="filterChannel"
      :sort-options="SORT_OPTIONS"
      :duration-filters="DURATION_FILTERS"
      :style-options="styleOptions"
      :ratio-options="ratioOptions"
      :channel-options="channelOptions"
      :filtered-count="filteredItems.length"
      @update:sort-by="sortBy = $event"
      @update:filter-style="filterStyle = $event"
      @update:filter-ratio="filterRatio = $event"
      @update:filter-duration="filterDuration = $event"
      @update:filter-channel="filterChannel = $event"
      @search="searchQuery = $event"
      @clear="clearFilters"
    />

    <!-- States -->
    <div v-if="loading && items.length === 0" class="state-msg">Loading export library...</div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="!loading && items.length === 0" class="state-msg">No exported videos found yet.</div>
    <div v-else-if="items.length > 0 && filteredItems.length === 0" class="state-msg">No videos match the current filters.</div>

    <!-- The same 48-hour calendar renders Production rows and Library cards. -->
    <ArchiveCalendar
      v-else
      ref="archiveCalendarRef"
      :items="filteredItems"
      :search-query="searchQuery"
      timestamp-key="modified_at"
      item-key="video_relpath"
      :search-keys="['project_id', 'project_name', 'video_name', 'channel_id', 'channel_name', 'style']"
      noun="video"
      layout="grid"
    >
      <template #item="{ item }">
        <ExportCard
          :item="item"
          :highlighted="highlightedItemKey === itemKey(item)"
          :ref="(el) => setCardRef(el, item)"
          @play="handlePlay"
          @editor="openEditor"
          @export="downloadVideo"
          @download-zip="downloadZip"
          @trash="handleTrash"
        />
      </template>
    </ArchiveCalendar>

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
  font-family: var(--body);
  font-size: 13px;
}

/* ---- Header ----
   .page-title / .page-subtitle come from the shared primitives. */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* The one primary action on the page — the only place the duotone lands. */
.sync-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 600;
  border: 1px solid transparent;
  border-radius: var(--r-s);
  background: var(--accent-grad);
  color: #fff;
  cursor: pointer;
  white-space: nowrap;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast);
  transition: filter 0.16s, box-shadow 0.16s, transform 0.12s var(--ease-spring);
}

.sync-btn:hover:not(:disabled) {
  filter: brightness(1.07) saturate(1.05);
  transform: translateY(-1px);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
}

.sync-btn--active {
  filter: brightness(1.07) saturate(1.05);
}

.sync-btn-icon {
  display: flex;
  align-items: center;
}

.sync-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  filter: none;
  transform: none;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 500;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel-grad);
  color: var(--text);
  cursor: pointer;
  white-space: nowrap;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.16s, border-color 0.16s, box-shadow 0.16s,
    transform 0.12s var(--ease-spring);
}

.refresh-btn:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  transform: translateY(-1px);
  box-shadow: var(--hairline-top), 0 4px 12px -4px rgba(0, 0, 0, 0.5);
}

.refresh-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
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
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  margin-bottom: 12px;
  position: relative;
  overflow: hidden;
}

/* An in-flight run is an active state, so it carries the duotone edge; a
   finished one hands over to the status ramp. */
.sync-panel::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--accent-grad);
}

.sync-panel--done::before {
  background: var(--ok);
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
  border-radius: var(--r-s);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.sync-panel-icon--active {
  background: var(--accent-dim);
  color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent-line);
}

.sync-panel-icon--done {
  background: var(--ok-dim);
  color: var(--ok);
  box-shadow: inset 0 0 0 1px var(--ok-line);
}

.sync-panel-status {
  min-width: 0;
}

.sync-panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.25;
}

.sync-panel-file {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
  margin-top: 3px;
}

/* Center: progress */
.sync-panel-center {
  flex: 1;
  min-width: 0;
}

.sync-panel-bar-track {
  height: 4px;
  background: var(--raise);
  border-radius: 3px;
  overflow: hidden;
}

.sync-panel-bar-fill {
  height: 100%;
  background: var(--accent-grad);
  border-radius: 3px;
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
  background: linear-gradient(90deg, transparent, var(--accent-line-2));
  border-radius: 0 3px 3px 0;
  animation: sync-bar-pulse 1.5s ease-in-out infinite;
}

.sync-panel-bar-fill--done {
  background: var(--ok);
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
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
}

.sync-panel-counter-sep {
  color: var(--faint);
  margin: 0 1px;
}

.sync-panel-size {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
}

.sync-panel-summary {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--ok);
  font-weight: 500;
}

/* ---- Stats Bar ---- */
.stats-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 20px;
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  margin-bottom: 12px;
  overflow-x: auto;
  flex-wrap: wrap;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  min-width: 50px;
}

.stat-num {
  font-family: var(--display);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.4px;
  line-height: 1;
  color: var(--text);
  white-space: nowrap;
}

.stat-lbl {
  font-family: var(--mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--muted);
  margin-top: 3px;
}

.stat-divider {
  width: 1px;
  height: 28px;
  background: var(--line);
  flex-shrink: 0;
}

/* (Filter bar moved to LibrarySearch component) */

/* ---- States ---- */
.state-msg {
  text-align: center;
  font-family: var(--body);
  font-size: 13px;
  color: var(--muted);
  padding: 48px 20px;
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
}

.state-error {
  color: var(--fail-text);
  background: var(--fail-dim);
  border-color: var(--fail-line);
  box-shadow: none;
}

/* ---- Grid ---- */
.export-grid {
  display: grid;
  /* minmax(0, …) rather than minmax(280px, …): below 280px the fixed track
     would be wider than the viewport and take a scrollbar with it. */
  grid-template-columns: repeat(auto-fill, minmax(min(280px, 100%), 1fr));
  gap: 14px;
}

/* Step 0.3 — the title and its two actions need their own lines on a phone. */
@media (max-width: 820px) {
  .page-header {
    flex-wrap: wrap;
    gap: 12px;
  }

  .header-actions {
    flex-wrap: wrap;
  }
}
</style>

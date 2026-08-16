<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { ratioLabel, aspectRatioFromDimensions } from '../composables/useExportLibrary.js'
import { formatBytes, timeAgo, fmtDuration, formatElapsed } from '@/shared/utils/format.js'

defineOptions({ name: 'ExportCard' })

const props = defineProps({
  item: { type: Object, required: true },
  highlighted: { type: Boolean, default: false },
})

const emit = defineEmits(['download-video', 'download-zip', 'play', 'trash'])

const rootEl = ref(null)
const videoEl = ref(null)
const loaded = ref(false)
const showTiming = ref(false)
const showDetails = ref(false)

const STEP_META = {
  tts:      { label: 'TTS',      icon: '\uD83C\uDFA4', color: '#4ECDC4' },
  timing:   { label: 'Alignment', icon: '\u23F1',  color: '#56CCF2' },
  segment:  { label: 'Segment',  icon: '\u2702',  color: '#A78BFA' },
  scenes:   { label: 'Scenes',   icon: '\uD83C\uDFAC', color: '#FFB347' },
  assets:   { label: 'Assets',   icon: '\uD83D\uDDBC',  color: '#FF6B6B' },
  assemble: { label: 'Assemble', icon: '\uD83D\uDD27', color: '#26DE81' },
  export:   { label: 'Export',   icon: '\uD83D\uDCE4', color: '#C084FC' },
}

function hasTiming() {
  const t = props.item.pipeline_timing
  return t && typeof t === 'object' && Object.keys(t).length > 0
}

function fmtSecs(s) {
  return formatElapsed(s) || '--'
}

function timingSteps() {
  const t = props.item.pipeline_timing || {}
  return Object.entries(STEP_META)
    .filter(([k]) => t[k] != null)
    .map(([k, meta]) => ({ key: k, ...meta, duration: t[k] }))
}

function maxStepDuration() {
  const t = props.item.pipeline_timing || {}
  return Math.max(...Object.entries(t).filter(([k]) => k !== 'total').map(([, v]) => v), 1)
}

function hasDetails() {
  return Boolean(
    resolutionLabel() ||
    props.item.source_folder ||
    props.item.audio_track_count ||
    props.item.caption_count ||
    props.item.has_captions ||
    mediaSummary() ||
    props.item.completed_at ||
    props.item.project_total_duration
  )
}

function resolutionLabel() {
  if (props.item.resolution_label) return props.item.resolution_label
  if (props.item.width && props.item.height) return `${props.item.width}x${props.item.height}`
  return ''
}

function mediaSummary() {
  const counts = props.item.media_counts || {}
  const parts = []
  if (counts.video) parts.push(`${counts.video} video${counts.video === 1 ? '' : 's'}`)
  if (counts.image) parts.push(`${counts.image} image${counts.image === 1 ? '' : 's'}`)
  if (counts.text) parts.push(`${counts.text} text${counts.text === 1 ? ' scene' : ' scenes'}`)
  return parts.join(' / ')
}

function captionSummary() {
  if (props.item.caption_count) {
    return `${props.item.caption_count} caption${props.item.caption_count === 1 ? '' : 's'}`
  }
  return props.item.has_captions ? 'Enabled' : 'None'
}

function audioSummary() {
  const count = Number(props.item.audio_track_count || 0)
  return count ? `${count} track${count === 1 ? '' : 's'}` : 'No tracks'
}

function exactTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString()
}

function stopPlayback() {
  if (videoEl.value && !videoEl.value.paused) {
    videoEl.value.pause()
    videoEl.value.currentTime = 0
  }
}

function onPlay() {
  emit('play', videoEl.value)
}

onBeforeUnmount(() => stopPlayback())

defineExpose({ stopPlayback, videoEl, cardRootEl: rootEl })

// --- Helpers ---
function styleLabel(id) {
  if (!id) return ''
  return id.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function styleColor(id) {
  if (!id) return 'var(--text-muted)'
  const map = {
    cinematic_realistic: '#4ECDC4',
    anime_manga: '#FF6B6B',
    watercolor_dreamy: '#A78BFA',
    pop_art_bold: '#FFB347',
    minimalist_clean: '#56CCF2',
    dark_horror: '#FF4757',
    nature_documentary: '#26DE81',
    noir_mystery: '#A0A0B0',
    surreal_dreamlike: '#C084FC',
    cyberpunk_neon: '#00D2FF',
    stickman_animation: '#FFD93D',
  }
  return map[id] || '#8B8B8B'
}

// Lazy load via IntersectionObserver
const cardEl = ref(null)
onMounted(() => {
  if (!cardEl.value || typeof IntersectionObserver !== 'function') {
    loaded.value = true
    return
  }
  const observer = new IntersectionObserver((entries, obs) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        loaded.value = true
        obs.unobserve(entry.target)
      }
    }
  }, { rootMargin: '200px' })
  observer.observe(cardEl.value)
})
</script>

<template>
  <article
    ref="rootEl"
    class="export-card"
    :class="{ highlighted: props.highlighted }"
    tabindex="-1"
  >
    <!-- Video -->
    <div ref="cardEl" class="video-wrap">
      <!-- Blurred background fill -->
      <video
        v-if="loaded"
        :src="item.preview_url"
        muted
        preload="metadata"
        playsinline
        class="video-bg"
        aria-hidden="true"
      />
      <!-- Main video -->
      <video
        v-if="loaded"
        ref="videoEl"
        :src="item.preview_url"
        controls
        preload="metadata"
        playsinline
        class="video-player"
        @play="onPlay"
      />
      <div v-if="!loaded" class="video-placeholder">
        <svg width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24" opacity="0.3">
          <polygon points="5,3 19,12 5,21" />
        </svg>
      </div>
    </div>

    <!-- Content -->
    <div class="card-content">
      <!-- Header row: project + style badge -->
      <div class="card-header">
        <h3 class="project-name">{{ item.project_id || item.video_name }}</h3>
        <span
          v-if="item.style"
          class="style-badge"
          :style="{ '--badge-color': styleColor(item.style) }"
        >
          <span class="style-dot"></span>
          {{ styleLabel(item.style) }}
        </span>
      </div>

      <!-- Filename -->
      <p class="filename" :title="item.video_name || ''">{{ item.video_name || '' }}</p>

      <!-- Metadata chips -->
      <div class="meta-row">
        <span v-if="item.scene_count" class="chip chip--teal">{{ item.scene_count }} scenes</span>
        <span v-if="fmtDuration(item.duration)" class="chip chip--amber">{{ fmtDuration(item.duration) }}</span>
        <span class="chip">{{ formatBytes(item.size_bytes) }}</span>
        <span class="chip">{{ timeAgo(item.modified_at) }}</span>
        <span v-if="item.video_ratio" class="chip chip--purple">{{ item.video_ratio.replace(':', 'x') }}</span>
        <span v-if="aspectRatioFromDimensions(item.video_ratio)" class="chip chip--purple-bold">{{ aspectRatioFromDimensions(item.video_ratio) }}</span>
        <span v-else-if="ratioLabel(item.ratio)" class="chip chip--purple-bold">{{ ratioLabel(item.ratio) }}</span>
        <button
          v-if="hasTiming()"
          class="chip chip--timing"
          @click.stop="showTiming = !showTiming"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" />
          </svg>
          {{ fmtSecs(item.pipeline_timing.total) }}
          <svg class="chip-chevron" :class="{ open: showTiming }" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
        </button>
        <button
          v-if="hasDetails()"
          class="chip chip--details"
          @click.stop="showDetails = !showDetails"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 10v6" />
            <path d="M12 7h.01" />
          </svg>
          Details
          <svg class="chip-chevron" :class="{ open: showDetails }" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
        </button>
      </div>

      <Transition name="timing-slide">
        <div v-if="showDetails && hasDetails()" class="details-panel">
          <div class="details-grid">
            <div v-if="resolutionLabel()" class="detail-row">
              <span class="detail-label">Resolution</span>
              <span class="detail-value detail-value--mono">{{ resolutionLabel() }}</span>
            </div>
            <div v-if="item.source_folder" class="detail-row">
              <span class="detail-label">Source</span>
              <span class="detail-value detail-value--mono">{{ item.source_folder }}</span>
            </div>
            <div v-if="mediaSummary()" class="detail-row">
              <span class="detail-label">Media</span>
              <span class="detail-value">{{ mediaSummary() }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">Audio</span>
              <span class="detail-value">{{ audioSummary() }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">Captions</span>
              <span class="detail-value">{{ captionSummary() }}</span>
            </div>
            <div v-if="item.project_total_duration" class="detail-row">
              <span class="detail-label">Timeline</span>
              <span class="detail-value">{{ fmtDuration(item.project_total_duration) }}</span>
            </div>
            <div v-if="hasTiming() && item.pipeline_timing.total" class="detail-row">
              <span class="detail-label">Pipeline</span>
              <span class="detail-value">{{ fmtSecs(item.pipeline_timing.total) }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">ZIP</span>
              <span class="detail-value">{{ item.zip_source === 'file' ? 'Bundled ZIP ready' : 'Generate on download' }}</span>
            </div>
            <div v-if="exactTime(item.completed_at || item.modified_at)" class="detail-row detail-row--wide">
              <span class="detail-label">Exported</span>
              <span class="detail-value">{{ exactTime(item.completed_at || item.modified_at) }}</span>
            </div>
          </div>
        </div>
      </Transition>

      <!-- Pipeline timing breakdown -->
      <Transition name="timing-slide">
        <div v-if="showTiming && hasTiming()" class="timing-panel">
          <div class="timing-steps">
            <div
              v-for="step in timingSteps()"
              :key="step.key"
              class="timing-step"
            >
              <span class="timing-icon">{{ step.icon }}</span>
              <span class="timing-label">{{ step.label }}</span>
              <div class="timing-bar-track">
                <div
                  class="timing-bar-fill"
                  :style="{
                    width: (step.duration / maxStepDuration() * 100) + '%',
                    background: step.color,
                  }"
                ></div>
              </div>
              <span class="timing-value" :style="{ color: step.color }">{{ fmtSecs(step.duration) }}</span>
            </div>
          </div>
          <div class="timing-total">
            <span>Total pipeline</span>
            <span class="timing-total-value">{{ fmtSecs(item.pipeline_timing.total) }}</span>
          </div>
        </div>
      </Transition>

      <!-- Actions -->
      <div class="actions">
        <button class="dl-btn" @click="emit('download-video', item)">
          <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Video
        </button>
        <button
          v-if="item.zip_download_url"
          class="dl-btn dl-btn--accent"
          @click="emit('download-zip', item)"
        >
          <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Project ZIP
        </button>
        <button
          class="dl-btn dl-btn--danger"
          @click="emit('trash', item)"
        >
          <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
          </svg>
          Delete
        </button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.export-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.25s, transform 0.2s;
  outline: none;
  display: flex;
  flex-direction: column;
}

.export-card:hover {
  border-color: var(--border-hover);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  transform: translateY(-1px);
}

.export-card.highlighted {
  border-color: #4ECDC4;
  box-shadow:
    0 0 0 1px rgba(78, 205, 196, 0.85),
    0 0 0 10px rgba(78, 205, 196, 0.10),
    0 18px 40px rgba(78, 205, 196, 0.18);
  animation: highlight-pulse 1.6s ease-in-out 3;
}

@keyframes highlight-pulse {
  0%, 100% { transform: translateY(0); box-shadow: 0 0 0 1px rgba(78,205,196,0.85), 0 0 0 10px rgba(78,205,196,0.1), 0 18px 40px rgba(78,205,196,0.18); }
  50% { transform: translateY(-2px); box-shadow: 0 0 0 1px rgba(78,205,196,1), 0 0 0 14px rgba(78,205,196,0.14), 0 22px 44px rgba(78,205,196,0.24); }
}

/* ---- Video ---- */
.video-wrap {
  position: relative;
  background: #000;
  aspect-ratio: 9 / 16;
  max-height: 380px;
  overflow: hidden;
}

.video-bg {
  position: absolute;
  inset: -20px;
  width: calc(100% + 40px);
  height: calc(100% + 40px);
  object-fit: cover;
  filter: blur(20px) brightness(0.5);
  pointer-events: none;
  z-index: 0;
}

.video-player {
  position: relative;
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
  z-index: 1;
}

.video-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}

/* ---- Content ---- */
.card-content {
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.project-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.style-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 9px;
  font-weight: 600;
  font-family: var(--font-mono);
  padding: 2px 8px;
  border-radius: 4px;
  color: var(--badge-color);
  background: color-mix(in srgb, var(--badge-color) 12%, transparent);
  letter-spacing: 0.02em;
}

.style-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--badge-color);
}

.filename {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.7;
}

/* ---- Metadata chips ---- */
.meta-row {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  margin: 2px 0 4px;
}

.chip {
  font-family: var(--font-mono);
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 3px;
  background: var(--bg-darkest);
  color: var(--text-muted);
  white-space: nowrap;
}

.chip--teal { color: #4ECDC4; background: rgba(78, 205, 196, 0.1); }
.chip--amber { color: #FFB347; background: rgba(255, 179, 71, 0.1); }
.chip--purple { color: #A78BFA; background: rgba(167, 139, 250, 0.1); }
.chip--purple-bold { color: #C084FC; background: rgba(192, 132, 252, 0.12); font-weight: 600; }

/* ---- Actions ---- */
.actions {
  display: flex;
  gap: 6px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.dl-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 7px 8px;
  font-size: 10px;
  font-weight: 600;
  font-family: var(--font-mono);
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.dl-btn:hover {
  border-color: var(--border-hover);
  color: var(--text);
  background: var(--bg-darkest);
}

.dl-btn--accent {
  border-color: rgba(78, 205, 196, 0.3);
  color: var(--accent);
}

.dl-btn--accent:hover {
  border-color: var(--accent);
  background: rgba(78, 205, 196, 0.08);
  color: var(--accent);
}

.dl-btn--danger {
  flex: 0.85;
  color: #FF9A9A;
  border-color: rgba(255, 107, 107, 0.35);
  background: rgba(255, 107, 107, 0.05);
}

.dl-btn--danger:hover {
  color: #FF6B6B;
  border-color: rgba(255, 107, 107, 0.6);
  background: rgba(255, 107, 107, 0.12);
}

/* ---- Timing chip & panel ---- */
.chip--timing {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #56CCF2;
  background: rgba(86, 204, 242, 0.08);
  border: 1px solid rgba(86, 204, 242, 0.15);
  transition: all 0.15s;
}
.chip--timing:hover {
  background: rgba(86, 204, 242, 0.15);
  border-color: rgba(86, 204, 242, 0.3);
}
.chip-chevron {
  transition: transform 0.2s;
  opacity: 0.6;
}
.chip-chevron.open {
  transform: rotate(180deg);
}

.chip--details {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #c7d2fe;
  background: rgba(199, 210, 254, 0.08);
  border: 1px solid rgba(199, 210, 254, 0.16);
  transition: all 0.15s;
}

.chip--details:hover {
  background: rgba(199, 210, 254, 0.14);
  border-color: rgba(199, 210, 254, 0.3);
}

.details-panel,
.timing-panel {
  background: var(--bg-darkest);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin: 2px 0 4px;
}

.details-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 12px;
}

.detail-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.detail-row--wide {
  grid-column: 1 / -1;
}

.detail-label {
  font-family: var(--font-mono);
  font-size: 8px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.detail-value {
  color: var(--text);
  font-size: 11px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.detail-value--mono {
  font-family: var(--font-mono);
  font-size: 10px;
}

.timing-steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.timing-step {
  display: grid;
  grid-template-columns: 16px 58px 1fr 42px;
  align-items: center;
  gap: 6px;
}

.timing-icon {
  font-size: 10px;
  text-align: center;
}

.timing-label {
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.timing-bar-track {
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.04);
  overflow: hidden;
}

.timing-bar-fill {
  height: 100%;
  border-radius: 2px;
  min-width: 2px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.timing-value {
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 700;
  text-align: right;
  letter-spacing: -0.02em;
}

.timing-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}

.timing-total span:first-child {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.timing-total-value {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 800;
  color: #56CCF2;
  letter-spacing: -0.02em;
}

/* Slide transition */
.timing-slide-enter-active,
.timing-slide-leave-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.timing-slide-enter-from,
.timing-slide-leave-to {
  max-height: 0;
  opacity: 0;
  margin: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.timing-slide-enter-to,
.timing-slide-leave-from {
  max-height: 300px;
  opacity: 1;
}

@media (max-width: 640px) {
  .details-grid {
    grid-template-columns: 1fr;
  }
}
</style>

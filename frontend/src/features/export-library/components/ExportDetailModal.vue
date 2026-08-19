<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { aspectRatioFromDimensions, ratioLabel } from '../composables/useExportLibrary.js'
import { formatBytes, fmtDuration, formatElapsed } from '@/shared/utils/format.js'
import { useToast } from '@/shared/composables/useToast.js'

defineOptions({ name: 'ExportDetailModal' })

const props = defineProps({
  item: { type: Object, default: null },
  /* While a nested confirm (delete) owns Escape, the detail view stays put. */
  escapeDisabled: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'editor', 'export', 'download-zip', 'trash'])

const toast = useToast()
const videoEl = ref(null)
const playing = ref(false)

/* Every step the pipeline can report. The bar reads in the run tone: this is a
   record of work, not seven categories that each deserve a colour of its own. */
const STEP_LABELS = {
  tts: 'TTS',
  timing: 'Alignment',
  segment: 'Segment',
  scenes: 'Scenes',
  assets: 'Assets',
  assemble: 'Assemble',
  export: 'Export',
}

const timing = computed(() => {
  const value = props.item?.pipeline_timing
  return value && typeof value === 'object' ? value : null
})

const timingSteps = computed(() => {
  if (!timing.value) return []
  return Object.entries(STEP_LABELS)
    .filter(([key]) => timing.value[key] != null)
    .map(([key, label]) => ({ key, label, duration: timing.value[key] }))
})

const maxStepDuration = computed(() => {
  const durations = Object.entries(timing.value || {})
    .filter(([key]) => key !== 'total')
    .map(([, value]) => value)
  return Math.max(...durations, 1)
})

function fmtSecs(seconds) {
  return formatElapsed(seconds) || '--'
}

const title = computed(() => props.item?.project_id || props.item?.video_name || '')

const resolution = computed(() => {
  const item = props.item
  if (!item) return ''
  if (item.resolution_label) return item.resolution_label
  if (item.width && item.height) return `${item.width}x${item.height}`
  return ''
})

const aspect = computed(() => {
  const item = props.item
  if (!item) return ''
  return aspectRatioFromDimensions(item.video_ratio) || ratioLabel(item.ratio) || ''
})

/* The preview keeps the export's own shape. The prototype hardcodes 9:16
   because it renders one channel; the library holds every ratio the pipeline
   has produced. */
const thumbStyle = computed(() => (aspect.value ? { aspectRatio: aspect.value.replace(':', ' / ') } : {}))

const styleLabel = computed(() => {
  const id = props.item?.style
  if (!id) return ''
  return id.replace(/[_-]/g, ' ').replace(/\b\w/g, character => character.toUpperCase())
})

const mediaSummary = computed(() => {
  const counts = props.item?.media_counts || {}
  const parts = []
  if (counts.video) parts.push(`${counts.video} video${counts.video === 1 ? '' : 's'}`)
  if (counts.image) parts.push(`${counts.image} image${counts.image === 1 ? '' : 's'}`)
  if (counts.text) parts.push(`${counts.text} text${counts.text === 1 ? ' scene' : ' scenes'}`)
  return parts.join(' / ')
})

const captionSummary = computed(() => {
  const count = props.item?.caption_count
  if (count) return `${count} caption${count === 1 ? '' : 's'}`
  return props.item?.has_captions ? 'Enabled' : 'None'
})

const audioSummary = computed(() => {
  const count = Number(props.item?.audio_track_count || 0)
  return count ? `${count} track${count === 1 ? '' : 's'}` : 'No tracks'
})

const exportedAt = computed(() => {
  const value = props.item?.completed_at || props.item?.modified_at
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
})

const zipNote = computed(() =>
  props.item?.zip_source === 'file' ? 'project ZIP bundled' : 'project ZIP built on download',
)

function play() {
  playing.value = true
  try {
    videoEl.value?.play?.()
  } catch {
    // A browser that refuses autoplay still gets the controls it needs.
  }
}

async function copyPath() {
  const path = props.item?.video_relpath
  if (!path) return
  try {
    await navigator.clipboard?.writeText(path)
    toast.success('Path copied to clipboard')
  } catch {
    toast.error('Could not copy the path')
  }
}

function onOverlayClick(event) {
  if (event.target === event.currentTarget) emit('close')
}

function onEscape(event) {
  if (props.escapeDisabled || !props.item || event.key !== 'Escape') return
  emit('close')
}

watch(() => props.item, () => { playing.value = false })

onMounted(() => document.addEventListener('keydown', onEscape))
onUnmounted(() => document.removeEventListener('keydown', onEscape))
</script>

<template>
  <Teleport v-if="item" to="body">
    <div class="overlay" @click="onOverlayClick">
      <div class="export-modal" role="dialog" aria-modal="true" aria-labelledby="export-detail-title">
        <div class="exp-head">
          <div class="ei">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <div class="et">
            <div id="export-detail-title" class="t">Library · {{ title }}</div>
            <div class="s">{{ item.video_name }} · {{ item.channel_name || item.channel_id || 'No channel' }} · stored output</div>
          </div>
          <button class="exp-close" aria-label="Close" @click="emit('close')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12" /></svg>
          </button>
        </div>

        <div class="exp-body">
          <div class="exp-preview">
            <div class="exp-thumb" :style="thumbStyle">
              <video
                ref="videoEl"
                :src="item.preview_url"
                :controls="playing"
                preload="metadata"
                playsinline
                class="exp-video"
              />
              <template v-if="!playing">
                <div class="cap">{{ title }}</div>
                <div v-if="fmtDuration(item.duration)" class="dur">{{ fmtDuration(item.duration) }}</div>
                <button type="button" class="play" aria-label="Play preview" @click="play">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3" /></svg>
                </button>
              </template>
            </div>
            <div class="exp-thumb-note">FINAL RENDER · {{ aspect || 'unknown ratio' }}</div>
          </div>

          <div class="exp-cfg">
            <div class="exp-sec">
              <div class="h">Output</div>
              <div v-if="resolution" class="exp-kv"><span class="k">Resolution</span><span class="v mono">{{ resolution }}</span></div>
              <div v-if="aspect" class="exp-kv"><span class="k">Ratio</span><span class="v mono">{{ aspect }}</span></div>
              <div class="exp-kv"><span class="k">Duration</span><span class="v mono">{{ fmtDuration(item.duration) || '—' }}</span></div>
              <div v-if="styleLabel" class="exp-kv"><span class="k">Style</span><span class="v">{{ styleLabel }}</span></div>
              <div v-if="item.scene_count" class="exp-kv"><span class="k">Scenes</span><span class="v">{{ item.scene_count }}</span></div>
              <div v-if="mediaSummary" class="exp-kv"><span class="k">Media</span><span class="v">{{ mediaSummary }}</span></div>
              <div class="exp-kv"><span class="k">Audio</span><span class="v">{{ audioSummary }}</span></div>
              <div class="exp-kv"><span class="k">Captions</span><span class="v">{{ captionSummary }}</span></div>
              <div v-if="item.project_total_duration" class="exp-kv"><span class="k">Timeline</span><span class="v mono">{{ fmtDuration(item.project_total_duration) }}</span></div>
              <div v-if="exportedAt" class="exp-kv"><span class="k">Exported</span><span class="v">{{ exportedAt }}</span></div>
            </div>

            <div v-if="timingSteps.length" class="exp-sec">
              <div class="h">Pipeline timing</div>
              <div class="timing-steps">
                <div v-for="step in timingSteps" :key="step.key" class="timing-step">
                  <span class="timing-label">{{ step.label }}</span>
                  <div class="timing-bar-track">
                    <div class="timing-bar-fill" :style="{ width: (step.duration / maxStepDuration * 100) + '%' }"></div>
                  </div>
                  <span class="timing-value">{{ fmtSecs(step.duration) }}</span>
                </div>
              </div>
              <div v-if="timing.total != null" class="exp-kv timing-total">
                <span class="k">Total pipeline</span><span class="v mono">{{ fmtSecs(timing.total) }}</span>
              </div>
            </div>

            <div class="exp-sec">
              <div class="h">Destination</div>
              <div class="exp-path">
                <span class="p">{{ item.video_relpath }}</span>
                <button class="btn sm" @click="copyPath">Copy</button>
              </div>
              <div v-if="item.source_folder" class="exp-kv"><span class="k">Source</span><span class="v mono">{{ item.source_folder }}</span></div>
              <div class="exp-size-note"><b>{{ formatBytes(item.size_bytes) }}</b> on disk · {{ zipNote }}</div>
            </div>
          </div>
        </div>

        <div class="exp-foot">
          <button class="btn ghost sm" @click="emit('editor', item)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
            Open in Editor
          </button>
          <button v-if="item.zip_download_url" class="btn ghost sm" @click="emit('download-zip', item)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
            Project ZIP
          </button>
          <button class="btn danger sm" @click="emit('trash', item)">Delete</button>
          <div class="spacer"></div>
          <button class="btn sm" @click="emit('close')">Close</button>
          <button class="btn primary sm" @click="emit('export', item)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
            Download
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* The prototype's export modal, ported in step 6.7. */
.overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(4, 6, 9, 0.68);
  backdrop-filter: blur(4px) saturate(1.1);
}

.export-modal {
  background: var(--panel-grad2);
  border: 1px solid var(--line);
  border-radius: var(--r-l);
  width: 720px;
  max-width: 94vw;
  max-height: 90vh;
  box-shadow: var(--shadow), 0 40px 80px -30px rgba(0, 0, 0, 0.85);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  font-family: var(--body);
  font-size: 13px;
}

.exp-head {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 18px 22px;
  border-bottom: 1px solid var(--line-soft);
}

.exp-head .ei {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  flex: none;
  display: grid;
  place-items: center;
  background: var(--ok-dim);
  color: var(--ok);
}

.exp-head .et {
  flex: 1;
  min-width: 0;
}

.exp-head .et .t {
  font-family: var(--display);
  font-weight: 600;
  font-size: 16px;
  letter-spacing: -0.3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.exp-head .et .s {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.exp-close {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 7px;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  display: grid;
  place-items: center;
}

.exp-close:hover {
  background: var(--raise);
  color: var(--text);
}

.exp-body {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 0;
  overflow-y: auto;
}

.exp-preview {
  padding: 22px;
  border-right: 1px solid var(--line-soft);
  background: var(--bg-2);
}

.exp-thumb {
  aspect-ratio: 9 / 16;
  width: 100%;
  max-width: 168px;
  margin: 0 auto;
  border-radius: var(--r);
  overflow: hidden;
  position: relative;
  box-shadow: 0 12px 30px -12px rgba(0, 0, 0, 0.7), inset 0 0 0 1px var(--line);
  display: grid;
  place-items: center;
  background: var(--bg);
}

.exp-video {
  grid-area: 1 / 1;
  width: 100%;
  height: 100%;
  object-fit: contain;
  z-index: 1;
}

/* Same overlay geometry as `.lib-thumb .play`: the video already claimed
   grid cell 1/1, so without absolute centering the button auto-places into a
   second row and gets clipped by `overflow: hidden`. */
.exp-thumb .play {
  position: absolute;
  inset: 0;
  margin: auto;
  width: 44px;
  height: 44px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: grid;
  place-items: center;
  color: #fff;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.3);
  cursor: pointer;
  z-index: 4;
}

.exp-thumb .play:hover {
  background: rgba(0, 0, 0, 0.6);
}

.exp-thumb .dur {
  position: absolute;
  bottom: 8px;
  right: 8px;
  font-family: var(--mono);
  font-size: 10px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  padding: 2px 6px;
  border-radius: 4px;
  z-index: 2;
}

.exp-thumb .cap {
  position: absolute;
  bottom: 34px;
  left: 8px;
  right: 8px;
  text-align: center;
  font-weight: 700;
  font-size: 12px;
  color: #fff;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9);
  z-index: 2;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.exp-thumb-note {
  text-align: center;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--faint);
  margin-top: 12px;
}

.exp-cfg {
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.exp-sec .h {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 11px;
}

.exp-kv {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 6px 0;
  font-size: 12.5px;
  border-bottom: 1px solid var(--line-soft);
}

.exp-kv:last-child {
  border-bottom: none;
}

.exp-kv .k {
  color: var(--muted);
  flex: none;
}

.exp-kv .v {
  color: var(--text);
  font-weight: 500;
  text-align: right;
  overflow-wrap: anywhere;
}

.exp-kv .v.mono {
  font-family: var(--mono);
  font-size: 11.5px;
}

.exp-size-note {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  margin-top: 10px;
}

.exp-size-note b {
  color: var(--text-2);
  font-weight: 600;
}

.exp-path {
  display: flex;
  gap: 8px;
  align-items: center;
}

.exp-path .p {
  flex: 1;
  min-width: 0;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  padding: 8px 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.exp-foot {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 14px 22px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg-2);
  flex-wrap: wrap;
}

.exp-foot .spacer {
  flex: 1;
}

/* Pipeline timing has no prototype counterpart — the prototype records no run.
   It reads in the run tone, like every other record of work in the app. */
.timing-steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.timing-step {
  display: grid;
  grid-template-columns: 62px 1fr 46px;
  align-items: center;
  gap: 8px;
}

.timing-label {
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 500;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.7px;
}

.timing-bar-track {
  height: 5px;
  background: var(--raise);
  border-radius: 3px;
  overflow: hidden;
}

.timing-bar-fill {
  height: 100%;
  min-width: 2px;
  background: var(--run);
  border-radius: 3px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.3);
}

.timing-value {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  color: var(--text-2);
  text-align: right;
}

.timing-total {
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px solid var(--line-soft);
}

@media (max-width: 640px) {
  .exp-body {
    grid-template-columns: 1fr;
  }

  .exp-preview {
    border-right: none;
    border-bottom: 1px solid var(--line-soft);
  }
}
</style>

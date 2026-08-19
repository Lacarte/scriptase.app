<script setup>
/**
 * Job creation rail (steps 2.5 and 4.1) — the prototype's config rail.
 *
 * Channel → Script source → Execution, then Add to Batch. Provider UI
 * appears only when the selected source mode needs a script provider (§6).
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { listChannels } from '@/features/channels/api.js'
import { listScripts } from '@/features/script/api.js'
import {
  channelAvatarLabel,
  channelAvatarStyle,
} from '@/shared/utils/channelIdentity.js'

import {
  createJob,
  createJobBatch,
  getJobDefaults,
  startJob,
} from '../api.js'
import {
  EXECUTION_MODE_CATALOG,
  SOURCE_MODE_CATALOG,
  defaultJobDraft,
  sourceModeRequiresProvider,
  validateJobSource,
} from '../sourceModes.js'

const props = defineProps({
  /** Prefill S1 Library with this script id (Use in Batch). */
  initialScriptId: { type: String, default: '' },
  /** Prefill the channel picker (New job with this). */
  initialChannelId: { type: String, default: '' },
  /** When true and Run Now is selected, start the Job immediately after create. */
  autoStart: { type: Boolean, default: true },
})

const emit = defineEmits(['created', 'started', 'cancel'])

const channels = ref([])
const sourceModes = ref([...SOURCE_MODE_CATALOG])
const executionModes = ref([...EXECUTION_MODE_CATALOG])

const channelId = ref('')
const executionMode = ref('manual')
const sourceMode = ref('paste')
const sourceKind = ref('input')
const studioScripts = ref([])
const selectedScriptIds = ref([])
const scriptsLoading = ref(false)
const topic = ref('')
const idea = ref('')
const pastedScript = ref('')
const removeSilenceOverride = ref('inherit')
const speedOverride = ref('')

const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const fieldErrors = ref([])

/** Queue / Run Now / Scheduled / Auto — when the Job should start. */
const launchIntent = ref(props.autoStart ? 'now' : 'queue')
const previousExec = ref('manual')
const channelOpen = ref(false)
const channelPickEl = ref(null)

const SOURCE_TILES = [
  {
    id: 'auto',
    kind: 'input',
    mode: 'automatic',
    t: 'Auto',
    d: 'Scriptase picks the next topic',
  },
  {
    id: 'paste',
    kind: 'input',
    mode: 'paste',
    t: 'Paste',
    d: 'Bring your own script',
  },
  {
    id: 'idea',
    kind: 'input',
    mode: 'idea',
    t: 'Idea → Script',
    d: 'S1 writes from a topic',
  },
  {
    id: 's1',
    kind: 'studio',
    mode: null,
    t: 'S1 Library',
    d: 'Reuse a saved script',
  },
]

const EXEC_TILES = [
  { id: 'queue', t: 'Queue', d: 'Runs on next slot' },
  { id: 'now', t: 'Run Now', d: 'Starts immediately' },
  { id: 'scheduled', t: 'Scheduled', d: 'At a set time' },
  { id: 'auto', t: 'Auto', d: 'Unattended pipeline' },
]

const SOURCE_SUMMARY = {
  automatic: 'Auto Script',
  topic: 'Topic → Script',
  idea: 'Idea → Script',
  paste: 'Pasted Script',
  manual: 'Manual',
}

const EXEC_SUMMARY = {
  queue: 'Queue',
  now: 'Run Now',
  scheduled: 'Scheduled',
  auto: 'Auto',
}

const selectedSource = computed(
  () => sourceModes.value.find((m) => m.mode === sourceMode.value) || null,
)

const providerRequired = computed(() => sourceModeRequiresProvider(sourceMode.value))
const selectedChannel = computed(
  () => channels.value.find((channel) => channel.id === channelId.value) || null,
)
const inheritedRemoveSilence = computed(
  () => selectedChannel.value?.audio_defaults?.remove_silence !== false,
)
const inheritedSpeed = computed(
  () => Number(selectedChannel.value?.audio_defaults?.speed) || 1,
)

const showTopic = computed(() => {
  const fields = selectedSource.value?.input_fields || []
  return sourceKind.value === 'input' && fields.includes('topic') && sourceMode.value !== 'automatic'
})

const showIdea = computed(() => {
  const fields = selectedSource.value?.input_fields || []
  return sourceKind.value === 'input' && fields.includes('idea') && sourceMode.value !== 'automatic'
})

const showPaste = computed(() => {
  const fields = selectedSource.value?.input_fields || []
  return sourceKind.value === 'input' && fields.includes('pasted_script')
})

const canSubmit = computed(() => {
  if (submitting.value || loading.value) return false
  if (!channelId.value) return false
  if (sourceKind.value === 'studio') return selectedScriptIds.value.length > 0
  return validateJobSource(buildSource()).length === 0
})

const activeSourceTile = computed(() => {
  if (sourceKind.value === 'studio') return 's1'
  if (sourceMode.value === 'automatic') return 'auto'
  if (sourceMode.value === 'idea' || sourceMode.value === 'topic') return 'idea'
  return 'paste'
})

const inheritChips = computed(() => {
  const channel = selectedChannel.value
  if (!channel) return []
  return [
    ['Image', channel.style || channel.visual_direction?.style],
    ['Tone', channel.content?.tone],
    ['Mood', channel.content?.mood],
    ['Voice', channel.audio_defaults?.voice],
    ['Captions', channel.captions?.preset],
    ['Branding', channel.branding?.watermark || channel.branding?.position],
  ].filter(([, value]) => value)
})

const pickMeta = computed(() => {
  const channel = selectedChannel.value
  if (!channel) return 'Pick a channel'
  return [channel.niche, channel.style].filter(Boolean).join(' · ')
})

const addSummary = computed(() => {
  const channel = selectedChannel.value?.name || 'Channel'
  const source = sourceKind.value === 'studio'
    ? 'S1 Library'
    : (SOURCE_SUMMARY[sourceMode.value] || 'Script')
  return `${channel} · ${source} · ${EXEC_SUMMARY[launchIntent.value] || 'Queue'}`
})

const pasteChars = computed(() => pastedScript.value.length)
const pasteDuration = computed(() => {
  const words = pastedScript.value.trim() ? pastedScript.value.trim().split(/\s+/).length : 0
  const seconds = Math.round((words / 150) * 60)
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0')
  const ss = String(seconds % 60).padStart(2, '0')
  return `~${mm}:${ss} narration`
})

const willStart = computed(() => launchIntent.value === 'now')

async function loadStudioScripts() {
  selectedScriptIds.value = []
  studioScripts.value = []
  if (sourceKind.value !== 'studio' || !channelId.value) return
  scriptsLoading.value = true
  error.value = ''
  try {
    const data = await listScripts({ channelId: channelId.value, limit: 500 })
    studioScripts.value = data.scripts || []
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    scriptsLoading.value = false
  }
}

function buildSource() {
  return {
    mode: sourceMode.value,
    topic: topic.value,
    idea: idea.value,
    pasted_script: pastedScript.value,
    references: [],
    remove_silence:
      removeSilenceOverride.value === 'inherit'
        ? null
        : removeSilenceOverride.value === 'on',
    speed: speedOverride.value === '' ? null : Number(speedOverride.value),
  }
}

function buildDraft() {
  const mode = launchIntent.value === 'auto' ? 'automatic' : executionMode.value
  const draft = {
    channel_id: channelId.value,
    execution_mode: mode,
    source: buildSource(),
  }
  return draft
}

function selectSource(tile) {
  if (tile.kind === 'studio') {
    sourceKind.value = 'studio'
    return
  }
  sourceKind.value = 'input'
  sourceMode.value = tile.mode
}

function selectExec(intent) {
  if (launchIntent.value !== 'auto') previousExec.value = executionMode.value
  launchIntent.value = intent
  if (intent === 'auto') {
    executionMode.value = 'automatic'
  } else if (executionMode.value === 'automatic') {
    executionMode.value = previousExec.value || 'assisted'
  }
}

function selectChannel(id) {
  channelId.value = id
  channelOpen.value = false
}

function toggleChannelDD(event) {
  event.stopPropagation()
  if (!channels.value.length) return
  channelOpen.value = !channelOpen.value
}

function onDocumentClick(event) {
  if (!channelPickEl.value?.contains(event.target)) channelOpen.value = false
}

async function loadCatalogs() {
  loading.value = true
  error.value = ''
  try {
    const [defaults, channelData] = await Promise.all([
      getJobDefaults().catch(() => null),
      listChannels({ limit: 500, seed: true }),
    ])
    if (defaults?.source_modes?.length) {
      sourceModes.value = defaults.source_modes
    }
    if (defaults?.execution_modes?.length) {
      executionModes.value = defaults.execution_modes
    }
    if (defaults?.defaults?.execution_mode) {
      executionMode.value = defaults.defaults.execution_mode
      previousExec.value = defaults.defaults.execution_mode
    }
    if (defaults?.defaults?.source?.mode) {
      sourceMode.value = defaults.defaults.source.mode
    }
    channels.value = channelData.channels || []
    if (props.initialChannelId && channels.value.some((ch) => ch.id === props.initialChannelId)) {
      channelId.value = props.initialChannelId
    } else if (!channelId.value && channels.value.length === 1) {
      channelId.value = channels.value[0].id
    }
    if (props.initialScriptId) {
      sourceKind.value = 'studio'
    }
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

async function onSubmit() {
  fieldErrors.value = sourceKind.value === 'studio'
    ? (selectedScriptIds.value.length ? [] : ['Select at least one Studio script'])
    : validateJobSource(buildSource())
  if (!channelId.value) {
    fieldErrors.value = ['Channel is required', ...fieldErrors.value]
  }
  if (fieldErrors.value.length || submitting.value) return

  submitting.value = true
  error.value = ''
  try {
    const resolvedMode = launchIntent.value === 'auto' ? 'automatic' : executionMode.value
    if (sourceKind.value === 'studio') {
      const batch = {
        channel_id: channelId.value,
        script_ids: [...selectedScriptIds.value],
        execution_mode: resolvedMode,
      }
      const result = await createJobBatch(batch)
      const jobs = result.jobs || []
      emit('created', { job: jobs[0] || null, jobs, batch: result })
      return
    }
    const { job } = await createJob(buildDraft())
    emit('created', { job })
    if (willStart.value) {
      const started = await startJob(job.id, { force: false })
      emit('started', {
        job: started.job || job,
        executionId: started.execution_id || started.job?.execution_id,
      })
    }
  } catch (err) {
    error.value = err.message || String(err)
    if (err.details?.problems) {
      fieldErrors.value = err.details.problems.map(
        (p) => p.msg || JSON.stringify(p),
      )
    }
  } finally {
    submitting.value = false
  }
}

watch([sourceKind, channelId], () => {
  void loadStudioScripts()
})

watch(
  () => studioScripts.value.map((script) => script.id).join(','),
  () => {
    if (!props.initialScriptId) return
    if (studioScripts.value.some((script) => script.id === props.initialScriptId)) {
      if (!selectedScriptIds.value.includes(props.initialScriptId)) {
        selectedScriptIds.value = [...selectedScriptIds.value, props.initialScriptId]
      }
    }
  },
)

onMounted(() => {
  void loadCatalogs()
  document.addEventListener('click', onDocumentClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
})

// Keep defaultJobDraft referenced so tree-shaking never drops the helper.
void defaultJobDraft
</script>

<template>
  <aside class="rail" aria-labelledby="job-create-title">
    <div class="rail-head">
      <h2 id="job-create-title">New Production Job</h2>
      <div class="sub">Channel → Source → Execution. The rest is inherited.</div>
    </div>

    <p v-if="loading" class="muted rail-loading">Loading channels…</p>

    <form v-else class="rail-form" @submit.prevent="onSubmit">
      <div class="rail-body">
        <!-- Hidden native controls keep the existing tests and a11y contract. -->
        <select
          v-model="channelId"
          required
          class="sr-only"
          data-testid="channel-select"
          aria-label="Channel"
          :disabled="submitting"
        >
          <option value="">Select a channel…</option>
          <option v-for="ch in channels" :key="ch.id" :value="ch.id">
            {{ ch.name || ch.id }}
          </option>
        </select>
        <select
          v-model="sourceKind"
          class="sr-only"
          data-testid="script-source-kind"
          aria-label="Script source kind"
          :disabled="submitting"
        >
          <option value="input">New script input</option>
          <option value="studio">Existing Studio scripts</option>
        </select>

        <!-- A. Channel -->
        <div class="field">
          <div class="lbl"><span>Channel</span><span class="step-n">01</span></div>
          <div
            ref="channelPickEl"
            class="channel-pick"
            :class="{ open: channelOpen }"
            role="button"
            tabindex="0"
            :aria-expanded="String(channelOpen)"
            aria-haspopup="listbox"
            @click="toggleChannelDD"
            @keydown.enter.prevent="toggleChannelDD"
            @keydown.space.prevent="toggleChannelDD"
          >
            <div
              class="ch-avatar"
              :style="selectedChannel ? channelAvatarStyle(selectedChannel) : {}"
              aria-hidden="true"
            >{{ selectedChannel ? channelAvatarLabel(selectedChannel) : '—' }}</div>
            <div class="ch-meta">
              <div class="nm">{{ selectedChannel?.name || 'Select a channel' }}</div>
              <div class="row2">{{ pickMeta }}</div>
            </div>
            <svg class="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
            <div class="dropdown" :class="{ open: channelOpen }" role="listbox">
              <button
                v-for="ch in channels"
                :key="ch.id"
                type="button"
                class="dd-item"
                :class="{ sel: ch.id === channelId }"
                role="option"
                :aria-selected="String(ch.id === channelId)"
                @click.stop="selectChannel(ch.id)"
              >
                <span class="ch-avatar" :style="channelAvatarStyle(ch)" aria-hidden="true">
                  {{ channelAvatarLabel(ch) }}
                </span>
                <span class="dd-txt">
                  <span class="nm">{{ ch.name || ch.id }}</span>
                  <span class="src">{{ [ch.niche, ch.style].filter(Boolean).join(' · ') }}</span>
                </span>
                <svg class="check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
              </button>
            </div>
          </div>
          <div v-if="inheritChips.length" class="inherits">
            <span v-for="[key, value] in inheritChips" :key="key" class="inherit-chip">
              <span class="k">{{ key }}</span>{{ value }}
            </span>
          </div>
          <div class="inherit-note">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="3"/></svg>
            Style, voice, tone, captions &amp; branding load from the channel.
          </div>
        </div>

        <!-- B. Script source -->
        <div class="field">
          <div class="lbl"><span>Script Source</span><span class="step-n">02</span></div>
          <div class="segmented seg-2" id="sourceSeg">
            <label
              v-for="tile in SOURCE_TILES"
              :key="tile.id"
              class="seg-opt"
              :class="{ sel: activeSourceTile === tile.id }"
            >
              <input
                type="radio"
                name="source_tile"
                :value="tile.mode || 'studio'"
                :checked="activeSourceTile === tile.id"
                :disabled="submitting"
                @change="selectSource(tile)"
              />
              <span class="ic" aria-hidden="true">
                <svg v-if="tile.id === 'auto'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v3M12 18v3M5 12H2M22 12h-3M6.3 6.3 4 4M20 20l-2.3-2.3M6.3 17.7 4 20M20 4l-2.3 2.3"/><circle cx="12" cy="12" r="4"/></svg>
                <svg v-else-if="tile.id === 'paste'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="3" width="8" height="4" rx="1"/><path d="M8 5H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/></svg>
                <svg v-else-if="tile.id === 'idea'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1V17h6v-.2c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z"/></svg>
                <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
              </span>
              <span class="txt"><span class="t">{{ tile.t }}</span><span class="d">{{ tile.d }}</span></span>
            </label>
          </div>

          <!-- Catalog radios (topic / manual / idea) stay in the tree for tests. -->
          <div class="sr-only" aria-hidden="true">
            <label v-for="mode in sourceModes" :key="mode.mode">
              <input
                v-model="sourceMode"
                type="radio"
                name="source_mode"
                :value="mode.mode"
                :disabled="submitting"
                @change="sourceKind = 'input'"
              />
              {{ mode.label }}
            </label>
          </div>

          <div class="source-detail" :class="{ show: showPaste }">
            <textarea
              v-if="showPaste"
              v-model="pastedScript"
              class="script-in"
              maxlength="10000"
              placeholder="Paste your narration script here…"
              :disabled="submitting"
            />
            <div v-if="showPaste" class="script-meta">
              <span>{{ pasteChars }} characters</span>
              <span>{{ pasteDuration }}</span>
            </div>
          </div>

          <div class="source-detail" :class="{ show: showIdea || showTopic }">
            <input
              v-if="showTopic"
              v-model="topic"
              class="txt"
              type="text"
              maxlength="4000"
              placeholder="e.g. Why people remember negative experiences more strongly…"
              :disabled="submitting"
            />
            <input
              v-else-if="showIdea"
              v-model="idea"
              class="txt"
              type="text"
              maxlength="4000"
              placeholder="e.g. Why people remember negative experiences more strongly…"
              :disabled="submitting"
            />
            <div v-if="showIdea || showTopic" class="idea-hint">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
              Sent to <b>S1</b> to generate &amp; save a full script.
            </div>
          </div>

          <div class="source-detail" :class="{ show: sourceKind === 'studio' }" data-testid="studio-script-list">
            <p v-if="scriptsLoading" class="muted">Loading scripts...</p>
            <p v-else-if="sourceKind === 'studio' && !studioScripts.length" class="provider-note">
              This Channel has no Studio scripts yet.
            </p>
            <div v-else-if="sourceKind === 'studio'" class="s1-list">
              <label
                v-for="script in studioScripts"
                :key="script.id"
                class="s1-row"
                :class="{ sel: selectedScriptIds.includes(script.id) }"
              >
                <span class="top">
                  <input v-model="selectedScriptIds" type="checkbox" :value="script.id" :disabled="submitting" />
                  <span class="title">{{ script.title || script.id }}</span>
                  <span class="tts-tag" :class="script.narration?.state === 'ready' ? 'tts-ready' : 'tts-only'">
                    {{ script.narration?.state === 'ready' ? 'TTS Ready' : 'Script Only' }}
                  </span>
                </span>
                <span class="meta2">{{ script.word_count || 0 }} words</span>
              </label>
            </div>
          </div>

          <div v-if="sourceKind === 'input' && providerRequired" class="provider-note" role="status">
            This mode uses a script provider from the Channel defaults. Configure
            providers under the Channel editor if generation fails.
          </div>
          <div v-else-if="sourceKind === 'input'" class="provider-note local" role="status">
            No provider. Paste / Manual run through Script Input only — no
            script provider is configured or required.
          </div>
        </div>

        <fieldset v-if="sourceKind === 'input'" class="field narration-fieldset">
          <legend class="field-label">Narration processing</legend>
          <p class="field-hint narration-source">
            {{
              removeSilenceOverride === 'inherit' && speedOverride === ''
                ? `Inherited from ${selectedChannel?.name || 'Channel'}`
                : 'Overridden for this script'
            }}
          </p>
          <div class="narration-grid">
            <label class="field-label" for="narration-silence">
              Remove silence
              <em v-if="removeSilenceOverride === 'inherit'">inherited</em>
            </label>
            <label class="field-label" for="narration-speed">
              Speed
              <em v-if="speedOverride === ''">inherited</em>
            </label>
            <select
              id="narration-silence"
              v-model="removeSilenceOverride"
              :disabled="submitting || !channelId"
            >
              <option value="inherit">
                Inherited ({{ inheritedRemoveSilence ? 'On' : 'Off' }})
              </option>
              <option value="on">On</option>
              <option value="off">Off</option>
            </select>
            <select
              id="narration-speed"
              v-model="speedOverride"
              :disabled="submitting || !channelId"
            >
              <option value="">Inherited ({{ inheritedSpeed }}×)</option>
              <option v-for="speed in [0.9, 1, 1.1, 1.15, 1.25, 1.5]" :key="speed" :value="String(speed)">
                {{ speed }}×
              </option>
            </select>
          </div>
        </fieldset>

        <!-- C. Execution -->
        <div class="field">
          <div class="lbl"><span>Execution</span><span class="step-n">03</span></div>
          <div class="segmented seg-2" id="execSeg">
            <label
              v-for="tile in EXEC_TILES"
              :key="tile.id"
              class="seg-opt"
              :class="{ sel: launchIntent === tile.id }"
            >
              <input
                type="radio"
                name="exec_tile"
                :value="tile.id"
                :checked="launchIntent === tile.id"
                :disabled="submitting"
                @change="selectExec(tile.id)"
              />
              <span class="ic" aria-hidden="true">
                <svg v-if="tile.id === 'queue'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h10"/></svg>
                <svg v-else-if="tile.id === 'now'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="6 3 20 12 6 21 6 3"/></svg>
                <svg v-else-if="tile.id === 'scheduled'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
                <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 6v6l4 2"/><path d="M16 2l4 4-4 4" stroke-width="1.6"/></svg>
              </span>
              <span class="txt"><span class="t">{{ tile.t }}</span><span class="d">{{ tile.d }}</span></span>
            </label>
          </div>
        </div>

        <ul v-if="fieldErrors.length" class="errors" role="alert">
          <li v-for="(msg, idx) in fieldErrors" :key="idx">{{ msg }}</li>
        </ul>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </div>

      <div class="rail-foot">
        <button type="submit" class="btn primary block" :disabled="!canSubmit">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
          {{
            submitting
              ? 'Adding…'
              : sourceKind === 'studio'
                ? `Queue ${selectedScriptIds.length} Job${selectedScriptIds.length === 1 ? '' : 's'}`
                : 'Add to Batch'
          }}
        </button>
        <div class="add-summary">{{ addSummary }}</div>
      </div>
    </form>
  </aside>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.rail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
  border-right: 1px solid var(--line);
  background: linear-gradient(180deg, var(--bg-2), var(--bg));
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.rail-head {
  position: sticky;
  top: 0;
  z-index: 5;
  padding: 18px 20px 12px;
  background: linear-gradient(180deg, var(--bg-2) 70%, transparent);
}

.rail-head h2 {
  margin: 0;
  font-family: var(--display);
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.rail-head .sub {
  color: var(--muted);
  font-size: 12px;
  margin-top: 3px;
}

.rail-form {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.rail-body {
  padding: 4px 20px 20px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.rail-loading { padding: 8px 20px; }

.field {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.field > .lbl {
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.9px;
  text-transform: uppercase;
  color: var(--muted);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.step-n { color: var(--faint); font-size: 10px; }

.field-label {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.field-hint {
  font-family: var(--mono);
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--faint);
}

.channel-pick {
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: var(--panel-grad);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 12px;
  cursor: pointer;
  position: relative;
  transition: border-color 0.16s, background 0.16s, box-shadow 0.16s;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.25);
}

.channel-pick:hover {
  border-color: var(--line-2);
  background: var(--panel-grad2);
  box-shadow: var(--hairline-top), 0 6px 16px -8px rgba(0, 0, 0, 0.5);
}

.channel-pick .chev {
  margin-left: auto;
  color: var(--muted);
  flex: none;
  transition: transform 0.18s;
}

.channel-pick.open .chev { transform: rotate(180deg); }

.ch-avatar {
  width: 38px;
  height: 38px;
  border-radius: 9px;
  flex: none;
  display: grid;
  place-items: center;
  font-family: var(--display);
  font-weight: 600;
  font-size: 15px;
  color: #fff;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
}

.ch-meta { min-width: 0; }
.ch-meta .nm {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: -0.1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ch-meta .row2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
  color: var(--muted);
  font-size: 11.5px;
}

.dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  z-index: 40;
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--shadow);
  overflow: hidden;
  padding: 5px;
  display: none;
}

.dropdown.open { display: block; animation: pop 0.14s ease; }

@keyframes pop {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}

.dd-item {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  padding: 9px;
  border: 0;
  border-radius: var(--r-s);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-align: left;
}

.dd-item:hover { background: var(--raise); }
.dd-item.sel { background: var(--accent-wash); }
.dd-item .ch-avatar { width: 32px; height: 32px; font-size: 13px; border-radius: 8px; }
.dd-item .check { margin-left: auto; color: var(--accent); opacity: 0; flex: none; }
.dd-item.sel .check { opacity: 1; }
.dd-txt { min-width: 0; display: flex; flex-direction: column; }
.dd-txt .nm { font-size: 13px; font-weight: 600; }
.dd-txt .src { font-family: var(--mono); font-size: 10px; color: var(--muted); }

.inherits {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.inherit-chip {
  font-size: 11px;
  color: var(--text-2);
  border: 1px solid var(--line-soft);
  background: var(--bg-2);
  border-radius: 20px;
  padding: 3px 9px 3px 7px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.inherit-chip .k { color: var(--muted); font-size: 10px; }

.inherit-note {
  font-size: 11px;
  color: var(--faint);
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.source-detail { display: none; }
.source-detail.show { display: block; animation: pop 0.16s ease; }

.script-in {
  width: 100%;
  min-height: 96px;
  resize: vertical;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
  line-height: 1.5;
  padding: 10px 11px;
}

.script-in:focus,
.txt:focus,
select:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.script-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--muted);
}

/* The prototype writes this as `input.txt`, and the element qualifier is
   load-bearing: `.txt` is also the label block inside every `.seg-opt` tile
   (`<span class="txt"><span class="t">…`). Unqualified, every source and
   execution tile got a text input's background, border and 10px padding
   painted behind its label — the dark box that made the tiles read as nested
   panels instead of the prototype's flat cards. */
input.txt {
  width: 100%;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
  padding: 10px 11px;
}

input.txt::placeholder { color: var(--faint); }

.idea-hint {
  font-size: 11px;
  color: var(--muted);
  margin-top: 7px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.idea-hint b { color: var(--accent); font-weight: 600; }

.s1-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 236px;
  overflow-y: auto;
  padding-right: 2px;
}

.s1-row {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: var(--r-s);
  padding: 9px 10px;
  cursor: pointer;
  transition: border-color 0.14s, background 0.14s;
}

.s1-row:hover { border-color: var(--line-2); background: var(--panel-2); }
.s1-row.sel { border-color: var(--accent-line); background: var(--accent-wash); }
.s1-row .top { display: flex; align-items: center; gap: 8px; }
.s1-row .title {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.s1-row .meta2 {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 5px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}

.tts-tag {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 9.5px;
  letter-spacing: 0.3px;
  padding: 2px 7px;
  border-radius: 5px;
  flex: none;
  text-transform: uppercase;
}

.tts-ready { color: var(--ok); background: var(--ok-dim); box-shadow: inset 0 0 0 1px var(--ok-line); }
.tts-only { color: var(--muted); background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line); }

.narration-fieldset {
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--bg-2);
}

.narration-source { margin: 0 0 10px; }
.narration-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-template-rows: auto auto;
  column-gap: 10px;
  row-gap: 6px;
  align-items: stretch;
}

.narration-grid .field-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  min-height: 1.4em;
}

.field-label em {
  margin-left: 0;
  flex: none;
  color: var(--accent);
  font-style: normal;
  letter-spacing: 0;
  text-transform: lowercase;
}

.narration-fieldset select {
  width: 100%;
  min-width: 0;
  height: 38px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--text);
  border-radius: var(--r-s);
  padding: 0 28px 0 11px;
  font-family: var(--body);
  font-size: 13px;
  line-height: 38px;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%237c8698' stroke-width='2'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
}

.provider-note {
  border-radius: var(--r-s);
  padding: 11px 13px;
  font-size: 12.5px;
  line-height: 1.55;
  background: var(--warn-dim);
  border: 1px solid var(--warn-line);
  color: var(--warn-text);
}

.provider-note.local {
  background: var(--ok-dim);
  border-color: var(--ok-line);
  color: var(--ok);
}

.rail-foot {
  margin-top: auto;
  padding: 14px 20px 18px;
  border-top: 1px solid var(--line);
  background: var(--bg-2);
  position: sticky;
  bottom: 0;
}

.add-summary {
  font-size: 11.5px;
  color: var(--muted);
  margin-top: 9px;
  text-align: center;
  line-height: 1.5;
}

.errors {
  margin: 0;
  padding: 11px 13px 11px 32px;
  border-radius: var(--r-s);
  background: var(--fail-dim);
  border: 1px solid var(--fail-line);
  color: var(--fail-text);
  font-size: 12.5px;
  line-height: 1.6;
}

.error {
  margin: 0;
  color: var(--fail);
  font-size: 12.5px;
  line-height: 1.5;
}

.muted { color: var(--muted); font-size: 13px; }

@media (max-width: 820px) {
  .rail {
    border-right: 0;
    border-bottom: 1px solid var(--line);
    max-height: none;
  }
}

@media (max-width: 640px) {
  .narration-grid { grid-template-columns: 1fr; }
}
</style>

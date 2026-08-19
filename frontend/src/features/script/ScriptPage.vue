<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { getChannel, listChannels } from '@/features/channels/api.js'
import { useToast } from '@/shared/composables/useToast.js'
import { channelAccent, channelInitials } from '@/shared/utils/channelIdentity.js'
import {
  createScript,
  generateNarration,
  generateScript,
  getScript,
  listNarrationVoices,
  listScripts,
  narrationAudioUrl,
  scoreScript,
  updateScript,
} from './api.js'
import { applyTemplateOutline } from './generation.js'
import ViralityPanel from './ViralityPanel.vue'

defineOptions({ name: 'ScriptPage' })

const router = useRouter()
const toast = useToast()
const scripts = ref([])
const channels = ref([])
const channelDetails = reactive({})
const selected = ref(null)
const narrationAudio = ref(null)
const query = ref('')
const narrationFilter = ref('all')
const loading = ref(true)
const loadingDetail = ref(false)
const saving = ref(false)
const creating = ref(false)
const generating = ref(false)
const generatingNarration = ref(false)
const scoringVirality = ref(false)
const virality = ref(null)
const viralityText = ref('')
const voices = ref([])
const error = ref('')
const dirty = ref(false)
const searchInput = ref(null)
let searchTimer = null

const form = reactive({ title: '', body: '' })
const narrationForm = reactive({ voice: '', removeSilence: null, speed: null })
const draft = reactive({
  mode: 'auto',
  channelId: '',
  title: '',
  idea: '',
  body: '',
})
/** Session-only, like the prototype — Narration has no persist field for it. */
const autoTts = ref(false)

const originLabels = {
  auto: 'Auto',
  paste: 'Pasted',
  idea: 'Idea → Script',
  manual: 'Manual',
}

/** The prototype's three library chips, in its order. */
const narrationFilters = [
  { id: 'all', label: 'All' },
  { id: 'ready', label: 'TTS Ready' },
  { id: 'only', label: 'Script Only' },
]

const SPEED_CHOICES = [0.75, 0.9, 1, 1.1, 1.25, 1.5]
/** Narration overrides are narrower than Channel audio_defaults.speed (0.25–4). */
const SPEED_OVERRIDE_MIN = 0.5
const SPEED_OVERRIDE_MAX = 2.0

/**
 * 48 bars, the prototype's deterministic silhouette. It is a progress track,
 * not a waveform: nothing here has a per-sample envelope to draw.
 */
const WAVE_BARS = Array.from({ length: 48 }, (_, index) => 18 + Math.abs(Math.sin(index * 1.7)) * 70)

const selectedChannel = computed(() => (
  channelDetails[draft.channelId]
  || channels.value.find(channel => channel.id === draft.channelId)
  || null
))
const template = computed(() => selectedChannel.value?.script_template || null)
const liveWordCount = computed(() => wordCount(form.body))
const liveDuration = computed(() => Math.round(liveWordCount.value / 2.5))
const pasteWordCount = computed(() => wordCount(draft.body))
const pasteDuration = computed(() => Math.round(pasteWordCount.value / 2.5))
const scriptChannel = computed(() => selected.value ? channelDetails[selected.value.channel_id] : null)
const channelAudio = computed(() => scriptChannel.value?.audio_defaults || {})
const activeRemoveSilence = computed(() => narrationForm.removeSilence ?? channelAudio.value.remove_silence ?? true)
const activeSpeed = computed(() => Number(narrationForm.speed ?? channelAudio.value.speed ?? 1))
const silenceInherited = computed(() => narrationForm.removeSilence === null)
const speedInherited = computed(() => narrationForm.speed === null)
const processingInherited = computed(() => silenceInherited.value && speedInherited.value)
/**
 * The `.prov` chip names the Channel's narration binding. It is an instance
 * reference read from the Channel document — never a provider name written here.
 */
const narrationProvider = computed(() => (
  channelAudio.value.tts_provider_instance_id
  || scriptChannel.value?.provider_defaults?.tts
  || 'Channel default'
))
/**
 * Override options stay inside the narration API window. An out-of-range
 * Channel default is listed only while inherited, so the select can show it
 * without offering an illegal override.
 */
const speedChoices = computed(() => {
  const values = new Set(SPEED_CHOICES)
  const effective = activeSpeed.value
  if (Number.isFinite(effective) && effective >= SPEED_OVERRIDE_MIN && effective <= SPEED_OVERRIDE_MAX) {
    values.add(effective)
  } else if (speedInherited.value && Number.isFinite(effective)) {
    values.add(effective)
  }
  return [...values].sort((left, right) => left - right)
})
const narrationState = computed(() => {
  if (generatingNarration.value) return 'generating'
  return selected.value?.narration?.state || 'none'
})
const audioUrl = computed(() => {
  const artifactId = selected.value?.narration?.audio_artifact_id
  return artifactId ? narrationAudioUrl(selected.value.id, artifactId) : ''
})
const takeDuration = computed(() => Number(selected.value?.narration?.duration_s) || 0)
const viralityStale = computed(() => Boolean(virality.value) && viralityText.value !== form.body)

const readyCount = computed(() => scripts.value.filter(isNarrated).length)
/**
 * Chip counts describe the set the search returned, not the whole library: the
 * query is answered by the backend, so counting anything else would take a
 * second unfiltered request whose numbers would disagree with the list.
 */
const filterCounts = computed(() => ({
  all: scripts.value.length,
  ready: readyCount.value,
  only: scripts.value.length - readyCount.value,
}))
const visibleScripts = computed(() => {
  if (narrationFilter.value === 'ready') return scripts.value.filter(isNarrated)
  if (narrationFilter.value === 'only') return scripts.value.filter(script => !isNarrated(script))
  return scripts.value
})

const audio = ref(null)
const playing = ref(false)
const elapsed = ref(0)
const playPos = computed(() => (takeDuration.value ? elapsed.value / takeDuration.value : 0))

function isNarrated(script) {
  return script?.narration?.state === 'ready'
}

/** The prototype folds `generating` into Script Only for the chips. */
function narrationTag(script) {
  if (isNarrated(script)) return { cls: 'tts-ready', label: 'TTS Ready' }
  if (script?.narration?.state === 'generating') return { cls: 'mini-run', label: 'Generating' }
  return { cls: 'tts-only', label: 'Script Only' }
}

function wordCount(value) {
  const text = String(value || '').trim()
  return text ? text.split(/\s+/).length : 0
}

function formatDuration(seconds) {
  const total = Math.max(0, Number(seconds) || 0)
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(Math.floor(total % 60)).padStart(2, '0')}`
}

function formatDate(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
    .format(new Date(value))
}

function channelFor(id) {
  return channels.value.find(channel => channel.id === id)
}

function scriptDraft(document, body = document.body) {
  return {
    title: document.title,
    body,
    channel_id: document.channel_id,
    origin: document.origin,
    narration: document.narration,
  }
}

async function loadLibrary() {
  loading.value = true
  error.value = ''
  try {
    const payload = await listScripts({ query: query.value })
    scripts.value = payload.scripts || []
  } catch (exc) {
    error.value = exc.message || 'Could not load the script library'
  } finally {
    loading.value = false
  }
}

function search() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadLibrary, 220)
}

function setFilter(id) {
  narrationFilter.value = id
}

function stopPlayer() {
  const element = audio.value
  if (element) {
    element.pause()
    element.currentTime = 0
  }
  playing.value = false
  elapsed.value = 0
}

function togglePlay() {
  const element = audio.value
  if (!element) return
  if (playing.value) {
    element.pause()
    return
  }
  // A blocked autoplay policy and jsdom both refuse. Neither is worth an error
  // banner, but the button must not be left reading Pause.
  try {
    const started = element.play()
    if (started?.catch) started.catch(() => { playing.value = false })
  } catch {
    playing.value = false
  }
}

function trackTime() {
  elapsed.value = Number(audio.value?.currentTime) || 0
}

async function openScript(summary) {
  if (dirty.value && selected.value?.id !== summary.id) {
    toast.warning('Save or discard the current edits before opening another script')
    return
  }
  loadingDetail.value = true
  error.value = ''
  stopPlayer()
  try {
    const payload = await getScript(summary.id)
    selected.value = payload.script
    narrationAudio.value = payload.narration_audio || null
    virality.value = payload.virality || null
    viralityText.value = payload.virality ? payload.script.body : ''
    const channel = await loadChannelDetail(payload.script.channel_id)
    form.title = payload.script.title
    form.body = payload.script.body
    narrationForm.voice = payload.script.narration.voice || channel?.audio_defaults?.voice || ''
    narrationForm.removeSilence = payload.script.narration.remove_silence ?? null
    narrationForm.speed = payload.script.narration.speed ?? null
    await loadVoices(channel)
    dirty.value = false
    creating.value = false
  } catch (exc) {
    error.value = exc.message || 'Could not open the script'
  } finally {
    loadingDetail.value = false
  }
}

function markDirty() {
  dirty.value = true
}

async function save() {
  if (!selected.value || saving.value) return
  const title = form.title.trim()
  if (!title) {
    toast.warning('Give this script a title')
    return
  }
  const bodyChanged = form.body !== selected.value.body
  saving.value = true
  error.value = ''
  try {
    const payload = await updateScript(
      selected.value.id,
      { ...scriptDraft(selected.value, form.body), title },
      selected.value.version,
    )
    selected.value = payload.script
    form.title = payload.script.title
    form.body = payload.script.body
    dirty.value = false
    await loadLibrary()
    toast.success(`${payload.script.id} saved`)
    if (autoTts.value && bodyChanged && narrationState.value !== 'ready') {
      toast.info('Auto-generate on: creating narration…')
      await makeNarration()
    }
  } catch (exc) {
    error.value = exc.message || 'Could not save the script'
  } finally {
    saving.value = false
  }
}

async function duplicateScript() {
  if (!selected.value) return
  try {
    const payload = await createScript({
      title: `${form.title.trim() || selected.value.title} (copy)`,
      body: form.body,
      channel_id: selected.value.channel_id,
      origin: selected.value.origin || 'paste',
      narration: { state: 'none', voice: narrationForm.voice || '' },
    })
    await loadLibrary()
    toast.success(`${payload.script.id} duplicated`)
    await openScript(payload.script)
  } catch (exc) {
    error.value = exc.message || 'Could not duplicate the script'
  }
}

async function loadChannelDetail(channelId) {
  if (!channelId || channelDetails[channelId]) return channelDetails[channelId]
  try {
    const payload = await getChannel(channelId)
    channelDetails[channelId] = payload.channel
    return payload.channel
  } catch (exc) {
    error.value = exc.message || 'Could not load the Channel template'
    return null
  }
}

async function loadVoices(channel) {
  const provider = channel?.audio_defaults?.tts_provider_instance_id
    || channel?.provider_defaults?.tts
    || undefined
  try {
    const items = await listNarrationVoices(provider)
    voices.value = Array.isArray(items) ? items : []
  } catch {
    voices.value = []
  }
  const chosen = narrationForm.voice || channel?.audio_defaults?.voice || ''
  if (chosen && !voices.value.some(item => item.id === chosen)) {
    voices.value.unshift({ id: chosen, label: chosen })
  }
  narrationForm.voice = chosen
}

/** Both processing controls write an explicit override; Reset restores null. */
function toggleRemoveSilence() {
  narrationForm.removeSilence = !activeRemoveSilence.value
}

function setSpeed(event) {
  const value = Number(event.target.value)
  const channelDefault = Number(channelAudio.value.speed ?? 1)
  // Re-picking the Channel default means inherit — same as Reset — and also
  // blocks writing an out-of-range Channel speed as an explicit override.
  if (!Number.isFinite(value) || value === channelDefault) {
    narrationForm.speed = null
    return
  }
  if (value < SPEED_OVERRIDE_MIN || value > SPEED_OVERRIDE_MAX) {
    narrationForm.speed = null
    return
  }
  narrationForm.speed = value
}

function resetProcessing() {
  narrationForm.removeSilence = null
  narrationForm.speed = null
}

async function makeNarration() {
  if (!selected.value || generatingNarration.value) return
  if (dirty.value) {
    toast.warning('Save the script edits before generating narration')
    return
  }
  generatingNarration.value = true
  error.value = ''
  stopPlayer()
  try {
    const payload = await generateNarration(selected.value.id, {
      voice: narrationForm.voice || undefined,
      remove_silence: narrationForm.removeSilence,
      speed: narrationForm.speed,
      expected_version: selected.value.version,
    })
    selected.value = payload.script
    narrationAudio.value = payload.narration_audio || null
    narrationForm.voice = payload.script.narration.voice
    narrationForm.removeSilence = payload.script.narration.remove_silence ?? null
    narrationForm.speed = payload.script.narration.speed ?? null
    await loadLibrary()
    toast.success('Narration ready')
  } catch (exc) {
    error.value = exc.message || 'Could not generate narration'
    // The backend restores the last playable take after a failed provider
    // call, which advances the optimistic version. Refresh before retrying.
    try {
      const payload = await getScript(selected.value.id)
      selected.value = payload.script
    } catch {
      /* Keep the actionable generation error visible. */
    }
  } finally {
    generatingNarration.value = false
  }
}

async function checkVirality() {
  if (!selected.value || scoringVirality.value) return
  if (!form.body.trim()) {
    toast.warning('Write a script before checking virality')
    return
  }
  scoringVirality.value = true
  error.value = ''
  try {
    const text = form.body
    const payload = await scoreScript(selected.value.id, text)
    virality.value = payload.virality
    viralityText.value = text
    toast.success(`Virality ${payload.virality.score} · ${payload.virality.band}`)
  } catch (exc) {
    error.value = exc.message || 'Could not score this script'
  } finally {
    scoringVirality.value = false
  }
}

async function startCreate() {
  if (dirty.value) {
    toast.warning('Save the current script before creating another one')
    return
  }
  stopPlayer()
  selected.value = null
  creating.value = true
  draft.mode = 'auto'
  draft.channelId = draft.channelId || channels.value[0]?.id || ''
  draft.title = ''
  draft.idea = ''
  draft.body = ''
  await loadChannelDetail(draft.channelId)
}

async function chooseChannel() {
  await loadChannelDetail(draft.channelId)
}

function chooseMode(mode) {
  draft.mode = mode
}

function cancelCreate() {
  creating.value = false
  if (scripts.value[0]) openScript(scripts.value[0])
}

function useInBatch() {
  if (!selected.value) return
  router.push({ name: 'production', query: { script: selected.value.id } })
}

const formatLabel = computed(() => {
  const mime = String(narrationAudio.value?.mime || '')
  if (!mime) return ''
  if (mime.includes('mpeg') || mime.includes('mp3')) return '48kHz · mp3'
  if (mime.includes('wav')) return '48kHz · wav'
  return mime.replace(/^audio\//, '')
})

function generationOptions(channel) {
  const content = channel?.content || {}
  return {
    idea: draft.mode === 'idea' ? draft.idea.trim() : undefined,
    niche_preset: content.niche || undefined,
    preset_style: content.script_style || 'cinematic',
    story_category: content.niche || 'motivation',
    story_tone: content.tone || undefined,
    language: content.language || 'english',
    duration: Math.min(180, Math.max(15, Number(content.target_duration_s) || 60)),
    template_brief: channel?.script_template?.brief,
    template_sections: channel?.script_template?.sections,
  }
}

async function createNew() {
  if (generating.value) return
  const channel = await loadChannelDetail(draft.channelId)
  if (!channel) return
  if (draft.mode === 'paste' && !draft.body.trim()) {
    toast.warning('Paste a script first')
    return
  }
  if (draft.mode === 'idea' && !draft.idea.trim()) {
    toast.warning('Describe the topic first')
    return
  }

  generating.value = true
  error.value = ''
  try {
    let body = draft.body
    let generatedTitle = ''
    if (draft.mode !== 'paste') {
      const result = await generateScript(generationOptions(channel))
      body = applyTemplateOutline(result.story_text, channel.script_template?.sections)
      generatedTitle = draft.mode === 'idea'
        ? draft.idea.trim().slice(0, 120)
        : `${channel.name} · ${formatDate(new Date())}`
    }

    const title = draft.title.trim()
      || generatedTitle
      || draft.body.trim().split(/\r?\n/)[0].slice(0, 120)
      || 'Untitled script'
    const payload = await createScript({
      title,
      body,
      channel_id: draft.channelId,
      origin: draft.mode,
      narration: { state: 'none', voice: '' },
    })
    creating.value = false
    selected.value = payload.script
    narrationAudio.value = payload.narration_audio || null
    virality.value = null
    viralityText.value = ''
    form.title = payload.script.title
    form.body = payload.script.body
    // Same handoff as openScript: do not keep the previous script's voice or
    // processing overrides on the new document.
    narrationForm.voice = payload.script.narration?.voice || channel.audio_defaults?.voice || ''
    narrationForm.removeSilence = payload.script.narration?.remove_silence ?? null
    narrationForm.speed = payload.script.narration?.speed ?? null
    await loadVoices(channel)
    dirty.value = false
    await loadLibrary()
    toast.success(`${payload.script.id} created`)
  } catch (exc) {
    error.value = exc.message || 'Could not create the script'
  } finally {
    generating.value = false
  }
}

function focusSearch(event) {
  if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return
  const target = event.target
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return
  event.preventDefault()
  searchInput.value?.focus()
}

// A take replaced mid-playback must not keep the old one's position.
watch(audioUrl, stopPlayer)

onMounted(async () => {
  window.addEventListener('keydown', focusSearch)
  try {
    const channelPayload = await listChannels({ limit: 500 })
    channels.value = channelPayload.channels || []
    draft.channelId = channels.value[0]?.id || ''
    await loadLibrary()
    if (scripts.value[0]) await openScript(scripts.value[0])
  } catch (exc) {
    error.value = exc.message || 'Could not open Script Studio'
    loading.value = false
  }
})

onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  window.removeEventListener('keydown', focusSearch)
})
</script>

<template>
  <section class="s1view" aria-label="Script Studio">
    <aside class="s1-rail">
      <div class="s1-rail-head">
        <div class="s1-rail-title">
          <h2>Script Library</h2>
          <button class="btn primary sm" type="button" @click="startCreate">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            New
          </button>
        </div>

        <label class="s1-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
          <span class="sr-only">Search scripts</span>
          <input ref="searchInput" v-model="query" type="search" placeholder="Search scripts…" @input="search">
          <kbd>/</kbd>
        </label>

        <div class="s1-filters" role="group" aria-label="Filter by narration state">
          <button
            v-for="chip in narrationFilters"
            :key="chip.id"
            type="button"
            class="s1-fchip"
            :class="{ sel: narrationFilter === chip.id }"
            :aria-pressed="narrationFilter === chip.id"
            :data-testid="`narration-filter-${chip.id}`"
            @click="setFilter(chip.id)"
          >{{ chip.label }} · {{ filterCounts[chip.id] }}</button>
        </div>
      </div>

      <div class="s1-list-wrap" data-testid="script-library" aria-live="polite">
        <div v-if="loading" class="rail-state">Loading scripts…</div>
        <div v-else-if="!scripts.length" class="rail-state">
          {{ query ? 'No scripts match that search.' : 'No scripts yet. Create the first one.' }}
        </div>
        <div v-else-if="!visibleScripts.length" class="rail-state">No scripts match.</div>
        <button
          v-for="script in visibleScripts"
          v-else
          :key="script.id"
          type="button"
          class="s1-card"
          :class="{ sel: selected?.id === script.id && !creating }"
          @click="openScript(script)"
        >
          <span class="row1">
            <span class="ch-avatar" :style="{ background: channelAccent(script.channel_id) }">{{ channelInitials(channelFor(script.channel_id)?.name) }}</span>
            <span class="ctitle">{{ script.title }}</span>
          </span>
          <span class="row2">
            <span class="origin-tag">{{ originLabels[script.origin] }}</span>
            <span class="meta">
              {{ formatDuration(script.estimated_duration_s) }}
              <span class="dot-sep" />
              {{ formatDate(script.updated_at) }}
            </span>
            <span class="tts-tag" :class="narrationTag(script).cls">{{ narrationTag(script).label }}</span>
          </span>
        </button>
      </div>

      <div class="s1-rail-foot">
        <span class="sd" />
        {{ readyCount }} with narration
        <span class="dot-sep" />
        {{ scripts.length }} total
      </div>
    </aside>

    <main class="s1-detail">
      <div v-if="error" class="banner error" role="alert">
        {{ error }}
        <button type="button" aria-label="Dismiss error" @click="error = ''">×</button>
      </div>

      <template v-if="creating">
        <div class="s1-doc-head">
          <div class="s1-doc-eyebrow">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            New Script
          </div>
          <input v-model="draft.title" class="s1-title-input" aria-label="New script title" placeholder="Untitled script">
          <div class="s1-doc-sub">
            <span class="kv">Channel
              <select v-model="draft.channelId" class="filter-select" aria-label="Draft channel" @change="chooseChannel">
                <option v-for="channel in channels" :key="channel.id" :value="channel.id">{{ channel.name }}</option>
              </select>
            </span>
          </div>
        </div>

        <div class="s1-doc-body single">
          <div class="s1-script-col">
            <div class="s1-col-label"><span>How should S1 create it?</span></div>
            <div class="segmented create-modes" role="tablist" aria-label="Create mode">
              <button type="button" role="tab" class="seg-opt" :class="{ sel: draft.mode === 'auto' }" :aria-selected="draft.mode === 'auto'" @click="chooseMode('auto')">
                <span class="ic"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2" /></svg></span>
                <span class="txt"><span class="t">Auto</span><span class="d">Next topic</span></span>
              </button>
              <button type="button" role="tab" class="seg-opt" :class="{ sel: draft.mode === 'idea' }" :aria-selected="draft.mode === 'idea'" @click="chooseMode('idea')">
                <span class="ic"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 18h6M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" /></svg></span>
                <span class="txt"><span class="t">Idea</span><span class="d">Topic → script</span></span>
              </button>
              <button type="button" role="tab" class="seg-opt" :class="{ sel: draft.mode === 'paste' }" :aria-selected="draft.mode === 'paste'" @click="chooseMode('paste')">
                <span class="ic"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="8" y="3" width="8" height="4" rx="1" /><path d="M8 5H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" /></svg></span>
                <span class="txt"><span class="t">Paste</span><span class="d">Bring your own</span></span>
              </button>
            </div>

            <p v-if="draft.mode === 'auto'" class="idea-hint">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              Scriptase picks the next topic for <b>{{ selectedChannel?.name || 'this channel' }}</b> and writes it to the template below.
            </p>

            <input
              v-if="draft.mode === 'idea'"
              id="idea-input"
              v-model="draft.idea"
              class="txt"
              aria-label="Topic or idea"
              placeholder="e.g. Why we replay old arguments in our heads…"
            >

            <template v-if="draft.mode !== 'paste'">
              <div v-if="template" class="s1-tpl-card">
                <div class="s1-tpl-head">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7V4h16v3M9 20h6M12 4v16" /></svg>
                  Using <b>{{ selectedChannel.name }}</b>'s template
                  <RouterLink class="s1-tpl-edit" :to="`/channels/${selectedChannel.id}`">Edit in Channel</RouterLink>
                </div>
                <div class="s1-tpl-brief">{{ template.brief }}</div>
                <div class="s1-tpl-chips" aria-label="Template section outline">
                  <span v-for="(section, index) in template.sections" :key="`${section}-${index}`" class="s1-tpl-chip">
                    <span class="n">{{ index + 1 }}</span>{{ section }}
                  </span>
                </div>
              </div>
              <div v-else class="rail-state">Loading Channel template…</div>
              <button
                class="btn primary s1-create-go"
                type="button"
                :disabled="generating || !draft.channelId"
                @click="createNew"
              >
                <svg v-if="draft.mode === 'auto'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v3M12 18v3M5 12H2M22 12h-3"/><circle cx="12" cy="12" r="4"/></svg>
                <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/></svg>
                {{ generating ? 'Writing…' : draft.mode === 'auto' ? 'Generate script' : 'Send to S1 → write script' }}
              </button>
            </template>

            <template v-else>
              <textarea id="paste-script" v-model="draft.body" class="s1-script-area paste" aria-label="Pasted script" placeholder="Paste your script here…" />
              <div class="script-meta"><span>{{ pasteWordCount }} words</span><span>~{{ formatDuration(pasteDuration) }} narration</span></div>
              <button
                class="btn primary s1-create-go"
                type="button"
                :disabled="generating || !draft.channelId"
                @click="createNew"
              >{{ generating ? 'Saving…' : 'Save pasted script' }}</button>
            </template>
          </div>
        </div>

        <div class="s1-doc-foot">
          <div class="spacer" />
          <button class="btn ghost sm" type="button" :disabled="generating" @click="cancelCreate">Cancel</button>
        </div>
      </template>

      <div v-else-if="loadingDetail" class="s1-empty"><h3>Opening script…</h3></div>

      <template v-else-if="selected">
        <div class="s1-doc-head">
          <div class="s1-doc-eyebrow">
            <span class="ch-avatar" :style="{ background: channelAccent(selected.channel_id) }">{{ channelInitials(channelFor(selected.channel_id)?.name) }}</span>
            {{ channelFor(selected.channel_id)?.name || 'Channel' }}
            <span class="dot-sep" />
            {{ selected.id }}
            <span class="dot-sep" />
            {{ originLabels[selected.origin] }}
          </div>
          <input v-model="form.title" class="s1-title-input" aria-label="Script title" @input="markDirty">
          <div class="s1-doc-sub">
            <span class="kv">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7V4h16v3M9 20h6M12 4v16" /></svg>
              <b>{{ liveWordCount }}</b> words
            </span>
            <span class="kv">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
              ~<b>{{ formatDuration(liveDuration) }}</b> narration
            </span>
            <span class="kv">Created <b>{{ formatDate(selected.created_at) }}</b></span>
          </div>
        </div>

        <div class="s1-doc-body">
          <div class="s1-script-col">
            <div class="s1-col-label">
              <span>Script</span>
              <button
                class="btn xs"
                type="button"
                title="Analyze this script for virality"
                data-testid="check-virality"
                :disabled="scoringVirality"
                @click="checkVirality"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 17l6-6 4 4 8-8" /><path d="M17 7h4v4" /></svg>
                Check Virality
              </button>
            </div>
            <textarea id="script-body" v-model="form.body" class="s1-script-area" :class="{ dirty }" aria-label="Script body" spellcheck="true" @input="markDirty" />
            <ViralityPanel
              :score="virality"
              :analyzing="scoringVirality"
              :stale="viralityStale"
              @analyze="checkVirality"
            />
          </div>

          <div class="s1-tts">
            <div class="s1-panel" aria-label="Narration controls">
              <div class="s1-panel-head">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" /><path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4" /></svg>
                <span class="pt">Narration</span>
                <span class="prov" data-testid="narration-provider">{{ narrationProvider }}</span>
              </div>
              <div class="s1-panel-body">
                <div
                  class="s1-tts-status"
                  :class="narrationState === 'ready' ? 'ready' : narrationState === 'generating' ? 'gen' : 'none'"
                  data-testid="narration-status"
                >
                  <div class="ic">
                    <svg v-if="narrationState === 'ready'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
                    <svg v-else-if="narrationState === 'generating'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2v4M12 18v4M2 12h4M18 12h4" /></svg>
                    <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2v20M6 8v8M18 8v8" /></svg>
                  </div>
                  <div class="txt">
                    <div class="t">
                      {{ narrationState === 'ready' ? 'Narration ready' : narrationState === 'generating' ? 'Generating…' : 'No narration yet' }}
                    </div>
                    <div class="d">
                      {{
                        narrationState === 'ready'
                          ? 'Production will reuse this — no regeneration'
                          : narrationState === 'generating'
                            ? 'The Channel’s voice provider is synthesizing narration'
                            : 'Generate narration to attach audio to this script'
                      }}
                    </div>
                  </div>
                </div>

                <div class="s1-kv">
                  <span class="k">Voice</span>
                  <span class="v">
                    <select v-model="narrationForm.voice" aria-label="Narration voice">
                      <option v-if="!voices.length" :value="narrationForm.voice">{{ narrationForm.voice || 'Channel default' }}</option>
                      <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.label || voice.id }}</option>
                    </select>
                  </span>
                </div>
                <div class="s1-kv">
                  <span class="k">Duration</span>
                  <span class="v mono">{{ takeDuration ? formatDuration(takeDuration) : '—' }}</span>
                </div>
                <div class="s1-kv">
                  <span class="k">Format</span>
                  <span class="v mono">{{ formatLabel || '—' }}</span>
                </div>

                <div v-if="audioUrl" class="s1-player">
                  <div class="controls">
                    <button
                      class="s1-play"
                      type="button"
                      :aria-label="playing ? 'Pause narration' : 'Play narration'"
                      data-testid="narration-play"
                      @click="togglePlay"
                    >
                      <svg v-if="playing" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
                      <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="6 3 20 12 6 21 6 3" /></svg>
                    </button>
                    <div class="s1-wave-track" aria-hidden="true">
                      <i
                        v-for="(height, index) in WAVE_BARS"
                        :key="index"
                        :class="{ on: index / WAVE_BARS.length <= playPos }"
                        :style="{ height: `${height}%` }"
                      />
                    </div>
                    <span class="time">{{ formatDuration(elapsed) }} / {{ formatDuration(takeDuration) }}</span>
                  </div>
                  <audio
                    ref="audio"
                    :key="audioUrl"
                    :src="audioUrl"
                    preload="metadata"
                    @play="playing = true"
                    @pause="playing = false"
                    @ended="stopPlayer"
                    @timeupdate="trackTime"
                  />
                </div>

                <div class="s1-tts-actions">
                  <button
                    class="btn sm block"
                    :class="{ primary: narrationState === 'none' }"
                    type="button"
                    data-testid="narration-generate"
                    :disabled="generatingNarration || dirty"
                    @click="makeNarration"
                  >
                    <svg v-if="narrationState === 'ready'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></svg>
                    <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2v20M6 8v8M18 8v8M2 11v2M22 11v2" /></svg>
                    {{ generatingNarration ? 'Generating…' : narrationState === 'ready' ? 'Regenerate narration' : 'Generate narration' }}
                  </button>
                </div>

                <div class="s1-proc">
                  <div class="s1-proc-head">
                    Processing
                    <span class="s1-proc-src">
                      {{ processingInherited ? `inherited from ${scriptChannel?.name || 'this Channel'}` : 'overridden for this script' }}
                    </span>
                  </div>
                  <div class="s1-kv">
                    <span class="k">Remove silence <span v-if="silenceInherited" class="s1-inh">inherited</span></span>
                    <span class="v">
                      <div
                        class="s1-toggle sm"
                        :class="{ on: activeRemoveSilence }"
                        role="switch"
                        tabindex="0"
                        :aria-checked="activeRemoveSilence"
                        aria-label="Remove silence override"
                        @click="toggleRemoveSilence"
                        @keydown.enter.prevent="toggleRemoveSilence"
                        @keydown.space.prevent="toggleRemoveSilence"
                      />
                    </span>
                  </div>
                  <div class="s1-kv">
                    <span class="k">Speed <span v-if="speedInherited" class="s1-inh">inherited</span></span>
                    <span class="v">
                      <select :value="activeSpeed" aria-label="Narration speed override" @change="setSpeed">
                        <option v-for="value in speedChoices" :key="value" :value="value">{{ value.toFixed(2) }}×</option>
                      </select>
                    </span>
                  </div>
                  <button v-if="!processingInherited" class="s1-proc-reset" type="button" @click="resetProcessing">
                    ↺ Reset to channel default
                  </button>
                </div>

                <div class="s1-autogen">
                  <div class="txt">
                    <div class="t">Auto-generate on save</div>
                    <div class="d">Keep narration in sync with the script</div>
                  </div>
                  <div
                    class="s1-toggle"
                    :class="{ on: autoTts }"
                    role="switch"
                    tabindex="0"
                    :aria-checked="autoTts"
                    aria-label="Auto-generate on save"
                    @click="autoTts = !autoTts"
                    @keydown.enter.prevent="autoTts = !autoTts"
                    @keydown.space.prevent="autoTts = !autoTts"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="s1-doc-foot">
          <div class="s1-dirty-note" :class="{ show: dirty }">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" /></svg>
            Unsaved changes
          </div>
          <div class="spacer" />
          <button class="btn ghost sm" type="button" :disabled="!selected" @click="useInBatch">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
            Use in Batch
          </button>
          <button class="btn sm" type="button" :disabled="!selected" @click="duplicateScript">Duplicate</button>
          <button class="btn primary sm" type="button" :disabled="saving || !dirty" @click="save">{{ saving ? 'Saving…' : 'Save' }}</button>
        </div>
      </template>

      <div v-else class="s1-empty">
        <div class="ic">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></svg>
        </div>
        <h3>No script selected</h3>
        <p>Pick a script from the library, or create a new one to start writing.</p>
        <button class="btn primary sm" type="button" @click="startCreate">Create script</button>
      </div>
    </main>
  </section>
</template>

<style scoped>
/* The prototype's `.body.s1view`: a library rail and a scrolling document. */
.s1view {
  display: grid;
  grid-template-columns: 380px minmax(0, 1fr);
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

/* ── Library rail ───────────────────────────────────────────────────── */
.s1-rail {
  border-right: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, .02), rgba(255, 255, 255, 0) 180px),
    linear-gradient(180deg, var(--bg-2), var(--bg));
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.s1-rail-head { padding: 18px 20px 14px; border-bottom: 1px solid var(--line-soft); }
.s1-rail-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.s1-rail-title h2 { margin: 0; font-family: var(--display); font-size: 15px; font-weight: 600; }

.s1-search { display: flex; align-items: center; gap: 8px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s); padding: 8px 11px; }
.s1-search:focus-within { border-color: var(--accent-line-2); box-shadow: 0 0 0 3px var(--accent-ring); }
.s1-search input { background: transparent; border: none; outline: none; color: var(--text); font-size: 13px; width: 100%; font-family: var(--body); }
.s1-search input::placeholder { color: var(--faint); }
.s1-search svg { color: var(--muted); flex: none; }
.s1-search kbd { flex: none; color: var(--faint); font: 10px var(--mono); }

.s1-filters { display: flex; gap: 6px; margin-top: 11px; flex-wrap: wrap; }
.s1-fchip {
  font-family: var(--mono); font-size: 10px; letter-spacing: .3px; text-transform: uppercase;
  color: var(--muted); border: 1px solid var(--line); background: var(--panel);
  border-radius: 20px; padding: 4px 10px; cursor: pointer; transition: all .12s;
}
.s1-fchip:hover { border-color: var(--line-2); color: var(--text-2); }
.s1-fchip.sel { color: var(--accent); border-color: var(--accent-line-2); background: var(--accent-dim); }

.s1-list-wrap { flex: 1; min-height: 0; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 7px; }
.s1-card {
  width: 100%; text-align: left; color: var(--text); flex: none;
  border: 1px solid var(--line); background: var(--panel); border-radius: var(--r-s);
  padding: 11px 12px; cursor: pointer; box-shadow: var(--hairline-top);
  transition: border-color .16s, background .16s, box-shadow .16s, transform .16s var(--ease-spring);
}
.s1-card:hover { border-color: var(--line-2); background: var(--panel-2); transform: translateY(-1px); }
.s1-card.sel { border-color: var(--accent-line-2); background: var(--accent-wash); box-shadow: var(--hairline-top), inset 0 0 0 1px var(--accent-line); }
.s1-card .row1 { display: flex; align-items: center; gap: 8px; }
/* Step 6.4 answered the colour question 6.3 left open: the plate is the
   shared `.ch-avatar`, tinted from the channel id, so the same channel reads
   the same here, in a job row and in the Channels rail. */
.s1-card .ch-avatar { width: 20px; height: 20px; border-radius: 5px; font-size: 9px; }
.s1-card .ctitle { font-size: 13px; font-weight: 600; letter-spacing: -.1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.s1-card .row2 { display: flex; align-items: center; gap: 7px; margin-top: 7px; }
.s1-card .meta { font-family: var(--mono); font-size: 10px; color: var(--muted); display: flex; align-items: center; gap: 6px; min-width: 0; }
.s1-card .origin-tag {
  flex: none; font-family: var(--mono); font-size: 9px; letter-spacing: .3px; text-transform: uppercase;
  padding: 2px 6px; border-radius: 4px; color: var(--text-2); background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line-soft);
}
.s1-card .tts-tag { margin-left: auto; }

.s1-rail-foot { padding: 11px 16px; border-top: 1px solid var(--line-soft); font-family: var(--mono); font-size: 10.5px; color: var(--muted); display: flex; align-items: center; gap: 8px; }
.s1-rail-foot .sd { width: 7px; height: 7px; border-radius: 50%; flex: none; background: var(--ok); }

.rail-state { padding: 30px 16px; text-align: center; color: var(--muted); font-size: 12.5px; line-height: 1.5; }

/* ── Detail / editor ────────────────────────────────────────────────── */
.s1-detail {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.s1-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: var(--muted); padding: 40px; }
.s1-empty .ic {
  width: 60px; height: 60px; border-radius: 16px; display: grid; place-items: center;
  background: var(--panel); box-shadow: inset 0 0 0 1px var(--line); color: var(--faint); margin-bottom: 18px;
}
.s1-empty h3 { margin: 0 0 7px; font-family: var(--display); font-size: 16px; color: var(--text); }
.s1-empty p { margin: 0; font-size: 13px; max-width: 300px; line-height: 1.6; }
.s1-empty .btn { margin-top: 16px; }

.s1-doc-head { flex: none; padding: 22px 30px 18px; border-bottom: 1px solid var(--line-soft); }
.s1-doc-eyebrow { display: flex; align-items: center; gap: 9px; font-family: var(--mono); font-size: 10.5px; letter-spacing: .5px; color: var(--muted); margin-bottom: 12px; text-transform: uppercase; }
.s1-doc-eyebrow .ch-avatar { width: 18px; height: 18px; border-radius: 5px; font-size: 8px; }
.s1-title-input {
  width: 100%; background: transparent; border: none; outline: none; color: var(--text);
  font-family: var(--display); font-weight: 600; font-size: 24px; letter-spacing: -.5px; padding: 0;
}
.s1-title-input:focus { color: #fff; }
.s1-doc-sub { display: flex; align-items: center; gap: 14px; margin-top: 12px; font-family: var(--mono); font-size: 11px; color: var(--muted); flex-wrap: wrap; }
.s1-doc-sub .kv { display: flex; align-items: center; gap: 5px; }
.s1-doc-sub .kv b { color: var(--text-2); font-weight: 500; }

.s1-doc-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 22px 30px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 26px;
  align-items: start;
}
/* The create flow has no narration column yet, so it runs one wide. */
.s1-doc-body.single { grid-template-columns: minmax(0, 1fr); max-width: 860px; }
.s1-script-col { min-width: 0; }
.s1-col-label { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 11px; font-family: var(--mono); font-size: 10px; letter-spacing: .8px; text-transform: uppercase; color: var(--muted); }
.s1-script-area {
  box-sizing: border-box; width: 100%; min-height: 340px; resize: vertical;
  background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r);
  color: var(--text); font-family: var(--body); font-size: 14.5px; line-height: 1.75; padding: 18px 20px;
}
.s1-script-area:focus { outline: none; border-color: var(--accent-line); box-shadow: 0 0 0 3px var(--accent-ring); }
.s1-script-area.dirty { border-color: var(--warn-line); }
.s1-script-area.paste { min-height: 220px; }

/* ── Create flow ────────────────────────────────────────────────────── */
.create-modes { grid-template-columns: repeat(3, 1fr); margin-bottom: 16px; }
.idea-hint { display: flex; align-items: center; gap: 6px; margin: 0 0 12px; font-size: 11px; color: var(--muted); }
.idea-hint b { color: var(--accent); font-weight: 600; }
.idea-hint svg { flex: none; }

input.txt {
  box-sizing: border-box; width: 100%; margin-bottom: 12px; padding: 10px 11px;
  background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r-s);
  color: var(--text); font-family: var(--body); font-size: 13px;
}
input.txt::placeholder { color: var(--faint); }
input.txt:focus { outline: none; border-color: var(--accent-line-2); box-shadow: 0 0 0 3px var(--accent-ring); }

.filter-select {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s);
  color: var(--text-2); font-family: var(--body); font-size: 12.5px; padding: 4px 8px; cursor: pointer;
}
.filter-select:focus { outline: none; border-color: var(--accent-line-2); }
.script-meta { display: flex; justify-content: space-between; margin-top: 8px; font-family: var(--mono); font-size: 10.5px; color: var(--muted); }

.s1-tpl-card { border: 1px solid var(--line); border-radius: var(--r); background: var(--panel-grad); box-shadow: var(--hairline-top); padding: 13px 14px; }
.s1-tpl-head { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 600; color: var(--text); }
.s1-tpl-head svg { flex: none; color: var(--accent); }
.s1-tpl-head b { color: var(--accent); font-weight: 600; }
.s1-tpl-edit { margin-left: auto; font-size: 11px; font-weight: 500; color: var(--muted); cursor: pointer; text-decoration: none; }
.s1-tpl-edit:hover { color: var(--accent); text-decoration: underline; }
.s1-tpl-brief { margin: 9px 0 12px; font-size: 12.5px; color: var(--text-2); line-height: 1.55; }
.s1-tpl-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.s1-tpl-chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px 3px 4px;
  border: 1px solid var(--line-soft); border-radius: 20px; background: var(--bg-2);
  color: var(--text-2); font-size: 11px;
}
.s1-tpl-chip .n {
  width: 16px; height: 16px; border-radius: 50%; display: grid; place-items: center;
  font-family: var(--mono); font-size: 9px; font-weight: 700; color: var(--accent); background: var(--accent-dim);
}

/* ── Narration panel ───────────────────────────────────────────────── */
.s1-tts { position: sticky; top: 0; }
.s1-panel { border: 1px solid var(--line); border-radius: var(--r); background: linear-gradient(180deg, var(--panel), var(--bg-2)); overflow: hidden; }
.s1-panel-head { display: flex; align-items: center; gap: 9px; padding: 13px 16px; border-bottom: 1px solid var(--line-soft); }
.s1-panel-head > svg { flex: none; color: var(--run); }
.s1-panel-head .pt { font-family: var(--display); font-weight: 600; font-size: 13.5px; }
.s1-panel-head .prov {
  margin-left: auto; max-width: 45%; padding: 3px 8px; border-radius: 5px;
  font-family: var(--mono); font-size: 10px; color: var(--run); background: var(--run-dim);
  box-shadow: inset 0 0 0 1px var(--run-line);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.s1-panel-body { padding: 15px 16px; }

.s1-tts-status { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-radius: var(--r-s); margin-bottom: 14px; }
.s1-tts-status.ready { background: var(--ok-dim); box-shadow: inset 0 0 0 1px var(--ok-line); }
.s1-tts-status.none { background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line); }
.s1-tts-status.gen { background: var(--run-dim); box-shadow: inset 0 0 0 1px var(--run-line); }
.s1-tts-status .ic { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; flex: none; }
.s1-tts-status.ready .ic { background: var(--ok-dim); color: var(--ok); }
.s1-tts-status.none .ic { background: var(--raise); color: var(--muted); }
.s1-tts-status.gen .ic { background: var(--run-dim); color: var(--run); }
.s1-tts-status .txt .t { font-size: 13px; font-weight: 600; }
.s1-tts-status .txt .d { margin-top: 1px; font-size: 11px; color: var(--muted); line-height: 1.35; }
.s1-tts-status.ready .txt .t { color: var(--ok); }
.s1-tts-status.gen .txt .t { color: var(--run); }

.s1-kv { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 0; font-size: 12.5px; border-bottom: 1px solid var(--line-soft); }
.s1-kv:last-of-type { border-bottom: none; }
.s1-kv .k { color: var(--muted); }
.s1-kv .v { min-width: 0; color: var(--text); font-weight: 500; }
.s1-kv select {
  max-width: 100%; background: var(--bg-2); border: 1px solid var(--line); border-radius: 6px;
  color: var(--text); font-family: var(--body); font-size: 12px; padding: 5px 8px; cursor: pointer;
}
.s1-kv select:focus { outline: none; border-color: var(--accent-line-2); }

.s1-player { margin: 14px 0 4px; padding: 12px 14px; border-radius: var(--r-s); background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line-soft); }
.s1-player .controls { display: flex; align-items: center; gap: 11px; }
.s1-play {
  width: 34px; height: 34px; border-radius: 50%; flex: none; border: none; cursor: pointer;
  background: linear-gradient(180deg, #4bbf92, var(--ok)); color: #052018; display: grid; place-items: center;
  box-shadow: 0 4px 12px -4px rgba(53, 192, 138, .7);
}
.s1-play:hover { filter: brightness(1.08); }
.s1-wave-track { flex: 1; min-width: 0; height: 26px; display: flex; align-items: center; gap: 2px; overflow: hidden; }
.s1-wave-track i { flex: 1; background: var(--faint); border-radius: 1px; min-width: 2px; transition: background .1s; }
.s1-wave-track i.on { background: var(--ok); }
.s1-player .time { flex: none; font-family: var(--mono); font-size: 11px; color: var(--muted); }
.s1-player audio { display: none; }

.s1-tts-actions { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.s1-create-go { margin-top: 14px; }
.s1-autogen { display: flex; align-items: center; gap: 10px; margin-top: 14px; padding-top: 13px; border-top: 1px solid var(--line-soft); }
.s1-autogen .txt { flex: 1; }
.s1-autogen .txt .t { font-size: 12.5px; font-weight: 500; }
.s1-autogen .txt .d { font-size: 10.5px; color: var(--muted); margin-top: 1px; }

.s1-proc { margin-top: 14px; padding-top: 13px; border-top: 1px solid var(--line-soft); }
.s1-proc-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; font-family: var(--mono); font-size: 9.5px; letter-spacing: .5px; text-transform: uppercase; color: var(--muted); }
.s1-proc-src { color: var(--faint); text-transform: none; letter-spacing: 0; }
.s1-inh {
  margin-left: 5px; padding: 1px 5px; border-radius: 4px; vertical-align: middle;
  font-family: var(--mono); font-size: 8.5px; text-transform: uppercase; letter-spacing: .3px;
  color: var(--muted); background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line-soft);
}
.s1-proc-reset {
  margin-top: 8px; width: 100%; padding: 6px; border: 1px dashed var(--line); border-radius: var(--r-s);
  background: transparent; color: var(--muted); font-family: var(--body); font-size: 11.5px; cursor: pointer;
}
.s1-proc-reset:hover { color: var(--text-2); border-color: var(--line-2); }

/* `.s1-toggle` itself lives in styles/shared.css: the prototype reuses it in
   the Channel editor's narration rows, so step 6.4 made it cross-cutting. */

/* ── Document footer ───────────────────────────────────────────────── */
.s1-doc-foot {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 30px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg-2);
  z-index: 4;
}
.s1-doc-foot .spacer { flex: 1; }
.s1-dirty-note { display: none; align-items: center; gap: 6px; font-family: var(--mono); font-size: 11px; color: var(--warn); }
.s1-dirty-note.show { display: flex; }

.banner.error { display: flex; align-items: center; gap: 12px; margin: 14px 30px 0; }
.banner.error button { margin-left: auto; border: 0; background: transparent; color: inherit; font-size: 15px; cursor: pointer; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }

@media (max-width: 820px) {
  .s1-doc-body { grid-template-columns: 1fr; }
  .s1-tts { position: static; }
}

/* The prototype hides the rail below 820px because its library lives in a
   modal there. This app has no such modal, so the rail stacks instead. */
@media (max-width: 820px) {
  .s1view { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); }
  .s1-rail { border-right: 0; border-bottom: 1px solid var(--line); }
  .s1-list-wrap { max-height: 260px; }
  .create-modes { grid-template-columns: 1fr; }
  .s1-doc-head, .s1-doc-body, .s1-doc-foot { padding-left: 16px; padding-right: 16px; }
  .banner.error { margin-left: 16px; margin-right: 16px; }
  .s1-title-input { font-size: 21px; }
}

@media (prefers-reduced-motion: reduce) {
  .s1-card, .s1-fchip, .s1-toggle, .s1-toggle::after, .s1-wave-track i { transition: none; }
  .s1-card:hover { transform: none; }
}
</style>

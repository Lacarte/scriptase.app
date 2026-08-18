<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { getChannel, listChannels } from '@/features/channels/api.js'
import { useToast } from '@/shared/composables/useToast.js'
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

const toast = useToast()
const scripts = ref([])
const channels = ref([])
const channelDetails = reactive({})
const selected = ref(null)
const query = ref('')
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

const originLabels = {
  auto: 'Auto',
  paste: 'Pasted',
  idea: 'Idea → Script',
  manual: 'Manual',
}

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
const activeSpeed = computed(() => narrationForm.speed ?? channelAudio.value.speed ?? 1)
const audioUrl = computed(() => {
  const artifactId = selected.value?.narration?.audio_artifact_id
  return artifactId ? narrationAudioUrl(selected.value.id, artifactId) : ''
})
const viralityStale = computed(() => Boolean(virality.value) && viralityText.value !== form.body)

function wordCount(value) {
  const text = String(value || '').trim()
  return text ? text.split(/\s+/).length : 0
}

function formatDuration(seconds) {
  const total = Math.max(0, Number(seconds) || 0)
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(Math.round(total % 60)).padStart(2, '0')}`
}

function formatDate(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
    .format(new Date(value))
}

function channelFor(id) {
  return channels.value.find(channel => channel.id === id)
}

function initials(name) {
  return String(name || 'S')
    .split(/\s+/)
    .slice(0, 2)
    .map(part => part[0])
    .join('')
    .toUpperCase()
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

async function openScript(summary) {
  if (dirty.value && selected.value?.id !== summary.id) {
    toast.warning('Save or discard the current edits before opening another script')
    return
  }
  loadingDetail.value = true
  error.value = ''
  try {
    const payload = await getScript(summary.id)
    selected.value = payload.script
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
  } catch (exc) {
    error.value = exc.message || 'Could not save the script'
  } finally {
    saving.value = false
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

async function makeNarration() {
  if (!selected.value || generatingNarration.value) return
  if (dirty.value) {
    toast.warning('Save the script edits before generating narration')
    return
  }
  generatingNarration.value = true
  error.value = ''
  try {
    const payload = await generateNarration(selected.value.id, {
      voice: narrationForm.voice || undefined,
      remove_silence: narrationForm.removeSilence,
      speed: narrationForm.speed,
      expected_version: selected.value.version,
    })
    selected.value = payload.script
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
    virality.value = null
    viralityText.value = ''
    form.title = payload.script.title
    form.body = payload.script.body
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
  <section class="studio" aria-label="Script Studio">
    <aside class="library-rail">
      <div class="rail-head">
        <div class="rail-title">
          <div>
            <span class="section-label">Studio</span>
            <h1>Script library</h1>
          </div>
          <button class="btn primary sm" type="button" @click="startCreate">+ New</button>
        </div>

        <label class="search-box">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
          <span class="sr-only">Search scripts</span>
          <input ref="searchInput" v-model="query" type="search" placeholder="Search scripts…" @input="search">
          <kbd>/</kbd>
        </label>
      </div>

      <div class="script-list" aria-live="polite">
        <div v-if="loading" class="rail-state">Loading scripts…</div>
        <div v-else-if="!scripts.length" class="rail-state">
          {{ query ? 'No scripts match that search.' : 'No scripts yet. Create the first one.' }}
        </div>
        <button
          v-for="script in scripts"
          v-else
          :key="script.id"
          type="button"
          class="script-card"
          :class="{ selected: selected?.id === script.id && !creating }"
          @click="openScript(script)"
        >
          <span class="card-row">
            <span class="avatar">{{ initials(channelFor(script.channel_id)?.name) }}</span>
            <span class="card-title">{{ script.title }}</span>
          </span>
          <span class="card-meta">
            <span>{{ formatDate(script.updated_at) }}</span>
            <span>{{ script.word_count }} words</span>
            <span class="origin">{{ originLabels[script.origin] }}</span>
          </span>
        </button>
      </div>

      <div class="rail-foot"><span class="status-dot" /> {{ scripts.length }} scripts · local library</div>
    </aside>

    <main class="studio-detail">
      <div v-if="error" class="error-banner" role="alert">
        {{ error }}
        <button type="button" aria-label="Dismiss error" @click="error = ''">×</button>
      </div>

      <div v-if="creating" class="create-sheet">
        <header class="document-head">
          <div class="eyebrow">+ New Script</div>
          <input v-model="draft.title" class="title-input" aria-label="New script title" placeholder="Untitled script">
          <label class="channel-select">Channel
            <select v-model="draft.channelId" @change="chooseChannel">
              <option v-for="channel in channels" :key="channel.id" :value="channel.id">{{ channel.name }}</option>
            </select>
          </label>
        </header>

        <div class="create-body">
          <span class="section-label">How should Scriptase create it?</span>
          <div class="create-modes" role="tablist" aria-label="Create mode">
            <button type="button" role="tab" :aria-selected="draft.mode === 'auto'" :class="{ active: draft.mode === 'auto' }" @click="chooseMode('auto')">
              <strong>Auto</strong><span>Pick the next topic</span>
            </button>
            <button type="button" role="tab" :aria-selected="draft.mode === 'idea'" :class="{ active: draft.mode === 'idea' }" @click="chooseMode('idea')">
              <strong>Topic to Idea</strong><span>Expand your topic</span>
            </button>
            <button type="button" role="tab" :aria-selected="draft.mode === 'paste'" :class="{ active: draft.mode === 'paste' }" @click="chooseMode('paste')">
              <strong>Paste</strong><span>Bring your own</span>
            </button>
          </div>

          <div v-if="draft.mode === 'idea'" class="mode-field">
            <label for="idea-input">Topic or idea</label>
            <input id="idea-input" v-model="draft.idea" class="text-input" placeholder="Why we replay old arguments in our heads…">
          </div>

          <template v-if="draft.mode !== 'paste'">
            <div v-if="template" class="template-card">
              <div class="template-head">
                <span>Using <b>{{ selectedChannel.name }}</b>'s template</span>
                <RouterLink :to="`/channels/${selectedChannel.id}`">Edit in Channel</RouterLink>
              </div>
              <p>{{ template.brief }}</p>
              <div class="template-chips" aria-label="Template section outline">
                <span v-for="(section, index) in template.sections" :key="`${section}-${index}`">
                  <i>{{ index + 1 }}</i>{{ section }}
                </span>
              </div>
            </div>
            <div v-else class="rail-state">Loading Channel template…</div>
          </template>

          <div v-else class="mode-field">
            <label for="paste-script">Script</label>
            <textarea id="paste-script" v-model="draft.body" class="script-area" placeholder="Paste your narration script here…" />
            <div class="paste-meta"><span>{{ pasteWordCount }} words</span><span>~{{ formatDuration(pasteDuration) }} narration</span></div>
          </div>
        </div>

        <footer class="document-foot">
          <button class="btn ghost" type="button" :disabled="generating" @click="cancelCreate">Cancel</button>
          <button class="btn primary" type="button" :disabled="generating || !draft.channelId" @click="createNew">
            {{ generating ? 'Writing…' : draft.mode === 'paste' ? 'Save pasted script' : 'Generate script' }}
          </button>
        </footer>
      </div>

      <div v-else-if="loadingDetail" class="empty-state"><h2>Opening script…</h2></div>

      <article v-else-if="selected" class="document">
        <header class="document-head">
          <div class="eyebrow">
            <span class="avatar">{{ initials(channelFor(selected.channel_id)?.name) }}</span>
            {{ channelFor(selected.channel_id)?.name || 'Channel' }} · {{ selected.id }} · {{ originLabels[selected.origin] }}
          </div>
          <input v-model="form.title" class="title-input" aria-label="Script title" @input="markDirty">
          <div class="document-meta">
            <span><b>{{ liveWordCount }}</b> words</span>
            <span>~<b>{{ formatDuration(liveDuration) }}</b> narration</span>
            <span>Created <b>{{ formatDate(selected.created_at) }}</b></span>
          </div>
        </header>

        <div class="document-body">
          <div class="editor-column">
            <label for="script-body" class="section-label">Script</label>
            <textarea id="script-body" v-model="form.body" class="script-area" :class="{ dirty }" spellcheck="true" @input="markDirty" />
            <ViralityPanel
              :score="virality"
              :analyzing="scoringVirality"
              :stale="viralityStale"
              @analyze="checkVirality"
            />
          </div>
          <aside class="narration-preview panel" aria-label="Narration controls">
            <div class="narration-head"><span>◖</span><strong>Narration</strong></div>
            <div class="narration-state" :class="{ ready: selected.narration.state === 'ready' }">
              <strong>{{ generatingNarration ? 'Generating narration…' : selected.narration.state === 'ready' ? 'Narration ready' : 'No narration yet' }}</strong>
              <span>{{ selected.narration.state === 'ready' ? 'This take is saved and ready for Production.' : 'Choose a voice and create the first take.' }}</span>
            </div>
            <audio v-if="audioUrl" :key="audioUrl" class="narration-player" controls preload="metadata" :src="audioUrl">
              Your browser does not support audio playback.
            </audio>
            <div class="narration-controls">
              <label>Voice
                <select v-model="narrationForm.voice" aria-label="Narration voice">
                  <option v-if="!voices.length" :value="narrationForm.voice">{{ narrationForm.voice || 'Channel default' }}</option>
                  <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.label || voice.id }}</option>
                </select>
              </label>
              <label>Remove silence
                <select v-model="narrationForm.removeSilence" :class="{ inherited: narrationForm.removeSilence === null }" aria-label="Remove silence override">
                  <option :value="null">Inherited · {{ channelAudio.remove_silence ? 'On' : 'Off' }}</option>
                  <option :value="true">On · Override</option>
                  <option :value="false">Off · Override</option>
                </select>
              </label>
              <label>Speed
                <select v-model="narrationForm.speed" :class="{ inherited: narrationForm.speed === null }" aria-label="Narration speed override">
                  <option :value="null">Inherited · {{ Number(channelAudio.speed || 1).toFixed(2) }}×</option>
                  <option v-for="value in [0.75, 0.9, 1, 1.1, 1.25, 1.5]" :key="value" :value="value">{{ value.toFixed(2) }}× · Override</option>
                </select>
              </label>
              <div class="active-processing" aria-label="Active narration processing">
                Active: {{ activeRemoveSilence ? 'trim silence' : 'keep silence' }} · {{ Number(activeSpeed).toFixed(2) }}×
              </div>
              <div v-if="selected.narration.duration_s" class="take-duration">Duration {{ formatDuration(selected.narration.duration_s) }}</div>
              <button class="btn primary narration-button" type="button" :disabled="generatingNarration || dirty" @click="makeNarration">
                {{ generatingNarration ? 'Generating…' : selected.narration.state === 'ready' ? 'Regenerate narration' : 'Generate narration' }}
              </button>
            </div>
          </aside>
        </div>

        <footer class="document-foot">
          <span v-if="dirty" class="dirty-note">● Unsaved changes</span>
          <span class="foot-spacer" />
          <button class="btn primary" type="button" :disabled="saving || !dirty" @click="save">{{ saving ? 'Saving…' : 'Save' }}</button>
        </footer>
      </article>

      <div v-else class="empty-state">
        <div class="empty-icon">S</div>
        <h2>No script selected</h2>
        <p>Pick a script from the library, or create a new one to start writing.</p>
        <button class="btn primary" type="button" @click="startCreate">Create script</button>
      </div>
    </main>
  </section>
</template>

<style scoped>
.studio { height: 100%; min-height: 0; display: grid; grid-template-columns: 360px minmax(0, 1fr); background: var(--bg); }
.library-rail { min-width: 0; min-height: 0; border-right: 1px solid var(--line); background: linear-gradient(180deg, var(--bg-2), var(--bg)); display: flex; flex-direction: column; }
.rail-head { padding: 18px 18px 14px; border-bottom: 1px solid var(--line-soft); }
.rail-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.rail-title h1 { margin: 3px 0 0; font: 600 17px var(--display); }
.search-box { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--panel); color: var(--muted); }
.search-box:focus-within { border-color: var(--accent-line); box-shadow: 0 0 0 3px var(--accent-dim); }
.search-box input { min-width: 0; flex: 1; border: 0; outline: 0; background: transparent; color: var(--text); font: 13px var(--body); }
.search-box kbd { color: var(--faint); font: 10px var(--mono); }
.script-list { flex: 1; min-height: 180px; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 7px; }
.script-card { width: 100%; padding: 11px 12px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--panel); color: var(--text); text-align: left; cursor: pointer; }
.script-card:hover { border-color: var(--line-2); background: var(--panel-2); }
.script-card.selected { border-color: var(--accent-line-2); background: var(--accent-dim); }
.card-row { display: flex; align-items: center; gap: 8px; }
.avatar { width: 21px; height: 21px; border-radius: 5px; display: inline-grid; place-items: center; flex: none; background: var(--accent-grad); color: white; font: 700 9px var(--display); }
.card-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-weight: 600; }
.card-meta { display: flex; align-items: center; gap: 7px; margin-top: 7px; color: var(--muted); font: 10px var(--mono); }
.origin { margin-left: auto; padding: 2px 6px; border-radius: 4px; background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line-soft); text-transform: uppercase; font-size: 9px; }
.rail-state { padding: 24px 12px; text-align: center; color: var(--muted); font-size: 12px; line-height: 1.5; }
.rail-foot { padding: 11px 16px; border-top: 1px solid var(--line-soft); color: var(--muted); font: 10.5px var(--mono); }
.status-dot { display: inline-block; width: 7px; height: 7px; margin-right: 6px; border-radius: 50%; background: var(--ok); }
.studio-detail { min-width: 0; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; }
.document, .create-sheet { flex: 1; display: flex; flex-direction: column; }
.document-head { padding: 22px 30px 18px; border-bottom: 1px solid var(--line-soft); }
.eyebrow { display: flex; align-items: center; gap: 8px; margin-bottom: 11px; color: var(--muted); font: 10.5px var(--mono); letter-spacing: .5px; text-transform: uppercase; }
.title-input { width: 100%; padding: 0; border: 0; outline: 0; background: transparent; color: var(--text); font: 600 24px var(--display); letter-spacing: -.5px; }
.document-meta { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; color: var(--muted); font: 11px var(--mono); }
.document-meta b { color: var(--text-2); font-weight: 500; }
.document-body { flex: 1; display: grid; grid-template-columns: minmax(0, 1fr) 300px; align-items: start; gap: 24px; padding: 22px 30px; }
.editor-column { min-width: 0; }
.script-area { box-sizing: border-box; width: 100%; min-height: 390px; resize: vertical; padding: 18px 20px; border: 1px solid var(--line); border-radius: var(--r); background: var(--bg-2); color: var(--text); font: 14.5px/1.75 var(--body); }
.script-area:focus { outline: 0; border-color: var(--accent-line-2); box-shadow: 0 0 0 3px var(--accent-dim); }
.script-area.dirty { border-color: var(--warn-line); }
.narration-preview { position: sticky; top: 76px; overflow: hidden; }
.narration-head { display: flex; gap: 8px; padding: 13px 15px; border-bottom: 1px solid var(--line-soft); color: var(--run); font-size: 13px; }
.narration-head strong { color: var(--text); }
.narration-state { display: flex; flex-direction: column; gap: 3px; margin: 15px; padding: 12px; border-radius: var(--r-s); background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line); }
.narration-state strong { font-size: 13px; }
.narration-state span { color: var(--muted); font-size: 11px; line-height: 1.4; }
.narration-state.ready { box-shadow: inset 3px 0 0 var(--ok), inset 0 0 0 1px var(--line); }
.narration-player { display: block; width: calc(100% - 30px); height: 36px; margin: 0 15px 14px; }
.narration-controls { display: flex; flex-direction: column; gap: 10px; padding: 0 15px 15px; }
.narration-controls label { display: flex; flex-direction: column; gap: 5px; color: var(--muted); font-size: 11px; }
.narration-controls select { width: 100%; }
.narration-controls select.inherited { border-style: dashed; color: var(--muted); }
.active-processing { padding: 7px 9px; border-radius: 5px; background: var(--accent-dim); color: var(--accent); font: 10px var(--mono); }
.take-duration { color: var(--muted); font: 10px var(--mono); }
.narration-button { width: 100%; justify-content: center; }
.document-foot { display: flex; align-items: center; gap: 9px; padding: 14px 30px; border-top: 1px solid var(--line-soft); background: var(--bg-2); }
.foot-spacer { flex: 1; }.dirty-note { color: var(--warn); font: 11px var(--mono); }
.create-body { flex: 1; width: min(800px, 100%); box-sizing: border-box; padding: 24px 30px; }
.channel-select { display: flex; align-items: center; gap: 8px; margin-top: 12px; color: var(--muted); font: 11px var(--mono); }
select, .text-input { border: 1px solid var(--line); border-radius: 6px; background: var(--bg-2); color: var(--text); font: 12px var(--body); padding: 7px 9px; }
.channel-select select { max-width: 260px; }
.create-modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin: 10px 0 18px; }
.create-modes button { display: flex; flex-direction: column; gap: 3px; padding: 12px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--panel); color: var(--text); text-align: left; cursor: pointer; }
.create-modes button span { color: var(--muted); font-size: 11px; }.create-modes button.active { border-color: var(--accent-line-2); background: var(--accent-dim); }
.mode-field { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }.mode-field label { color: var(--text-2); font-size: 12px; }.text-input { width: 100%; box-sizing: border-box; }
.template-card { padding: 14px; border: 1px solid var(--line); border-radius: var(--r); background: var(--panel-grad); box-shadow: var(--hairline-top); }
.template-head { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 600; }.template-head b { color: var(--accent); }.template-head a { margin-left: auto; color: var(--muted); font-size: 11px; }
.template-card p { margin: 9px 0 12px; color: var(--text-2); font-size: 12.5px; line-height: 1.55; }
.template-chips { display: flex; flex-wrap: wrap; gap: 6px; }.template-chips span { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px 3px 4px; border: 1px solid var(--line-soft); border-radius: 20px; background: var(--bg-2); color: var(--text-2); font-size: 11px; }.template-chips i { width: 16px; height: 16px; display: grid; place-items: center; border-radius: 50%; background: var(--accent-dim); color: var(--accent); font: normal 700 9px var(--mono); }
.paste-meta { display: flex; justify-content: space-between; color: var(--muted); font: 10.5px var(--mono); }
.error-banner { display: flex; align-items: center; gap: 12px; margin: 14px 20px 0; padding: 10px 12px; border: 1px solid var(--fail-line); border-radius: var(--r-s); background: var(--fail-dim); color: var(--fail); font-size: 12px; }.error-banner button { margin-left: auto; border: 0; background: transparent; color: inherit; cursor: pointer; }
.empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; text-align: center; color: var(--muted); }.empty-state h2 { margin: 0 0 7px; color: var(--text); font: 600 16px var(--display); }.empty-state p { max-width: 320px; margin: 0 0 16px; font-size: 13px; line-height: 1.6; }.empty-icon { width: 58px; height: 58px; display: grid; place-items: center; margin-bottom: 16px; border: 1px solid var(--line); border-radius: 16px; background: var(--panel); color: var(--accent); font: 600 22px var(--display); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
@media (max-width: 900px) { .studio { grid-template-columns: 290px minmax(0, 1fr); }.document-body { grid-template-columns: 1fr; }.narration-preview { position: static; }.document-head, .document-body, .create-body, .document-foot { padding-left: 20px; padding-right: 20px; } }
@media (max-width: 700px) { .studio { display: block; overflow-y: auto; }.library-rail { border-right: 0; border-bottom: 1px solid var(--line); }.studio-detail { overflow: visible; }.script-list { max-height: 260px; }.create-modes { grid-template-columns: 1fr; }.document-head, .document-body, .create-body, .document-foot { padding-left: 14px; padding-right: 14px; }.document-foot { position: sticky; bottom: 0; z-index: 2; }.title-input { font-size: 21px; } }
</style>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  CHANNEL_COLORS,
  PLATFORM_COLORS,
  PLATFORM_NAMES,
  PLATFORM_ORDER,
  channelAccent,
  channelInitials,
} from '@/shared/utils/channelIdentity.js'
import { listJobs } from '@/features/production/api.js'

import ProviderSelector from '@/features/providers/components/ProviderSelector.vue'

import ChannelRail from './ChannelRail.vue'
import {
  composeVisualPrompt,
  createChannel,
  deleteChannel,
  getChannel,
  getChannelDefaults,
  listBrandingAssets,
  listMusicAssets,
  updateChannel,
  uploadBrandingLogo,
  uploadChannelThumbnail,
  uploadMusicTrack,
} from './api.js'

const route = useRoute()
const router = useRouter()

const railRef = ref(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const success = ref('')
const dirty = ref(false)
const brandingAssets = ref([])
const musicAssets = ref([])
const uploadBusy = ref(false)
const promptPreview = ref('')
const promptPreviewLoading = ref(false)
const logoInput = ref(null)
const thumbnailInput = ref(null)
const previewAudio = ref(null)
const playingRef = ref('')
let promptPreviewRequest = 0
let loadRequest = 0
/** Suppress the dirty-discard prompt while we revert a cancelled rail click. */
let revertingChannelNav = false

const channelId = computed(() => route.params.id)

// The bundled royalty-free beds ship here; a new Channel points at them so
// music works out of the box. Mirrors DEFAULT_MUSIC_FOLDER in the backend model.
const DEFAULT_MUSIC_FOLDER = 'resources\\sounds\\music\\default'

/** Full document for version / timestamps; form holds the editable draft. */
const meta = reactive({
  id: '',
  version: 1,
  schema_version: 1,
  created_at: '',
  updated_at: '',
})

const form = reactive({
  name: '',
  branding: {
    logo_asset_id: null,
    thumbnail_asset_id: null,
    accent_color: null,
    enabled: false,
    position: 'bottom-right',
    size: 0.12,
    opacity: 1,
    margin: 0.04,
  },
  content: {
    niche: '',
    language: 'en',
    audience: '',
    script_style: '',
    tone: '',
    mood: '',
    hook_style: '',
    cta_style: '',
    duration_target: null,
    platforms: [],
  },
  script_template: {
    brief: '',
    sections: [],
  },
  visual_direction: {
    style: '',
    style_prompt: '',
    pattern: [],
    palette: '',
    lighting: '',
    camera: '',
    character_style: '',
    continuity: '',
    negative_prompt: '',
    references: [],
  },
  audio_defaults: {
    tts_provider_instance_id: null,
    voice: '',
    remove_silence: true,
    speed: 1,
    music_profile: '',
    music_random: true,
    scene_pacing: 'balanced',
    loudness: null,
    ducking: null,
  },
  music_library: {
    folder: DEFAULT_MUSIC_FOLDER,
    tracks: [],
  },
  captions: {
    preset: '',
    position: '',
    font_treatment: '',
    animation: '',
  },
  provider_defaults: {
    script: null,
    tts: null,
    scene_director: null,
    image: null,
    video: null,
    review: null,
  },
  export_defaults: {
    aspect_ratio: '9:16',
    resolution: '',
    fps: null,
    profile: '',
  },
  default_workflow_id: null,
  review_policy: {
    thresholds: {},
    max_repairs: 3,
    escalation: '',
    human_checkpoints: [],
  },
  budget: {
    max_generations: null,
    max_cost: null,
    currency: 'USD',
  },
})

/**
 * Blocks with no control in this editor. They are held outside `form` — plain,
 * unwrapped, never rendered — and written back verbatim, so that pressing Save
 * cannot silently erase a cadence schedule (step 9.2) or a stage fallback
 * chain configured elsewhere.
 */
const carried = { cadence: null, fallback_policies: {} }

/**
 * The six provider domains that `ChannelProfile.provider_defaults` carries.
 * `domain` is what the catalog knows; `key` is the form field; `label` is what
 * the user reads. The order follows the pipeline.
 */
const providerDomains = [
  { domain: 'script', key: 'script', label: 'Script' },
  { domain: 'tts', key: 'tts', label: 'TTS' },
  { domain: 'scene_director', key: 'scene_director', label: 'Scene director' },
  { domain: 'image', key: 'image', label: 'Image' },
  { domain: 'video', key: 'video', label: 'Video' },
  { domain: 'review', key: 'review', label: 'Review' },
]

function onProviderConfigure() {
  router.push({ name: 'providers' })
}

const accent = computed(() => channelAccent(meta.id, form.branding.accent_color))
const channelStats = reactive({ videos: 0, published: 0, batch: 0 })
const initials = computed(() => channelInitials(form.name))

const logoPreviewUrl = computed(() => {
  const refId = form.branding.logo_asset_id
  if (!refId) return ''
  // Managed refs look like "branding/filename.png"
  if (refId.startsWith('branding/')) return `/output/${refId}`
  return `/output/branding/${refId}`
})

const thumbnailPreviewUrl = computed(() => {
  const refId = form.branding.thumbnail_asset_id
  return refId ? `/output/${refId}` : ''
})

const heroAvatarStyle = computed(() => ({
  background: thumbnailPreviewUrl.value
    ? `center/cover url("${thumbnailPreviewUrl.value}")`
    : accent.value,
}))

/**
 * The nine watermark cells, in the prototype's reading order. The labels are
 * the backend's own `WATERMARK_POSITIONS` values, so the picker writes exactly
 * what `Branding.position` validates — no `tl`/`br` translation table.
 */
const POSITIONS = [
  { id: 'top-left', label: 'Top left' },
  { id: 'top-center', label: 'Top center' },
  { id: 'top-right', label: 'Top right' },
  { id: 'middle-left', label: 'Left' },
  { id: 'center', label: 'Center' },
  { id: 'middle-right', label: 'Right' },
  { id: 'bottom-left', label: 'Bottom left' },
  { id: 'bottom-center', label: 'Bottom center' },
  { id: 'bottom-right', label: 'Bottom right' },
]

const ASPECT_RATIOS = ['9:16', '16:9', '1:1', '4:5']
const SPEEDS = [0.9, 1, 1.05, 1.1, 1.15, 1.25, 1.5]
const LANGUAGES = ['English', 'French', 'Spanish', 'Haitian Creole']
const IMAGE_STYLES = ['Cinematic Muted', 'Noir Contrast', 'Bright Warm', 'Archival Sepia', 'Neon Synth', 'Editorial Clean']
const TONES = ['Reflective', 'Ominous', 'Uplifting', 'Narrative', 'Provocative', 'Calm']
const MOODS = ['Contemplative', 'Tense', 'Energetic', 'Grounded', 'Dreamy', 'Urgent']
const CAPTION_PRESETS = ['Minimal Serif', 'Bold Impact', 'Kinetic Pop', 'Documentary', 'Clean Sans', 'Handwritten']
const VOICES = ['Ashley', 'Marcus', 'Ryan', 'Ellen', 'Nova', 'Theo']
const BRANDING_OPTIONS = ['None', 'Lower-third watermark', 'Corner bug', 'End card']
const LENGTHS = ['30–60s', '45–75s', '60–90s', '90–120s']

function withCurrent(options, current) {
  const value = String(current || '').trim()
  if (!value || options.includes(value)) return options
  return [value, ...options]
}

const languageOptions = computed(() => withCurrent(LANGUAGES, displayLanguage.value))
const imageStyleOptions = computed(() => withCurrent(IMAGE_STYLES, form.visual_direction.style))
const toneOptions = computed(() => withCurrent(TONES, form.content.tone))
const moodOptions = computed(() => withCurrent(MOODS, form.content.mood))
const captionOptions = computed(() => withCurrent(CAPTION_PRESETS, form.captions.preset))
const voiceOptions = computed(() => withCurrent(VOICES, form.audio_defaults.voice))

const LANGUAGE_LABELS = { en: 'English', fr: 'French', es: 'Spanish', ht: 'Haitian Creole', 'ht-ht': 'Haitian Creole' }
const displayLanguage = computed(() => {
  const raw = String(form.content.language || '').trim()
  return LANGUAGE_LABELS[raw.toLowerCase()] || raw || 'English'
})

const lengthLabel = computed(() => {
  const seconds = Number(form.content.duration_target)
  if (!Number.isFinite(seconds) || seconds <= 0) return '60–90s'
  if (seconds <= 45) return '30–60s'
  if (seconds <= 70) return '45–75s'
  if (seconds <= 90) return '60–90s'
  return '90–120s'
})

const brandingTreatment = computed(() => {
  if (!form.branding.enabled) return 'None'
  if (form.branding.position.startsWith('bottom')) return 'Lower-third watermark'
  if (form.branding.position === 'center') return 'End card'
  return 'Corner bug'
})

function setLanguage(value) {
  form.content.language = value
  markDirty()
}

function setLength(value) {
  const map = { '30–60s': 45, '45–75s': 60, '60–90s': 75, '90–120s': 105 }
  form.content.duration_target = map[value] || 75
  markDirty()
}

function setBrandingTreatment(value) {
  if (value === 'None') {
    form.branding.enabled = false
  } else {
    form.branding.enabled = true
    if (value === 'Lower-third watermark') form.branding.position = 'bottom-right'
    else if (value === 'End card') form.branding.position = 'center'
    else form.branding.position = 'top-right'
  }
  markDirty()
}

function setAccent(color) {
  form.branding.accent_color = color
  markDirty()
}

function togglePlatform(code) {
  const current = [...(form.content.platforms || [])]
  const index = current.indexOf(code)
  if (index >= 0) {
    if (current.length === 1) {
      error.value = 'Keep at least one platform'
      return
    }
    current.splice(index, 1)
  } else {
    current.push(code)
  }
  form.content.platforms = current
  markDirty()
}

function platformOn(code) {
  return (form.content.platforms || []).includes(code)
}

const positionLabel = computed(
  () => POSITIONS.find((p) => p.id === form.branding.position)?.label || 'Top right',
)

const aspectOptions = computed(() => {
  const current = form.export_defaults.aspect_ratio
  return current && !ASPECT_RATIOS.includes(current)
    ? [current, ...ASPECT_RATIOS]
    : ASPECT_RATIOS
})

/** A saved channel may carry any float in 0.25–4.0; never drop it from the list. */
const speedOptions = computed(() => {
  const current = Number(form.audio_defaults.speed)
  return SPEEDS.includes(current) ? SPEEDS : [current, ...SPEEDS].sort((a, b) => a - b)
})

/** How long each scene stays on screen — the segmenter's target duration band. */
const pacingOptions = [
  { id: 'fast', label: 'Fast', hint: 'Tight, punchy cuts (~2.5–4s per scene) — high energy.' },
  { id: 'balanced', label: 'Balanced', hint: 'One scene per ~5s clip (~3.5–5s) — matches most video models.' },
  { id: 'cinematic', label: 'Cinematic', hint: 'Slow, contemplative shots (~5–7s per scene).' },
]
const pacingHint = computed(() =>
  (pacingOptions.find((p) => p.id === form.audio_defaults.scene_pacing) || pacingOptions[1]).hint,
)

/** Where the watermark sits inside the aspect-ratio preview frame. */
const watermarkFrameStyle = computed(() => ({
  '--fr': form.export_defaults.aspect_ratio.replace(':', '/') || '9/16',
  background: `linear-gradient(160deg, ${accent.value}, ${accent.value}44)`,
}))

const watermarkPreviewStyle = computed(() => {
  const [vertical, horizontal] = form.branding.position === 'center'
    ? ['middle', 'center']
    : form.branding.position.split('-')
  const style = { position: 'absolute' }
  if (vertical === 'top') style.top = '8px'
  else if (vertical === 'bottom') style.bottom = '8px'
  else style.top = '50%'
  if (horizontal === 'left') style.left = '8px'
  else if (horizontal === 'right') style.right = '8px'
  else style.left = '50%'
  const tx = horizontal === 'center' ? '-50%' : '0'
  const ty = vertical === 'middle' ? '-50%' : '0'
  if (tx !== '0' || ty !== '0') style.transform = `translate(${tx}, ${ty})`
  return style
})

/** The prototype's inherit strip, read from the fields the backend does have. */
const inheritedChips = computed(() => [
  ['Image', form.visual_direction.style],
  ['Tone', form.content.tone],
  ['Mood', form.content.mood],
  ['TTS', form.audio_defaults.voice],
  ['Captions', form.captions.preset],
  ['Aspect', form.export_defaults.aspect_ratio],
].filter(([, value]) => value))

const trackName = (refId) =>
  musicAssets.value.find((track) => track.ref === refId)?.filename
  || refId.split('/').pop()

const channelTracks = computed(() =>
  (form.music_library.tracks || []).map((ref) => ({
    ref,
    filename: trackName(ref),
    path: musicAssets.value.find((track) => track.ref === ref)?.path || '',
  })),
)

const defaultBedOptions = computed(() => {
  const names = channelTracks.value.map((track) => track.filename).filter(Boolean)
  return names.length ? [...names, 'None'] : ['(no tracks)', 'None']
})

const defaultBedValue = computed(() => {
  if (!form.audio_defaults.music_profile) return channelTracks.value.length ? 'None' : '(no tracks)'
  return trackName(form.audio_defaults.music_profile) || 'None'
})

function setDefaultBed(filename) {
  if (!filename || filename === 'None' || filename === '(no tracks)') {
    form.audio_defaults.music_profile = ''
    markDirty()
    return
  }
  const hit = channelTracks.value.find((track) => track.filename === filename)
  form.audio_defaults.music_profile = hit?.ref || filename
  markDirty()
}

function selectBed(refId) {
  form.audio_defaults.music_profile = refId
  markDirty()
}

function markDirty() {
  dirty.value = true
  success.value = ''
}

async function refreshPromptPreview() {
  const requestId = ++promptPreviewRequest
  promptPreviewLoading.value = true
  try {
    const result = await composeVisualPrompt({
      scene_subject: 'A lone traveler finds a glowing door in the rain',
      visual_style: form.visual_direction.style_prompt,
      mood: form.content.mood,
      aspect_ratio: form.export_defaults.aspect_ratio,
    })
    if (requestId === promptPreviewRequest) {
      promptPreview.value = result?.prompt || ''
    }
  } catch {
    if (requestId === promptPreviewRequest) promptPreview.value = 'Preview unavailable'
  } finally {
    if (requestId === promptPreviewRequest) promptPreviewLoading.value = false
  }
}

watch(
  [
    () => form.visual_direction.style_prompt,
    () => form.content.mood,
    () => form.export_defaults.aspect_ratio,
  ],
  refreshPromptPreview,
  { immediate: true },
)

function applyDocument(doc) {
  meta.id = doc.id
  meta.version = doc.version
  meta.schema_version = doc.schema_version
  meta.created_at = doc.created_at
  meta.updated_at = doc.updated_at

  form.name = doc.name || ''
  Object.assign(form.branding, {
    logo_asset_id: null,
    thumbnail_asset_id: null,
    accent_color: null,
    enabled: false,
    position: 'bottom-right',
    size: 0.12,
    opacity: 1,
    margin: 0.04,
    ...(doc.branding || {}),
  })
  Object.assign(form.content, {
    niche: '',
    language: 'en',
    audience: '',
    script_style: '',
    tone: '',
    mood: '',
    hook_style: '',
    cta_style: '',
    duration_target: null,
    platforms: [],
    ...(doc.content || {}),
  })
  form.content.platforms = Array.isArray(doc.content?.platforms) ? [...doc.content.platforms] : []
  Object.assign(form.script_template, {
    brief: '',
    sections: [],
    ...(doc.script_template || {}),
  })
  form.script_template.sections = Array.isArray(doc.script_template?.sections)
    ? [...doc.script_template.sections]
    : []
  const vd = doc.visual_direction || {}
  form.visual_direction.style = vd.style || ''
  form.visual_direction.style_prompt = vd.style_prompt || ''
  form.visual_direction.pattern = Array.isArray(vd.pattern)
    ? vd.pattern.map((p) => ({
        narrative_role: p.narrative_role || '',
        shot: p.shot || '',
      }))
    : []
  form.visual_direction.palette = vd.palette || ''
  form.visual_direction.lighting = vd.lighting || ''
  form.visual_direction.camera = vd.camera || ''
  form.visual_direction.character_style = vd.character_style || ''
  form.visual_direction.continuity = vd.continuity || ''
  form.visual_direction.negative_prompt = vd.negative_prompt || ''
  form.visual_direction.references = Array.isArray(vd.references)
    ? [...vd.references]
    : []
  Object.assign(form.audio_defaults, {
    tts_provider_instance_id: null,
    voice: '',
    remove_silence: true,
    speed: 1,
    music_profile: '',
    music_random: true,
    scene_pacing: 'balanced',
    loudness: null,
    ducking: null,
    ...(doc.audio_defaults || {}),
  })
  Object.assign(form.music_library, {
    folder: DEFAULT_MUSIC_FOLDER,
    tracks: [],
    ...(doc.music_library || {}),
  })
  form.music_library.tracks = Array.isArray(doc.music_library?.tracks)
    ? [...doc.music_library.tracks]
    : []
  Object.assign(form.captions, {
    preset: '',
    position: '',
    font_treatment: '',
    animation: '',
    ...(doc.captions || {}),
  })
  Object.assign(form.provider_defaults, {
    script: null,
    tts: null,
    scene_director: null,
    image: null,
    video: null,
    review: null,
    ...(doc.provider_defaults || {}),
  })
  Object.assign(form.export_defaults, {
    aspect_ratio: '9:16',
    resolution: '',
    fps: null,
    profile: '',
    ...(doc.export_defaults || {}),
  })
  form.default_workflow_id = doc.default_workflow_id || null
  Object.assign(form.review_policy, {
    thresholds: {},
    max_repairs: 3,
    escalation: '',
    human_checkpoints: [],
    ...(doc.review_policy || {}),
  })
  Object.assign(form.budget, {
    max_generations: null,
    max_cost: null,
    currency: 'USD',
    ...(doc.budget || {}),
  })
  carried.cadence = doc.cadence ? structuredClone(doc.cadence) : null
  carried.fallback_policies = doc.fallback_policies
    ? structuredClone(doc.fallback_policies)
    : {}
  dirty.value = false
}

function draftPayload() {
  const emptyToNull = (v) => {
    if (v === '' || v === undefined) return null
    return v
  }
  const emptyToEmpty = (v) => (v == null ? '' : v)

  const payload = {
    name: form.name,
    branding: {
      ...form.branding,
      logo_asset_id: emptyToNull(form.branding.logo_asset_id),
      thumbnail_asset_id: emptyToNull(form.branding.thumbnail_asset_id),
      size: Number(form.branding.size),
      opacity: Number(form.branding.opacity),
      margin: Number(form.branding.margin),
    },
    content: {
      ...form.content,
      duration_target:
        form.content.duration_target === '' || form.content.duration_target == null
          ? null
          : Number(form.content.duration_target),
    },
    script_template: {
      brief: form.script_template.brief.trim(),
      sections: form.script_template.sections
        .map((section) => section.trim())
        .filter(Boolean),
    },
    visual_direction: {
      ...form.visual_direction,
      pattern: form.visual_direction.pattern
        .filter((p) => (p.narrative_role || '').trim() && (p.shot || '').trim())
        .map((p) => ({
          narrative_role: p.narrative_role.trim(),
          shot: p.shot.trim(),
        })),
      references: (form.visual_direction.references || []).filter(Boolean),
    },
    audio_defaults: {
      ...form.audio_defaults,
      tts_provider_instance_id: emptyToNull(form.audio_defaults.tts_provider_instance_id),
      speed: Number(form.audio_defaults.speed) || 1,
      loudness:
        form.audio_defaults.loudness === '' || form.audio_defaults.loudness == null
          ? null
          : Number(form.audio_defaults.loudness),
      ducking:
        form.audio_defaults.ducking === '' || form.audio_defaults.ducking == null
          ? null
          : Number(form.audio_defaults.ducking),
    },
    music_library: {
      folder: form.music_library.folder.trim(),
      tracks: [...form.music_library.tracks],
    },
    captions: { ...form.captions },
    provider_defaults: {
      script: emptyToNull(form.provider_defaults.script),
      tts: emptyToNull(form.provider_defaults.tts),
      scene_director: emptyToNull(form.provider_defaults.scene_director),
      image: emptyToNull(form.provider_defaults.image),
      video: emptyToNull(form.provider_defaults.video),
      review: emptyToNull(form.provider_defaults.review),
    },
    fallback_policies: structuredClone(carried.fallback_policies || {}),
    review_policy: {
      ...form.review_policy,
      max_repairs: Number(form.review_policy.max_repairs) || 0,
      human_checkpoints: form.review_policy.human_checkpoints || [],
    },
    budget: {
      max_generations:
        form.budget.max_generations === '' || form.budget.max_generations == null
          ? null
          : Number(form.budget.max_generations),
      max_cost:
        form.budget.max_cost === '' || form.budget.max_cost == null
          ? null
          : Number(form.budget.max_cost),
      currency: emptyToEmpty(form.budget.currency) || 'USD',
    },
    export_defaults: {
      ...form.export_defaults,
      fps:
        form.export_defaults.fps === '' || form.export_defaults.fps == null
          ? null
          : Number(form.export_defaults.fps),
    },
    default_workflow_id: emptyToNull(form.default_workflow_id),
  }
  if (carried.cadence) payload.cadence = structuredClone(carried.cadence)
  return payload
}

async function load() {
  const requestId = ++loadRequest
  const requestedId = channelId.value
  loading.value = true
  error.value = ''
  success.value = ''
  try {
    const [{ channel }, branding, music] = await Promise.all([
      getChannel(requestedId),
      listBrandingAssets().catch(() => ({ assets: [] })),
      listMusicAssets().catch(() => []),
    ])
    // Rail clicks reuse this component; a slow getChannel for A must not
    // overwrite the document already shown for B.
    if (requestId !== loadRequest || channelId.value !== requestedId) return
    applyDocument(channel)
    brandingAssets.value = branding.assets || []
    musicAssets.value = Array.isArray(music) ? music : music?.tracks || []
    await loadChannelStats(requestedId)
  } catch (err) {
    if (requestId !== loadRequest || channelId.value !== requestedId) return
    error.value = err.message || String(err)
  } finally {
    if (requestId === loadRequest) loading.value = false
  }
}

function syncRailSummary(channel) {
  railRef.value?.upsertSummary?.({
    id: channel.id,
    name: channel.name,
    version: channel.version,
    niche: channel.content?.niche || '',
    style: channel.visual_direction?.style || '',
    platforms: channel.content?.platforms || [],
    accent_color: channel.branding?.accent_color || null,
    thumbnail_asset_id: channel.branding?.thumbnail_asset_id || null,
    track_count: channel.music_library?.tracks?.length || 0,
    created_at: channel.created_at,
    updated_at: channel.updated_at,
  })
}

async function onSave() {
  saving.value = true
  error.value = ''
  success.value = ''
  try {
    const { channel } = await updateChannel(
      meta.id,
      draftPayload(),
      meta.version,
    )
    applyDocument(channel)
    // Keep the sibling rail's optimistic-concurrency token current so a
    // subsequent Undo-delete does not 409 against the version we just wrote.
    syncRailSummary(channel)
    success.value = `Saved (v${channel.version})`
  } catch (err) {
    error.value = err.message || String(err)
    if (err.details?.problems) {
      error.value +=
        ': ' +
        err.details.problems
          .map((p) => `${(p.loc || []).join('.')}: ${p.msg}`)
          .join('; ')
    }
  } finally {
    saving.value = false
  }
}

async function onDelete() {
  if (!window.confirm(`Delete channel “${form.name}”?`)) return
  saving.value = true
  error.value = ''
  try {
    await deleteChannel(meta.id, meta.version)
    await router.push({ name: 'channels' })
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    saving.value = false
  }
}

async function loadChannelStats(id) {
  channelStats.videos = 0
  channelStats.published = 0
  channelStats.batch = 0
  try {
    const data = await listJobs({ limit: 500 })
    const jobs = (data.jobs || []).filter((job) => job.channel_id === id)
    const done = jobs.filter((job) => job.status === 'completed')
    channelStats.videos = done.length
    channelStats.published = done.length
    channelStats.batch = jobs.filter((job) => ['queued', 'running', 'paused'].includes(job.status)).length
  } catch {
    /* counters stay at zero */
  }
}

function useInBatch() {
  if (!meta.id) return
  router.push({ name: 'production', query: { channel: meta.id } })
}

async function duplicateChannel() {
  saving.value = true
  error.value = ''
  try {
    const { channel } = await createChannel({
      ...draftPayload(),
      name: `${form.name} (copy)`,
    })
    railRef.value?.upsertSummary(channel)
    await router.push({ name: 'channel-edit', params: { id: channel.id } })
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    saving.value = false
  }
}

async function onLogoFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploadBusy.value = true
  error.value = ''
  try {
    const asset = await uploadBrandingLogo(file)
    form.branding.logo_asset_id = asset.ref
    form.branding.enabled = true
    brandingAssets.value = [
      asset,
      ...brandingAssets.value.filter((a) => a.ref !== asset.ref),
    ]
    markDirty()
    success.value = 'Logo uploaded — save the channel to keep the reference.'
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    uploadBusy.value = false
  }
}

async function onThumbnailFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploadBusy.value = true
  error.value = ''
  try {
    const asset = await uploadChannelThumbnail(file)
    form.branding.thumbnail_asset_id = asset.ref
    brandingAssets.value = [asset, ...brandingAssets.value.filter((a) => a.ref !== asset.ref)]
    markDirty()
    success.value = 'Thumbnail uploaded — save the channel to keep the reference.'
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    uploadBusy.value = false
  }
}

async function onMusicFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploadBusy.value = true
  error.value = ''
  try {
    const asset = await uploadMusicTrack(file)
    musicAssets.value = [asset, ...musicAssets.value.filter((a) => a.ref !== asset.ref)]
    if (!form.music_library.tracks.includes(asset.ref)) form.music_library.tracks.push(asset.ref)
    markDirty()
    success.value = 'Track uploaded and added to this channel.'
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    uploadBusy.value = false
  }
}

/**
 * Bulk-add a folder of beds.
 *
 * `webkitdirectory` makes the browser enumerate the chosen folder and hand
 * over the *files*, not the path — so this is still the managed upload the
 * security rule requires: nothing server-side is told where anything lives on
 * disk, and every track goes through the same validation as a single upload.
 * A folder is a convenience for choosing, never a location the app reads from.
 *
 * Directory pickers ignore `accept`, so the audio filter is applied here.
 * Uploads run one at a time: the endpoint validates and rewrites each asset,
 * and a folder of fifty beds firing at once is how you get a queue of failures
 * that are hard to attribute.
 */
async function onMusicFolder(event) {
  const picked = Array.from(event.target.files || [])
  event.target.value = ''
  if (!picked.length) return

  const audio = picked.filter(
    file => file.type.startsWith('audio/') || /\.(mp3|wav|ogg|m4a|flac)$/i.test(file.name),
  )
  const skipped = picked.length - audio.length
  if (!audio.length) {
    error.value = `No audio files in that folder (${picked.length} skipped).`
    return
  }

  const relative = audio[0]?.webkitRelativePath || audio[0]?.name || ''
  const folderName = relative.includes('/') ? relative.split('/')[0] : ''
  // Reflect the chosen folder name when the field is still empty or holds the
  // bundled default — a folder the user picked themselves is left untouched.
  const currentFolder = form.music_library.folder.trim()
  if (folderName && (!currentFolder || currentFolder === DEFAULT_MUSIC_FOLDER)) {
    form.music_library.folder = folderName
  }

  uploadBusy.value = true
  error.value = ''
  success.value = ''
  const failures = []
  let added = 0

  try {
    for (const file of audio) {
      try {
        const asset = await uploadMusicTrack(file)
        musicAssets.value = [asset, ...musicAssets.value.filter(a => a.ref !== asset.ref)]
        if (!form.music_library.tracks.includes(asset.ref)) {
          form.music_library.tracks.push(asset.ref)
        }
        added += 1
        if (!form.audio_defaults.music_profile) {
          form.audio_defaults.music_profile = asset.ref
        }
      } catch (err) {
        // One bad file must not abandon the rest of the folder.
        failures.push(`${file.name}: ${err.message || err}`)
      }
    }
    if (added) markDirty()

    const parts = [`${added} track${added === 1 ? '' : 's'} added`]
    if (skipped) parts.push(`${skipped} non-audio skipped`)
    if (failures.length) parts.push(`${failures.length} failed`)
    success.value = added ? `${parts.join(' · ')}.` : ''
    if (failures.length) error.value = failures.slice(0, 3).join(' | ')
  } finally {
    uploadBusy.value = false
  }
}

function toggleTrack(refId) {
  const index = form.music_library.tracks.indexOf(refId)
  if (index >= 0) form.music_library.tracks.splice(index, 1)
  else form.music_library.tracks.push(refId)
  markDirty()
}

/**
 * Audition a bed. `path` is the managed URL the library hands back
 * (`/output/musics/…` or `/assets/sounds/music/…`) — never a disk path — and
 * one element serves every row, so starting a track stops the last one.
 */
function togglePlay(track) {
  const element = previewAudio.value
  if (!element || !track.path) return
  if (playingRef.value === track.ref) {
    element.pause()
    playingRef.value = ''
    return
  }
  element.src = track.path
  playingRef.value = track.ref
  try {
    element.play()?.catch(() => { playingRef.value = '' })
  } catch {
    playingRef.value = ''
  }
}

function pickThumbnail() {
  thumbnailInput.value?.click()
}

function pickLogo() {
  logoInput.value?.click()
}

function clearAsset(key) {
  form.branding[key] = null
  if (key === 'logo_asset_id') form.branding.enabled = false
  markDirty()
}

function setPosition(id) {
  form.branding.position = id
  markDirty()
}

function addPatternRow() {
  form.visual_direction.pattern.push({ narrative_role: '', shot: '' })
  markDirty()
}

function removePatternRow(index) {
  form.visual_direction.pattern.splice(index, 1)
  markDirty()
}

function movePattern(index, delta) {
  const next = index + delta
  if (next < 0 || next >= form.visual_direction.pattern.length) return
  const list = form.visual_direction.pattern
  const [row] = list.splice(index, 1)
  list.splice(next, 0, row)
  markDirty()
}

function addTemplateSection() {
  form.script_template.sections.push('New section')
  markDirty()
}

function removeTemplateSection(index) {
  form.script_template.sections.splice(index, 1)
  markDirty()
}

function moveTemplateSection(index, delta) {
  const next = index + delta
  if (next < 0 || next >= form.script_template.sections.length) return
  const [section] = form.script_template.sections.splice(index, 1)
  form.script_template.sections.splice(next, 0, section)
  markDirty()
}

/**
 * The house outline comes from `/api/channels/defaults`, which is the same
 * blank draft the backend builds a new Channel from. Hardcoding the five
 * section names here would be a second source of truth for them.
 */
async function resetTemplateSections() {
  error.value = ''
  try {
    const defaults = await getChannelDefaults()
    const sections = defaults?.draft?.script_template?.sections
    if (Array.isArray(sections) && sections.length) {
      form.script_template.sections = [...sections]
      markDirty()
    }
  } catch (err) {
    error.value = err.message || String(err)
  }
}

watch(channelId, (next, prev) => {
  if (!next) return
  if (revertingChannelNav) {
    revertingChannelNav = false
    return
  }
  // The rail sits beside the editor now, so switching channels is a click
  // away. Dropping a dirty draft without asking would silently lose work.
  if (dirty.value && prev && prev !== next) {
    if (!window.confirm('Discard unsaved changes?')) {
      revertingChannelNav = true
      router.replace({ name: 'channel-edit', params: { id: prev } })
      return
    }
  }
  load()
})

onMounted(load)
</script>

<template>
  <section class="chview" aria-label="Channel editor">
    <ChannelRail ref="railRef" />

    <main class="ch-detail">
      <div v-if="loading" class="ch-empty"><h3>Loading…</h3></div>

      <template v-else>
        <!-- ── Hero ─────────────────────────────────────────────────── -->
        <div class="ch-hero" :style="{ '--hero-color': accent }">
          <button
            type="button"
            class="ch-hero-av ch-avatar"
            :style="heroAvatarStyle"
            title="Channel thumbnail — click to upload"
            aria-label="Upload channel thumbnail"
            @click="pickThumbnail"
          >
            {{ thumbnailPreviewUrl ? '' : initials }}
            <span class="av-edit" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
            </span>
          </button>
          <input
            ref="thumbnailInput"
            type="file"
            class="hidden-file"
            accept="image/png,image/jpeg,image/webp"
            :disabled="uploadBusy"
            @change="onThumbnailFile"
          />

          <div class="ch-hero-main">
            <input
              v-model="form.name"
              class="ch-name-input"
              type="text"
              required
              maxlength="120"
              aria-label="Channel name"
              @input="markDirty"
            />
            <div class="ch-hero-sub">
              <span v-if="form.content.platforms.length" class="plats">
                <span
                  v-for="plat in form.content.platforms"
                  :key="plat"
                  class="plat-ic"
                  :style="{ background: PLATFORM_COLORS[plat] }"
                >{{ plat[0] }}</span>
              </span>
              <span v-else class="no-plats">No platforms</span>
              <span class="dot-sep" />
              <span>{{ displayLanguage }}</span>
              <span class="dot-sep" />
              <span>{{ form.export_defaults.aspect_ratio }} · {{ lengthLabel }}</span>
              <span class="dot-sep" />
              <span class="mono">{{ form.content.niche || meta.id }}</span>
            </div>
          </div>

          <div class="ch-hero-stats">
            <div class="ch-stat">
              <div class="n">{{ channelStats.videos }}</div>
              <div class="l">Videos</div>
            </div>
            <div class="ch-stat">
              <div class="n">{{ channelStats.published }}</div>
              <div class="l">Published</div>
            </div>
            <div class="ch-stat">
              <div class="n">{{ channelStats.batch }}</div>
              <div class="l">In batch</div>
            </div>
          </div>
        </div>

        <p v-if="error" class="banner error ch-alert" role="alert">{{ error }}</p>
        <p v-if="success" class="banner ok ch-alert">{{ success }}</p>

        <form class="ch-body" @submit.prevent="onSave">
          <!-- ── Identity ───────────────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 21v-1a6 6 0 0 1 12 0v1" /></svg>
              Identity
            </h3>
            <div class="desc">
              How the channel presents itself. Platforms and language flow into every job.
            </div>
            <div class="ch-grid">
              <div class="ch-field">
                <span class="ch-field-label">Accent color</span>
                <div class="ch-swatches" role="radiogroup" aria-label="Accent color">
                  <button
                    v-for="color in CHANNEL_COLORS"
                    :key="color"
                    type="button"
                    class="ch-sw"
                    :class="{ sel: accent.toLowerCase() === color }"
                    :style="{ background: color, color }"
                    :aria-label="color"
                    :aria-checked="accent.toLowerCase() === color"
                    role="radio"
                    @click="setAccent(color)"
                  />
                </div>
              </div>
              <div class="ch-field">
                <label for="ch-language">Language</label>
                <select id="ch-language" class="ch-select" :value="displayLanguage" @change="setLanguage($event.target.value)">
                  <option v-for="lang in languageOptions" :key="lang" :value="lang">{{ lang }}</option>
                </select>
              </div>
            </div>
            <div class="ch-field" style="margin-top: 14px">
              <span class="ch-field-label">Platforms</span>
              <div class="ch-plat-row">
                <button
                  v-for="code in PLATFORM_ORDER"
                  :key="code"
                  type="button"
                  class="ch-plat"
                  :class="{ on: platformOn(code) }"
                  @click="togglePlatform(code)"
                >
                  <span class="pdot" :style="{ background: PLATFORM_COLORS[code] }">{{ code[0] }}</span>
                  {{ PLATFORM_NAMES[code] }}
                  <svg class="pcheck" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
                </button>
              </div>
            </div>
          </section>

          <!-- ── Look & voice ───────────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="13.5" cy="6.5" r="2.5" /><circle cx="17.5" cy="10.5" r="2.5" /><circle cx="8.5" cy="7.5" r="2.5" /><circle cx="6.5" cy="12.5" r="2.5" /><path d="M12 2a10 10 0 1 0 0 20 2 2 0 0 0 0-4 2 2 0 0 1 0-4h2a4 4 0 0 0 4-4 10 10 0 0 0-10-8z" /></svg>
              Look &amp; voice
            </h3>
            <div class="desc">
              Inherited by S1 and the production pipeline. Change once here, every job follows.
            </div>
            <div class="ch-grid">
              <div class="ch-field">
                <label for="ch-style">Image style</label>
                <select id="ch-style" v-model="form.visual_direction.style" class="ch-select" @change="markDirty">
                  <option v-for="opt in imageStyleOptions" :key="opt" :value="opt">{{ opt }}</option>
                </select>
              </div>
              <div class="ch-field">
                <label for="ch-voice">Narration voice · Inworld</label>
                <select id="ch-voice" v-model="form.audio_defaults.voice" class="ch-select" @change="markDirty">
                  <option v-for="opt in voiceOptions" :key="opt" :value="opt">{{ opt }}</option>
                </select>
              </div>
              <div class="ch-field">
                <label for="ch-tone">Tone</label>
                <select id="ch-tone" v-model="form.content.tone" class="ch-select" @change="markDirty">
                  <option v-for="opt in toneOptions" :key="opt" :value="opt">{{ opt }}</option>
                </select>
              </div>
              <div class="ch-field">
                <label for="ch-mood">Mood</label>
                <select id="ch-mood" v-model="form.content.mood" class="ch-select" @change="markDirty">
                  <option v-for="opt in moodOptions" :key="opt" :value="opt">{{ opt }}</option>
                </select>
              </div>
              <div class="ch-field">
                <label for="ch-captions">Caption preset</label>
                <select id="ch-captions" v-model="form.captions.preset" class="ch-select" @change="markDirty">
                  <option v-for="opt in captionOptions" :key="opt" :value="opt">{{ opt }}</option>
                </select>
              </div>
              <div class="ch-field">
                <label for="ch-branding">Branding</label>
                <select id="ch-branding" class="ch-select" :value="brandingTreatment" @change="setBrandingTreatment($event.target.value)">
                  <option v-for="opt in BRANDING_OPTIONS" :key="opt" :value="opt">{{ opt }}</option>
                </select>
              </div>
            </div>
            <div class="ch-field wide">
              <label for="ch-style-prompt">
                Visual style prompt
                <span class="note">· prepended to every scene's image prompt</span>
              </label>
              <textarea
                id="ch-style-prompt"
                v-model="form.visual_direction.style_prompt"
                class="ch-input"
                rows="3"
                placeholder="Describe the Channel's house look, materials, color treatment, and rendering style."
                @input="markDirty"
              ></textarea>
            </div>
            <div class="ch-imgprev" aria-live="polite">
              <div class="ch-imgprev-h">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></svg>
                Example image prompt
              </div>
              <code class="ch-imgprev-code">{{
                promptPreviewLoading && !promptPreview ? 'Composing…' : promptPreview
              }}</code>
            </div>
          </section>

          <!-- ── Visual direction ───────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M2 7h20M7 7v14M2 12h5M2 17h5" /><rect x="7" y="7" width="15" height="14" rx="2" /></svg>
              Visual direction
            </h3>
            <div class="desc">
              <code>pattern</code> is a structured ordered list of narrative role → shot —
              never free text. That is what makes Scene Director deterministic.
            </div>
            <div class="pattern-table">
              <div class="pattern-head">
                <span>Narrative role</span>
                <span>Shot</span>
                <span></span>
              </div>
              <div
                v-for="(row, index) in form.visual_direction.pattern"
                :key="index"
                class="pattern-row"
              >
                <input v-model="row.narrative_role" class="ch-input" type="text" placeholder="hook" :aria-label="`Narrative role ${index + 1}`" @input="markDirty" />
                <input v-model="row.shot" class="ch-input" type="text" placeholder="extreme close-up" :aria-label="`Shot ${index + 1}`" @input="markDirty" />
                <div class="pattern-actions">
                  <button type="button" class="ch-tpl-mv" :disabled="index === 0" :aria-label="`Move role ${index + 1} up`" @click="movePattern(index, -1)">↑</button>
                  <button type="button" class="ch-tpl-mv" :disabled="index === form.visual_direction.pattern.length - 1" :aria-label="`Move role ${index + 1} down`" @click="movePattern(index, 1)">↓</button>
                  <button type="button" class="ch-tpl-x" :aria-label="`Remove role ${index + 1}`" @click="removePatternRow(index)">✕</button>
                </div>
              </div>
            </div>
            <div class="ch-tpl-actions">
              <button type="button" class="btn xs" @click="addPatternRow">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
                Add role
              </button>
            </div>
            <div class="ch-grid spaced">
              <div class="ch-field">
                <label for="ch-palette">Palette</label>
                <input id="ch-palette" v-model="form.visual_direction.palette" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-lighting">Lighting</label>
                <input id="ch-lighting" v-model="form.visual_direction.lighting" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-camera">Camera</label>
                <input id="ch-camera" v-model="form.visual_direction.camera" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-character">Character style</label>
                <input id="ch-character" v-model="form.visual_direction.character_style" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-continuity">Continuity</label>
                <input id="ch-continuity" v-model="form.visual_direction.continuity" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-negative">Negative prompt</label>
                <input id="ch-negative" v-model="form.visual_direction.negative_prompt" class="ch-input" type="text" @input="markDirty" />
              </div>
            </div>
          </section>

          <!-- ── Script template ────────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7V4h16v3M9 20h6M12 4v16" /></svg>
              Script template
            </h3>
            <div class="desc">
              How Script Studio writes for this channel. Used when a job auto-generates
              or expands an idea into a script — pasted scripts are left as they are.
            </div>
            <div class="ch-field wide">
              <label for="ch-brief">Structure brief</label>
              <textarea
                id="ch-brief"
                v-model="form.script_template.brief"
                class="ch-input"
                rows="4"
                required
                placeholder="Describe the story shape in plain language."
                @input="markDirty"
              ></textarea>
            </div>
            <div class="ch-field wide">
              <label>
                Section outline
                <span class="note">· the beats, in order</span>
              </label>
              <div class="ch-tpl-sections">
                <div
                  v-for="(section, index) in form.script_template.sections"
                  :key="index"
                  class="ch-tpl-sec"
                >
                  <span class="ch-tpl-num">{{ index + 1 }}</span>
                  <input
                    v-model="form.script_template.sections[index]"
                    class="ch-input"
                    type="text"
                    required
                    maxlength="80"
                    :aria-label="`Section ${index + 1} name`"
                    @input="markDirty"
                  />
                  <button type="button" class="ch-tpl-mv" :disabled="index === 0" :aria-label="`Move ${section} up`" @click="moveTemplateSection(index, -1)">↑</button>
                  <button type="button" class="ch-tpl-mv" :disabled="index === form.script_template.sections.length - 1" :aria-label="`Move ${section} down`" @click="moveTemplateSection(index, 1)">↓</button>
                  <button type="button" class="ch-tpl-x" :disabled="form.script_template.sections.length === 1" :aria-label="`Remove ${section}`" @click="removeTemplateSection(index)">✕</button>
                </div>
              </div>
              <div class="ch-tpl-actions">
                <button type="button" class="btn xs" @click="addTemplateSection">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
                  Add section
                </button>
                <button type="button" class="btn xs ghost" @click="resetTemplateSections">
                  Reset to default
                </button>
              </div>
            </div>
          </section>

          <!-- ── Production defaults ────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M9 21V9" /></svg>
              Production defaults
            </h3>
            <div class="desc">Starting values for new jobs — still overridable per job.</div>
            <div class="ch-grid">
              <div class="ch-field">
                <label for="ch-aspect">Aspect ratio</label>
                <select id="ch-aspect" v-model="form.export_defaults.aspect_ratio" class="ch-select" @change="markDirty">
                  <option v-for="ratio in aspectOptions" :key="ratio" :value="ratio">{{ ratio }}</option>
                </select>
              </div>
              <div class="ch-field">
                <label for="ch-duration">Target length (seconds)</label>
                <input id="ch-duration" v-model="form.content.duration_target" class="ch-input" type="number" min="1" max="600" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-resolution">Resolution</label>
                <input id="ch-resolution" v-model="form.export_defaults.resolution" class="ch-input" type="text" placeholder="1080x1920" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-fps">FPS</label>
                <input id="ch-fps" v-model="form.export_defaults.fps" class="ch-input" type="number" min="1" max="120" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-profile">Encode profile</label>
                <input id="ch-profile" v-model="form.export_defaults.profile" class="ch-input" type="text" @input="markDirty" />
              </div>
            </div>
          </section>

          <!-- ── Music library ──────────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" /></svg>
              Music library
            </h3>
            <div class="desc">Music beds are loaded from this channel's folder. Point it at your tracks.</div>
            <div class="ch-field">
              <label for="ch-folder">Music folder</label>
              <div class="ch-path-row">
                <input
                  id="ch-folder"
                  v-model="form.music_library.folder"
                  class="ch-input mono"
                  type="text"
                  placeholder="e.g. D:\Scriptase\music\channel"
                  @input="markDirty"
                />
                <label class="btn sm upload-btn" :class="{ disabled: uploadBusy }" title="Choose a folder of tracks — files are uploaded, the disk path is not stored">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>
                  {{ uploadBusy ? 'Adding…' : 'Add location' }}
                  <input type="file" class="hidden-file" webkitdirectory directory multiple :disabled="uploadBusy" @change="onMusicFolder" />
                </label>
              </div>
            </div>
            <div class="ch-narr-item" style="margin-top: 14px">
              <div class="ch-narr-txt">
                <div class="t">Pick a random music</div>
                <div class="d">Choose a different bed from the library for each job, instead of a fixed track</div>
              </div>
              <button
                type="button"
                class="s1-toggle"
                :class="{ on: form.audio_defaults.music_random }"
                role="switch"
                :aria-checked="form.audio_defaults.music_random"
                aria-label="Pick a random music"
                @click="form.audio_defaults.music_random = !form.audio_defaults.music_random; markDirty()"
              ></button>
            </div>
            <div class="ch-field" style="margin-top: 14px">
              <label for="ch-default-bed">
                Default music bed
                <span class="note">· {{ channelTracks.length }} track{{ channelTracks.length === 1 ? '' : 's' }} in folder</span>
                <span v-if="form.audio_defaults.music_random" class="note">· random pick is on</span>
              </label>
              <select
                id="ch-default-bed"
                class="ch-select"
                :value="defaultBedValue"
                :disabled="!channelTracks.length || form.audio_defaults.music_random"
                @change="setDefaultBed($event.target.value)"
              >
                <option v-for="opt in defaultBedOptions" :key="opt" :value="opt">{{ opt }}</option>
              </select>
            </div>
            <div v-if="channelTracks.length" class="ch-tracklist" role="listbox" aria-label="Tracks in folder">
              <div
                v-for="track in channelTracks"
                :key="track.ref"
                class="ch-track"
                :class="{ sel: form.audio_defaults.music_profile === track.ref }"
                role="option"
                :aria-selected="String(form.audio_defaults.music_profile === track.ref)"
                @click="selectBed(track.ref)"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" /></svg>
                {{ track.filename }}
                <span
                  v-if="track.path"
                  class="ch-track-play"
                  role="button"
                  tabindex="0"
                  :aria-label="`${playingRef === track.ref ? 'Stop' : 'Play'} ${track.filename}`"
                  @click.stop="togglePlay(track)"
                  @keydown.enter.stop.prevent="togglePlay(track)"
                  @keydown.space.stop.prevent="togglePlay(track)"
                >
                  <svg v-if="playingRef === track.ref" width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" /><rect x="14" y="5" width="4" height="14" /></svg>
                  <svg v-else width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="6 3 20 12 6 21 6 3" /></svg>
                </span>
              </div>
            </div>
            <audio ref="previewAudio" class="hidden-file" @ended="playingRef = ''"></audio>
          </section>

          <!-- ── Narration processing ───────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" /><path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4" /></svg>
              Narration processing
            </h3>
            <div class="desc">
              Applied to every job's narration. An individual script can override this
              in Script Studio.
            </div>
            <div class="ch-narr-row">
              <div class="ch-narr-item">
                <div class="ch-narr-txt">
                  <div class="t">Remove silence</div>
                  <div class="d">Trim dead air &amp; long pauses from the voiceover</div>
                </div>
                <button
                  type="button"
                  class="s1-toggle"
                  :class="{ on: form.audio_defaults.remove_silence }"
                  role="switch"
                  :aria-checked="form.audio_defaults.remove_silence"
                  aria-label="Remove silence"
                  @click="form.audio_defaults.remove_silence = !form.audio_defaults.remove_silence; markDirty()"
                ></button>
              </div>
              <div class="ch-narr-item">
                <div class="ch-narr-txt">
                  <div class="t">Speed up audio</div>
                  <div class="d">Time-stretch narration to tighten pacing</div>
                </div>
                <select v-model.number="form.audio_defaults.speed" class="ch-select narr-select" aria-label="Narration speed" @change="markDirty">
                  <option v-for="speed in speedOptions" :key="speed" :value="speed">{{ speed }}×</option>
                </select>
              </div>
              <div class="ch-narr-item">
                <div class="ch-narr-txt">
                  <div class="t">Scene pacing</div>
                  <div class="d">{{ pacingHint }}</div>
                </div>
                <select v-model="form.audio_defaults.scene_pacing" class="ch-select narr-select" aria-label="Scene pacing" @change="markDirty">
                  <option v-for="p in pacingOptions" :key="p.id" :value="p.id">{{ p.label }}</option>
                </select>
              </div>
            </div>
            <div class="ch-grid spaced">
              <div class="ch-field">
                <label for="ch-tts-instance">TTS provider instance id</label>
                <input id="ch-tts-instance" v-model="form.audio_defaults.tts_provider_instance_id" class="ch-input mono" type="text" placeholder="instance id only — never a key" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-music-profile">Music profile</label>
                <input id="ch-music-profile" v-model="form.audio_defaults.music_profile" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-loudness">Loudness (LUFS)</label>
                <input id="ch-loudness" v-model="form.audio_defaults.loudness" class="ch-input" type="number" step="0.5" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-ducking">Music ducking (0–1)</label>
                <input id="ch-ducking" v-model="form.audio_defaults.ducking" class="ch-input" type="number" min="0" max="1" step="0.05" @input="markDirty" />
              </div>
            </div>
          </section>

          <!-- ── Captions ───────────────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="2" /><path d="M7 15h4M14 15h3" /></svg>
              Captions
            </h3>
            <div class="desc">
              Captions are a local service, not a provider domain — the preset names a
              built-in treatment.
            </div>
            <div class="ch-grid">
              <div class="ch-field">
                <label for="ch-cap-preset">Preset</label>
                <input id="ch-cap-preset" v-model="form.captions.preset" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-cap-position">Position</label>
                <input id="ch-cap-position" v-model="form.captions.position" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-cap-font">Font treatment</label>
                <input id="ch-cap-font" v-model="form.captions.font_treatment" class="ch-input" type="text" @input="markDirty" />
              </div>
              <div class="ch-field">
                <label for="ch-cap-anim">Animation</label>
                <input id="ch-cap-anim" v-model="form.captions.animation" class="ch-input" type="text" @input="markDirty" />
              </div>
            </div>
          </section>

          <!-- ── Brand assets ───────────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></svg>
              Brand assets
            </h3>
            <div class="desc">
              Optional. The thumbnail identifies the channel in lists; the logo is burned
              onto exports as a watermark. Both upload through the managed branding
              library — never a filesystem path.
            </div>
            <div class="ch-grid">
              <div class="ch-field">
                <label>Thumbnail</label>
                <div class="ch-asset-drop" role="button" tabindex="0" @click="pickThumbnail" @keydown.enter.prevent="pickThumbnail" @keydown.space.prevent="pickThumbnail">
                  <img v-if="thumbnailPreviewUrl" :src="thumbnailPreviewUrl" class="ch-asset-img" alt="Channel thumbnail preview" />
                  <div v-else class="ch-asset-ph" :style="{ background: `${accent}22`, color: accent }">{{ initials }}</div>
                  <div class="ch-asset-meta">
                    <div class="t">{{ thumbnailPreviewUrl ? 'Thumbnail set' : 'Add thumbnail' }}</div>
                    <div class="d">{{ thumbnailPreviewUrl ? 'Click to replace' : 'PNG / JPG · used in lists' }}</div>
                  </div>
                  <button v-if="thumbnailPreviewUrl" type="button" class="ch-asset-x" aria-label="Remove thumbnail" @click.stop="clearAsset('thumbnail_asset_id')">✕</button>
                </div>
              </div>
              <div class="ch-field">
                <label>Logo · watermark</label>
                <div class="ch-asset-drop" role="button" tabindex="0" @click="pickLogo" @keydown.enter.prevent="pickLogo" @keydown.space.prevent="pickLogo">
                  <div v-if="logoPreviewUrl" class="ch-asset-img wm-check">
                    <img :src="logoPreviewUrl" alt="Channel logo preview" />
                  </div>
                  <div v-else class="ch-asset-ph placeholder-logo">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
                  </div>
                  <div class="ch-asset-meta">
                    <div class="t">{{ logoPreviewUrl ? 'Logo set' : 'Add logo' }}</div>
                    <div class="d">{{ logoPreviewUrl ? 'Watermark on export' : 'PNG w/ transparency' }}</div>
                  </div>
                  <button v-if="logoPreviewUrl" type="button" class="ch-asset-x" aria-label="Remove logo" @click.stop="clearAsset('logo_asset_id')">✕</button>
                </div>
              </div>
            </div>
            <input
              ref="logoInput"
              type="file"
              class="hidden-file"
              accept="image/png,image/jpeg,image/webp"
              :disabled="uploadBusy"
              @change="onLogoFile"
            />

            <div class="ch-wm-pos-wrap">
              <span class="ch-field-label">
                Watermark position
                <span class="note">· {{ positionLabel }}</span>
              </span>
              <div class="ch-wm-editor">
                <div class="ch-wm-frame" :style="watermarkFrameStyle">
                  <div class="ch-wm-preview" :style="watermarkPreviewStyle">
                    <img v-if="logoPreviewUrl" :src="logoPreviewUrl" alt="" />
                    <span v-else class="wm-dot"></span>
                  </div>
                </div>
                <div class="ch-wm-grid" role="radiogroup" aria-label="Watermark position">
                  <button
                    v-for="position in POSITIONS"
                    :key="position.id"
                    type="button"
                    class="ch-wm-cell"
                    :class="{ sel: form.branding.position === position.id }"
                    role="radio"
                    :aria-checked="form.branding.position === position.id"
                    :aria-label="position.label"
                    :title="position.label"
                    @click="setPosition(position.id)"
                  ><span class="dot"></span></button>
                </div>
              </div>
              <p class="ch-wm-note">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
                Burned in at <b>&nbsp;{{ positionLabel }}&nbsp;</b> on export when the
                watermark is enabled.
              </p>
              <div class="ch-grid spaced">
                <div class="ch-field">
                  <label class="check">
                    <input v-model="form.branding.enabled" type="checkbox" @change="markDirty" />
                    Show the logo on video
                  </label>
                </div>
                <div class="ch-field">
                  <label for="ch-wm-size">Size (0–1)</label>
                  <input id="ch-wm-size" v-model.number="form.branding.size" class="ch-input" type="number" min="0" max="1" step="0.01" @input="markDirty" />
                </div>
                <div class="ch-field">
                  <label for="ch-wm-opacity">Opacity</label>
                  <input id="ch-wm-opacity" v-model.number="form.branding.opacity" class="ch-input" type="number" min="0" max="1" step="0.05" @input="markDirty" />
                </div>
                <div class="ch-field">
                  <label for="ch-wm-margin">Margin</label>
                  <input id="ch-wm-margin" v-model.number="form.branding.margin" class="ch-input" type="number" min="0" max="0.5" step="0.01" @input="markDirty" />
                </div>
              </div>
            </div>
          </section>

          <!-- ── Provider defaults ──────────────────────────────────── -->
          <section class="ch-section">
            <h3>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="2" y="7" width="20" height="10" rx="2" /><path d="M6 12h.01M10 12h.01" /></svg>
              Provider defaults
            </h3>
            <div class="desc">
              Choose a provider instance for each domain. Credentials resolve at runtime
              from the provider instance store and never enter a Channel document.
            </div>
            <div class="ch-providers">
              <ProviderSelector
                v-for="pd in providerDomains"
                :key="pd.domain"
                variant="inline"
                :domain="pd.domain"
                :label="pd.label"
                :model-value="form.provider_defaults[pd.key] || ''"
                @update:model-value="(id) => { form.provider_defaults[pd.key] = id || null; markDirty() }"
                @configure="onProviderConfigure"
              />
            </div>
          </section>

          <!-- ── What a job inherits ────────────────────────────────── -->
          <div class="ch-preview">
            <div class="pt">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 12h16M4 12l4-4M4 12l4 4" /></svg>
              What a job inherits from this channel
            </div>
            <div class="ch-preview-chips">
              <span v-for="[key, value] in inheritedChips" :key="key" class="ch-pchip">
                <span class="k">{{ key }}</span> {{ value }}
              </span>
              <span v-if="!inheritedChips.length" class="ch-pchip">
                <span class="k">Nothing set yet</span>
              </span>
            </div>
          </div>
        </form>

        <div class="ch-foot">
          <div class="ch-dirty" :class="{ show: dirty }">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" /></svg>
            Unsaved changes
          </div>
          <div class="spacer"></div>
          <button type="button" class="btn ghost sm" :disabled="saving" @click="useInBatch">
            → New job with this
          </button>
          <button type="button" class="btn sm" :disabled="saving" @click="duplicateChannel">
            Duplicate
          </button>
          <button type="button" class="btn danger sm" :disabled="saving" @click="onDelete">
            Delete
          </button>
          <!-- The rail's New button is also `.btn.primary`, so the save
               control is addressed by test id rather than by class. -->
          <button
            type="button"
            class="btn primary sm"
            data-testid="channel-save"
            :disabled="saving"
            @click="onSave"
          >
            {{ saving ? 'Saving…' : 'Save changes' }}
          </button>
        </div>
      </template>
    </main>
  </section>
</template>

<style scoped>
/* The prototype's `.body.chview` and its `ch-*` editor. Where the prototype
   writes a literal rgba, the port uses the token that already names it. */
.chview {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.ch-detail {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.ch-empty {
  flex: 1;
  display: grid;
  place-items: center;
  color: var(--muted);
  padding: 40px;
}
.ch-empty h3 { font-family: var(--display); font-size: 16px; color: var(--text); }

/* ── Hero ─────────────────────────────────────────────────────────── */
.ch-hero {
  padding: 26px 32px 22px;
  border-bottom: 1px solid var(--line-soft);
  display: flex;
  align-items: center;
  gap: 20px;
  position: relative;
  overflow: hidden;
  /* The prototype's `.ch-detail` is a plain block, so the hero sits at its
     natural height. Here `.ch-detail` is a flex column — `.ch-empty` needs a
     flex parent to centre in — which makes the hero a flex child free to
     shrink, and `overflow: hidden` then clips the avatar and the stats rather
     than scrolling them. Opting out of shrinking restores the prototype's
     height without taking the centring away from `.ch-empty`. */
  flex: none;
}

/* The channel's own colour bleeding in from the top-left corner. */
.ch-hero::before {
  content: "";
  position: absolute;
  inset: 0;
  opacity: .10;
  background: radial-gradient(420px 200px at 12% -30%, var(--hero-color, var(--accent)), transparent 70%);
  pointer-events: none;
}

.ch-hero-av {
  width: 66px;
  height: 66px;
  border-radius: 16px;
  font-size: 26px;
  position: relative;
  z-index: 1;
  cursor: pointer;
  border: none;
  padding: 0;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .18),
    inset 0 0 0 1px rgba(255, 255, 255, .14),
    0 10px 24px -10px rgba(0, 0, 0, .6);
}

.ch-hero-av .av-edit {
  position: absolute;
  inset: 0;
  border-radius: 16px;
  background: rgba(0, 0, 0, .45);
  display: grid;
  place-items: center;
  opacity: 0;
  transition: opacity .15s;
  color: #fff;
}

.ch-hero-av:hover .av-edit,
.ch-hero-av:focus-visible .av-edit { opacity: 1; }

.ch-hero-main { flex: 1; min-width: 0; z-index: 1; }

.ch-name-input {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-family: var(--display);
  font-weight: 600;
  font-size: 26px;
  letter-spacing: -.5px;
  padding: 0;
}
.ch-name-input:focus { color: #fff; }

.ch-hero-sub {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--muted);
  flex-wrap: wrap;
}

.ch-hero-stats { display: flex; gap: 26px; z-index: 1; }
.ch-stat { text-align: right; }
.ch-stat .n { font-family: var(--display); font-size: 22px; font-weight: 600; letter-spacing: -.5px; }
.ch-stat .l {
  font-family: var(--mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: .7px;
  color: var(--muted);
  margin-top: 3px;
}

.ch-alert { margin: 16px 32px 0; }

/* ── Sections and fields ──────────────────────────────────────────── */
.ch-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 24px 32px 28px;
  display: flex;
  flex-direction: column;
  gap: 26px;
  max-width: 920px;
}

.ch-section h3 {
  font-family: var(--display);
  font-size: 13px;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 9px;
}
.ch-section h3 svg { color: var(--muted); flex: none; }
.ch-section .desc { color: var(--muted); font-size: 12px; margin-bottom: 16px; line-height: 1.5; }
.ch-section .desc code {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  padding: 1px 5px;
  border-radius: 5px;
}

.ch-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.ch-grid.spaced { margin-top: 14px; }
.ch-providers { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }

.ch-field { display: flex; flex-direction: column; gap: 8px; }
.ch-field.wide { margin-top: 14px; }
.ch-field > label {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 7px;
}
.ch-field > label .note { color: var(--faint); text-transform: none; letter-spacing: 0; }
.ch-field > label.check {
  flex-direction: row;
  align-items: center;
  gap: 9px;
  font-family: var(--body);
  font-size: 13px;
  letter-spacing: .1px;
  text-transform: none;
  color: var(--text-2);
}

.ch-select,
.ch-input {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text);
  font-size: 13px;
  padding: 9px 11px;
  font-family: var(--body);
  width: 100%;
  transition: border-color .16s, box-shadow .16s;
}

.ch-input.mono { font-family: var(--mono); font-size: 12px; }
textarea.ch-input { resize: vertical; line-height: 1.5; }
.ch-input::placeholder { color: var(--faint); }

.ch-select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2379828d' stroke-width='2'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 32px;
}

.ch-select:focus,
.ch-input:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.ch-swatches { display: flex; gap: 7px; flex-wrap: wrap; }
.ch-sw {
  width: 20px;
  height: 20px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
  transition: transform 0.1s;
}
.ch-sw:hover { transform: scale(1.12); }
.ch-sw.sel { box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px currentColor; }

.ch-plat-row { display: flex; gap: 8px; flex-wrap: wrap; }
.ch-plat {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: var(--r-s);
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--text-2);
  transition: border-color 0.14s, background 0.14s, color 0.14s;
}
.ch-plat:hover { border-color: var(--line-2); }
.ch-plat.on { color: var(--text); border-color: var(--accent-line-2); background: var(--accent-wash); }
.ch-plat .pdot {
  width: 15px;
  height: 15px;
  border-radius: 4px;
  display: grid;
  place-items: center;
  font-size: 8px;
  font-weight: 700;
  color: #fff;
}
.ch-plat .pcheck { color: var(--accent); opacity: 0; }
.ch-plat.on .pcheck { opacity: 1; }

.plats { display: inline-flex; gap: 5px; }
.no-plats { color: var(--faint); }
.plat-ic {
  width: 15px;
  height: 15px;
  border-radius: 4px;
  display: grid;
  place-items: center;
  font-size: 8px;
  font-weight: 700;
  color: #fff;
}

input[type="checkbox"] { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; flex: none; }

/* The real file inputs stay operable behind the surfaces that trigger them. */
.hidden-file { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.upload-btn { flex: none; cursor: pointer; position: relative; }

/* ── Inherited preview strip ──────────────────────────────────────── */
.ch-preview {
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: linear-gradient(180deg, var(--panel), var(--bg-2));
  padding: 14px 16px;
}
.ch-preview .pt {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.ch-preview-chips { display: flex; flex-wrap: wrap; gap: 7px; }
.ch-pchip {
  font-size: 11.5px;
  color: var(--text-2);
  border: 1px solid var(--line-soft);
  background: var(--bg-2);
  border-radius: 20px;
  padding: 4px 11px 4px 9px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ch-pchip .k { color: var(--muted); font-size: 10px; }

/* ── Music ────────────────────────────────────────────────────────── */
.ch-path-row { display: flex; gap: 8px; }
.ch-path-row .ch-input { flex: 1; }

.ch-tracklist { margin-top: 12px; display: flex; flex-direction: column; gap: 5px; max-height: 260px; overflow-y: auto; }
.ch-track {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border-radius: var(--r-s);
  border: 1px solid var(--line-soft);
  background: var(--bg-2);
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text-2);
  cursor: pointer;
  text-align: left;
  transition: border-color .12s, background .12s, color .12s;
}
.ch-track:hover { border-color: var(--line-2); background: var(--panel); color: var(--text); }
.ch-track.sel { border-color: var(--accent-line-2); background: var(--accent-wash); color: var(--text); }
.ch-track svg { color: var(--muted); flex: none; }
.ch-track.sel svg { color: var(--accent); }
.ch-track .tspan { margin-left: auto; color: var(--faint); flex: none; }

/* Nested inside the row's button, so it is a focusable span rather than a
   second <button> — auditioning a bed must not also select it. */
.ch-track-play {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  background: var(--raise);
  color: var(--text-2);
  cursor: pointer;
  display: grid;
  place-items: center;
  flex: none;
  transition: background .12s, color .12s;
}
.ch-track-play:hover { background: var(--accent); color: #fff; }

/* ── Narration processing ─────────────────────────────────────────── */
.ch-narr-row { display: flex; flex-direction: column; gap: 10px; }
.ch-narr-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  background: var(--bg-2);
  box-shadow: var(--hairline-top);
}
.ch-narr-item .ch-narr-txt { flex: 1; min-width: 0; }
.ch-narr-item .ch-narr-txt .t { font-size: 13px; font-weight: 600; }
.ch-narr-item .ch-narr-txt .d { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.narr-select { width: 120px; flex: none; }

/* `.s1-toggle` is the prototype's own choice here — it puts Script Studio's
   switch in this row. It lives in styles/shared.css for that reason. */

/* ── Script template outline & the pattern table ──────────────────── */
.ch-tpl-sections { display: flex; flex-direction: column; gap: 6px; }
.ch-tpl-sec { display: flex; align-items: center; gap: 6px; }
.ch-tpl-sec .ch-input { flex: 1; }
.ch-tpl-num {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 700;
  color: var(--accent);
  background: var(--accent-dim);
  box-shadow: inset 0 0 0 1px var(--accent-line);
}
.ch-tpl-mv,
.ch-tpl-x {
  flex: none;
  width: 26px;
  height: 30px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--muted);
  border-radius: 6px;
  cursor: pointer;
  font-family: var(--mono);
  font-size: 12px;
}
.ch-tpl-mv:hover:not(:disabled),
.ch-tpl-x:hover:not(:disabled) { background: var(--panel-2); color: var(--text); }
.ch-tpl-mv:disabled,
.ch-tpl-x:disabled { opacity: .3; cursor: not-allowed; }
.ch-tpl-x:hover:not(:disabled) { color: var(--fail); border-color: var(--fail-line-2); background: var(--fail-dim); }
.ch-tpl-actions { display: flex; gap: 8px; margin-top: 10px; }

.pattern-table { display: flex; flex-direction: column; gap: 6px; }
.pattern-head,
.pattern-row { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; align-items: center; }
.pattern-head {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: .8px;
}
.pattern-actions { display: flex; gap: 6px; }

/* ── Composed image prompt ────────────────────────────────────────── */
.ch-imgprev {
  margin-top: 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  background: var(--bg-2);
  box-shadow: var(--hairline-top);
  overflow: hidden;
}
.ch-imgprev-h {
  font-family: var(--mono);
  font-size: 9.5px;
  letter-spacing: .5px;
  text-transform: uppercase;
  color: var(--muted);
  padding: 8px 11px;
  border-bottom: 1px solid var(--line-soft);
  display: flex;
  align-items: center;
  gap: 7px;
}
.ch-imgprev-h svg { color: var(--accent); }
.ch-imgprev-code {
  display: block;
  padding: 10px 11px;
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Brand asset drops ────────────────────────────────────────────── */
.ch-asset-drop {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px;
  border: 1px dashed var(--line);
  border-radius: var(--r);
  background: var(--bg-2);
  cursor: pointer;
  position: relative;
  transition: border-color .13s, background .13s;
}
.ch-asset-drop:hover { border-color: var(--accent-line-2); background: var(--panel); }

.ch-asset-img {
  width: 46px;
  height: 46px;
  border-radius: 8px;
  object-fit: cover;
  flex: none;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .08);
}

/* A transparent PNG needs a checkerboard behind it or it reads as empty. */
.ch-asset-img.wm-check {
  display: grid;
  place-items: center;
  background-color: #1a1e24;
  background-image:
    linear-gradient(45deg, #242a31 25%, transparent 25%),
    linear-gradient(-45deg, #242a31 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #242a31 75%),
    linear-gradient(-45deg, transparent 75%, #242a31 75%);
  background-size: 10px 10px;
  background-position: 0 0, 0 5px, 5px -5px, -5px 0;
}
.ch-asset-img.wm-check img { max-width: 40px; max-height: 40px; }

.ch-asset-ph {
  width: 46px;
  height: 46px;
  border-radius: 8px;
  flex: none;
  display: grid;
  place-items: center;
  font-family: var(--display);
  font-weight: 600;
  font-size: 15px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .08);
}
.ch-asset-ph.placeholder-logo { background: var(--raise); color: var(--muted); }

.ch-asset-meta { flex: 1; min-width: 0; }
.ch-asset-meta .t { font-size: 12.5px; font-weight: 600; }
.ch-asset-meta .d { font-size: 11px; color: var(--muted); margin-top: 2px; }

.ch-asset-x {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 20px;
  height: 20px;
  border-radius: 5px;
  border: none;
  background: var(--raise);
  color: var(--muted);
  cursor: pointer;
  font-size: 11px;
}
.ch-asset-x:hover { background: var(--fail-dim); color: var(--fail); }

.ch-wm-note {
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--ok);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ch-wm-note b { color: var(--text); font-weight: 600; }

/* ── Watermark position picker ────────────────────────────────────── */
.ch-wm-pos-wrap { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--line-soft); }

.ch-field-label {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--muted);
  display: block;
  margin-bottom: 11px;
}
.ch-field-label .note { color: var(--faint); text-transform: none; letter-spacing: 0; }

.ch-wm-editor { display: flex; align-items: center; gap: 18px; }

/* The frame takes the channel's export aspect, so the picker shows where the
   mark actually lands rather than where it lands on a square. */
.ch-wm-frame {
  position: relative;
  width: 96px;
  aspect-ratio: var(--fr, 9/16);
  max-height: 150px;
  border-radius: 8px;
  overflow: hidden;
  flex: none;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .08), 0 8px 20px -10px rgba(0, 0, 0, .7);
}

.ch-wm-preview { z-index: 2; }
.ch-wm-preview img { display: block; max-width: 26px; max-height: 16px; filter: drop-shadow(0 1px 3px rgba(0, 0, 0, .6)); }
.ch-wm-preview .wm-dot {
  display: block;
  width: 16px;
  height: 10px;
  border-radius: 3px;
  background: rgba(255, 255, 255, .75);
  box-shadow: 0 1px 3px rgba(0, 0, 0, .6);
}

.ch-wm-grid { display: grid; grid-template-columns: repeat(3, 34px); grid-template-rows: repeat(3, 34px); gap: 5px; }
.ch-wm-cell {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 7px;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: border-color .12s, background .12s, box-shadow .12s;
  padding: 0;
}
.ch-wm-cell:hover { border-color: var(--line-2); background: var(--panel-2); }
.ch-wm-cell .dot { width: 8px; height: 8px; border-radius: 2px; background: var(--faint); transition: background .12s, width .12s, height .12s; }
.ch-wm-cell:hover .dot { background: var(--text-2); }
.ch-wm-cell.sel {
  border-color: var(--accent-line-2);
  background: var(--accent-dim);
  box-shadow: inset 0 0 0 1px var(--accent-line);
}
.ch-wm-cell.sel .dot { background: var(--accent); width: 10px; height: 10px; }

/* ── Footer ───────────────────────────────────────────────────────── */
.ch-foot {
  flex: none;
  padding: 14px 32px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg-2);
  display: flex;
  align-items: center;
  gap: 10px;
  position: relative;
  z-index: 4;
}
.ch-foot .spacer { flex: 1; }

.ch-dirty {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--warn);
  display: none;
  align-items: center;
  gap: 6px;
}
.ch-dirty.show { display: flex; }

@media (max-width: 1000px) {
  .ch-grid, .ch-providers { grid-template-columns: 1fr; }
  .ch-hero { flex-wrap: wrap; }
  .ch-hero-stats { width: 100%; justify-content: flex-start; gap: 30px; }
  .pattern-head, .pattern-row { grid-template-columns: 1fr; }
  .pattern-head { display: none; }
}

/* The prototype hides the rail here. It is the only way back to the list on
   this route, so it stacks above the editor instead. */
@media (max-width: 820px) {
  .chview { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); }
  .ch-rail { border-right: 0; border-bottom: 1px solid var(--line); }
  .ch-hero, .ch-body, .ch-foot { padding-left: 18px; padding-right: 18px; }
}
</style>

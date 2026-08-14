<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  deleteChannel,
  getChannel,
  listBrandingAssets,
  updateChannel,
  uploadBrandingLogo,
} from './api.js'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const success = ref('')
const brandingAssets = ref([])
const uploadBusy = ref(false)

const channelId = computed(() => route.params.id)

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
  },
  visual_direction: {
    style: '',
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
    speed: 1,
    music_profile: '',
    loudness: null,
    ducking: null,
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

const logoPreviewUrl = computed(() => {
  const refId = form.branding.logo_asset_id
  if (!refId) return ''
  // Managed refs look like "branding/filename.png"
  if (refId.startsWith('branding/')) return `/output/${refId}`
  return `/output/branding/${refId}`
})

const POSITIONS = [
  'top-left',
  'top-right',
  'bottom-left',
  'bottom-right',
  'center',
]

function applyDocument(doc) {
  meta.id = doc.id
  meta.version = doc.version
  meta.schema_version = doc.schema_version
  meta.created_at = doc.created_at
  meta.updated_at = doc.updated_at

  form.name = doc.name || ''
  Object.assign(form.branding, {
    logo_asset_id: null,
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
    ...(doc.content || {}),
  })
  const vd = doc.visual_direction || {}
  form.visual_direction.style = vd.style || ''
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
    speed: 1,
    music_profile: '',
    loudness: null,
    ducking: null,
    ...(doc.audio_defaults || {}),
  })
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
}

function draftPayload() {
  const emptyToNull = (v) => {
    if (v === '' || v === undefined) return null
    return v
  }
  const emptyToEmpty = (v) => (v == null ? '' : v)

  return {
    name: form.name,
    branding: {
      ...form.branding,
      logo_asset_id: emptyToNull(form.branding.logo_asset_id),
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
    captions: { ...form.captions },
    provider_defaults: {
      script: emptyToNull(form.provider_defaults.script),
      tts: emptyToNull(form.provider_defaults.tts),
      scene_director: emptyToNull(form.provider_defaults.scene_director),
      image: emptyToNull(form.provider_defaults.image),
      video: emptyToNull(form.provider_defaults.video),
      review: emptyToNull(form.provider_defaults.review),
    },
    fallback_policies: {},
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
}

async function load() {
  loading.value = true
  error.value = ''
  success.value = ''
  try {
    const [{ channel }, branding] = await Promise.all([
      getChannel(channelId.value),
      listBrandingAssets().catch(() => ({ assets: [] })),
    ])
    applyDocument(channel)
    brandingAssets.value = branding.assets || []
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
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
    success.value = 'Logo uploaded — save the channel to keep the reference.'
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    uploadBusy.value = false
  }
}

function selectExistingLogo(refId) {
  form.branding.logo_asset_id = refId
  form.branding.enabled = true
}

function clearLogo() {
  form.branding.logo_asset_id = null
  form.branding.enabled = false
}

function addPatternRow() {
  form.visual_direction.pattern.push({ narrative_role: '', shot: '' })
}

function removePatternRow(index) {
  form.visual_direction.pattern.splice(index, 1)
}

function movePattern(index, delta) {
  const next = index + delta
  if (next < 0 || next >= form.visual_direction.pattern.length) return
  const list = form.visual_direction.pattern
  const [row] = list.splice(index, 1)
  list.splice(next, 0, row)
}

watch(channelId, () => {
  if (channelId.value) load()
})

onMounted(load)
</script>

<template>
  <section class="editor">
    <header class="page-header">
      <div>
        <router-link class="back" :to="{ name: 'channels' }">← Channels</router-link>
        <h1 v-if="!loading">{{ form.name || 'Channel' }}</h1>
        <h1 v-else>Loading…</h1>
        <p v-if="meta.id" class="meta-line">
          <code>{{ meta.id }}</code>
          · v{{ meta.version }}
          · schema {{ meta.schema_version }}
          <span v-if="meta.updated_at"> · updated {{ meta.updated_at }}</span>
        </p>
      </div>
      <div class="actions">
        <button type="button" class="danger ghost" :disabled="saving || loading" @click="onDelete">
          Delete
        </button>
        <button type="button" class="primary" :disabled="saving || loading" @click="onSave">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </header>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="success" class="success">{{ success }}</p>

    <form v-if="!loading" class="form" @submit.prevent="onSave">
      <fieldset>
        <legend>Identity</legend>
        <label>
          Name
          <input v-model="form.name" type="text" required maxlength="120" />
        </label>
        <label>
          Default workflow id
          <input v-model="form.default_workflow_id" type="text" placeholder="optional" />
        </label>
      </fieldset>

      <fieldset>
        <legend>Branding</legend>
        <p class="hint">
          Logo upload uses the managed branding library
          (<code>POST /api/workflow/branding</code>). Never paste a filesystem path.
        </p>
        <div class="logo-row">
          <div class="logo-preview" v-if="logoPreviewUrl">
            <img :src="logoPreviewUrl" alt="Channel logo preview" />
          </div>
          <div class="logo-preview empty" v-else>No logo</div>
          <div class="logo-controls">
            <label class="check">
              <input v-model="form.branding.enabled" type="checkbox" />
              Show logo on video
            </label>
            <label>
              Upload logo
              <input type="file" accept="image/png,image/jpeg,image/webp" :disabled="uploadBusy" @change="onLogoFile" />
            </label>
            <label>
              Or pick existing
              <select
                :value="form.branding.logo_asset_id || ''"
                @change="selectExistingLogo($event.target.value || null)"
              >
                <option value="">—</option>
                <option v-for="asset in brandingAssets" :key="asset.ref" :value="asset.ref">
                  {{ asset.filename }}
                </option>
              </select>
            </label>
            <button type="button" class="ghost" @click="clearLogo">Clear logo</button>
            <div class="grid-2">
              <label>
                Position
                <select v-model="form.branding.position">
                  <option v-for="p in POSITIONS" :key="p" :value="p">{{ p }}</option>
                </select>
              </label>
              <label>
                Size (0–1)
                <input v-model.number="form.branding.size" type="number" min="0" max="1" step="0.01" />
              </label>
              <label>
                Opacity
                <input v-model.number="form.branding.opacity" type="number" min="0" max="1" step="0.05" />
              </label>
              <label>
                Margin
                <input v-model.number="form.branding.margin" type="number" min="0" max="0.5" step="0.01" />
              </label>
            </div>
          </div>
        </div>
      </fieldset>

      <fieldset>
        <legend>Content</legend>
        <div class="grid-2">
          <label>Niche <input v-model="form.content.niche" type="text" /></label>
          <label>Language <input v-model="form.content.language" type="text" /></label>
          <label>Audience / category <input v-model="form.content.audience" type="text" /></label>
          <label>Tone <input v-model="form.content.tone" type="text" /></label>
          <label>Mood <input v-model="form.content.mood" type="text" /></label>
          <label>Script style <input v-model="form.content.script_style" type="text" /></label>
          <label>Hook style <input v-model="form.content.hook_style" type="text" /></label>
          <label>CTA style <input v-model="form.content.cta_style" type="text" /></label>
          <label>
            Duration target (s)
            <input v-model="form.content.duration_target" type="number" min="1" max="600" />
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Visual direction</legend>
        <p class="hint">
          <code>pattern</code> is a structured ordered list of narrative role → shot —
          never free text. That is what makes Scene Director deterministic.
        </p>
        <label>Style <input v-model="form.visual_direction.style" type="text" /></label>
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
            <input v-model="row.narrative_role" type="text" placeholder="hook" />
            <input v-model="row.shot" type="text" placeholder="extreme close-up" />
            <div class="pattern-actions">
              <button type="button" class="ghost" title="Move up" @click="movePattern(index, -1)">↑</button>
              <button type="button" class="ghost" title="Move down" @click="movePattern(index, 1)">↓</button>
              <button type="button" class="ghost danger" @click="removePatternRow(index)">✕</button>
            </div>
          </div>
          <button type="button" class="ghost" @click="addPatternRow">+ Add role</button>
        </div>
        <div class="grid-2">
          <label>Palette <input v-model="form.visual_direction.palette" type="text" /></label>
          <label>Lighting <input v-model="form.visual_direction.lighting" type="text" /></label>
          <label>Camera <input v-model="form.visual_direction.camera" type="text" /></label>
          <label>Character style <input v-model="form.visual_direction.character_style" type="text" /></label>
          <label>Continuity <input v-model="form.visual_direction.continuity" type="text" /></label>
          <label>Negative prompt <input v-model="form.visual_direction.negative_prompt" type="text" /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Audio defaults</legend>
        <div class="grid-2">
          <label>Voice <input v-model="form.audio_defaults.voice" type="text" /></label>
          <label>Speed <input v-model.number="form.audio_defaults.speed" type="number" min="0.25" max="4" step="0.05" /></label>
          <label>
            TTS provider instance id
            <input
              v-model="form.audio_defaults.tts_provider_instance_id"
              type="text"
              placeholder="instance id only — never a key"
            />
          </label>
          <label>Music profile <input v-model="form.audio_defaults.music_profile" type="text" /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Provider defaults (instance ids)</legend>
        <p class="hint">
          Instance references only. Credentials resolve at runtime from the provider
          instance store and never enter a Channel document.
        </p>
        <div class="grid-2">
          <label>Script <input v-model="form.provider_defaults.script" type="text" /></label>
          <label>TTS <input v-model="form.provider_defaults.tts" type="text" /></label>
          <label>Scene director <input v-model="form.provider_defaults.scene_director" type="text" /></label>
          <label>Image <input v-model="form.provider_defaults.image" type="text" /></label>
          <label>Video <input v-model="form.provider_defaults.video" type="text" /></label>
          <label>Review <input v-model="form.provider_defaults.review" type="text" /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Export defaults</legend>
        <div class="grid-2">
          <label>Aspect ratio <input v-model="form.export_defaults.aspect_ratio" type="text" /></label>
          <label>Resolution <input v-model="form.export_defaults.resolution" type="text" /></label>
          <label>FPS <input v-model="form.export_defaults.fps" type="number" min="1" max="120" /></label>
          <label>Profile <input v-model="form.export_defaults.profile" type="text" /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Captions</legend>
        <div class="grid-2">
          <label>Preset <input v-model="form.captions.preset" type="text" /></label>
          <label>Position <input v-model="form.captions.position" type="text" /></label>
          <label>Font treatment <input v-model="form.captions.font_treatment" type="text" /></label>
          <label>Animation <input v-model="form.captions.animation" type="text" /></label>
        </div>
      </fieldset>

      <div class="form-footer">
        <button type="submit" class="primary" :disabled="saving">
          {{ saving ? 'Saving…' : 'Save channel' }}
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.editor {
  max-width: 880px;
  margin: 0 auto;
  padding: 1.5rem 1.25rem 3rem;
  font-family: "Segoe UI", system-ui, sans-serif;
  color: #e8eaed;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.back {
  color: #8ab4f8;
  text-decoration: none;
  font-size: 0.9rem;
}

h1 {
  margin: 0.25rem 0 0.2rem;
  font-size: 1.5rem;
  font-weight: 650;
}

.meta-line {
  margin: 0;
  color: #9aa0a6;
  font-size: 0.85rem;
}

.meta-line code {
  font-family: ui-monospace, Consolas, monospace;
  background: #2d2e30;
  padding: 0.05rem 0.35rem;
  border-radius: 4px;
}

.actions {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
}

button {
  border: 1px solid #3c4043;
  background: #2d2e30;
  color: #e8eaed;
  border-radius: 8px;
  padding: 0.45rem 0.85rem;
  font-size: 0.9rem;
  cursor: pointer;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

button.primary {
  background: #8ab4f8;
  border-color: #8ab4f8;
  color: #202124;
  font-weight: 600;
}

button.ghost {
  background: transparent;
}

button.danger {
  color: #f28b82;
}

fieldset {
  border: 1px solid #2d2e30;
  border-radius: 12px;
  margin: 0 0 1rem;
  padding: 1rem 1.1rem 1.15rem;
  background: #1a1a1c;
}

legend {
  padding: 0 0.4rem;
  font-weight: 600;
  color: #fdd663;
  font-size: 0.9rem;
}

label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.85rem;
  color: #bdc1c6;
  margin-bottom: 0.65rem;
}

label.check {
  flex-direction: row;
  align-items: center;
  gap: 0.45rem;
}

input[type="text"],
input[type="number"],
input[type="file"],
select {
  background: #0f0f10;
  border: 1px solid #3c4043;
  border-radius: 8px;
  color: #e8eaed;
  padding: 0.45rem 0.6rem;
  font-size: 0.95rem;
}

.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.35rem 0.85rem;
}

.hint {
  color: #9aa0a6;
  font-size: 0.82rem;
  margin: 0 0 0.75rem;
  line-height: 1.4;
}

.hint code {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.78rem;
}

.logo-row {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}

.logo-preview {
  width: 120px;
  height: 120px;
  border-radius: 10px;
  border: 1px dashed #5f6368;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #0f0f10;
  color: #9aa0a6;
  font-size: 0.8rem;
  flex-shrink: 0;
}

.logo-preview img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.logo-controls {
  flex: 1;
  min-width: 220px;
}

.pattern-table {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 0.75rem;
}

.pattern-head,
.pattern-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 0.5rem;
  align-items: center;
}

.pattern-head {
  font-size: 0.75rem;
  color: #9aa0a6;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.pattern-actions {
  display: flex;
  gap: 0.2rem;
}

.pattern-actions button {
  padding: 0.25rem 0.45rem;
}

.error {
  color: #f28b82;
  background: #3c1f1e;
  border: 1px solid #5f3a38;
  border-radius: 8px;
  padding: 0.6rem 0.85rem;
}

.success {
  color: #81c995;
  background: #1e3a2a;
  border: 1px solid #2d5a3d;
  border-radius: 8px;
  padding: 0.6rem 0.85rem;
}

.form-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.5rem;
}

@media (max-width: 640px) {
  .grid-2,
  .pattern-head,
  .pattern-row {
    grid-template-columns: 1fr;
  }
}
</style>

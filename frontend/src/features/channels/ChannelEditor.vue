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
/* Channel editor — the prototype's `.ch-body` section stack. Each fieldset
   is a raised, lit panel; every control is the recessed field primitive with
   a mono/uppercase eyebrow; the accent duotone is reserved for the primary
   action and the focus ring. */

.editor {
  max-width: 880px;
  margin: 0 auto;
  padding: 24px 20px 48px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.back {
  display: inline-block;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.3px;
  color: var(--muted);
  text-decoration: none;
  transition: color 0.14s;
}

.back:hover {
  color: var(--accent);
}

h1 {
  margin: 6px 0 5px;
  font-family: var(--display);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: var(--text);
}

.meta-line {
  margin: 0;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* A recessed well for the identity readout. */
.meta-line code {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  padding: 1px 6px;
  border-radius: 5px;
}

.actions {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  flex-shrink: 0;
}

/* The template carries bare .primary / .ghost / .danger rather than .btn,
   so the shared button primitive is restated here on the element itself. */
button {
  border: 1px solid var(--line);
  background: var(--panel-grad);
  color: var(--text);
  border-radius: var(--r-s);
  padding: 9px 14px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  white-space: nowrap;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.16s, border-color 0.16s, color 0.14s,
    box-shadow 0.16s, transform 0.12s var(--ease-spring);
}

button:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  transform: translateY(-1px);
  box-shadow: var(--hairline-top), 0 4px 12px -4px rgba(0, 0, 0, 0.5);
}

button:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--hairline-top), inset 0 2px 4px rgba(0, 0, 0, 0.35);
}

button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

button.primary {
  background: var(--accent-grad);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast);
}

button.primary:hover:not(:disabled) {
  filter: brightness(1.07) saturate(1.05);
  border-color: transparent;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
}

button.ghost {
  background: transparent;
  box-shadow: none;
}

button.ghost:hover:not(:disabled) {
  background: var(--panel);
  box-shadow: var(--hairline-top);
}

/* Ordered after .ghost so the danger wash wins on the `.danger.ghost` rows. */
button.danger {
  color: var(--fail);
  border-color: var(--fail-line);
}

button.danger:hover:not(:disabled) {
  background: var(--fail-dim);
  border-color: var(--fail-line-2);
}

/* A section is a raised panel lit from above. */
fieldset {
  border: 1px solid var(--line);
  border-radius: var(--r);
  margin: 0 0 16px;
  padding: 16px 18px 18px;
  background: var(--panel-grad);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  transition: border-color 0.18s;
}

fieldset:hover {
  border-color: var(--line-2);
}

legend {
  padding: 0 6px;
  font-family: var(--display);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.2px;
  color: var(--text);
}

/* The field eyebrow. The control is a sibling text node's peer inside the
   same <label>, so `text-transform` and `letter-spacing` are reset on the
   controls below — otherwise typed values would render uppercased. */
label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 12px;
}

label.check {
  flex-direction: row;
  align-items: center;
  gap: 9px;
  font-family: var(--body);
  font-size: 13px;
  letter-spacing: 0.1px;
  text-transform: none;
  color: var(--text-2);
}

input[type="checkbox"] {
  width: 15px;
  height: 15px;
  accent-color: var(--accent);
  cursor: pointer;
  flex: none;
}

input[type="text"],
input[type="number"],
input[type="file"],
select {
  width: 100%;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
  letter-spacing: 0.1px;
  text-transform: none;
  padding: 9px 11px;
  transition: border-color 0.16s, box-shadow 0.16s;
}

select {
  cursor: pointer;
}

input::placeholder {
  color: var(--faint);
}

input[type="text"]:focus,
input[type="number"]:focus,
input[type="file"]:focus,
select:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

input[type="file"] {
  padding: 7px 9px;
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
}

input[type="file"]:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 14px;
}

.hint {
  color: var(--muted);
  font-size: 12px;
  margin: 0 0 14px;
  line-height: 1.5;
}

.hint code {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0;
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  padding: 1px 5px;
  border-radius: 5px;
}

.logo-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.logo-preview {
  width: 120px;
  height: 120px;
  border-radius: var(--r);
  border: 1px dashed var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: var(--bg-2);
  box-shadow: var(--hairline-top);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
  flex-shrink: 0;
  transition: border-color 0.14s, background 0.14s;
}

.logo-preview:hover {
  border-color: var(--accent-line-2);
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
  gap: 6px;
  margin-bottom: 14px;
}

.pattern-head,
.pattern-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 8px;
  align-items: center;
}

.pattern-head {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.8px;
}

.pattern-actions {
  display: flex;
  gap: 4px;
}

.pattern-actions button {
  padding: 0;
  width: 30px;
  height: 32px;
  flex: none;
  font-family: var(--mono);
  font-size: 12px;
  border-radius: 6px;
}

.pattern-actions button.ghost:not(.danger) {
  color: var(--muted);
}

.pattern-actions button.ghost:not(.danger):hover:not(:disabled) {
  color: var(--text);
}

.error {
  background: var(--fail-dim);
  border: 1px solid var(--fail-line);
  border-radius: var(--r-s);
  color: var(--fail-text);
  padding: 11px 13px;
  font-size: 12.5px;
  line-height: 1.55;
  margin-bottom: 12px;
}

.success {
  background: var(--ok-dim);
  border: 1px solid var(--ok-line);
  border-radius: var(--r-s);
  color: var(--ok);
  padding: 11px 13px;
  font-size: 12.5px;
  line-height: 1.55;
  margin-bottom: 12px;
}

.form-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

@media (max-width: 640px) {
  .grid-2,
  .pattern-head,
  .pattern-row {
    grid-template-columns: 1fr;
  }
}
</style>

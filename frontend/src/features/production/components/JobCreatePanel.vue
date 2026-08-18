<script setup>
/**
 * Job creation (steps 2.5 and 4.1).
 *
 * Channel picker, Script stage source mode (topic / idea / paste / manual /
 * automatic), existing Studio-script multi-select, workflow choice, and
 * execution mode. Provider UI appears only when the selected source mode
 * needs a script provider (§6).
 */
import { computed, onMounted, ref, watch } from 'vue'

import { listChannels } from '@/features/channels/api.js'
import { listScripts } from '@/features/script/api.js'

import {
  createJob,
  createJobBatch,
  getJobDefaults,
  listWorkflows,
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
  /** Prefill workflow id when the Production page already selected one. */
  initialWorkflowId: { type: String, default: '' },
  /** When true, start the Job immediately after create. */
  autoStart: { type: Boolean, default: true },
})

const emit = defineEmits(['created', 'started', 'cancel'])

const channels = ref([])
const workflows = ref([])
const sourceModes = ref([...SOURCE_MODE_CATALOG])
const executionModes = ref([...EXECUTION_MODE_CATALOG])

const channelId = ref('')
const workflowId = ref('')
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
  return fields.includes('topic')
})

const showIdea = computed(() => {
  const fields = selectedSource.value?.input_fields || []
  return fields.includes('idea')
})

const showPaste = computed(() => {
  const fields = selectedSource.value?.input_fields || []
  return fields.includes('pasted_script')
})

const canSubmit = computed(() => {
  if (submitting.value || loading.value) return false
  if (!channelId.value) return false
  if (sourceKind.value === 'studio') return selectedScriptIds.value.length > 0
  return validateJobSource(buildSource()).length === 0
})

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
  const draft = {
    channel_id: channelId.value,
    execution_mode: executionMode.value,
    source: buildSource(),
  }
  if (workflowId.value) draft.workflow_id = workflowId.value
  return draft
}

async function loadCatalogs() {
  loading.value = true
  error.value = ''
  try {
    const [defaults, channelData, workflowData] = await Promise.all([
      getJobDefaults().catch(() => null),
      listChannels({ limit: 500, seed: true }),
      listWorkflows({ limit: 200 }),
    ])
    if (defaults?.source_modes?.length) {
      sourceModes.value = defaults.source_modes
    }
    if (defaults?.execution_modes?.length) {
      executionModes.value = defaults.execution_modes
    }
    if (defaults?.defaults?.execution_mode) {
      executionMode.value = defaults.defaults.execution_mode
    }
    if (defaults?.defaults?.source?.mode) {
      sourceMode.value = defaults.defaults.source.mode
    }
    channels.value = channelData.channels || []
    workflows.value = workflowData.workflows || workflowData.items || []
    if (!channelId.value && channels.value.length === 1) {
      channelId.value = channels.value[0].id
    }
    if (!workflowId.value && props.initialWorkflowId) {
      workflowId.value = props.initialWorkflowId
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
    if (sourceKind.value === 'studio') {
      const batch = {
        channel_id: channelId.value,
        script_ids: [...selectedScriptIds.value],
        execution_mode: executionMode.value,
      }
      if (workflowId.value) batch.workflow_id = workflowId.value
      const result = await createJobBatch(batch)
      const jobs = result.jobs || []
      emit('created', { job: jobs[0] || null, jobs, batch: result })
      return
    }
    const { job } = await createJob(buildDraft())
    emit('created', { job })
    if (props.autoStart) {
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

watch(
  () => props.initialWorkflowId,
  (id) => {
    if (id && !workflowId.value) workflowId.value = id
  },
)

watch([sourceKind, channelId], () => {
  void loadStudioScripts()
})

onMounted(() => {
  void loadCatalogs()
})

// Keep defaultJobDraft referenced so tree-shaking never drops the helper.
void defaultJobDraft
</script>

<template>
  <section class="job-create" aria-labelledby="job-create-title">
    <header class="create-head">
      <div>
        <p class="step-tag">Step 0</p>
        <h2 id="job-create-title">Create Job</h2>
        <p class="lede">
          Pick a Channel, Script input mode, workflow, and execution mode.
          Paste and Manual need no script provider.
        </p>
      </div>
      <button type="button" class="ghost" :disabled="submitting" @click="emit('cancel')">
        Close
      </button>
    </header>

    <p v-if="loading" class="muted">Loading channels and workflows…</p>

    <form v-else class="create-form" @submit.prevent="onSubmit">
      <label class="field">
        <span class="field-label">Channel</span>
        <select v-model="channelId" required :disabled="submitting">
          <option value="">Select a channel…</option>
          <option v-for="ch in channels" :key="ch.id" :value="ch.id">
            {{ ch.name || ch.id }}
          </option>
        </select>
      </label>

      <label class="field">
        <span class="field-label">Script source</span>
        <select v-model="sourceKind" data-testid="script-source-kind" :disabled="submitting">
          <option value="input">New script input</option>
          <option value="studio">Existing Studio scripts</option>
        </select>
        <span class="field-hint">Select several Studio scripts to create one queued Job for each.</span>
      </label>

      <fieldset v-if="sourceKind === 'studio'" class="field studio-fieldset">
        <legend class="field-label">Studio scripts</legend>
        <p v-if="scriptsLoading" class="muted">Loading scripts...</p>
        <p v-else-if="!studioScripts.length" class="provider-note">
          This Channel has no Studio scripts yet.
        </p>
        <div v-else class="s1-list" data-testid="studio-script-list">
          <label v-for="script in studioScripts" :key="script.id" class="s1-row" :class="{ sel: selectedScriptIds.includes(script.id) }">
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
        <span class="field-hint">
          {{ selectedScriptIds.length }} selected. Jobs stay queued until you run the batch.
        </span>
      </fieldset>

      <fieldset v-if="sourceKind === 'input'" class="field mode-fieldset">
        <legend class="field-label">Script stage mode</legend>
        <div class="segmented mode-grid">
          <label
            v-for="mode in sourceModes"
            :key="mode.mode"
            class="seg-opt"
            :class="{ sel: sourceMode === mode.mode }"
          >
            <input
              v-model="sourceMode"
              type="radio"
              name="source_mode"
              :value="mode.mode"
              :disabled="submitting"
            />
            <span class="txt">
              <span class="t">{{ mode.label }}</span>
              <span class="d">{{ mode.description }}</span>
              <span
                class="mode-badge"
                :data-provider="mode.provider_required ? 'yes' : 'no'"
              >
                {{ mode.provider_required ? 'Provider required' : 'No provider' }}
              </span>
            </span>
          </label>
        </div>
      </fieldset>

      <label v-if="sourceKind === 'input' && showTopic" class="field">
        <span class="field-label">Topic</span>
        <input
          v-model="topic"
          type="text"
          maxlength="4000"
          placeholder="e.g. Marcus Aurelius on control of the mind"
          :disabled="submitting"
        />
      </label>

      <label v-if="sourceKind === 'input' && showIdea" class="field">
        <span class="field-label">Idea</span>
        <textarea
          v-model="idea"
          rows="4"
          maxlength="4000"
          placeholder="Rough premise the script provider will expand…"
          :disabled="submitting"
        />
      </label>

      <label v-if="sourceKind === 'input' && showPaste" class="field">
        <span class="field-label">
          {{ sourceMode === 'manual' ? 'Script text' : 'Pasted script' }}
        </span>
        <textarea
          v-model="pastedScript"
          rows="8"
          maxlength="10000"
          placeholder="Final narration text — no AI generation needed."
          :disabled="submitting"
        />
        <span class="field-hint">{{ pastedScript.length }} / 10000</span>
      </label>

      <div v-if="sourceKind === 'input' && providerRequired" class="provider-note" role="status">
        This mode uses a script provider from the Channel defaults. Configure
        providers under the Channel editor if generation fails.
      </div>
      <div v-else-if="sourceKind === 'input'" class="provider-note local" role="status">
        Paste / Manual run through Script Input only — no script provider is
        configured or required.
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
          <label class="field">
            <span class="field-label">
              Remove silence
              <em v-if="removeSilenceOverride === 'inherit'">Inherited</em>
            </span>
            <select v-model="removeSilenceOverride" :disabled="submitting || !channelId">
              <option value="inherit">
                Inherited ({{ inheritedRemoveSilence ? 'On' : 'Off' }})
              </option>
              <option value="on">On</option>
              <option value="off">Off</option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">
              Speed
              <em v-if="speedOverride === ''">Inherited</em>
            </span>
            <select v-model="speedOverride" :disabled="submitting || !channelId">
              <option value="">Inherited ({{ inheritedSpeed }}×)</option>
              <option v-for="speed in [0.9, 1, 1.1, 1.15, 1.25, 1.5]" :key="speed" :value="String(speed)">
                {{ speed }}×
              </option>
            </select>
          </label>
        </div>
        <button
          v-if="removeSilenceOverride !== 'inherit' || speedOverride !== ''"
          type="button"
          class="ghost reset-processing"
          @click="removeSilenceOverride = 'inherit'; speedOverride = ''"
        >
          Reset to Channel defaults
        </button>
      </fieldset>

      <label class="field">
        <span class="field-label">Execution mode</span>
        <select v-model="executionMode" :disabled="submitting">
          <option
            v-for="mode in executionModes"
            :key="mode.mode"
            :value="mode.mode"
          >
            {{ mode.label }}
          </option>
        </select>
        <span class="field-hint">
          {{
            executionModes.find((m) => m.mode === executionMode)?.description
              || ''
          }}
        </span>
      </label>

      <label class="field">
        <span class="field-label">Workflow</span>
        <select v-model="workflowId" :disabled="submitting">
          <option value="">Channel default workflow</option>
          <option
            v-for="wf in workflows"
            :key="wf.workflow_id || wf.id"
            :value="wf.workflow_id || wf.id"
          >
            {{ wf.name || wf.workflow_id || wf.id }}
          </option>
        </select>
      </label>

      <ul v-if="fieldErrors.length" class="errors" role="alert">
        <li v-for="(msg, idx) in fieldErrors" :key="idx">{{ msg }}</li>
      </ul>
      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <div class="form-actions">
        <button type="button" class="ghost" :disabled="submitting" @click="emit('cancel')">
          Cancel
        </button>
        <button type="submit" class="primary" :disabled="!canSubmit">
          {{
            submitting
              ? 'Creating…'
              : sourceKind === 'studio'
                ? `Queue ${selectedScriptIds.length} Job${selectedScriptIds.length === 1 ? '' : 's'}`
                : autoStart ? 'Create & Run' : 'Create Job'
          }}
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
/* Raised panel — lit from above by the top hairline. */
.job-create {
  margin-bottom: 20px;
  padding: 18px 18px 20px;
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.create-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.step-tag {
  margin: 0 0 6px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: var(--accent);
}

h2 {
  margin: 0 0 5px;
  font-family: var(--display);
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: var(--text);
}

.lede {
  margin: 0;
  max-width: 560px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--muted);
}

.create-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Micro-label — mono, uppercase, tracked out. */
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

select,
input[type='text'],
textarea {
  width: 100%;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--text);
  border-radius: var(--r-s);
  padding: 9px 11px;
  font-family: var(--body);
  font-size: 13px;
  transition: border-color 0.16s, box-shadow 0.16s;
}

select {
  cursor: pointer;
}

select:focus,
input[type='text']:focus,
textarea:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

input[type='text']::placeholder,
textarea::placeholder {
  color: var(--faint);
}

select:disabled,
input[type='text']:disabled,
textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

textarea {
  resize: vertical;
  min-height: 96px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.55;
}

.mode-fieldset {
  border: 0;
  margin: 0;
  padding: 0;
  min-width: 0;
}

.narration-fieldset {
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--bg-2);
}

.studio-fieldset {
  margin: 0;
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--bg-2);
}

/* The prototype's script picker (step 6.3). Its rows are single-select there;
   here one Job per script is the point, so the row carries a checkbox and
   `.sel` follows the box rather than a cursor. */
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

.s1-row:hover {
  border-color: var(--line-2);
  background: var(--panel-2);
}

.s1-row.sel {
  border-color: var(--accent-line);
  background: var(--accent-wash);
}

.s1-row .top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.s1-row .title {
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

@media (prefers-reduced-motion: reduce) {
  .s1-row { transition: none; }
}

.narration-source { margin: 0 0 10px; }

.narration-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.field-label em {
  margin-left: 6px;
  color: var(--accent);
  font-style: normal;
  letter-spacing: 0;
  text-transform: lowercase;
}

.reset-processing { align-self: flex-start; margin-top: 8px; }

/* The options themselves are the shared `.segmented` / `.seg-opt` primitive
   (step 6.1); only the track's column count is this panel's business. */
.mode-grid {
  grid-template-columns: repeat(auto-fill, minmax(184px, 1fr));
  gap: 9px;
}

.mode-badge {
  align-self: flex-start;
  margin-top: 6px;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  padding: 3px 9px;
  border-radius: 20px;
  color: var(--queue);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line);
}

.mode-badge[data-provider='yes'] {
  color: var(--warn);
  background: var(--warn-dim);
  box-shadow: inset 0 0 0 1px var(--warn-line);
}

.mode-badge[data-provider='no'] {
  color: var(--ok);
  background: var(--ok-dim);
  box-shadow: inset 0 0 0 1px var(--ok-line);
}

/* Advisory banners: status wash + status hairline. */
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

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  margin-top: 4px;
}

/* Secondary button. */
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-grad);
  color: var(--text);
  border-radius: var(--r-s);
  padding: 9px 14px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
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

/* Primary button. */
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
  background: var(--accent-grad);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
}

/* Ghost button. */
button.ghost {
  background: transparent;
  box-shadow: none;
}

button.ghost:hover:not(:disabled) {
  background: var(--panel);
  box-shadow: var(--hairline-top);
}

button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
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

.muted {
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 640px) {
  .narration-grid { grid-template-columns: 1fr; }
}
</style>

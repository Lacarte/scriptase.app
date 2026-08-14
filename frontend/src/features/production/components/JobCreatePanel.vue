<script setup>
/**
 * Step 0 — Job creation (step 2.5).
 *
 * Channel picker, Script stage source mode (topic / idea / paste / manual /
 * automatic), workflow choice, and execution mode. Provider UI appears only
 * when the selected source mode needs a script provider (§6).
 */
import { computed, onMounted, ref, watch } from 'vue'

import { listChannels } from '@/features/channels/api.js'

import {
  createJob,
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
const topic = ref('')
const idea = ref('')
const pastedScript = ref('')

const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const fieldErrors = ref([])

const selectedSource = computed(
  () => sourceModes.value.find((m) => m.mode === sourceMode.value) || null,
)

const providerRequired = computed(() => sourceModeRequiresProvider(sourceMode.value))

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
  return validateJobSource(buildSource()).length === 0
})

function buildSource() {
  return {
    mode: sourceMode.value,
    topic: topic.value,
    idea: idea.value,
    pasted_script: pastedScript.value,
    references: [],
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
  fieldErrors.value = validateJobSource(buildSource())
  if (!channelId.value) {
    fieldErrors.value = ['Channel is required', ...fieldErrors.value]
  }
  if (fieldErrors.value.length || submitting.value) return

  submitting.value = true
  error.value = ''
  try {
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

      <fieldset class="field mode-fieldset">
        <legend class="field-label">Script stage mode</legend>
        <div class="mode-grid">
          <label
            v-for="mode in sourceModes"
            :key="mode.mode"
            class="mode-card"
            :class="{ selected: sourceMode === mode.mode }"
          >
            <input
              v-model="sourceMode"
              type="radio"
              name="source_mode"
              :value="mode.mode"
              :disabled="submitting"
            />
            <span class="mode-title">{{ mode.label }}</span>
            <span class="mode-desc">{{ mode.description }}</span>
            <span
              class="mode-badge"
              :data-provider="mode.provider_required ? 'yes' : 'no'"
            >
              {{ mode.provider_required ? 'Provider required' : 'No provider' }}
            </span>
          </label>
        </div>
      </fieldset>

      <label v-if="showTopic" class="field">
        <span class="field-label">Topic</span>
        <input
          v-model="topic"
          type="text"
          maxlength="4000"
          placeholder="e.g. Marcus Aurelius on control of the mind"
          :disabled="submitting"
        />
      </label>

      <label v-if="showIdea" class="field">
        <span class="field-label">Idea</span>
        <textarea
          v-model="idea"
          rows="4"
          maxlength="4000"
          placeholder="Rough premise the script provider will expand…"
          :disabled="submitting"
        />
      </label>

      <label v-if="showPaste" class="field">
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

      <div v-if="providerRequired" class="provider-note" role="status">
        This mode uses a script provider from the Channel defaults. Configure
        providers under the Channel editor if generation fails.
      </div>
      <div v-else class="provider-note local" role="status">
        Paste / Manual run through Script Input only — no script provider is
        configured or required.
      </div>

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

      <ul v-if="fieldErrors.length" class="errors" role="alert">
        <li v-for="(msg, idx) in fieldErrors" :key="idx">{{ msg }}</li>
      </ul>
      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <div class="form-actions">
        <button type="button" class="ghost" :disabled="submitting" @click="emit('cancel')">
          Cancel
        </button>
        <button type="submit" class="primary" :disabled="!canSubmit">
          {{ submitting ? 'Starting…' : autoStart ? 'Create & Run' : 'Create Job' }}
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.job-create {
  border: 1px solid var(--border, #2a3a4e);
  border-radius: 12px;
  background: var(--bg-surface, #121820);
  padding: 1.1rem 1.15rem 1.25rem;
  margin-bottom: 1.25rem;
}

.create-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  margin-bottom: 1rem;
}

.step-tag {
  margin: 0 0 0.2rem;
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent, #8ab4f8);
  font-weight: 600;
}

h2 {
  margin: 0 0 0.3rem;
  font-size: 1.15rem;
  font-weight: 650;
  font-family: var(--font-display, system-ui, sans-serif);
}

.lede {
  margin: 0;
  color: var(--text-secondary, #8899aa);
  font-size: 0.88rem;
  line-height: 1.4;
  max-width: 36rem;
}

.create-form {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.field-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-secondary, #9aa0a6);
}

.field-hint {
  font-size: 0.75rem;
  color: var(--text-muted, #6b7f93);
}

select,
input[type='text'],
textarea {
  border: 1px solid var(--border-hover, #2a3a4e);
  background: var(--bg-darkest, #0a0e13);
  color: var(--text, #e8edf3);
  border-radius: 8px;
  padding: 0.5rem 0.65rem;
  font: inherit;
  font-size: 0.9rem;
}

textarea {
  resize: vertical;
  min-height: 6rem;
  font-family: var(--font-mono, ui-monospace, monospace);
  line-height: 1.45;
}

.mode-fieldset {
  border: 0;
  margin: 0;
  padding: 0;
  min-width: 0;
}

.mode-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(11.5rem, 1fr));
  gap: 0.55rem;
}

.mode-card {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  border: 1px solid var(--border, #2a3a4e);
  border-radius: 10px;
  padding: 0.65rem 0.7rem;
  cursor: pointer;
  background: var(--bg-darkest, #0a0e13);
  position: relative;
}

.mode-card.selected {
  border-color: var(--accent, #8ab4f8);
  box-shadow: 0 0 0 1px var(--accent, #8ab4f8);
}

.mode-card input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.mode-title {
  font-weight: 600;
  font-size: 0.88rem;
}

.mode-desc {
  font-size: 0.74rem;
  color: var(--text-secondary, #8899aa);
  line-height: 1.35;
}

.mode-badge {
  margin-top: 0.2rem;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--text-muted, #6b7f93);
}

.mode-badge[data-provider='yes'] {
  color: #f0c674;
}

.mode-badge[data-provider='no'] {
  color: #7dcea0;
}

.provider-note {
  border-radius: 8px;
  padding: 0.55rem 0.7rem;
  font-size: 0.82rem;
  line-height: 1.4;
  background: rgba(240, 198, 116, 0.08);
  border: 1px solid rgba(240, 198, 116, 0.25);
  color: var(--text-secondary, #c5cdd6);
}

.provider-note.local {
  background: rgba(125, 206, 160, 0.08);
  border-color: rgba(125, 206, 160, 0.25);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.55rem;
  margin-top: 0.25rem;
}

button {
  border: 1px solid var(--border-hover, #2a3a4e);
  background: var(--bg-surface, #161d2a);
  color: var(--text, #e8edf3);
  border-radius: 8px;
  padding: 0.45rem 0.9rem;
  font-size: 0.9rem;
  cursor: pointer;
}

button.primary {
  background: var(--accent, #3b6fd9);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
}

button.ghost {
  background: transparent;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.errors {
  margin: 0;
  padding-left: 1.1rem;
  color: #f28b82;
  font-size: 0.85rem;
}

.error {
  margin: 0;
  color: #f28b82;
  font-size: 0.88rem;
}

.muted {
  color: var(--text-muted, #6b7f93);
  font-size: 0.9rem;
}
</style>

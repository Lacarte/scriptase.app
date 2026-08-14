<script setup>
/**
 * Per-port input source picker for standalone / test runs (step 4.1 / §9.1).
 *
 * Sources: current Job, previous Job, artifact library, managed upload,
 * manual value, sample stub. ``run_deps`` is a mode switch handled by the
 * parent (use node_with_deps), not a payload.
 */
import { computed, ref, watch } from 'vue'
import {
  INPUT_SOURCES,
  listArtifacts,
  makeBinding,
  uploadArtifact,
} from '../api.js'

const props = defineProps({
  /** Port definition from the registry: { id, type, required, multiple? } */
  port: { type: Object, required: true },
  /** Current binding object, or null */
  modelValue: { type: Object, default: null },
  /** Job id used for current_job resolution */
  currentJobId: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

const source = ref(props.modelValue?.source || 'sample')
const artifactId = ref(props.modelValue?.artifact_id || '')
const jobId = ref(props.modelValue?.job_id || props.currentJobId || '')
const sceneId = ref(props.modelValue?.scene_id || '')
const manualText = ref(
  props.modelValue?.value != null
    ? typeof props.modelValue.value === 'string'
      ? props.modelValue.value
      : JSON.stringify(props.modelValue.value, null, 2)
    : '',
)
const library = ref([])
const busy = ref(false)
const error = ref('')

const kindForPort = computed(() => {
  const map = {
    script: 'script',
    audio_file: 'audio',
    tts_metadata: 'audio',
    alignment: 'alignment',
    segments: 'segments',
    scenes: 'scene_spec',
    image_prompts: 'scene_spec',
    storyboard_images: 'image',
    animation_assets: 'video',
    captions: 'captions',
    music_track: 'music',
    editor_project: 'timeline',
    video_file: 'export',
  }
  return map[props.port?.type] || ''
})

const sourceOptions = computed(() => [
  { value: 'sample', label: 'Sample stub' },
  { value: 'current_job', label: 'Current Job' },
  { value: 'job', label: 'Previous Job' },
  { value: 'library', label: 'Artifact library' },
  { value: 'upload', label: 'Managed upload' },
  { value: 'manual', label: 'Manual value' },
  { value: 'run_deps', label: 'Run dependencies' },
])

async function refreshLibrary() {
  error.value = ''
  try {
    const data = await listArtifacts({
      kind: kindForPort.value || undefined,
      jobId: source.value === 'job' || source.value === 'current_job'
        ? (jobId.value || undefined)
        : undefined,
      limit: 50,
      includeSuperseded: false,
    })
    library.value = data.artifacts || []
  } catch (err) {
    library.value = []
    error.value = err?.message || 'Could not load artifacts'
  }
}

watch(
  () => [source.value, jobId.value, kindForPort.value],
  () => {
    if (['library', 'job', 'current_job', 'upload'].includes(source.value)) {
      refreshLibrary()
    }
  },
  { immediate: true },
)

function emitBinding() {
  if (source.value === 'sample') {
    emit('update:modelValue', makeBinding('sample', {
      port_type: props.port?.type,
    }))
    return
  }
  if (source.value === 'run_deps') {
    emit('update:modelValue', makeBinding('run_deps'))
    return
  }
  if (source.value === 'manual') {
    let value = manualText.value
    try {
      value = JSON.parse(manualText.value)
    } catch {
      /* keep as string for script/text ports */
    }
    emit('update:modelValue', makeBinding('manual', { value }))
    return
  }
  if (source.value === 'current_job') {
    emit('update:modelValue', makeBinding('current_job', {
      job_id: jobId.value || props.currentJobId || undefined,
      artifact_id: artifactId.value || undefined,
      kind: kindForPort.value || undefined,
      scene_id: sceneId.value || undefined,
      port_type: props.port?.type,
    }))
    return
  }
  if (source.value === 'job') {
    emit('update:modelValue', makeBinding('job', {
      job_id: jobId.value,
      artifact_id: artifactId.value || undefined,
      kind: kindForPort.value || undefined,
      scene_id: sceneId.value || undefined,
      port_type: props.port?.type,
    }))
    return
  }
  // library / upload
  emit('update:modelValue', makeBinding(source.value, {
    artifact_id: artifactId.value,
    port_type: props.port?.type,
  }))
}

watch(
  [source, artifactId, jobId, sceneId, manualText],
  () => emitBinding(),
  { deep: true },
)

async function onFileChosen(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  busy.value = true
  error.value = ''
  try {
    const data = await uploadArtifact(file, {
      kind: kindForPort.value || undefined,
      jobId: props.currentJobId || undefined,
      sceneId: sceneId.value || undefined,
    })
    artifactId.value = data.artifact?.id || ''
    source.value = 'upload'
    await refreshLibrary()
    emitBinding()
  } catch (err) {
    error.value = err?.message || 'Upload failed'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="input-picker">
    <div class="picker-row">
      <label class="picker-label">{{ port.id }}</label>
      <span v-if="port.required" class="picker-badge">required</span>
      <span class="picker-type">{{ port.type }}</span>
    </div>

    <select v-model="source" class="picker-select" aria-label="Input source">
      <option v-for="opt in sourceOptions" :key="opt.value" :value="opt.value">
        {{ opt.label }}
      </option>
    </select>

    <div v-if="source === 'job' || source === 'current_job'" class="picker-fields">
      <input
        v-model="jobId"
        class="picker-input"
        type="text"
        :placeholder="source === 'current_job' ? 'Current job id' : 'Job id (job_XXXXXX)'"
      />
      <input
        v-model="sceneId"
        class="picker-input"
        type="text"
        placeholder="Scene id (optional)"
      />
    </div>

    <div v-if="['library', 'job', 'current_job', 'upload'].includes(source)" class="picker-fields">
      <select v-model="artifactId" class="picker-select" aria-label="Artifact">
        <option value="">Select artifact…</option>
        <option v-for="item in library" :key="item.id" :value="item.id">
          {{ item.id }} · {{ item.kind }} v{{ item.version }}
          <template v-if="item.scene_id"> · {{ item.scene_id }}</template>
          — {{ item.path }}
        </option>
      </select>
    </div>

    <div v-if="source === 'upload'" class="picker-fields">
      <label class="picker-file">
        <input type="file" :disabled="busy" @change="onFileChosen" />
        {{ busy ? 'Uploading…' : 'Choose managed file' }}
      </label>
    </div>

    <div v-if="source === 'manual'" class="picker-fields">
      <textarea
        v-model="manualText"
        class="picker-textarea"
        rows="4"
        placeholder="JSON or plain text"
      />
    </div>

    <p v-if="source === 'run_deps'" class="picker-hint">
      Parent will run this node with its upstream dependencies instead of isolation.
    </p>
    <p v-if="source === 'sample'" class="picker-hint">
      Uses the bundled sample fixture for <code>{{ port.type }}</code>.
    </p>
    <p v-if="error" class="picker-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.input-picker {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--border, #2a3140);
  border-radius: 8px;
  background: var(--surface-2, #12161f);
}
.picker-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
}
.picker-label {
  font-weight: 600;
  color: var(--text, #e8ecf4);
}
.picker-badge {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #f0b429;
}
.picker-type {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--muted, #8b93a7);
  font-family: ui-monospace, monospace;
}
.picker-select,
.picker-input,
.picker-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border, #2a3140);
  border-radius: 6px;
  background: var(--surface, #0d1118);
  color: var(--text, #e8ecf4);
  font-size: 0.82rem;
  padding: 0.35rem 0.5rem;
}
.picker-fields {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.picker-file {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  cursor: pointer;
  color: var(--accent, #6ea8fe);
}
.picker-file input {
  max-width: 100%;
}
.picker-hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--muted, #8b93a7);
}
.picker-error {
  margin: 0;
  font-size: 0.78rem;
  color: #f87171;
}
</style>

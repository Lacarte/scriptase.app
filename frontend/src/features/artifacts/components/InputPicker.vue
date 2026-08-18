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
  gap: 7px;
  padding: 10px 11px;
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  background: var(--bg-2);
  box-shadow: var(--hairline-top);
}
.picker-row {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
}
.picker-label {
  font-weight: 600;
  color: var(--text);
}
.picker-badge {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 4px 10px;
  border-radius: 20px;
  color: var(--warn);
  background: var(--warn-dim);
  box-shadow: inset 0 0 0 1px var(--warn-line);
}
.picker-type {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}
.picker-select,
.picker-input,
.picker-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel);
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
  padding: 9px 11px;
}
.picker-textarea {
  line-height: 1.55;
  resize: vertical;
}
.picker-select {
  cursor: pointer;
}
.picker-select:focus,
.picker-input:focus,
.picker-textarea:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}
.picker-input::placeholder,
.picker-textarea::placeholder {
  color: var(--faint);
}
.picker-fields {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.picker-file {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  cursor: pointer;
  color: var(--accent);
}
.picker-file input {
  max-width: 100%;
}
.picker-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--muted);
}
.picker-hint code {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
}
.picker-error {
  margin: 0;
  font-size: 12.5px;
  color: var(--fail);
}
</style>

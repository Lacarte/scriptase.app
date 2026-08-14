<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/shared/api/client.js'

/**
 * Managed media picker for `media_asset` fields (step 2.3).
 * Value shape: {ref, filename, url} — a managed reference into
 * output/branding/, never a raw filesystem path.
 */
const props = defineProps({
  field: { type: Object, required: true },
  value: { default: null },
})
const emit = defineEmits(['update'])

const fileInput = ref(null)
const existing = ref([])
const busy = ref(false)
const error = ref('')

async function refreshExisting() {
  try {
    const data = await api.get('/api/workflow/branding')
    existing.value = data.assets || []
  } catch {
    existing.value = []
  }
}

onMounted(refreshExisting)

async function onFileChosen(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (file.size > 5 * 1024 * 1024) {
    error.value = 'Logo exceeds the 5 MB limit'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/workflow/branding', { method: 'POST', body: form })
    const data = await res.json().catch(() => null)
    if (!res.ok) {
      throw new Error(data?.error?.message || `Upload failed (${res.status})`)
    }
    emit('update', data.asset)
    await refreshExisting()
  } catch (err) {
    error.value = err?.message || 'Upload failed'
  } finally {
    busy.value = false
  }
}

function onPickExisting(event) {
  const pickedRef = event.target.value
  event.target.value = ''
  if (!pickedRef) return
  const asset = existing.value.find((a) => a.ref === pickedRef)
  if (asset) emit('update', asset)
}
</script>

<template>
  <div class="media-field">
    <div v-if="value?.url" class="media-preview">
      <img :src="value.url" :alt="value.filename" />
      <span class="media-name" :title="value.filename">{{ value.filename }}</span>
      <button class="media-btn danger" title="Remove logo" @click="emit('update', null)">✕</button>
    </div>

    <div class="media-actions">
      <button class="media-btn" :disabled="busy" @click="fileInput?.click()">
        {{ busy ? 'Uploading…' : 'Upload' }}
      </button>
      <select v-if="existing.length" class="media-select" @change="onPickExisting">
        <option value="">Pick existing…</option>
        <option v-for="asset in existing" :key="asset.ref" :value="asset.ref">
          {{ asset.filename }}
        </option>
      </select>
      <input
        ref="fileInput"
        class="media-file-input"
        type="file"
        :accept="(field.accept || []).map((e) => `.${e}`).join(',')"
        @change="onFileChosen"
      />
    </div>

    <span v-if="error" class="media-error">{{ error }}</span>
  </div>
</template>

<style scoped>
.media-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.media-preview {
  display: flex;
  align-items: center;
  gap: 8px;
}

.media-preview img {
  width: 44px;
  height: 44px;
  object-fit: contain;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-dark);
}

.media-name {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.media-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.media-btn {
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  padding: 5px 10px;
  cursor: pointer;
}

.media-btn:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.media-btn.danger:hover {
  color: #f87171;
  border-color: #f87171;
}

.media-select {
  flex: 1;
  min-width: 0;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 7px;
  color: var(--text);
  font-size: 11px;
  padding: 5px 8px;
}

.media-file-input {
  display: none;
}

.media-error {
  font-size: 11px;
  color: #f87171;
}
</style>

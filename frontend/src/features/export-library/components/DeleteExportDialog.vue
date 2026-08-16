<script setup>
import { computed, onMounted, onUnmounted } from 'vue'

defineOptions({ name: 'DeleteExportDialog' })

const props = defineProps({
  visible: { type: Boolean, default: false },
  item: { type: Object, default: null },
  deleting: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'confirm'])

const fileList = computed(() => {
  if (!props.item) return []

  const files = [
    { label: 'Video file', value: props.item.video_name || props.item.video_relpath || '' },
    { label: 'Metadata', value: 'Matching .json sidecar if present' },
  ]

  if (props.item.zip_download_url) {
    files.push({ label: 'Project ZIP', value: 'Matching .zip file if present' })
  }

  return files
})

function handleOverlayClick(event) {
  if (props.deleting) return
  if (event.target === event.currentTarget) emit('close')
}

function onEscape(event) {
  if (!props.visible || props.deleting) return
  if (event.key === 'Escape') emit('close')
}

onMounted(() => document.addEventListener('keydown', onEscape))
onUnmounted(() => document.removeEventListener('keydown', onEscape))
</script>

<template>
  <Teleport v-if="visible" to="body">
    <div class="overlay" @click="handleOverlayClick">
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="delete-export-title">
        <div class="dialog-header">
          <div class="icon-wrap">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </div>
          <div class="header-copy">
            <h3 id="delete-export-title" class="dialog-title">Move Export To Trash?</h3>
            <p class="dialog-desc">
              This removes the export from the library and moves the related files into `output/TRASH`.
            </p>
          </div>
        </div>

        <div v-if="item" class="preview-card">
          <div class="preview-row">
            <span class="preview-label">Project</span>
            <span class="preview-value">{{ item.project_id || 'Unknown project' }}</span>
          </div>
          <div class="preview-row">
            <span class="preview-label">Video</span>
            <span class="preview-value mono">{{ item.video_name || item.video_relpath }}</span>
          </div>
          <div class="preview-files">
            <p class="preview-files-title">Files that may be moved</p>
            <div
              v-for="file in fileList"
              :key="`${file.label}:${file.value}`"
              class="file-row"
            >
              <span class="file-label">{{ file.label }}</span>
              <span class="file-value">{{ file.value }}</span>
            </div>
          </div>
        </div>

        <div class="dialog-footer">
          <button class="btn btn-secondary" :disabled="deleting" @click="emit('close')">
            Cancel
          </button>
          <button class="btn btn-danger" :disabled="deleting" @click="emit('confirm')">
            {{ deleting ? 'Moving…' : 'Move To Trash' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(7, 10, 18, 0.72);
  backdrop-filter: blur(8px);
}

.dialog {
  width: min(100%, 460px);
  border-radius: 18px;
  border: 1px solid rgba(255, 107, 107, 0.28);
  background:
    radial-gradient(circle at top right, rgba(255, 107, 107, 0.08), transparent 34%),
    linear-gradient(180deg, rgba(20, 26, 40, 0.98), rgba(14, 18, 30, 0.98));
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
  overflow: hidden;
}

.dialog-header {
  display: flex;
  gap: 14px;
  padding: 22px 22px 16px;
}

.icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ff7b7b;
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.24);
  flex-shrink: 0;
}

.header-copy {
  min-width: 0;
}

.dialog-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
}

.dialog-desc {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.preview-card {
  margin: 0 22px;
  padding: 14px;
  border-radius: 14px;
  background: rgba(7, 11, 18, 0.55);
  border: 1px solid var(--border);
}

.preview-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.preview-row + .preview-row {
  margin-top: 8px;
}

.preview-label {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  flex-shrink: 0;
}

.preview-value {
  font-size: 12px;
  color: var(--text);
  text-align: right;
  word-break: break-word;
}

.mono {
  font-family: var(--font-mono);
}

.preview-files {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.preview-files-title {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}

.file-row {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  font-size: 11px;
}

.file-row + .file-row {
  margin-top: 6px;
}

.file-label {
  color: var(--text-muted);
}

.file-value {
  color: var(--text-secondary);
  text-align: right;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 18px 22px 22px;
}

.btn {
  min-width: 118px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: all 0.16s ease;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-secondary:hover:not(:disabled) {
  border-color: var(--border-hover);
  background: rgba(255, 255, 255, 0.03);
}

.btn-danger {
  border-color: rgba(255, 107, 107, 0.38);
  color: #ffb0b0;
  background: rgba(255, 107, 107, 0.08);
}

.btn-danger:hover:not(:disabled) {
  border-color: rgba(255, 107, 107, 0.62);
  color: #ff7b7b;
  background: rgba(255, 107, 107, 0.14);
}

@media (max-width: 640px) {
  .dialog-header {
    padding: 18px 18px 14px;
  }

  .preview-card {
    margin: 0 18px;
  }

  .dialog-footer {
    padding: 16px 18px 18px;
    flex-direction: column-reverse;
  }

  .btn {
    width: 100%;
  }

  .preview-row,
  .file-row {
    flex-direction: column;
  }

  .preview-value,
  .file-value {
    text-align: left;
  }
}
</style>

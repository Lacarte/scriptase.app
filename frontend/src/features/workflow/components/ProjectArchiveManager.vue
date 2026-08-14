<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '@/shared/api/client.js'
import { useWorkflowStore } from '../stores/workflow.js'

const emit = defineEmits(['close', 'restored'])
const store = useWorkflowStore()
const projects = ref([])
const selectedProject = ref('')
const loading = ref(false)
const restoring = ref(false)
const error = ref('')
const restoreInput = ref(null)
const projectIdMode = ref('new')
const workflowIdMode = ref('new')
const canExport = computed(() => !!store.workflowId && !!selectedProject.value)

function formatDate(value) {
  if (!value) return 'Unknown date'
  return new Date(value).toLocaleString()
}

async function loadProjects() {
  if (!store.workflowId) return
  loading.value = true
  error.value = ''
  try {
    const workflowId = encodeURIComponent(store.workflowId)
    const result = await api.get(`/api/workflows/${workflowId}/projects`)
    projects.value = result.projects || []
    if (!projects.value.some((item) => item.project_id === selectedProject.value)) {
      selectedProject.value = projects.value[0]?.project_id || ''
    }
  } catch (err) {
    error.value = err?.message || 'Could not load workflow projects'
  } finally {
    loading.value = false
  }
}

function exportProject() {
  if (!canExport.value) return
  const workflowId = encodeURIComponent(store.workflowId)
  const projectId = encodeURIComponent(selectedProject.value)
  const anchor = document.createElement('a')
  anchor.href = `/api/workflows/${workflowId}/projects/${projectId}/archive`
  anchor.download = `${store.workflowId}_${selectedProject.value}.sts-project.zip`
  anchor.click()
}

async function restoreProject(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  restoring.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file)
    form.append('project_id_mode', projectIdMode.value)
    form.append('workflow_id_mode', workflowIdMode.value)
    const response = await fetch('/api/workflow/projects/restore', { method: 'POST', body: form })
    const result = await response.json().catch(() => null)
    if (!response.ok) throw new Error(result?.error?.message || 'Project restore failed')
    emit('restored', result.workflow?.workflow_id, result.project_id)
  } catch (err) {
    error.value = err?.message || 'Project restore failed'
  } finally {
    restoring.value = false
  }
}

onMounted(loadProjects)
</script>

<template>
  <div class="archive-backdrop" @click.self="emit('close')">
    <section class="archive-dialog" role="dialog" aria-modal="true" aria-labelledby="archive-title">
      <header>
        <div>
          <h2 id="archive-title">Project archive &amp; restore</h2>
          <p>Move a workflow project, its run history, referenced artifacts, and branding in one verified archive.</p>
        </div>
        <button class="close" aria-label="Close project archive" @click="emit('close')">×</button>
      </header>

      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <section class="archive-section">
        <h3>Export project</h3>
        <p v-if="!store.workflowId" class="empty">Save this workflow before exporting a project.</p>
        <p v-else-if="loading" class="empty">Loading projects…</p>
        <p v-else-if="!projects.length" class="empty">Run this workflow once to create an archivable project.</p>
        <label v-else>
          Project
          <select v-model="selectedProject" aria-label="Project to archive">
            <option v-for="item in projects" :key="item.project_id" :value="item.project_id">
              {{ item.project_id }} · {{ item.execution_count }} run{{ item.execution_count === 1 ? '' : 's' }} · {{ formatDate(item.last_run_at) }}
            </option>
          </select>
        </label>
        <button class="primary" :disabled="!canExport" @click="exportProject">Download archive</button>
      </section>

      <section class="archive-section">
        <h3>Restore archive</h3>
        <div class="mode-grid">
          <label>Project ID
            <select v-model="projectIdMode" aria-label="Restored project ID">
              <option value="new">Create a new ID</option>
              <option value="original">Keep original ID</option>
            </select>
          </label>
          <label>Workflow ID
            <select v-model="workflowIdMode" aria-label="Restored workflow ID">
              <option value="new">Create a new ID</option>
              <option value="original">Keep original ID</option>
            </select>
          </label>
        </div>
        <p>Original IDs are only restored when their destinations are free. Existing files are never overwritten.</p>
        <button class="primary" :disabled="restoring" @click="restoreInput?.click()">
          {{ restoring ? 'Verifying and restoring…' : 'Choose archive…' }}
        </button>
        <input ref="restoreInput" class="file-input" type="file" accept=".zip,.sts-project.zip,application/zip" @change="restoreProject">
      </section>

      <footer><button @click="emit('close')">Close</button></footer>
    </section>
  </div>
</template>

<style scoped>
.archive-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2,7,13,.72); }
.archive-dialog { width: min(680px, calc(100vw - 32px)); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid var(--border); border-radius: 13px; padding: 18px; color: var(--text); background: var(--bg-darkest); box-shadow: 0 24px 70px rgba(0,0,0,.55); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; } h2, h3 { margin: 0; } h2 { font-size: 17px; } h3 { font-size: 13px; }
p { margin: 5px 0 12px; color: var(--text-muted); font-size: 11px; line-height: 1.5; }.error { color: #fb7185; }.empty { margin-block: 10px; }.archive-section { margin-top: 16px; padding: 14px; border: 1px solid var(--border); border-radius: 9px; background: rgba(12,22,34,.55); }
label { display: grid; gap: 5px; color: var(--text-secondary); font-size: 11px; } select, button { border: 1px solid var(--border); border-radius: 7px; padding: 7px 10px; color: var(--text-secondary); background: rgba(20,34,51,.78); } button { cursor: pointer; } button:disabled { opacity: .45; cursor: default; }.primary { margin-top: 11px; color: white; border-color: #0f766e; background: #0f766e; }.close { border: 0; padding: 2px 7px; font-size: 22px; background: transparent; }.mode-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }.file-input { display: none; } footer { justify-content: flex-end; margin-top: 16px; }
@media (max-width: 560px) { .mode-grid { grid-template-columns: 1fr; } }
</style>

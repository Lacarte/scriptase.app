<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '@/shared/api/client.js'

const emit = defineEmits(['close'])
const report = ref(null)
const loading = ref(false)
const deleting = ref(false)
const error = ref('')
const selected = ref(new Set())
const selectedItems = computed(() => (report.value?.orphans || []).filter((item) => selected.value.has(item.path)))
const selectedBytes = computed(() => selectedItems.value.reduce((total, item) => total + item.size, 0))

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function toggle(path, checked) {
  const next = new Set(selected.value)
  if (checked) next.add(path)
  else next.delete(path)
  selected.value = next
}

async function scan() {
  loading.value = true
  error.value = ''
  try {
    report.value = await api.get('/api/workflow/assets/orphans')
    selected.value = new Set((report.value.orphans || []).map((item) => item.path))
  } catch (err) {
    error.value = err?.message || 'Could not scan output assets'
  } finally {
    loading.value = false
  }
}

async function collect() {
  const paths = [...selected.value]
  if (!paths.length || !window.confirm(`Permanently delete ${paths.length} orphaned asset(s)?`)) return
  deleting.value = true
  error.value = ''
  try {
    const result = await api.post('/api/workflow/assets/gc', { body: { paths, dry_run: false } })
    if (result.failures?.length) error.value = `${result.failures.length} asset(s) could not be deleted.`
    await scan()
  } catch (err) {
    error.value = err?.message || 'Could not collect orphaned assets'
  } finally {
    deleting.value = false
  }
}

onMounted(scan)
</script>

<template>
  <div class="gc-backdrop" @click.self="emit('close')">
    <section class="gc-dialog" role="dialog" aria-modal="true" aria-labelledby="gc-title">
      <header>
        <div><h2 id="gc-title">Asset garbage collection</h2><p>The scan excludes workflow state, trash, referenced execution artifacts, and pinned result payloads.</p></div>
        <button class="close" aria-label="Close asset garbage collection" @click="emit('close')">×</button>
      </header>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="loading" class="empty">Scanning…</p>
      <p v-else-if="!report?.orphans?.length" class="empty">No orphaned assets found.</p>
      <template v-else>
        <div class="summary"><strong>{{ report.count }} orphaned assets · {{ formatBytes(report.bytes) }}</strong><button @click="scan">Scan again</button></div>
        <ul>
          <li v-for="item in report.orphans" :key="item.path">
            <label><input type="checkbox" :checked="selected.has(item.path)" @change="toggle(item.path, $event.target.checked)" /><span>{{ item.path }}</span><small>{{ formatBytes(item.size) }}</small></label>
          </li>
        </ul>
      </template>
      <footer>
        <span>{{ selected.size }} selected · {{ formatBytes(selectedBytes) }}</span>
        <button @click="emit('close')">Close</button>
        <button class="delete" :disabled="deleting || !selected.size" @click="collect">{{ deleting ? 'Deleting…' : 'Delete selected' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.gc-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2,7,13,.72); }
.gc-dialog { width: min(760px, calc(100vw - 32px)); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid var(--border); border-radius: 13px; padding: 18px; color: var(--text); background: var(--bg-darkest); box-shadow: 0 24px 70px rgba(0,0,0,.55); }
header, .summary, footer, label { display: flex; align-items: center; gap: 12px; } header, .summary { justify-content: space-between; }
h2 { margin: 0; font-size: 17px; } p { margin: 4px 0 0; color: var(--text-muted); font-size: 11px; }
button { border: 1px solid var(--border); border-radius: 7px; padding: 7px 10px; color: var(--text-secondary); background: rgba(20,34,51,.78); cursor: pointer; } button:disabled { opacity: .45; cursor: default; }
.close { border: 0; padding: 2px 7px; font-size: 22px; background: transparent; }.summary { margin-top: 18px; font-size: 12px; }
ul { max-height: 360px; overflow: auto; margin: 10px 0; padding: 0; border: 1px solid var(--border); border-radius: 8px; list-style: none; } li + li { border-top: 1px solid var(--border); }
label { padding: 9px 10px; font: 11px ui-monospace, monospace; } label span { flex: 1; overflow-wrap: anywhere; } small, footer span { color: var(--text-muted); }
.empty, .error { margin: 18px 0; }.error { color: #fb7185; } footer { justify-content: flex-end; margin-top: 16px; font-size: 11px; } footer span { margin-right: auto; }.delete { color: white; border-color: #be123c; background: #9f1239; }
</style>

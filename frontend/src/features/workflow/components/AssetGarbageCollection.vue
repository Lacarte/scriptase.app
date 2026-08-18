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
.gc-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(0,0,0,.62); }
.gc-dialog { width: min(760px, calc(100vw - 32px)); max-height: calc(100vh - 40px); overflow: auto; padding: 18px; border: 1px solid var(--line); border-radius: var(--r-l); color: var(--text); background: var(--panel-grad); box-shadow: var(--shadow); }
header, .summary, footer, label { display: flex; align-items: center; gap: 12px; } header, .summary { justify-content: space-between; }
h2 { margin: 0; font-family: var(--display); font-size: 17px; font-weight: 600; letter-spacing: -.4px; } p { margin: 5px 0 0; color: var(--muted); font-size: 12.5px; line-height: 1.5; }
button { border: 1px solid var(--line); border-radius: var(--r-s); padding: 7px 12px; color: var(--text); background: var(--panel-grad); font-family: var(--body); font-size: 12px; font-weight: 500; cursor: pointer; box-shadow: var(--hairline-top), 0 1px 2px rgba(0,0,0,.28); transition: background .16s, border-color .16s, color .14s, transform .12s var(--ease-spring); }
button:hover:not(:disabled) { border-color: var(--line-2); background: var(--panel-grad2); transform: translateY(-1px); } button:disabled { opacity: .4; cursor: not-allowed; transform: none; }
.close { border: 0; padding: 2px 7px; color: var(--muted); font-size: 22px; background: transparent; box-shadow: none; } .close:hover:not(:disabled) { color: var(--text); background: var(--panel); transform: none; }
.summary { margin-top: 18px; font-size: 12.5px; } .summary strong { font-family: var(--display); font-weight: 600; }
ul { max-height: 360px; overflow: auto; margin: 10px 0; padding: 0; border: 1px solid var(--line-soft); border-radius: var(--r-s); background: var(--bg-2); list-style: none; } li + li { border-top: 1px solid var(--line-soft); }
label { padding: 9px 10px; font-family: var(--mono); font-size: 11px; } label span { flex: 1; color: var(--text-2); overflow-wrap: anywhere; } small, footer span { color: var(--muted); }
input[type="checkbox"] { accent-color: var(--accent); }
.empty, .error { margin: 18px 0; font-size: 12.5px; }.empty { color: var(--muted); }.error { color: var(--fail); } footer { justify-content: flex-end; margin-top: 16px; font-size: 12px; } footer span { margin-right: auto; }
.delete { color: var(--fail); border-color: var(--fail-line); }.delete:hover:not(:disabled) { background: var(--fail-dim); border-color: var(--fail-line-2); }
</style>

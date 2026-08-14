<script setup>
import { computed } from 'vue'
import { useWorkflowStore } from '../stores/workflow.js'

const emit = defineEmits(['close'])
const store = useWorkflowStore()
const defaults = {
  enabled: false,
  folder: '',
  pattern: '*.txt',
  target_node_id: '',
  target_port: '',
}
const watchFolder = computed(() => ({ ...defaults, ...(store.settings.watch_folder || {}) }))
const hasScriptInput = computed(() => store.nodes.some((node) => (
  node.type === 'script.input' && !node.disabled
)))
const targets = computed(() => store.nodes.flatMap((node) => {
  if (node.disabled) return []
  const definition = store.nodeTypes[node.type] || {}
  return (definition.inputs || []).filter((port) => {
    const type = port.type === 'dynamic' ? node.configuration?.port_type : port.type
    return type === 'text' || type === 'script'
  }).map((port) => ({
    value: `${node.id}:${port.id}`,
    label: `${node.name} — ${port.id}`,
  }))
}))
const selectedTarget = computed(() => (
  watchFolder.value.target_node_id && watchFolder.value.target_port
    ? `${watchFolder.value.target_node_id}:${watchFolder.value.target_port}`
    : ''
))

function update(patch) {
  store.setWatchFolder({ ...watchFolder.value, ...patch })
}

function updateTarget(value) {
  const separator = value.indexOf(':')
  update(separator < 0
    ? { target_node_id: '', target_port: '' }
    : { target_node_id: value.slice(0, separator), target_port: value.slice(separator + 1) })
}
</script>

<template>
  <div class="watch-backdrop" @click.self="emit('close')">
    <section class="watch-dialog" role="dialog" aria-modal="true" aria-labelledby="watch-title">
      <header>
        <div>
          <h2 id="watch-title">Watch folder</h2>
          <p>Stable matching files queue a run, then move into the folder's processed/ directory.</p>
        </div>
        <button class="close" aria-label="Close watch folder" @click="emit('close')">×</button>
      </header>

      <label class="enabled">
        <input type="checkbox" :checked="watchFolder.enabled" @change="update({ enabled: $event.target.checked })" />
        <span>Enable file-triggered runs</span>
      </label>
      <label>
        <span>Absolute folder path</span>
        <input
          class="path"
          :value="watchFolder.folder"
          placeholder="D:\Automation\incoming"
          @change="update({ folder: $event.target.value.trim() })"
        />
      </label>
      <div class="fields">
        <label>
          <span>Filename pattern</span>
          <input :value="watchFolder.pattern" placeholder="*.txt" @change="update({ pattern: $event.target.value.trim() })" />
        </label>
        <label>
          <span>Content destination</span>
          <select :value="selectedTarget" @change="updateTarget($event.target.value)">
            <option value="">Automatic Script Input</option>
            <option v-for="target in targets" :key="target.value" :value="target.value">{{ target.label }}</option>
          </select>
        </label>
      </div>
      <p v-if="!selectedTarget && !hasScriptInput" class="warning" role="alert">
        Add an enabled Script Input node or select a compatible text/script port.
      </p>
      <p class="hint">Files must remain unchanged for at least one second. UTF-8 text files up to 10 KB are accepted.</p>

      <footer>
        <span>{{ store.dirty ? 'Save the workflow to apply these settings.' : 'Settings are active.' }}</span>
        <button class="done" @click="emit('close')">Done</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.watch-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 7, 13, .72); }
.watch-dialog { width: min(650px, calc(100vw - 32px)); border: 1px solid var(--border); border-radius: 13px; padding: 18px; color: var(--text); background: var(--bg-darkest); box-shadow: 0 24px 70px rgba(0,0,0,.55); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
h2 { margin: 0; font-size: 17px; } p { margin: 4px 0 0; color: var(--text-muted); font-size: 11px; }
.close, .done { border: 1px solid var(--border); border-radius: 7px; padding: 7px 10px; color: var(--text-secondary); background: rgba(20,34,51,.78); cursor: pointer; }
.close { border: 0; padding: 2px 7px; font-size: 22px; background: transparent; }
label { display: grid; gap: 6px; margin-top: 15px; color: var(--text-muted); font-size: 10px; }
.enabled { display: flex; align-items: center; color: var(--text-secondary); font-size: 12px; }
input:not([type="checkbox"]), select { min-width: 0; border: 1px solid var(--border); border-radius: 6px; padding: 9px; color: var(--text); background: var(--bg-dark); font: 12px ui-monospace, monospace; }
.path { width: 100%; box-sizing: border-box; }.fields { display: grid; grid-template-columns: 1fr 1.4fr; gap: 12px; }
.warning { color: #fb7185; }.hint { margin-top: 14px; } footer { margin-top: 18px; color: var(--text-muted); font-size: 10px; }
.done { color: #062318; border-color: var(--accent); background: var(--accent); }
@media (max-width: 560px) { .fields { grid-template-columns: 1fr; } }
</style>

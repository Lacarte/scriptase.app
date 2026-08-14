<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '@/shared/api/client.js'
import { useWorkflowStore } from '../stores/workflow.js'

const emit = defineEmits(['close'])
const store = useWorkflowStore()
const defaults = { enabled: false, mappings: [] }
const token = ref('')
const hookPath = ref('')
const loading = ref(false)
const error = ref('')
const webhook = computed(() => ({ ...defaults, ...(store.settings.webhook || {}) }))
const hookUrl = computed(() => hookPath.value ? `${window.location.origin}${hookPath.value}` : '')
const targets = computed(() => store.nodes.flatMap((node) => {
  if (node.disabled) return []
  const definition = store.nodeTypes[node.type] || {}
  return (definition.inputs || []).flatMap((port) => {
    const type = port.type === 'dynamic' ? node.configuration?.port_type : port.type
    if (!type || type === 'control') return []
    return [{ value: `${node.id}:${port.id}`, label: `${node.name} — ${port.id} (${type})` }]
  })
}))

function update(patch) {
  store.setWebhook({ ...webhook.value, ...patch })
}

function updateMapping(index, patch) {
  const mappings = webhook.value.mappings.map((item, position) => (
    position === index ? { ...item, ...patch } : item
  ))
  update({ mappings })
}

function updateTarget(index, value) {
  const separator = value.indexOf(':')
  updateMapping(index, separator < 0
    ? { target_node_id: '', target_port: '' }
    : { target_node_id: value.slice(0, separator), target_port: value.slice(separator + 1) })
}

function addMapping() {
  const first = targets.value[0]?.value || ':'
  const separator = first.indexOf(':')
  update({ mappings: [...webhook.value.mappings, {
    payload_path: 'value',
    target_node_id: first.slice(0, separator),
    target_port: first.slice(separator + 1),
    required: true,
  }] })
}

function removeMapping(index) {
  update({ mappings: webhook.value.mappings.filter((_item, position) => position !== index) })
}

async function loadToken() {
  if (!store.workflowId) return
  loading.value = true
  error.value = ''
  try {
    const result = await api.get(`/api/workflows/${store.workflowId}/webhook`)
    token.value = result.token
    hookPath.value = result.path
  } catch (err) {
    error.value = `${err?.message || 'Failed to load webhook'}${err?.code ? ` [${err.code}]` : ''}`
  } finally {
    loading.value = false
  }
}

async function regenerate() {
  if (!store.workflowId || !window.confirm('Replace the webhook token? The previous URL will stop working immediately.')) return
  loading.value = true
  error.value = ''
  try {
    const result = await api.post(`/api/workflows/${store.workflowId}/webhook/regenerate`, { body: {} })
    token.value = result.token
    hookPath.value = result.path
  } catch (err) {
    error.value = `${err?.message || 'Failed to regenerate webhook'}${err?.code ? ` [${err.code}]` : ''}`
  } finally {
    loading.value = false
  }
}

async function copyUrl() {
  if (hookUrl.value) await navigator.clipboard?.writeText(hookUrl.value)
}

onMounted(loadToken)
</script>

<template>
  <div class="hook-backdrop" @click.self="emit('close')">
    <section class="hook-dialog" role="dialog" aria-modal="true" aria-labelledby="hook-title">
      <header>
        <div>
          <h2 id="hook-title">Webhook trigger</h2>
          <p>A loopback JSON POST maps declared payload fields into typed node inputs.</p>
        </div>
        <button class="close" aria-label="Close webhook settings" @click="emit('close')">×</button>
      </header>

      <p v-if="!store.workflowId" class="warning" role="alert">Save this workflow before creating its private webhook URL.</p>
      <template v-else>
        <label class="enabled">
          <input type="checkbox" :checked="webhook.enabled" @change="update({ enabled: $event.target.checked })" />
          <span>Enable webhook-triggered runs</span>
        </label>
        <label>
          <span>Private loopback URL</span>
          <div class="url-row">
            <input class="url" readonly :value="loading ? 'Loading…' : hookUrl" />
            <button :disabled="!hookUrl" @click="copyUrl">Copy</button>
            <button :disabled="loading" @click="regenerate">Regenerate</button>
          </div>
        </label>
        <p v-if="error" class="warning" role="alert">{{ error }}</p>

        <div class="mapping-head">
          <div><strong>Payload mappings</strong><p>Use dotted paths such as story.text.</p></div>
          <button :disabled="targets.length === 0 || webhook.mappings.length >= 32" @click="addMapping">Add mapping</button>
        </div>
        <div v-for="(mapping, index) in webhook.mappings" :key="index" class="mapping">
          <label>
            <span>JSON payload path</span>
            <input :value="mapping.payload_path" @change="updateMapping(index, { payload_path: $event.target.value.trim() })" />
          </label>
          <label>
            <span>Typed input destination</span>
            <select :value="`${mapping.target_node_id}:${mapping.target_port}`" @change="updateTarget(index, $event.target.value)">
              <option value=":" disabled>Select an input</option>
              <option v-for="target in targets" :key="target.value" :value="target.value">{{ target.label }}</option>
            </select>
          </label>
          <label class="required"><input type="checkbox" :checked="mapping.required" @change="updateMapping(index, { required: $event.target.checked })" /> Required</label>
          <button class="remove" aria-label="Remove mapping" @click="removeMapping(index)">Remove</button>
        </div>
        <p v-if="webhook.enabled && !webhook.mappings.length" class="warning" role="alert">Add at least one mapping before saving an enabled webhook.</p>
      </template>

      <footer>
        <span>{{ store.dirty ? 'Save the workflow to apply mapping changes.' : 'Saved mappings are active.' }}</span>
        <button class="done" @click="emit('close')">Done</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.hook-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 7, 13, .72); }
.hook-dialog { width: min(780px, calc(100vw - 32px)); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid var(--border); border-radius: 13px; padding: 18px; color: var(--text); background: var(--bg-darkest); box-shadow: 0 24px 70px rgba(0,0,0,.55); }
header, footer, .mapping-head, .url-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { margin: 0; font-size: 17px; } p { margin: 4px 0 0; color: var(--text-muted); font-size: 11px; }
button { border: 1px solid var(--border); border-radius: 7px; padding: 7px 10px; color: var(--text-secondary); background: rgba(20,34,51,.78); cursor: pointer; }
button:disabled { opacity: .45; cursor: not-allowed; }.close { border: 0; padding: 2px 7px; font-size: 22px; background: transparent; }
label { display: grid; gap: 6px; color: var(--text-muted); font-size: 10px; }.enabled { display: flex; align-items: center; margin: 15px 0; color: var(--text-secondary); font-size: 12px; }
input:not([type="checkbox"]), select { min-width: 0; border: 1px solid var(--border); border-radius: 6px; padding: 9px; color: var(--text); background: var(--bg-dark); font: 12px ui-monospace, monospace; }
.url { flex: 1; }.mapping-head { margin-top: 20px; }.mapping { display: grid; grid-template-columns: 1fr 1.5fr auto auto; gap: 10px; align-items: end; margin-top: 10px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; }
.required { display: flex; align-items: center; height: 34px; }.remove { color: #fb7185; }.warning { color: #fb7185; } footer { margin-top: 18px; color: var(--text-muted); font-size: 10px; }.done { color: #062318; border-color: var(--accent); background: var(--accent); }
@media (max-width: 680px) { .mapping { grid-template-columns: 1fr; }.url-row { align-items: stretch; flex-direction: column; } }
</style>

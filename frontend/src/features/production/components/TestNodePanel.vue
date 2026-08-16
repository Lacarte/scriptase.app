<script setup>
/**
 * Test Node panel (step 4.2 / product §9).
 *
 * Wires the 4.1 InputPicker to ``node_isolated``. A test run never advances
 * the Job — when ``jobId`` is set the parent posts to
 * ``POST /api/jobs/<id>/test-node``; otherwise it uses ``/api/workflow/run``
 * with ``run_mode=node_isolated``. Sample-fed results keep the
 * ``from_sample_data`` marker so stub-derived output is never mistaken for
 * real output.
 *
 * Step 13.3: when the node has a provider domain, the provider stops being
 * read-only text and becomes a picker over that domain's catalog instances.
 * The choice travels as the one-shot ``provider_instance_id`` of 13.2, so
 * "what would the other instance do?" is a question rather than an edit — the
 * node's saved configuration is never written.
 */
import { computed, ref, watch } from 'vue'

import InputPicker from '@/features/artifacts/components/InputPicker.vue'
import { bindingsForNode, makeBinding } from '@/features/artifacts/api.js'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
import { AVAILABLE, availabilityInfo, isSelectable } from '@/features/providers/availability.js'

const props = defineProps({
  /** Display name, e.g. stage label or node display name. */
  title: { type: String, default: 'Test Node' },
  nodeId: { type: String, required: true },
  nodeType: { type: String, default: '' },
  /** Registry input ports: { id, type, required?, multiple? } */
  ports: { type: Array, default: () => [] },
  currentJobId: { type: String, default: '' },
  providerLabel: { type: String, default: '' },
  /**
   * Provider domain of the node under test, or '' for a local node. Non-empty
   * turns the read-only provider line into the 13.3 picker.
   */
  providerDomain: { type: String, default: '' },
  running: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  /**
   * Last test result for this node:
   * { status, from_sample_data, outputs_summary, error, execution_id,
   *   provider_instance_id, selection_reason }
   */
  lastResult: { type: Object, default: null },
})

const emit = defineEmits(['run', 'close'])

const providerCatalog = useProviderCatalogStore()

/** port_id → binding */
const bindings = ref({})

/**
 * One-shot instance for the next run. `''` means "whatever the node is
 * configured with" — the panel never pre-selects an instance, because a
 * pre-filled override would send `provider_instance_id` on a run the user
 * never asked to repoint.
 */
const providerOverride = ref('')

const dataPorts = computed(() =>
  (props.ports || []).filter(
    (p) => p && p.id && p.type && p.type !== 'control' && p.type !== 'error',
  ),
)

const requiredPorts = computed(() =>
  dataPorts.value.filter((p) => p.required !== false),
)

const wantsRunDeps = computed(() =>
  Object.values(bindings.value).some((b) => b?.source === 'run_deps'),
)

const runMode = computed(() =>
  wantsRunDeps.value ? 'node_with_deps' : 'node_isolated',
)

const canSubmit = computed(() => {
  if (!props.nodeId || props.running || props.disabled) return false
  // Every required data port must have a binding (or run_deps covers all).
  if (wantsRunDeps.value) return true
  for (const port of requiredPorts.value) {
    const b = bindings.value[port.id]
    if (!b || !b.source) return false
    if (b.source === 'sample') continue
    if (b.source === 'manual' && b.value === undefined) return false
    if (
      ['library', 'upload', 'job', 'current_job'].includes(b.source)
      && !b.artifact_id
      && !(b.source === 'current_job' || b.source === 'job')
    ) {
      // job / current_job may resolve by kind without an explicit id
      // when the library has an active tip; still allow submit.
    }
    if (b.source === 'job' && !b.job_id) return false
  }
  return true
})

function defaultBinding(port) {
  return makeBinding('sample', { port_type: port.type })
}

function seedBindings() {
  const next = {}
  for (const port of dataPorts.value) {
    next[port.id] = bindings.value[port.id] || defaultBinding(port)
  }
  bindings.value = next
}

watch(
  () => [props.nodeId, props.ports],
  () => seedBindings(),
  { immediate: true, deep: true },
)

// A different node means a different provider question; carrying the previous
// node's override forward would silently repoint the new one.
watch(() => props.nodeId, () => { providerOverride.value = '' })

watch(
  () => props.providerDomain,
  (domain) => { if (domain) providerCatalog.loadCatalog() },
  { immediate: true },
)

/**
 * Selectable instances for the node's domain. The list, the labels, and the
 * availability all come from the catalog — no provider id is named here.
 */
const providerOptions = computed(() =>
  props.providerDomain ? providerCatalog.catalogEntriesFor(props.providerDomain) : [],
)

const showProviderPicker = computed(() => Boolean(props.providerDomain))

/** Entry label carrying any resting state other than "ready" (§21.5). */
function providerOptionLabel(entry) {
  const state = entry.availability
  if (!state || state === AVAILABLE) return entry.label
  return `${entry.label} — ${availabilityInfo(state).label}`
}

function providerOptionDisabled(entry) {
  return !isSelectable(entry)
}

/** What the run will actually use, for the confirmation line under the picker. */
const effectiveProviderLabel = computed(() => {
  if (!providerOverride.value) return props.providerLabel || 'Node default'
  const entry = providerCatalog.resolveInstance(props.providerDomain, providerOverride.value)
  return entry?.label || providerOverride.value
})

function onBindingUpdate(portId, value) {
  bindings.value = { ...bindings.value, [portId]: value }
}

function onSubmit() {
  if (!canSubmit.value) return
  // Strip run_deps ports from bindings — parent switches mode.
  const portBindings = {}
  for (const [portId, binding] of Object.entries(bindings.value)) {
    if (!binding || binding.source === 'run_deps') continue
    portBindings[portId] = binding
  }
  const inputBindings = Object.keys(portBindings).length
    ? bindingsForNode(props.nodeId, portBindings)
    : {}
  emit('run', {
    nodeId: props.nodeId,
    runMode: runMode.value,
    inputBindings,
    currentJobId: props.currentJobId || undefined,
    // Omitted entirely when the node keeps its own provider, so the default
    // path stays byte-identical to a pre-13.2 request.
    providerInstanceId: providerOverride.value || undefined,
  })
}

function pretty(value) {
  if (value === undefined || value === null) return 'No data recorded'
  try {
    const text = JSON.stringify(value, null, 2)
    if (!text || text === '{}' || text === '[]') return 'No data recorded'
    return text
  } catch {
    return String(value)
  }
}
</script>

<template>
  <section class="test-node-panel" aria-label="Test Node">
    <header class="tn-head">
      <div>
        <h3>{{ title }} — Test Node</h3>
        <p class="tn-sub">
          <code v-if="nodeId">{{ nodeId }}</code>
          <span v-if="nodeType" class="muted"> · {{ nodeType }}</span>
        </p>
      </div>
      <button type="button" class="tn-close" title="Close" @click="emit('close')">×</button>
    </header>

    <p class="tn-hint">
      Isolated run via <code>{{ runMode }}</code>.
      <template v-if="currentJobId">
        Bound Job <code>{{ currentJobId }}</code> will
        <strong>not</strong> advance (status, stage, artifacts stay put).
      </template>
      <template v-else>
        No Job bound — exploratory run only.
      </template>
    </p>

    <div v-if="showProviderPicker" class="tn-provider">
      <label class="tn-provider-label" :for="`tn-provider-${nodeId}`">Provider</label>
      <select
        :id="`tn-provider-${nodeId}`"
        v-model="providerOverride"
        class="tn-provider-select"
        :disabled="running || disabled"
      >
        <option value="">
          Node's provider{{ providerLabel ? ` (${providerLabel})` : '' }}
        </option>
        <option
          v-for="entry in providerOptions"
          :key="entry.id"
          :value="entry.id"
          :disabled="providerOptionDisabled(entry)"
        >
          {{ providerOptionLabel(entry) }}
        </option>
      </select>
      <p class="tn-hint">
        This run uses <strong>{{ effectiveProviderLabel }}</strong>.
        <template v-if="providerOverride">
          One-shot — the node's saved configuration is unchanged.
        </template>
      </p>
    </div>

    <dl v-else-if="providerLabel" class="tn-meta">
      <div>
        <dt>Provider</dt>
        <dd>{{ providerLabel }}</dd>
      </div>
    </dl>

    <div v-if="dataPorts.length" class="tn-inputs">
      <h4>Inputs</h4>
      <InputPicker
        v-for="port in dataPorts"
        :key="port.id"
        :port="port"
        :model-value="bindings[port.id]"
        :current-job-id="currentJobId"
        @update:model-value="(v) => onBindingUpdate(port.id, v)"
      />
    </div>
    <p v-else class="muted tn-hint">
      This node has no data inputs — Test runs it alone.
    </p>

    <div class="tn-actions">
      <button
        type="button"
        class="tn-run"
        :disabled="!canSubmit"
        @click="onSubmit"
      >
        {{ running ? 'Testing…' : 'Test Node' }}
      </button>
      <button type="button" class="tn-cancel" :disabled="running" @click="emit('close')">
        Cancel
      </button>
    </div>

    <section v-if="lastResult" class="tn-result" aria-label="Test result">
      <h4>
        Result
        <span
          v-if="lastResult.from_sample_data"
          class="sample-marker"
          title="Result came from sample data"
        >
          from sample data
        </span>
        <span class="status-pill" :data-status="lastResult.status || 'idle'">
          {{ lastResult.status || 'idle' }}
        </span>
      </h4>
      <p v-if="lastResult.execution_id" class="muted small">
        Execution <code>{{ lastResult.execution_id }}</code>
      </p>
      <p v-if="lastResult.provider_instance_id" class="muted small">
        Produced by <code>{{ lastResult.provider_instance_id }}</code>
        <span v-if="lastResult.selection_reason === 'request'"> · one-shot override</span>
      </p>
      <pre v-if="lastResult.error">{{ pretty(lastResult.error) }}</pre>
      <pre v-else>{{ pretty(lastResult.outputs_summary) }}</pre>
    </section>
  </section>
</template>

<style scoped>
.test-node-panel {
  margin-top: 0.75rem;
  padding: 0.85rem 0.9rem;
  border: 1px solid rgba(78, 205, 196, 0.35);
  border-radius: 10px;
  background: rgba(78, 205, 196, 0.04);
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.tn-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.5rem;
}

.tn-head h3 {
  margin: 0;
  font-size: 0.98rem;
}

.tn-sub {
  margin: 0.2rem 0 0;
  font-size: 0.78rem;
  color: var(--text-secondary, #8899aa);
}

.tn-close {
  border: none;
  background: transparent;
  color: var(--text-secondary, #8899aa);
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
  padding: 0 0.25rem;
}

.tn-hint {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-secondary, #8899aa);
  line-height: 1.4;
}

.tn-provider {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.tn-provider-label {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted, #6b7f93);
}

.tn-provider-select {
  width: 100%;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--border, #1e2a3a);
  border-radius: 6px;
  background: var(--bg-dark, #0f1520);
  color: var(--text, #e6edf5);
  font-size: 0.82rem;
}

.tn-provider-select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.tn-meta {
  margin: 0;
}

.tn-meta dt {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted, #6b7f93);
}

.tn-meta dd {
  margin: 0.1rem 0 0;
  font-size: 0.88rem;
}

.tn-inputs {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.tn-inputs h4,
.tn-result h4 {
  margin: 0 0 0.25rem;
  font-size: 0.82rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted, #6b7f93);
}

.tn-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.tn-run {
  border: 1px solid rgba(78, 205, 196, 0.5);
  background: rgba(78, 205, 196, 0.15);
  color: var(--accent, #4ecdc4);
  border-radius: 8px;
  padding: 0.4rem 0.85rem;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
}

.tn-run:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tn-cancel {
  border: 1px solid var(--border, #1e2a3a);
  background: transparent;
  color: var(--text-secondary, #8899aa);
  border-radius: 8px;
  padding: 0.4rem 0.75rem;
  font-size: 0.85rem;
  cursor: pointer;
}

.tn-result {
  border-top: 1px solid var(--border, #1e2a3a);
  padding-top: 0.65rem;
}

.tn-result pre {
  margin: 0.35rem 0 0;
  padding: 0.55rem 0.65rem;
  background: var(--bg-dark, #0f1520);
  border-radius: 8px;
  font-family: var(--font-mono, monospace);
  font-size: 0.72rem;
  line-height: 1.4;
  overflow: auto;
  max-height: 12rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.sample-marker {
  display: inline-block;
  margin-left: 0.4rem;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  background: rgba(240, 180, 41, 0.15);
  color: #f0b429;
  border: 1px solid rgba(240, 180, 41, 0.35);
}

.status-pill {
  display: inline-block;
  margin-left: 0.35rem;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  background: var(--bg-elevated, #222d3d);
  color: var(--text-secondary, #8899aa);
}

.status-pill[data-status='succeeded'] {
  background: rgba(38, 222, 129, 0.12);
  color: var(--accent-ready, #26de81);
}

.status-pill[data-status='failed'] {
  background: rgba(255, 107, 107, 0.12);
  color: var(--coral, #ff6b6b);
}

.muted {
  color: var(--text-secondary, #8899aa);
}

.small {
  font-size: 0.78rem;
}

code {
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
  background: var(--bg-dark, #0f1520);
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
}
</style>

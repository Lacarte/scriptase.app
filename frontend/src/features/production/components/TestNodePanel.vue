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
/* The panel is an *opened* affordance, so it wears the active-state accent —
   the only place besides a primary button the duotone is allowed. */
.test-node-panel {
  margin-top: 12px;
  padding: 14px 15px;
  border: 1px solid var(--accent-line);
  border-radius: var(--r);
  background: var(--accent-wash);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
  gap: 11px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.tn-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.tn-head h3 {
  margin: 0;
  font-family: var(--display);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: var(--text);
}

.tn-sub {
  margin: 4px 0 0;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}

.tn-close {
  flex: none;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
  padding: 0;
  transition: background 0.14s, color 0.14s;
}

.tn-close:hover {
  background: var(--raise);
  color: var(--text);
}

.tn-hint {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--muted);
}

.tn-hint strong {
  color: var(--text-2);
  font-weight: 600;
}

.tn-provider {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tn-provider-label {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.tn-provider-select {
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel);
  color: var(--text);
  font-family: var(--body);
  font-size: 12.5px;
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.tn-provider-select:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.tn-provider-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tn-meta {
  margin: 0;
}

.tn-meta dt {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.tn-meta dd {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--text);
}

.tn-inputs {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.tn-inputs h4,
.tn-result h4 {
  margin: 0 0 7px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 7px;
}

.tn-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* Primary button. */
.tn-run {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid transparent;
  border-radius: var(--r-s);
  background: var(--accent-grad);
  color: #fff;
  padding: 9px 16px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast);
  transition: filter 0.16s, box-shadow 0.16s, transform 0.12s var(--ease-spring);
}

.tn-run:hover:not(:disabled) {
  filter: brightness(1.07) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
}

.tn-run:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  filter: none;
}

/* Secondary button. */
.tn-cancel {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel-grad);
  color: var(--text);
  padding: 9px 14px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.16s, border-color 0.16s, box-shadow 0.16s,
    transform 0.12s var(--ease-spring);
}

.tn-cancel:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  transform: translateY(-1px);
  box-shadow: var(--hairline-top), 0 4px 12px -4px rgba(0, 0, 0, 0.5);
}

.tn-cancel:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

.tn-result {
  border-top: 1px solid var(--line);
  padding-top: 11px;
}

/* Recessed well for the read-only JSON readout. */
.tn-result pre {
  margin: 7px 0 0;
  padding: 10px 12px;
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-2);
  overflow: auto;
  max-height: 200px;
  white-space: pre-wrap;
  word-break: break-word;
}

.sample-marker {
  display: inline-flex;
  align-items: center;
  margin-left: 7px;
  padding: 4px 10px;
  border-radius: 20px;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--warn);
  background: var(--warn-dim);
  box-shadow: inset 0 0 0 1px var(--warn-line);
}

.status-pill {
  display: inline-flex;
  align-items: center;
  margin-left: 7px;
  padding: 4px 10px;
  border-radius: 20px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--queue);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line);
}

.status-pill[data-status='running'] {
  color: var(--run);
  background: var(--run-dim);
  box-shadow: inset 0 0 0 1px var(--run-line);
}

.status-pill[data-status='succeeded'] {
  color: var(--ok);
  background: var(--ok-dim);
  box-shadow: inset 0 0 0 1px var(--ok-line);
}

.status-pill[data-status='failed'] {
  color: var(--fail);
  background: var(--fail-dim);
  box-shadow: inset 0 0 0 1px var(--fail-line);
}

.status-pill[data-status='partial'] {
  color: var(--warn);
  background: var(--warn-dim);
  box-shadow: inset 0 0 0 1px var(--warn-line);
}

.muted {
  color: var(--muted);
}

.small {
  font-size: 11.5px;
  line-height: 1.5;
}

code {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
  background: var(--bg-2);
  border-radius: 4px;
  padding: 1px 5px;
}
</style>

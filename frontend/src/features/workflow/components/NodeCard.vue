<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { useWorkflowStore } from '../stores/workflow.js'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
import { PORT_COLORS } from '../constants.js'
import NodeIcon from '@/shared/components/NodeIcon.vue'

// Generic card for every node type — rendering is driven entirely by the
// registry definition carried in `data` (Automa BlockBasic pattern).
const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const store = useWorkflowStore()
const catalog = useProviderCatalogStore()

const def = computed(() => store.nodeTypes[props.data.nodeType] || {})
const category = computed(() => store.categories[def.value.category] || {})
const color = computed(() => category.value.color || '#9CA3AF')

const inputs = computed(() => def.value.inputs || [])
const outputs = computed(() => def.value.outputs || [])

const issues = computed(() => store.issuesByNode[props.id] || [])
const issueSummary = computed(() => issues.value.map((issue) => issue.message).join('\n'))

// Sample-data stubs (step 2.5): half-height dashed cards with a "sample"
// badge; dynamic handles take the colour of their configured port type.
const isStub = computed(() => def.value.category === 'testing')
const node = computed(() => store.nodeById(props.id))
const execution = computed(() => store.nodeExecution(props.id))
const status = computed(() => execution.value.status || 'idle')
const isPinned = computed(() => node.value?.type === 'stub.output' && node.value.configuration?.pinned === true)
const resultSummary = computed(() => {
  if (node.value?.type !== 'stub.output') return ''
  const value = isPinned.value
    ? node.value.configuration?.payload
    : (status.value === 'succeeded' ? execution.value.outputs_summary?.value : undefined)
  if (value === undefined) return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 72 ? `${text.slice(0, 69)}…` : text
})

// Provider-backed nodes (step 12.3) name their domain in the one field of type
// `provider`; nothing here is keyed on a concrete provider id or domain, so a
// new provider — or a new provider domain — needs no edit to this card.
const providerField = computed(() =>
  (def.value.config_schema || []).find((field) => field.type === 'provider'),
)

const providerId = computed(() => {
  const field = providerField.value
  if (!field) return ''
  const configured = node.value?.configuration?.[field.name]
  return configured || field.default || catalog.selectedProvider(field.provider_domain)?.id || ''
})

// Falls back to the raw id while the catalog is still loading, so the card
// says something true immediately instead of flashing empty.
const providerLabel = computed(() => {
  const field = providerField.value
  if (!field || !providerId.value) return ''
  return catalog.resolveProvider(field.provider_domain, providerId.value)?.label || providerId.value
})

const subtitle = computed(() => providerLabel.value || def.value.display_name || '')
const subtitleTitle = computed(() =>
  providerLabel.value ? `${def.value.display_name} — provider: ${providerLabel.value}` : def.value.display_name,
)

function resolvedType(port) {
  if (port.type !== 'dynamic') return port.type
  return node.value?.configuration?.port_type || 'generic_json'
}

function portColor(port) {
  if (port.id === 'error' && port.type === 'control') return '#fb7185'
  return PORT_COLORS[resolvedType(port)] || PORT_COLORS.generic_json
}

function handleStyle(port, index, total) {
  return {
    top: `${((index + 1) / (total + 1)) * 100}%`,
    background: portColor(port),
    border: port.type === 'control' ? '1.5px dashed rgba(255,255,255,0.6)' : '1.5px solid rgba(0,0,0,0.45)',
  }
}

function handleTitle(port, required) {
  return `${port.id} (${resolvedType(port)})${required ? ' — required' : ''}`
}
</script>

<template>
  <div
    v-memo="[selected, data.nodeType, data.label, data.disabled, def, category, status, execution.from_sample_data, issueSummary, isPinned, resultSummary, color, subtitle]"
    class="node-card"
    :class="[{ selected, disabled: data.disabled, stub: isStub }, `status-${status}`]"
  >
    <span class="node-strip" :style="{ background: color }" />

    <Handle
      v-for="(port, i) in inputs"
      :id="port.id"
      :key="`in-${port.id}`"
      type="target"
      :position="Position.Left"
      class="node-handle"
      :style="handleStyle(port, i, inputs.length)"
      :title="handleTitle(port, port.required)"
    />

    <div class="node-body">
      <span class="node-icon" :style="{ color }">
        <NodeIcon :icon="def.icon" />
      </span>
      <div class="node-text">
        <span class="node-name">{{ data.label }}</span>
        <span
          v-if="!isStub"
          class="node-type"
          :class="{ 'node-provider': providerLabel }"
          :title="subtitleTitle"
        >{{ subtitle }}</span>
      </div>
      <span v-if="isPinned" class="pin-badge" title="Pinned result overrides upstream data">pinned</span>
      <span v-else-if="isStub" class="stub-badge" :title="def.display_name">sample</span>
      <span v-if="execution.from_sample_data && status === 'succeeded'" class="sample-result" title="Result came from sample data">S</span>
      <span class="status-dot" :title="status" />
      <span
        v-if="issues.length"
        class="node-badge"
        :title="issueSummary"
      >{{ issues.length }}</span>
    </div>
    <div v-if="resultSummary" class="result-summary" :title="resultSummary">{{ resultSummary }}</div>

    <Handle
      v-for="(port, i) in outputs"
      :id="port.id"
      :key="`out-${port.id}`"
      type="source"
      :position="Position.Right"
      class="node-handle"
      :style="handleStyle(port, i, outputs.length)"
      :title="handleTitle(port, false)"
    />
  </div>
</template>

<style scoped>
.node-card {
  position: relative;
  min-width: 172px;
  max-width: 220px;
  background: var(--bg-darkest, #101418);
  border: 1px solid var(--border, #2a3138);
  border-radius: 10px;
  color: var(--text, #e5e7eb);
  font-size: 12px;
  transition: border-color 0.15s, box-shadow 0.15s;
  --status-color: #64748b;
}

.node-card.status-running { --status-color: #38bdf8; border-color: rgba(56,189,248,.65); box-shadow: 0 0 15px rgba(56,189,248,.16); }
.node-card.status-waiting { --status-color: #a78bfa; }
.node-card.status-succeeded { --status-color: #34d399; border-color: rgba(52,211,153,.45); }
.node-card.status-failed { --status-color: #fb7185; border-color: rgba(251,113,133,.7); }
.node-card.status-cancelled { --status-color: #f59e0b; }
.node-card.status-skipped { --status-color: #94a3b8; }
.node-card.status-stale { --status-color: #fb923c; }

.node-card.selected {
  border-color: var(--accent, #4ecdc4);
  box-shadow: 0 0 0 1px var(--accent, #4ecdc4), 0 4px 18px rgba(0, 0, 0, 0.35);
}

.node-card.disabled {
  opacity: 0.45;
}

/* Sample-data stubs: half-height, dashed, visually secondary (step 2.5). */
.node-card.stub {
  min-width: 140px;
  max-width: 190px;
  border-style: dashed;
  border-color: rgba(120, 113, 108, 0.9);
  background: rgba(16, 20, 24, 0.75);
}

.node-card.stub .node-body {
  padding: 4px 12px;
  gap: 7px;
}

.node-card.stub .node-icon {
  width: 14px;
  height: 14px;
  min-width: 14px;
}

.node-card.stub .node-name {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary, #b5bcc4);
}

.stub-badge {
  margin-left: auto;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #a8a29e;
  border: 1px dashed rgba(168, 162, 158, 0.6);
  border-radius: 5px;
  padding: 1px 4px;
}

.pin-badge {
  margin-left: auto;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #fdba74;
  border: 1px solid rgba(251, 146, 60, 0.65);
  border-radius: 5px;
  padding: 1px 4px;
}

.node-card.stub .node-badge {
  margin-left: 4px;
}

.node-strip {
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 3px 3px 0;
}

.node-body {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 14px;
}

.node-icon {
  width: 20px;
  height: 20px;
  min-width: 20px;
}

.node-icon svg {
  width: 100%;
  height: 100%;
}

.node-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.node-name {
  font-weight: 600;
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-type {
  font-size: 10px;
  color: var(--text-muted, #8b949e);
  line-height: 1.3;
}

/* The provider is a configured value, not a static type label — give it
   slightly more presence so it reads as "what this node will actually run". */
.node-provider {
  color: var(--text-secondary, #adbac7);
  font-weight: 500;
}

.node-handle {
  width: 10px;
  height: 10px;
}

.node-badge {
  margin-left: auto;
  min-width: 16px;
  height: 16px;
  border-radius: 8px;
  background: rgba(255, 179, 71, 0.18);
  border: 1px solid rgba(255, 179, 71, 0.5);
  color: var(--accent-warning, #ffb347);
  font-size: 10px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
}

.status-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: var(--status-color); box-shadow: 0 0 0 2px rgba(255,255,255,.05); }
.status-running .status-dot { animation: status-pulse 1.1s ease-in-out infinite; }
.sample-result { flex: 0 0 auto; width: 15px; height: 15px; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; background: rgba(167,139,250,.18); color: #c4b5fd; font-size: 8px; font-weight: 800; }
.result-summary { border-top: 1px dashed rgba(148,163,184,.22); padding: 4px 12px 5px; color: var(--text-muted); font: 9px/1.35 var(--font-mono, monospace); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@keyframes status-pulse { 50% { opacity: .35; transform: scale(.75); } }
</style>

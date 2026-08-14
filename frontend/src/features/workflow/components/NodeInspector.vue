<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useWorkflowStore } from '../stores/workflow.js'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
import { shouldDisplayField } from '../schema.js'
import ConfigField from './ConfigField.vue'
import NodeIcon from './NodeIcon.vue'
import { expressionOptions } from '../expressions.js'

const store = useWorkflowStore()
const providerCatalog = useProviderCatalogStore()

const node = computed(() => store.selectedNode)
const def = computed(() => (node.value ? store.nodeTypes[node.value.type] : null))
const category = computed(() => store.categories[def.value?.category] || {})
const errorPolicy = computed(() => node.value?.on_error || { policy: 'stop' })
const errorPolicies = computed(() => {
  const capabilities = def.value?.capabilities || {}
  return [
    { value: 'stop', label: 'Stop workflow' },
    ...(capabilities.retry ? [{ value: 'retry', label: 'Retry' }] : []),
    ...(capabilities.error_output ? [{ value: 'continue_error', label: 'Use error output' }] : []),
    ...(capabilities.skip_optional ? [{ value: 'skip_optional', label: 'Skip optional node' }] : []),
  ]
})

// display_options re-evaluated on every config change (n8n NDV pattern).
const visibleFields = computed(() =>
  (def.value?.config_schema || []).filter((field) =>
    shouldDisplayField(field, node.value?.configuration),
  ),
)

/**
 * The provider this node runs on, for its `provider_options` sub-form.
 *
 * Read from whichever field declares the `provider` widget — the node's own
 * selection is authoritative, never the domain's global one, or switching the
 * selection would silently reconfigure every saved workflow (§24.1 rule 2).
 * The schema default counts, because a workflow saved before step 12.3 carries
 * no `provider_id` and must still show the options of the provider it will
 * actually run (§41.3 M4). This mirrors `options.configured_provider()`.
 */
const providerField = computed(
  () => (def.value?.config_schema || []).find((f) => f.type === 'provider') || null,
)

const selectedProviderId = computed(() => {
  const field = providerField.value
  if (!field) return ''
  const stored = node.value?.configuration?.[field.name]
  return (typeof stored === 'string' && stored) || field.default || ''
})

/** The domain that provider belongs to, so sibling dropdowns can scope to it. */
const providerDomain = computed(() => providerField.value?.provider_domain || '')

/**
 * Provider capabilities granted for the node-selected instance (step 6.1).
 * Only keys true on the manifest and inside the domain vocabulary are offered.
 */
const providerCapabilities = computed(() => {
  const domain = providerDomain.value
  const id = selectedProviderId.value
  if (!domain || !id) return []
  return providerCatalog.grantedCapabilitiesOf(domain, id)
})

const issues = computed(() => store.issuesByNode[node.value?.id] || [])
const mappingOptions = computed(() => expressionOptions(
  node.value, store.nodes, store.edges, store.nodeTypes, store.variables,
))
const variablesError = ref('')
const VARIABLES_FIELD_KEY = 'workflow:variables'

function updateVariables(event) {
  try {
    const parsed = JSON.parse(event.target.value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
    variablesError.value = ''
    store.reportInvalidField(VARIABLES_FIELD_KEY, '')
    store.updateVariables(parsed)
  } catch {
    variablesError.value = 'Variables must be a valid JSON object'
    store.reportInvalidField(
      VARIABLES_FIELD_KEY,
      'Fix the workflow variables JSON before saving',
    )
  }
}

function onUpdate(name, value) {
  store.updateNodeConfig(node.value.id, name, value)
}

// A widget holding unparseable text registers a Save block; the invalid
// text only exists inside the mounted widget, so switching nodes (or
// closing the inspector) discards it and must release the block too.
function onFieldInvalid(field, message) {
  if (!node.value) return
  store.reportInvalidField(
    `${node.value.id}:${field.name}`,
    message
      ? `Fix invalid JSON in "${node.value.name}" → "${field.label || field.name}" before saving`
      : '',
  )
}

watch(() => store.selectedNodeId, (_current, previous) => {
  if (previous) store.clearInvalidFields(`${previous}:`)
  if (!store.selectedNodeId) {
    variablesError.value = ''
    store.clearInvalidFields()
  }
})

onBeforeUnmount(() => store.clearInvalidFields())

function onDelete() {
  store.removeNodes([node.value.id])
  store.clearSelection()
}


function updateErrorPolicy(patch) {
  store.updateNodeErrorPolicy(node.value.id, patch)
}
</script>

<template>
  <div v-if="!node || !def" class="wf-panel-empty">
    Select a node to configure it
  </div>

  <div v-else class="inspector">
    <header class="inspector-head">
      <span class="inspector-icon" :style="{ color: category.color }">
        <NodeIcon :icon="def.icon" />
      </span>
      <input
        class="inspector-name"
        :value="node.name"
        :maxlength="120"
        title="Rename node"
        @change="store.renameNode(node.id, $event.target.value.trim() || def.display_name)"
      />
    </header>
    <div class="inspector-sub">
      <span class="inspector-type">{{ def.display_name }} · v{{ node.type_version }}</span>
      <span class="inspector-actions">
        <button
          class="ins-btn"
          :class="{ off: node.disabled }"
          :title="node.disabled ? 'Enable node' : 'Disable node'"
          @click="store.setNodeDisabled(node.id, !node.disabled)"
        >{{ node.disabled ? 'Enable' : 'Disable' }}</button>
        <button class="ins-btn" title="Duplicate node" @click="store.duplicateNode(node.id)">Duplicate</button>
        <button class="ins-btn danger" title="Delete node" @click="onDelete">Delete</button>
      </span>
    </div>

    <p v-if="def.description" class="inspector-desc">{{ def.description }}</p>

    <p
      v-if="providerCapabilities.length"
      class="provider-capabilities"
      data-testid="provider-capabilities"
      :title="`Capabilities of the selected ${providerDomain} provider`"
    >
      <span
        v-for="name in providerCapabilities"
        :key="name"
        class="cap-badge"
      >{{ name }}</span>
    </p>

    <details class="workflow-variables">
      <summary>Workflow variables</summary>
      <textarea
        class="variables-editor"
        :value="JSON.stringify(store.variables, null, 2)"
        rows="4"
        spellcheck="false"
        @blur="updateVariables"
      />
      <span v-if="variablesError" class="variables-error">{{ variablesError }}</span>
      <p>Named finite JSON values are available as <code v-pre>{{ variables.name }}</code>.</p>
    </details>

    <section v-if="errorPolicies.length > 1" class="error-policy">
      <label>
        <span>On error</span>
        <select
          :value="errorPolicy.policy"
          @change="updateErrorPolicy({ policy: $event.target.value })"
        >
          <option v-for="option in errorPolicies" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>
      <div v-if="errorPolicy.policy === 'retry'" class="retry-grid">
        <label>
          <span>Max attempts</span>
          <input type="number" min="1" max="10" :value="errorPolicy.max_attempts ?? 3"
            @change="updateErrorPolicy({ max_attempts: Number($event.target.value) })" />
        </label>
        <label>
          <span>Delay (ms)</span>
          <input type="number" min="0" max="60000" :value="errorPolicy.delay_ms ?? 1000"
            @change="updateErrorPolicy({ delay_ms: Number($event.target.value) })" />
        </label>
        <label>
          <span>Backoff</span>
          <input type="number" min="1" max="10" step="0.1" :value="errorPolicy.backoff_multiplier ?? 2"
            @change="updateErrorPolicy({ backoff_multiplier: Number($event.target.value) })" />
        </label>
      </div>
    </section>

    <ul v-if="issues.length" class="inspector-issues">
      <li v-for="issue in issues" :key="issue.kind + issue.name">{{ issue.message }}</li>
    </ul>

    <div v-if="!visibleFields.length" class="wf-panel-empty">
      This node has no settings.
    </div>

    <div v-else class="inspector-fields">
      <ConfigField
        v-for="field in visibleFields"
        :key="field.name"
        :field="field"
        :value="node.configuration[field.name]"
        :expression-options="mappingOptions"
        :provider-id="selectedProviderId"
        :provider-domain="providerDomain"
        @update="(value) => onUpdate(field.name, value)"
        @invalid="(message) => onFieldInvalid(field, message)"
      />
    </div>
  </div>
</template>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

.inspector-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 14px 0;
}

.inspector-icon {
  width: 18px;
  height: 18px;
  min-width: 18px;
}

.inspector-icon svg {
  width: 100%;
  height: 100%;
}

.inspector-name {
  flex: 1;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
  padding: 4px 6px;
  outline: none;
  min-width: 0;
}

.inspector-name:hover,
.inspector-name:focus {
  border-color: var(--border);
  background: var(--bg-dark);
}

.inspector-sub {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 14px 0;
  flex-wrap: wrap;
}

.provider-capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 14px 0;
  margin: 0;
}

.cap-badge {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--bg-elevated, #222d3d);
  color: var(--text-secondary, #8899aa);
  border: 1px solid var(--border, #1e2a3a);
}

.inspector-type {
  font-size: 10px;
  color: var(--text-muted);
}

.inspector-actions {
  display: flex;
  gap: 5px;
}

.ins-btn {
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 10.5px;
  font-weight: 600;
  padding: 3px 8px;
  cursor: pointer;
}

.ins-btn:hover {
  color: var(--text);
  border-color: var(--accent);
}

.ins-btn.off {
  color: var(--accent-warning, #ffb347);
}

.ins-btn.danger:hover {
  color: #f87171;
  border-color: #f87171;
}

.inspector-desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
  padding: 6px 14px 2px;
}

.error-policy {
  margin: 8px 14px 2px;
  padding: 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-dark);
}

.workflow-variables { margin: 6px 14px 0; border: 1px solid var(--border); border-radius: 8px; }
.workflow-variables summary { cursor: pointer; padding: 7px 9px; color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.workflow-variables :deep(.cfg-field) { padding: 4px 9px 9px; }
.variables-editor { width: calc(100% - 18px); margin: 0 9px; padding: 6px; resize: vertical; background: var(--bg-dark); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font: 10.5px ui-monospace, 'Cascadia Mono', Consolas, monospace; }
.workflow-variables p, .variables-error { display: block; margin: 5px 9px 8px; font-size: 9.5px; color: var(--text-muted); }
.variables-error { color: #f87171; }

.error-policy label { display: grid; gap: 4px; font-size: 10.5px; color: var(--text-muted); }
.error-policy select,
.error-policy input {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--bg-panel);
  color: var(--text);
  padding: 5px 6px;
  font-size: 11px;
}
.retry-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 7px; }

.inspector-issues {
  margin: 6px 14px 0;
  padding: 8px 10px 8px 24px;
  border: 1px solid rgba(255, 179, 71, 0.35);
  border-radius: 8px;
  background: rgba(255, 179, 71, 0.07);
  font-size: 11px;
  color: var(--accent-warning, #ffb347);
  line-height: 1.5;
}

.inspector-fields {
  flex: 1;
  overflow-y: auto;
  padding-bottom: 12px;
}

.wf-panel-empty {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 14px;
  opacity: 0.7;
}
</style>

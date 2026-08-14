<script setup>
/**
 * Per-stage detail panel (§18 / step 2.4).
 *
 * Executable actions (Run / Test / Regenerate / Run From Here) post the same
 * body the Workflow canvas would send to POST /api/workflow/run. Inspect
 * actions read the current execution's node records. Approve is shown now and
 * becomes durable at 2.6.
 */
import { computed, ref, watch } from 'vue'

import {
  ACTION_HINTS,
  ACTION_LABELS,
  actionRequiresProvider,
  buildStageRunRequest,
  canApproveStage,
  isExecutableAction,
  stagePrimaryTarget,
} from '../stageActions.js'
import { statusLabel } from '../stageStatus.js'

const props = defineProps({
  stage: { type: Object, default: null },
  workflowId: { type: String, default: '' },
  workflow: { type: Object, default: null },
  /** node_id → execution record fields */
  nodeRecords: { type: Object, default: () => ({}) },
  executionId: { type: String, default: '' },
  executionActive: { type: Boolean, default: false },
  running: { type: Boolean, default: false },
  actionError: { type: String, default: '' },
  actionMessage: { type: String, default: '' },
})

const emit = defineEmits(['run', 'inspect'])

const inspectPane = ref(null) // 'input' | 'output' | 'history' | 'provider' | null

watch(
  () => props.stage?.key,
  () => {
    inspectPane.value = null
  },
)

const primaryNodeId = computed(() => {
  if (!props.stage) return null
  try {
    return stagePrimaryTarget(props.stage, props.workflow || {})
  } catch {
    return (props.stage.node_ids || [])[0] || null
  }
})

const primaryRecord = computed(() => {
  const id = primaryNodeId.value
  if (!id) return null
  return props.nodeRecords?.[id] || null
})

const hasMembers = computed(
  () => Array.isArray(props.stage?.node_ids) && props.stage.node_ids.length > 0,
)

const canRunActions = computed(
  () => hasMembers.value && Boolean(props.workflowId || props.workflow) && !props.executionActive && !props.running,
)

const approveEnabled = computed(() => canApproveStage(props.stage) && !props.running)

const executableActions = ['run', 'test', 'regenerate', 'run_from_here']
const inspectActions = ['view_input', 'view_output', 'provider', 'history', 'approve']

function showProviderAction(action) {
  if (action !== 'provider') return true
  // Provider selection appears only on provider-capable stages (§6, §19).
  return Boolean(props.stage?.provider_capable)
}

function actionDisabled(action) {
  if (action === 'approve') return !approveEnabled.value
  if (isExecutableAction(action)) return !canRunActions.value
  // Inspect actions need a stage; history/input/output prefer a record.
  if (!props.stage) return true
  if (action === 'provider') return !props.stage.provider_capable
  return false
}

function onAction(action) {
  if (!props.stage) return
  if (action === 'approve') {
    emit('inspect', { action: 'approve', stage: props.stage, nodeId: primaryNodeId.value })
    return
  }
  if (action === 'view_input') {
    inspectPane.value = inspectPane.value === 'input' ? null : 'input'
    emit('inspect', { action, stage: props.stage, nodeId: primaryNodeId.value })
    return
  }
  if (action === 'view_output') {
    inspectPane.value = inspectPane.value === 'output' ? null : 'output'
    emit('inspect', { action, stage: props.stage, nodeId: primaryNodeId.value })
    return
  }
  if (action === 'history') {
    inspectPane.value = inspectPane.value === 'history' ? null : 'history'
    emit('inspect', { action, stage: props.stage, nodeId: primaryNodeId.value })
    return
  }
  if (action === 'provider') {
    inspectPane.value = inspectPane.value === 'provider' ? null : 'provider'
    emit('inspect', { action, stage: props.stage, nodeId: primaryNodeId.value })
    return
  }
  if (!isExecutableAction(action) || actionDisabled(action)) return

  const body = buildStageRunRequest(action, props.stage, {
    workflowId: props.workflowId || undefined,
    workflow: props.workflowId ? undefined : props.workflow || undefined,
  })
  emit('run', {
    action,
    stage: props.stage,
    body,
    runMode: body.run_mode,
    targetNodeIds: body.target_node_ids,
    requiresProvider: actionRequiresProvider(action, props.stage),
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
  <aside class="step-detail" aria-live="polite">
    <template v-if="stage">
      <header class="detail-head">
        <h2>{{ stage.label }}</h2>
        <span class="status-badge" :data-status="stage.status || 'idle'">
          {{ statusLabel(stage.status) }}
        </span>
      </header>

      <dl class="detail-grid">
        <div>
          <dt>Key</dt>
          <dd><code>{{ stage.key }}</code></dd>
        </div>
        <div>
          <dt>Primary node</dt>
          <dd>
            <code v-if="primaryNodeId">{{ primaryNodeId }}</code>
            <span v-else class="muted">None</span>
          </dd>
        </div>
        <div>
          <dt>Nodes</dt>
          <dd>
            <ul v-if="(stage.node_ids || []).length" class="node-ids">
              <li v-for="nid in stage.node_ids" :key="nid">
                <code :class="{ primary: nid === primaryNodeId }">{{ nid }}</code>
              </li>
            </ul>
            <span v-else class="muted">None in this workflow</span>
          </dd>
        </div>
        <div v-if="stage.provider_capable">
          <dt>Provider</dt>
          <dd>
            <span class="provider-id">
              {{ stage.active_provider_instance_id || 'Not selected' }}
            </span>
          </dd>
        </div>
        <div v-else>
          <dt>Provider</dt>
          <dd class="muted">Local (not provider-capable)</dd>
        </div>
        <div v-if="(stage.artifacts || []).length">
          <dt>Artifacts</dt>
          <dd>
            <ul class="node-ids">
              <li v-for="ref in stage.artifacts" :key="ref">
                <code>{{ ref }}</code>
              </li>
            </ul>
          </dd>
        </div>
      </dl>

      <div class="action-toolbar" role="toolbar" aria-label="Stage actions">
        <div class="action-group">
          <button
            v-for="action in executableActions"
            :key="action"
            type="button"
            class="action-btn"
            :class="`action-${action}`"
            :disabled="actionDisabled(action)"
            :title="ACTION_HINTS[action]"
            @click="onAction(action)"
          >
            {{ ACTION_LABELS[action] }}
          </button>
        </div>
        <div class="action-group inspect-group">
          <button
            v-for="action in inspectActions.filter(showProviderAction)"
            :key="action"
            type="button"
            class="action-btn ghost"
            :class="[
              `action-${action}`,
              {
                active:
                  (action === 'view_input' && inspectPane === 'input')
                  || (action === 'view_output' && inspectPane === 'output')
                  || (action === 'history' && inspectPane === 'history')
                  || (action === 'provider' && inspectPane === 'provider'),
              },
            ]"
            :disabled="actionDisabled(action)"
            :title="ACTION_HINTS[action]"
            @click="onAction(action)"
          >
            {{ ACTION_LABELS[action] }}
          </button>
        </div>
      </div>

      <p v-if="actionError" class="action-error" role="alert">{{ actionError }}</p>
      <p v-else-if="actionMessage" class="action-message" role="status">{{ actionMessage }}</p>
      <p v-else-if="running" class="action-message muted" role="status">Starting run…</p>
      <p v-else-if="executionActive" class="action-message muted" role="status">
        A run is in progress. Wait for it to finish before starting another.
      </p>

      <section v-if="inspectPane === 'input'" class="inspect-pane" aria-label="Resolved inputs">
        <h3>View Input</h3>
        <p class="muted small">
          Resolved inputs for <code>{{ primaryNodeId || '—' }}</code>
          <template v-if="executionId"> on run <code>{{ executionId }}</code></template>.
        </p>
        <pre>{{ pretty(primaryRecord?.resolved_inputs_summary) }}</pre>
      </section>

      <section v-if="inspectPane === 'output'" class="inspect-pane" aria-label="Outputs">
        <h3>View Output</h3>
        <p class="muted small">
          Outputs for <code>{{ primaryNodeId || '—' }}</code>
          <template v-if="executionId"> on run <code>{{ executionId }}</code></template>.
        </p>
        <pre>{{ pretty(primaryRecord?.outputs_summary) }}</pre>
        <template v-if="(primaryRecord?.artifact_refs || []).length">
          <h4>Artifact references</h4>
          <ul class="node-ids">
            <li v-for="ref in primaryRecord.artifact_refs" :key="ref">
              <code>{{ ref }}</code>
            </li>
          </ul>
        </template>
      </section>

      <section v-if="inspectPane === 'history'" class="inspect-pane" aria-label="Attempt history">
        <h3>History</h3>
        <p class="muted small">
          Attempts for <code>{{ primaryNodeId || '—' }}</code>
          on the current execution. Full version comparison lands in step 4.3.
        </p>
        <dl class="history-meta">
          <div>
            <dt>Attempts</dt>
            <dd>{{ primaryRecord?.attempts ?? 0 }}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{{ statusLabel(primaryRecord?.status || stage.status) }}</dd>
          </div>
          <div v-if="primaryRecord?.error">
            <dt>Last error</dt>
            <dd>
              <code>{{ primaryRecord.error.code || 'ERROR' }}</code>
              {{ primaryRecord.error.message || '' }}
            </dd>
          </div>
        </dl>
        <pre v-if="(primaryRecord?.attempt_errors || []).length">{{ pretty(primaryRecord.attempt_errors) }}</pre>
        <p v-else class="muted small">No prior attempt errors recorded.</p>
      </section>

      <section v-if="inspectPane === 'provider'" class="inspect-pane" aria-label="Provider">
        <h3>Provider</h3>
        <p class="muted small">
          Provider selection is metadata on the stage — never a “-P” suffix on
          the name. Instance-aware override UI lands with Phase 3.
        </p>
        <dl class="history-meta">
          <div>
            <dt>Active instance</dt>
            <dd>
              <code>{{ stage.active_provider_instance_id || 'Not selected' }}</code>
            </dd>
          </div>
          <div>
            <dt>Capable</dt>
            <dd>{{ stage.provider_capable ? 'Yes' : 'No' }}</dd>
          </div>
        </dl>
      </section>
    </template>
    <template v-else>
      <p class="muted empty-detail">
        Select a stage to open its detail panel. Actions map onto the same
        engine run modes the Workflow canvas uses — one execution path.
      </p>
    </template>
  </aside>
</template>

<style scoped>
.step-detail {
  background: var(--bg-surface, #161d2a);
  border: 1px solid var(--border, #1e2a3a);
  border-radius: 12px;
  padding: 1rem 1.1rem;
  min-height: 12rem;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}

.detail-head h2 {
  margin: 0;
  font-size: 1.15rem;
  font-family: var(--font-display, system-ui, sans-serif);
}

.status-badge {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.28rem 0.55rem;
  border-radius: 6px;
  background: var(--bg-elevated, #222d3d);
  color: var(--text-secondary, #8899aa);
  border: 1px solid var(--border, #1e2a3a);
}

.status-badge[data-status='running'] {
  background: rgba(255, 159, 67, 0.12);
  color: var(--accent-active, #ff9f43);
  border-color: rgba(255, 159, 67, 0.35);
}

.status-badge[data-status='succeeded'] {
  background: rgba(38, 222, 129, 0.12);
  color: var(--accent-ready, #26de81);
  border-color: rgba(38, 222, 129, 0.35);
}

.status-badge[data-status='failed'] {
  background: rgba(255, 107, 107, 0.12);
  color: var(--coral, #ff6b6b);
  border-color: rgba(255, 107, 107, 0.35);
}

.status-badge[data-status='awaiting_approval'] {
  background: rgba(167, 139, 250, 0.12);
  color: var(--accent-secondary, #a78bfa);
  border-color: rgba(167, 139, 250, 0.35);
}

.detail-grid {
  margin: 0 0 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.detail-grid dt {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-muted, #6b7f93);
  margin-bottom: 0.15rem;
}

.detail-grid dd {
  margin: 0;
  font-size: 0.9rem;
}

.detail-grid code,
.node-ids code {
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
  background: var(--bg-dark, #0f1520);
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
}

.node-ids code.primary {
  border: 1px solid rgba(78, 205, 196, 0.45);
  color: var(--accent, #4ecdc4);
}

.node-ids {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.provider-id {
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
}

.action-toolbar {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.action-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.action-btn {
  border: 1px solid var(--border-hover, #2a3a4e);
  background: var(--bg-elevated, #222d3d);
  color: var(--text, #e8edf3);
  border-radius: 8px;
  padding: 0.4rem 0.7rem;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}

.action-btn:hover:not(:disabled) {
  border-color: var(--accent, #4ecdc4);
}

.action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.action-btn.ghost {
  background: transparent;
  font-weight: 500;
}

.action-btn.ghost.active {
  border-color: var(--accent, #4ecdc4);
  color: var(--accent, #4ecdc4);
}

.action-btn.action-run:not(:disabled) {
  background: rgba(78, 205, 196, 0.12);
  border-color: rgba(78, 205, 196, 0.4);
  color: var(--accent, #4ecdc4);
}

.action-error {
  color: var(--coral, #ff6b6b);
  font-size: 0.85rem;
  margin: 0 0 0.75rem;
}

.action-message {
  font-size: 0.85rem;
  margin: 0 0 0.75rem;
  color: var(--text-secondary, #8899aa);
}

.inspect-pane {
  margin-top: 0.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border, #1e2a3a);
}

.inspect-pane h3 {
  margin: 0 0 0.4rem;
  font-size: 0.95rem;
}

.inspect-pane h4 {
  margin: 0.65rem 0 0.3rem;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted, #6b7f93);
}

.inspect-pane pre {
  margin: 0.4rem 0 0;
  padding: 0.65rem 0.75rem;
  background: var(--bg-dark, #0f1520);
  border-radius: 8px;
  font-family: var(--font-mono, monospace);
  font-size: 0.75rem;
  line-height: 1.4;
  overflow: auto;
  max-height: 16rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.history-meta {
  margin: 0.4rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.history-meta dt {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-muted, #6b7f93);
  margin-bottom: 0.1rem;
}

.history-meta dd {
  margin: 0;
  font-size: 0.88rem;
}

.muted {
  color: var(--text-secondary, #8899aa);
}

.small {
  font-size: 0.8rem;
  line-height: 1.4;
}

.empty-detail {
  margin: 0;
  line-height: 1.45;
}
</style>

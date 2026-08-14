<script setup>
/**
 * Per-stage detail panel (§18 / step 2.4 + Test Node panel at 4.2).
 *
 * Executable actions (Run / Test / Regenerate / Run From Here) post the same
 * body the Workflow canvas would send to POST /api/workflow/run. Test opens
 * the Test Node panel (input picker → node_isolated) instead of firing
 * immediately. Inspect actions read the current execution's node records.
 * Approve is durable at 2.6.
 */
import { computed, ref, watch } from 'vue'

import AttemptHistory from '@/features/artifacts/components/AttemptHistory.vue'
import {
  ACTION_HINTS,
  ACTION_LABELS,
  actionRequiresProvider,
  buildStageRunRequest,
  canApproveStage,
  isExecutableAction,
  stagePrimaryTarget,
} from '../stageActions.js'
import { sourceModeLabel, sourceModeRequiresProvider } from '../sourceModes.js'
import { statusLabel } from '../stageStatus.js'
import TestNodePanel from './TestNodePanel.vue'

/** Stage key → primary artifact kind for history (step 4.3). */
const STAGE_KIND = {
  script: 'script',
  tts: 'audio',
  timing: 'alignment',
  segments: 'segments',
  scenes: 'scene_spec',
  images: 'image',
  videos: 'video',
  captions: 'captions',
  music: 'music',
  composer: 'timeline',
  export: 'export',
}

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
  /** Job source.mode when bound (step 2.5); drives Script provider UI. */
  scriptSourceMode: { type: String, default: null },
  /**
   * Explicit override: when non-null, controls whether the Script stage shows
   * provider UI. Paste / Manual pass false even if the graph has story.generate.
   */
  scriptProviderRequired: { type: Boolean, default: null },
  /** Bound Job id — Test Node never advances this Job (step 4.2). */
  jobId: { type: String, default: '' },
  /**
   * node type → definition (inputs/ports) from GET /api/workflow/node-types.
   * Used by the Test Node panel to render InputPickers.
   */
  nodeTypes: { type: Object, default: () => ({}) },
  /** Last Test Node result for the primary node (from_sample_data, etc.). */
  testResult: { type: Object, default: null },
  /**
   * Optional preloaded attempt history (tests / parent-owned fetch).
   * When absent, AttemptHistory loads from the artifact API using jobId + kind.
   */
  attemptHistory: { type: Object, default: null },
  /** Focus artifact id for history (optional; chain lookup uses job + kind). */
  historyArtifactId: { type: String, default: '' },
  historySceneId: { type: String, default: '' },
})

const emit = defineEmits(['run', 'inspect', 'test-run'])

const inspectPane = ref(null) // 'input' | 'output' | 'history' | 'provider' | null
const showTestPanel = ref(false)

watch(
  () => props.stage?.key,
  () => {
    inspectPane.value = null
    showTestPanel.value = false
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

const isScriptStage = computed(() => props.stage?.key === 'script')

/**
 * Provider UI for the Script stage follows the Job source mode (§6):
 * Paste / Manual never show a provider even when the graph is provider-capable.
 * Other stages still use graph-derived provider_capable.
 */
const showProviderUi = computed(() => {
  if (!props.stage) return false
  if (isScriptStage.value) {
    if (props.scriptProviderRequired !== null && props.scriptProviderRequired !== undefined) {
      return Boolean(props.scriptProviderRequired)
    }
    if (props.scriptSourceMode) {
      return sourceModeRequiresProvider(props.scriptSourceMode)
    }
  }
  return Boolean(props.stage.provider_capable)
})

const scriptModeDisplay = computed(() => {
  if (!isScriptStage.value || !props.scriptSourceMode) return null
  return sourceModeLabel(props.scriptSourceMode)
})

const executableActions = ['run', 'test', 'regenerate', 'run_from_here']
const inspectActions = ['view_input', 'view_output', 'provider', 'history', 'approve']

const primaryNodeType = computed(() => {
  const id = primaryNodeId.value
  if (!id) return ''
  const node = (props.workflow?.nodes || []).find((n) => n.id === id)
  return node?.type || ''
})

const primaryPorts = computed(() => {
  const typeKey = primaryNodeType.value
  const def = typeKey ? props.nodeTypes?.[typeKey] : null
  return Array.isArray(def?.inputs) ? def.inputs : []
})

const providerLabel = computed(() => {
  if (!showProviderUi.value) return ''
  return props.stage?.active_provider_instance_id || 'Not selected'
})

/** Artifact kind for the History pane (step 4.3 version chain). */
const historyKind = computed(() => {
  const key = props.stage?.key
  return (key && STAGE_KIND[key]) || 'image'
})

const showAttemptHistory = computed(
  () =>
    inspectPane.value === 'history'
    && Boolean(props.jobId || props.historyArtifactId || props.attemptHistory),
)

function showProviderAction(action) {
  if (action !== 'provider') return true
  // Provider selection appears only where the stage needs one (§6, §19).
  return showProviderUi.value
}

function actionDisabled(action) {
  if (action === 'approve') return !approveEnabled.value
  if (action === 'test') {
    // Test opens the panel even while another production run is active —
    // the test path never advances the Job. Still block while a test is
    // itself running (props.running).
    return !hasMembers.value || !(props.workflowId || props.workflow) || props.running
  }
  if (isExecutableAction(action)) return !canRunActions.value
  // Inspect actions need a stage; history/input/output prefer a record.
  if (!props.stage) return true
  if (action === 'provider') return !showProviderUi.value
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
  if (action === 'test') {
    // Step 4.2: open the Test Node panel rather than firing isolation blind.
    if (actionDisabled(action)) return
    showTestPanel.value = !showTestPanel.value
    inspectPane.value = null
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
    requiresProvider: showProviderUi.value && actionRequiresProvider(action, props.stage),
  })
}

function onTestRun(payload) {
  emit('test-run', {
    stage: props.stage,
    nodeId: payload.nodeId,
    runMode: payload.runMode,
    inputBindings: payload.inputBindings,
    currentJobId: payload.currentJobId || props.jobId || undefined,
    workflowId: props.workflowId || undefined,
    workflow: props.workflowId ? undefined : props.workflow || undefined,
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
        <div v-if="scriptModeDisplay">
          <dt>Script mode</dt>
          <dd>{{ scriptModeDisplay }}</dd>
        </div>
        <div v-if="showProviderUi">
          <dt>Provider</dt>
          <dd>
            <span class="provider-id">
              {{ stage.active_provider_instance_id || 'Not selected' }}
            </span>
          </dd>
        </div>
        <div v-else>
          <dt>Provider</dt>
          <dd class="muted">
            {{
              isScriptStage && scriptModeDisplay
                ? 'Not required for this Script mode'
                : 'Local (not provider-capable)'
            }}
          </dd>
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
      <p v-else-if="executionActive && !showTestPanel" class="action-message muted" role="status">
        A run is in progress. Wait for it to finish before starting another.
      </p>

      <TestNodePanel
        v-if="showTestPanel && primaryNodeId"
        :title="stage.label"
        :node-id="primaryNodeId"
        :node-type="primaryNodeType"
        :ports="primaryPorts"
        :current-job-id="jobId"
        :provider-label="providerLabel"
        :running="running"
        :last-result="testResult"
        @run="onTestRun"
        @close="showTestPanel = false"
      />

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
          Per-node run attempts for <code>{{ primaryNodeId || '—' }}</code>
          <template v-if="executionId"> on <code>{{ executionId }}</code></template>,
          plus immutable artifact version comparison (provider instance, seed,
          prompt revision).
        </p>
        <dl class="history-meta">
          <div>
            <dt>Run attempts</dt>
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

        <AttemptHistory
          v-if="showAttemptHistory"
          :artifact-id="historyArtifactId"
          :job-id="jobId"
          :kind="historyKind"
          :scene-id="historySceneId"
          :history="attemptHistory"
        />
        <p v-else class="muted small">
          Bind a Job to load artifact version history for this stage
          (<code>{{ historyKind }}</code>).
        </p>
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
            <dt>Required for this mode</dt>
            <dd>{{ showProviderUi ? 'Yes' : 'No' }}</dd>
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

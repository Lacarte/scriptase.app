<script setup>
/**
 * Per-stage detail panel (§18 / step 2.4 + Test Node panel at 4.2).
 *
 * Executable actions (Run / Test / Regenerate / Run From Here) post the same
 * body the Workflow canvas would send to POST /api/workflow/run. Test opens
 * the Test Node panel (input picker → node_isolated) instead of firing
 * immediately. Inspect actions read the current execution's node records.
 * Approve is durable at 2.6.
 *
 * Step 11.4: the projection's `stage.issues` render here, and the History pane
 * carries the Job's repair history (routed node, what was retried, superseded
 * versions) from the read-only repair-history endpoint.
 *
 * Step 16.3: `stage.score` renders the script virality verdict on the Script
 * stage, above the actions, so a weak hook is visible before anyone spends a
 * TTS or image call on it.
 */
import { computed, ref, watch } from 'vue'

import AttemptHistory from '@/features/artifacts/components/AttemptHistory.vue'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
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
import RepairHistoryPane from './RepairHistoryPane.vue'
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

/**
 * Stage key → provider domain for capability display (step 6.1).
 * Only provider-capable stages map; local services (captions/music) do not.
 */
const STAGE_PROVIDER_DOMAIN = {
  script: 'script',
  voice: 'tts',
  scenes: 'scene_director',
  images: 'image',
  videos: 'video',
  review: 'review',
}

/**
 * Scored dimension id → display name (step 16.3). The six ids are a frozen
 * part of the 16.1 contract, so this map is bounded and cannot silently grow;
 * an unknown id still renders via the humanizing fallback rather than blank.
 */
const DIMENSION_LABELS = {
  hook: 'Hook',
  opening_line: 'Opening line',
  pacing: 'Pacing',
  open_loops: 'Open loops',
  cta: 'Call to action',
  balance: 'Section balance',
}

/**
 * Reason codes are structured machine strings by contract — the scorer states
 * what it measured and never writes prose. Turning `hook_missing` into
 * "Hook missing" here keeps the panel readable without shipping a forty-entry
 * translation table that would drift the moment a scorer version added a code.
 */
function humanizeCode(code) {
  const text = String(code || '').replace(/_/g, ' ').trim()
  if (!text) return ''
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** One chip per distinct reason code, in the order the scorer emitted them. */
function dedupeReasons(reasons) {
  const seen = new Set()
  const out = []
  for (const reason of Array.isArray(reasons) ? reasons : []) {
    const code = reason?.code
    if (!code || seen.has(code)) continue
    seen.add(code)
    out.push({
      code,
      label: humanizeCode(code),
      impact: reason.impact === 'positive' ? 'positive' : 'negative',
    })
  }
  return out
}

const providerCatalog = useProviderCatalogStore()

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
  /**
   * Optional preloaded repair history (tests / parent-owned fetch). When
   * absent, RepairHistoryPane loads it from the Job API (step 11.4).
   */
  repairHistory: { type: Object, default: null },
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

/** Registry display name for a member node, e.g. "Scene Director". */
function nodeDisplayName(nodeId) {
  const node = (props.workflow?.nodes || []).find((n) => n.id === nodeId)
  const typeKey = node?.type || ''
  return props.nodeTypes?.[typeKey]?.display_name || typeKey || ''
}

const primaryPorts = computed(() => {
  const typeKey = primaryNodeType.value
  const def = typeKey ? props.nodeTypes?.[typeKey] : null
  return Array.isArray(def?.inputs) ? def.inputs : []
})

const providerLabel = computed(() => {
  if (!showProviderUi.value) return ''
  return props.stage?.active_provider_instance_id || 'Not selected'
})

/** Provider domain for this stage (image / video / …), or null. */
const stageProviderDomain = computed(() => {
  const key = props.stage?.key
  return (key && STAGE_PROVIDER_DOMAIN[key]) || null
})

/**
 * Domain the Test Node picker offers instances from (step 13.3). A stage that
 * shows no provider UI — Paste-mode Script, a local service — offers no
 * override either, or the picker would imply a choice the run cannot honour.
 */
const testProviderDomain = computed(() =>
  showProviderUi.value ? stageProviderDomain.value || '' : '',
)

/**
 * Granted capabilities of the active instance, filtered by domain vocabulary
 * so an undeclared key is never offered in the step UI (step 6.1).
 */
const stageProviderCapabilities = computed(() => {
  const domain = stageProviderDomain.value
  const instanceId = props.stage?.active_provider_instance_id
  if (!domain || !instanceId) return []
  return providerCatalog.grantedCapabilitiesOf(domain, instanceId)
})

/** Artifact kind for the History pane (step 4.3 version chain). */
const historyKind = computed(() => {
  const key = props.stage?.key
  return (key && STAGE_KIND[key]) || 'image'
})

/**
 * Open ReviewIssue ids the projection attached to this stage (step 11.4).
 * The list is structured data from the backend — never free text.
 */
const stageIssues = computed(() => {
  const ids = props.stage?.issues
  return Array.isArray(ids) ? ids.filter((id) => typeof id === 'string' && id) : []
})

/**
 * The script virality verdict the projection attached to this stage (16.3).
 * Only `script.analyze` produces one, so this is null on every other stage
 * and on a Script stage whose analyzer has not run yet.
 */
const stageScore = computed(() => {
  const score = props.stage?.score
  if (!score || typeof score !== 'object') return null
  return typeof score.score === 'number' ? score : null
})

/**
 * Tri-state, and the three states say different things: below the Channel
 * bar, above it, or never measured because no Channel set one. Collapsing the
 * last into "passed" would claim a check that never happened.
 */
const scoreGate = computed(() => {
  const score = stageScore.value
  if (!score || typeof score.threshold !== 'number') return null
  return {
    threshold: score.threshold,
    passed: score.passed === true,
  }
})

const scoreDimensions = computed(() => {
  const dimensions = stageScore.value?.dimensions
  if (!Array.isArray(dimensions)) return []
  return dimensions
    .filter((d) => d && typeof d === 'object' && d.id)
    .map((d) => {
      const value = typeof d.score === 'number' ? d.score : 0
      return {
        id: d.id,
        label: DIMENSION_LABELS[d.id] || humanizeCode(d.id),
        // The scorer normalizes every dimension to 0..1; the panel shows the
        // percentage rather than the weighted points so a strong dimension
        // with a small weight does not read as a failure.
        percent: Math.round(Math.min(1, Math.max(0, value)) * 100),
        // Deduped by code. A dimension can report the same fault once per
        // section — `balance` emits `section_missing` for each missing one —
        // and repeating the chip says nothing the first one did not, besides
        // colliding on the render key.
        reasons: dedupeReasons(d.reasons),
      }
    })
})

// Load the catalog once so step provider badges resolve without a second path.
watch(
  () => showProviderUi.value,
  (visible) => {
    if (visible) providerCatalog.loadCatalog()
  },
  { immediate: true },
)

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
    providerInstanceId: payload.providerInstanceId || undefined,
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
                <span v-if="nodeDisplayName(nid)" class="node-name">{{ nodeDisplayName(nid) }}</span>
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
        <div v-if="stageIssues.length">
          <dt>Open issues</dt>
          <dd>
            <ul class="node-ids issue-ids" data-testid="stage-issues">
              <li v-for="issueId in stageIssues" :key="issueId">
                <code>{{ issueId }}</code>
              </li>
            </ul>
            <p class="muted small issue-hint">
              Raised by review. Open History for the node each was routed to
              and the versions the repair superseded.
            </p>
          </dd>
        </div>
      </dl>

      <section
        v-if="stageScore"
        class="score-pane"
        data-testid="stage-score"
        aria-label="Script virality score"
      >
        <header class="score-head">
          <h3>Virality score</h3>
          <span
            class="score-value"
            :data-band="stageScore.band || 'unknown'"
            data-testid="score-value"
          >
            {{ stageScore.score }}
          </span>
          <span v-if="stageScore.band" class="score-band">{{ stageScore.band }}</span>
        </header>

        <p v-if="scoreGate" class="score-gate muted small" data-testid="score-gate">
          <span :class="scoreGate.passed ? 'gate-pass' : 'gate-fail'">
            {{ scoreGate.passed ? 'Meets' : 'Below' }}
          </span>
          the Channel minimum of {{ scoreGate.threshold }}.
          <template v-if="!scoreGate.passed">
            Review raised an issue routed back to Script.
          </template>
        </p>
        <p v-else class="score-gate muted small" data-testid="score-gate">
          Advisory only — this Channel sets no virality threshold.
        </p>

        <ul v-if="scoreDimensions.length" class="score-dimensions" data-testid="score-dimensions">
          <li v-for="dimension in scoreDimensions" :key="dimension.id" class="score-dimension">
            <div class="dimension-head">
              <span class="dimension-label">{{ dimension.label }}</span>
              <span class="dimension-percent">{{ dimension.percent }}%</span>
            </div>
            <div
              class="dimension-bar"
              role="img"
              :aria-label="`${dimension.label} scored ${dimension.percent} percent`"
            >
              <span class="dimension-fill" :style="{ width: `${dimension.percent}%` }" />
            </div>
            <ul v-if="dimension.reasons.length" class="dimension-reasons">
              <li
                v-for="reason in dimension.reasons"
                :key="reason.code"
                :class="`impact-${reason.impact}`"
              >
                {{ reason.label }}
              </li>
            </ul>
          </li>
        </ul>
      </section>

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
        :provider-domain="testProviderDomain"
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

        <RepairHistoryPane
          class="repair-pane"
          :job-id="jobId"
          :issue-ids="stageIssues"
          :history="repairHistory"
        />
      </section>

      <section v-if="inspectPane === 'provider'" class="inspect-pane" aria-label="Provider">
        <h3>Provider</h3>
        <p class="muted small">
          Provider selection is metadata on the stage — never a “-P” suffix on
          the name. Capabilities are declared per provider and filtered by the
          domain vocabulary (step 6.1).
        </p>
        <dl class="history-meta">
          <div>
            <dt>Active instance</dt>
            <dd>
              <code>{{ stage.active_provider_instance_id || 'Not selected' }}</code>
            </dd>
          </div>
          <div v-if="stageProviderDomain">
            <dt>Domain</dt>
            <dd><code>{{ stageProviderDomain }}</code></dd>
          </div>
          <div>
            <dt>Required for this mode</dt>
            <dd>{{ showProviderUi ? 'Yes' : 'No' }}</dd>
          </div>
          <div v-if="stageProviderCapabilities.length">
            <dt>Capabilities</dt>
            <dd>
              <p
                class="provider-capabilities"
                data-testid="stage-provider-capabilities"
              >
                <span
                  v-for="name in stageProviderCapabilities"
                  :key="name"
                  class="cap-badge"
                >{{ name }}</span>
              </p>
            </dd>
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
/* Raised panel — the top hairline is the signature. */
.step-detail {
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  padding: 16px 18px 18px;
  min-height: 192px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.detail-head h2 {
  margin: 0;
  font-family: var(--display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: var(--text);
}

/* Status badge — the ramp, never the accent. */
.status-badge {
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 20px;
  white-space: nowrap;
  color: var(--queue);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line);
}

.status-badge[data-status='running'] {
  color: var(--run);
  background: var(--run-dim);
  box-shadow: inset 0 0 0 1px var(--run-line);
}

.status-badge[data-status='succeeded'] {
  color: var(--ok);
  background: var(--ok-dim);
  box-shadow: inset 0 0 0 1px var(--ok-line);
}

.status-badge[data-status='failed'] {
  color: var(--fail);
  background: var(--fail-dim);
  box-shadow: inset 0 0 0 1px var(--fail-line);
}

.status-badge[data-status='invalid'],
.status-badge[data-status='stale'] {
  color: var(--warn);
  background: var(--warn-dim);
  box-shadow: inset 0 0 0 1px var(--warn-line);
}

.status-badge[data-status='awaiting_approval'] {
  color: var(--sched);
  background: var(--sched-dim);
  box-shadow: inset 0 0 0 1px var(--sched-line);
}

.detail-grid {
  margin: 0 0 16px;
  display: flex;
  flex-direction: column;
  gap: 13px;
}

.detail-grid dt {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
  margin-bottom: 5px;
}

.detail-grid dd {
  margin: 0;
  font-size: 12.5px;
  color: var(--text);
}

/* Inline code reads as a recessed well. */
.detail-grid code,
.node-ids code {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  border-radius: 5px;
  padding: 2px 6px;
}

.issue-ids code {
  color: var(--warn);
  background: var(--warn-dim);
  border-color: var(--warn-line);
}

.issue-hint {
  margin: 7px 0 0;
}

.repair-pane {
  margin-top: 14px;
  padding-top: 13px;
  border-top: 1px solid var(--line-soft);
}

/* Step 16.3 — script virality verdict. */
.score-pane {
  margin-top: 15px;
  padding-top: 14px;
  border-top: 1px solid var(--line-soft);
}

.score-head {
  display: flex;
  align-items: baseline;
  gap: 9px;
}

.score-head h3 {
  margin: 0;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.score-value {
  margin-left: auto;
  font-family: var(--display);
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.5px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}

.score-value[data-band='strong'] {
  color: var(--ok);
}

.score-value[data-band='solid'] {
  color: var(--run);
}

.score-value[data-band='weak'] {
  color: var(--warn);
}

.score-value[data-band='poor'] {
  color: var(--fail);
}

.score-band {
  font-family: var(--mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.score-gate {
  margin: 8px 0 0;
}

.gate-pass {
  color: var(--ok);
  font-weight: 600;
}

.gate-fail {
  color: var(--fail);
  font-weight: 600;
}

.score-dimensions {
  list-style: none;
  margin: 13px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 11px;
}

.dimension-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  color: var(--text-2);
}

.dimension-percent {
  font-family: var(--mono);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text);
  font-weight: 600;
}

/* Progress track — the prototype's 4px rail. */
.dimension-bar {
  margin-top: 5px;
  height: 4px;
  border-radius: 3px;
  background: var(--raise);
  overflow: hidden;
}

.dimension-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--run);
  transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.dimension-reasons {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.dimension-reasons li {
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 20px;
  background: var(--bg-2);
  color: var(--queue);
  box-shadow: inset 0 0 0 1px var(--line);
}

.dimension-reasons li.impact-negative {
  color: var(--warn);
  background: var(--warn-dim);
  box-shadow: inset 0 0 0 1px var(--warn-line);
}

.dimension-reasons li.impact-positive {
  color: var(--ok);
  background: var(--ok-dim);
  box-shadow: inset 0 0 0 1px var(--ok-line);
}

/* The primary node is an active selection — the accent's other home. */
.node-ids code.primary {
  color: var(--accent);
  background: var(--accent-dim);
  border-color: var(--accent-line);
}

.node-ids {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.node-name {
  margin-left: 7px;
  font-size: 11.5px;
  color: var(--faint);
}

.provider-capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: 0;
}

.cap-badge {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.3px;
  padding: 3px 9px;
  border-radius: 20px;
  background: var(--bg-2);
  color: var(--text-2);
  border: 1px solid var(--line-soft);
}

.provider-id {
  font-family: var(--mono);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}

.action-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.action-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* Matches the shared `.action-btn` primitive so the two are identical. */
.action-btn {
  padding: 4px 10px;
  border-radius: 6px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: border-color 0.14s, color 0.14s, background 0.14s;
}

.action-btn:hover:not(:disabled) {
  border-color: var(--accent-line);
  background: var(--accent-dim);
  color: var(--text);
}

.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.action-btn.ghost {
  background: transparent;
  font-weight: 600;
}

.action-btn.ghost.active {
  border-color: var(--accent-line-2);
  background: var(--accent-wash);
  color: var(--accent);
}

.action-btn.action-run:not(:disabled) {
  border-color: var(--accent-line);
  background: var(--accent-dim);
  color: var(--accent);
}

/* Advisory banner. */
.action-error {
  margin: 0 0 12px;
  padding: 11px 13px;
  border-radius: var(--r-s);
  background: var(--fail-dim);
  border: 1px solid var(--fail-line);
  color: var(--fail-text);
  font-size: 12.5px;
  line-height: 1.55;
}

.action-message {
  margin: 0 0 12px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-2);
}

.inspect-pane {
  margin-top: 9px;
  padding-top: 13px;
  border-top: 1px solid var(--line-soft);
}

.inspect-pane h3 {
  margin: 0 0 7px;
  font-family: var(--display);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: var(--text);
}

.inspect-pane h4 {
  margin: 12px 0 6px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

/* Recessed well for read-only readouts. */
.inspect-pane pre {
  margin: 8px 0 0;
  padding: 11px 13px;
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-2);
  overflow: auto;
  max-height: 256px;
  white-space: pre-wrap;
  word-break: break-word;
}

.history-meta {
  margin: 8px 0;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.history-meta dt {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
  margin-bottom: 4px;
}

.history-meta dd {
  margin: 0;
  font-size: 12.5px;
  color: var(--text);
}

.muted {
  color: var(--muted);
}

.small {
  font-size: 11.5px;
  line-height: 1.5;
}

.empty-detail {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
}
</style>

<script setup>
/**
 * Production view (§3.1) — ordered step list with live per-step status.
 *
 * Stages come from the backend projection (step 2.2). Live updates share the
 * canvas SSE stream (ring-buffer reset + Last-Event-ID). No step array is
 * hardcoded here, and there is no second polling mechanism.
 *
 * Step detail actions (step 2.4) map onto existing engine run modes only.
 * Job creation and Script stage modes land in step 2.5.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { listExecutions, listWorkflows } from './api.js'
import StepDetailPanel from './components/StepDetailPanel.vue'
import { useProductionStages } from './composables/useProductionStages.js'
import { ACTION_LABELS } from './stageActions.js'
import { statusLabel } from './stageStatus.js'

const route = useRoute()
const router = useRouter()

const {
  stages,
  workflowId,
  workflowDocument,
  executionId,
  executionStatus,
  loading,
  error,
  streamError,
  nodeRecords,
  actionRunning,
  actionError,
  actionMessage,
  hasStages,
  active,
  loadWorkflow,
  hydrateFromExecution,
  runStageAction,
  dispose,
} = useProductionStages()

const workflows = ref([])
const executions = ref([])
const workflowsLoading = ref(false)
const executionsLoading = ref(false)
const selectedWorkflowId = ref('')
const selectedExecutionId = ref('')
const selectedStageKey = ref(null)

const selectedStage = computed(() =>
  stages.value.find((s) => s.key === selectedStageKey.value) || null,
)

const headerMeta = computed(() => {
  const bits = []
  if (workflowId.value) bits.push(`Workflow ${workflowId.value}`)
  if (executionId.value) bits.push(`Run ${executionId.value}`)
  if (executionStatus.value) bits.push(statusLabel(executionStatus.value))
  return bits.join(' · ')
})

async function refreshWorkflows() {
  workflowsLoading.value = true
  try {
    const data = await listWorkflows({ limit: 200 })
    workflows.value = data.workflows || data.items || []
  } catch {
    workflows.value = []
  } finally {
    workflowsLoading.value = false
  }
}

async function refreshExecutions(wfId) {
  if (!wfId) {
    executions.value = []
    return
  }
  executionsLoading.value = true
  try {
    const data = await listExecutions({ workflowId: wfId, limit: 50 })
    executions.value = data.executions || []
  } catch {
    executions.value = []
  } finally {
    executionsLoading.value = false
  }
}

async function bindFromRoute() {
  const qExec = String(route.query.execution_id || route.query.executionId || '').trim()
  const qWf = String(route.query.workflow_id || route.query.workflowId || '').trim()

  selectedExecutionId.value = qExec
  selectedWorkflowId.value = qWf

  if (qExec) {
    await hydrateFromExecution(qExec)
    if (workflowId.value) {
      selectedWorkflowId.value = workflowId.value
      await refreshExecutions(workflowId.value)
    }
    return
  }
  if (qWf) {
    await loadWorkflow(qWf)
    await refreshExecutions(qWf)
    return
  }
  // Nothing selected — clear stages, keep the pickers.
  dispose()
  stages.value = []
}

function onWorkflowChange() {
  const id = selectedWorkflowId.value
  selectedExecutionId.value = ''
  selectedStageKey.value = null
  router.replace({
    name: 'production',
    query: id ? { workflow_id: id } : {},
  })
}

function onExecutionChange() {
  const id = selectedExecutionId.value
  selectedStageKey.value = null
  const query = {}
  if (selectedWorkflowId.value) query.workflow_id = selectedWorkflowId.value
  if (id) query.execution_id = id
  router.replace({ name: 'production', query })
}

function selectStage(stage) {
  selectedStageKey.value = stage?.key ?? null
}

function openWorkflowCanvas() {
  const query = {}
  if (workflowId.value || selectedWorkflowId.value) {
    query.workflow_id = workflowId.value || selectedWorkflowId.value
  }
  if (executionId.value) query.execution_id = executionId.value
  router.push({ name: 'workflow', query })
}

function stageOrdinal(stage) {
  // Prefer 1-based display ordinals matching §3.1.
  if (typeof stage.ordinal === 'number') return stage.ordinal + 1
  return '·'
}

/**
 * Step detail executable action — same /api/workflow/run body the canvas sends.
 * After queueing, bind the new execution into the route so reload survives.
 */
async function onStageRun({ action, body }) {
  if (!selectedStage.value) return
  try {
    const result = await runStageAction(action, selectedStage.value, { body })
    selectedExecutionId.value = result.execution_id
    const query = {
      workflow_id: workflowId.value || selectedWorkflowId.value,
      execution_id: result.execution_id,
    }
    await router.replace({ name: 'production', query })
    await refreshExecutions(query.workflow_id)
  } catch {
    // actionError is already set on the composable.
  }
}

function onStageInspect({ action }) {
  if (action === 'approve') {
    // Durable approval is step 2.6; surface a clear message until then.
    actionMessage.value = canShowApproveMessage(selectedStage.value)
      ? 'Approval received — durable checkpoint resume lands in step 2.6.'
      : 'Approve is available when a stage is awaiting approval (step 2.6).'
  }
}

function canShowApproveMessage(stage) {
  return String(stage?.status || '') === 'awaiting_approval'
}

// Keep ACTION_LABELS referenced so tree-shaking never drops the module edge
// used by tests that import labels alongside the page.
void ACTION_LABELS

watch(
  () => [route.query.execution_id, route.query.executionId, route.query.workflow_id, route.query.workflowId],
  () => {
    void bindFromRoute()
  },
)

onMounted(async () => {
  await refreshWorkflows()
  await bindFromRoute()
})
</script>

<template>
  <section class="production-page">
    <header class="page-header">
      <div>
        <h1>Production</h1>
        <p class="lede">
          Step list projected from the workflow graph. Live status shares the
          same execution stream as the Workflow canvas — one run, two views.
        </p>
        <p v-if="headerMeta" class="meta-line">{{ headerMeta }}</p>
      </div>
      <div class="actions">
        <button
          type="button"
          class="ghost"
          :disabled="!workflowId && !selectedWorkflowId"
          @click="openWorkflowCanvas"
        >
          Open Workflow
        </button>
      </div>
    </header>

    <div class="pickers">
      <label class="picker">
        <span class="picker-label">Workflow</span>
        <select
          v-model="selectedWorkflowId"
          :disabled="workflowsLoading || loading"
          @change="onWorkflowChange"
        >
          <option value="">Select a workflow…</option>
          <option
            v-for="wf in workflows"
            :key="wf.workflow_id || wf.id"
            :value="wf.workflow_id || wf.id"
          >
            {{ wf.name || wf.workflow_id || wf.id }}
          </option>
        </select>
      </label>

      <label class="picker">
        <span class="picker-label">Run</span>
        <select
          v-model="selectedExecutionId"
          :disabled="!selectedWorkflowId || executionsLoading || loading"
          @change="onExecutionChange"
        >
          <option value="">Workflow only (idle stages)</option>
          <option
            v-for="ex in executions"
            :key="ex.execution_id"
            :value="ex.execution_id"
          >
            {{ ex.execution_id }}
            <template v-if="ex.status"> — {{ statusLabel(ex.status) }}</template>
          </option>
        </select>
      </label>

      <span
        v-if="active"
        class="live-pill"
        title="Receiving live execution events over SSE"
      >
        Live
      </span>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="streamError && !error" class="stream-warn" role="status">{{ streamError }}</p>
    <p v-if="loading" class="muted">Loading stages…</p>

    <div v-else-if="hasStages" class="stage-layout">
      <ol class="stage-list" aria-label="Production stages">
        <li
          v-for="stage in stages"
          :key="stage.key"
          class="stage-row"
          :class="[
            `status-${stage.status || 'idle'}`,
            { selected: selectedStageKey === stage.key },
          ]"
          @click="selectStage(stage)"
        >
          <span class="ordinal">{{ stageOrdinal(stage) }}</span>
          <div class="stage-body">
            <strong class="stage-label">{{ stage.label }}</strong>
            <span class="stage-sub">
              <span v-if="stage.provider_capable" class="provider-meta">
                {{ stage.active_provider_instance_id || 'Provider-capable' }}
              </span>
              <span v-else class="provider-meta muted-meta">Local</span>
              <span
                v-if="(stage.node_ids || []).length"
                class="node-count"
                :title="(stage.node_ids || []).join(', ')"
              >
                {{ stage.node_ids.length }} node{{ stage.node_ids.length === 1 ? '' : 's' }}
              </span>
            </span>
          </div>
          <span class="status-badge" :data-status="stage.status || 'idle'">
            {{ statusLabel(stage.status) }}
          </span>
        </li>
      </ol>

      <StepDetailPanel
        :stage="selectedStage"
        :workflow-id="workflowId || selectedWorkflowId"
        :workflow="workflowDocument"
        :node-records="nodeRecords"
        :execution-id="executionId || ''"
        :execution-active="active"
        :running="actionRunning"
        :action-error="actionError"
        :action-message="actionMessage"
        @run="onStageRun"
        @inspect="onStageInspect"
      />
    </div>

    <div v-else-if="!loading" class="empty muted">
      <p v-if="!selectedWorkflowId">
        Choose a workflow to project its Production stages. The list is computed
        on the backend from the graph — never hardcoded here.
      </p>
      <p v-else>
        This workflow has no production stages to project.
      </p>
    </div>
  </section>
</template>

<style scoped>
.production-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.5rem 1.25rem 3rem;
  font-family: var(--font-body, system-ui, sans-serif);
  color: var(--text, #e8edf3);
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  margin-bottom: 1.25rem;
}

h1 {
  margin: 0 0 0.35rem;
  font-size: 1.6rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  font-family: var(--font-display, system-ui, sans-serif);
}

.lede {
  margin: 0;
  max-width: 40rem;
  color: var(--text-secondary, #8899aa);
  font-size: 0.95rem;
  line-height: 1.45;
}

.meta-line {
  margin: 0.45rem 0 0;
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
  color: var(--text-muted, #6b7f93);
}

.actions {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}

button {
  border: 1px solid var(--border-hover, #2a3a4e);
  background: var(--bg-surface, #161d2a);
  color: var(--text, #e8edf3);
  border-radius: 8px;
  padding: 0.45rem 0.85rem;
  font-size: 0.9rem;
  cursor: pointer;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

button.ghost {
  background: transparent;
}

.pickers {
  display: flex;
  flex-wrap: wrap;
  gap: 0.85rem;
  align-items: flex-end;
  margin-bottom: 1.25rem;
}

.picker {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-width: 14rem;
  flex: 1 1 14rem;
}

.picker-label {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--text-muted, #6b7f93);
}

.picker select {
  background: var(--bg-surface, #161d2a);
  border: 1px solid var(--border, #1e2a3a);
  border-radius: 8px;
  color: var(--text, #e8edf3);
  padding: 0.5rem 0.65rem;
  font-size: 0.9rem;
}

.live-pill {
  align-self: center;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 0.3rem 0.65rem;
  border-radius: 999px;
  background: rgba(255, 159, 67, 0.15);
  color: var(--accent-active, #ff9f43);
  border: 1px solid rgba(255, 159, 67, 0.35);
  animation: pulse 1.6s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.error {
  color: var(--coral, #ff6b6b);
  background: rgba(255, 107, 107, 0.08);
  border: 1px solid rgba(255, 107, 107, 0.25);
  border-radius: 8px;
  padding: 0.55rem 0.85rem;
  margin: 0 0 1rem;
}

.stream-warn {
  color: var(--accent-warning, #ffb347);
  font-size: 0.85rem;
  margin: 0 0 0.75rem;
}

.muted {
  color: var(--text-secondary, #8899aa);
}

.stage-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}

@media (max-width: 800px) {
  .stage-layout {
    grid-template-columns: 1fr;
  }
}

.stage-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.stage-row {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  background: var(--bg-surface, #161d2a);
  border: 1px solid var(--border, #1e2a3a);
  border-radius: 10px;
  padding: 0.7rem 0.9rem;
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}

.stage-row:hover {
  border-color: var(--border-hover, #2a3a4e);
  background: var(--bg-surface-hover, #1c2536);
}

.stage-row.selected {
  border-color: var(--accent, #4ecdc4);
  box-shadow: 0 0 0 1px rgba(78, 205, 196, 0.25);
}

.ordinal {
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-muted, #6b7f93);
  min-width: 1.5rem;
  text-align: right;
}

.stage-body {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.stage-label {
  font-size: 1rem;
  font-weight: 600;
}

.stage-sub {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  font-size: 0.78rem;
  color: var(--text-secondary, #8899aa);
}

.provider-meta {
  font-family: var(--font-mono, monospace);
}

.muted-meta {
  opacity: 0.75;
}

.node-count {
  opacity: 0.8;
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

.status-badge[data-status='cancelled'] {
  background: rgba(139, 139, 139, 0.12);
  color: var(--accent-muted, #8b8b8b);
}

.status-badge[data-status='awaiting_approval'] {
  background: rgba(167, 139, 250, 0.12);
  color: var(--accent-secondary, #a78bfa);
  border-color: rgba(167, 139, 250, 0.35);
}

.empty {
  padding: 2rem 0;
  line-height: 1.5;
}
</style>

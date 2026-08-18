<script setup>
/**
 * Production view (§3.1) — ordered step list with live per-step status.
 *
 * Stages come from the backend projection (step 2.2). Live updates share the
 * canvas SSE stream (ring-buffer reset + Last-Event-ID). No step array is
 * hardcoded here, and there is no second polling mechanism.
 *
 * Step detail actions (step 2.4) map onto existing engine run modes only.
 * Job creation and Script stage modes (step 2.5) are Step 0 on this page.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  getExecution,
  getJob,
  getJobCost,
  getNodeTypes,
  listExecutions,
  listWorkflows,
  runWorkflow,
  testJobNode,
} from './api.js'
import JobCreatePanel from './components/JobCreatePanel.vue'
import StepDetailPanel from './components/StepDetailPanel.vue'
import { useProductionStages } from './composables/useProductionStages.js'
import { ACTION_LABELS } from './stageActions.js'
import { sourceModeLabel, sourceModeRequiresProvider } from './sourceModes.js'
import { statusLabel } from './stageStatus.js'
import { onShortcut } from '@/shared/composables/useShortcuts.js'
import { openAppWindow } from '@/shared/utils/openWindow.js'

const route = useRoute()
const router = useRouter()

const {
  stages,
  workflowId,
  workflowDocument,
  executionId,
  executionStatus,
  projectId,
  loading,
  error,
  streamError,
  nodeRecords,
  actionRunning,
  actionError,
  actionMessage,
  queuePosition,
  queueWaiting,
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
const showJobCreate = ref(false)
const activeJobId = ref('')
const activeJobSourceMode = ref(null)
const activeJobExecutionMode = ref(null)
/** Job cost report (step 9.3) — generations + cost by stage / instance. */
const jobCost = ref(null)
const jobCostLoading = ref(false)
const jobCostError = ref('')
/** Registry definitions for the Test Node panel port list (step 4.2). */
const nodeTypes = ref({})
/** Last Test Node result shown in the detail panel. */
const testResult = ref(null)

/** Free-text stage filter — the input `/` focuses (step 0.3). */
const stageFilter = ref('')
/** Row under the keyboard cursor. Distinct from selection: moving is not choosing. */
const focusedStageKey = ref(null)
const stageListEl = ref(null)

const selectedStage = computed(() =>
  stages.value.find((s) => s.key === selectedStageKey.value) || null,
)

const visibleStages = computed(() => {
  const q = stageFilter.value.trim().toLowerCase()
  if (!q) return stages.value
  return stages.value.filter((stage) =>
    `${stage.label || ''} ${stage.key || ''} ${stage.status || ''}`
      .toLowerCase()
      .includes(q),
  )
})

const focusedStage = computed(() =>
  visibleStages.value.find((s) => s.key === focusedStageKey.value) || null,
)

/**
 * Jobs run strictly one at a time (step 13.1), so a queued Job is waiting on
 * a specific number of Jobs ahead of it — say so instead of a bare "Queued".
 */
const queueLabel = computed(() => {
  const position = queuePosition.value
  if (!Number.isFinite(position) || position < 1) return ''
  return queueWaiting.value > 1
    ? `Queued ${position} of ${queueWaiting.value}`
    : `Queued ${position}`
})

const headerMeta = computed(() => {
  const bits = []
  if (activeJobId.value) bits.push(`Job ${activeJobId.value}`)
  if (activeJobSourceMode.value) {
    bits.push(sourceModeLabel(activeJobSourceMode.value))
  }
  if (workflowId.value) bits.push(`Workflow ${workflowId.value}`)
  if (executionId.value) bits.push(`Run ${executionId.value}`)
  if (queueLabel.value) bits.push(queueLabel.value)
  else if (executionStatus.value) bits.push(statusLabel(executionStatus.value))
  return bits.join(' · ')
})

/** Script stage: provider UI only when the Job source mode needs one. */
const scriptProviderVisible = computed(() => {
  if (!activeJobSourceMode.value) return null
  return sourceModeRequiresProvider(activeJobSourceMode.value)
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

async function refreshJobCost(jobId) {
  if (!jobId) {
    jobCost.value = null
    jobCostError.value = ''
    return
  }
  jobCostLoading.value = true
  jobCostError.value = ''
  try {
    const data = await getJobCost(jobId)
    jobCost.value = data?.cost || data || null
  } catch (err) {
    jobCost.value = null
    jobCostError.value = err?.message || String(err)
  } finally {
    jobCostLoading.value = false
  }
}

async function bindJobFromRoute(jobId) {
  if (!jobId) {
    activeJobId.value = ''
    activeJobSourceMode.value = null
    activeJobExecutionMode.value = null
    jobCost.value = null
    return
  }
  try {
    const data = await getJob(jobId)
    const job = data.job || data
    activeJobId.value = job.id || jobId
    activeJobSourceMode.value = job.source?.mode || null
    activeJobExecutionMode.value = job.execution_mode || null
    if (job.workflow_id) {
      selectedWorkflowId.value = job.workflow_id
    }
    // Load cost report in parallel with stage hydrate (step 9.3).
    void refreshJobCost(activeJobId.value)
    if (job.execution_id) {
      selectedExecutionId.value = job.execution_id
      await hydrateFromExecution(job.execution_id)
      if (workflowId.value) {
        selectedWorkflowId.value = workflowId.value
        await refreshExecutions(workflowId.value)
      }
      return
    }
    if (job.workflow_id) {
      await loadWorkflow(job.workflow_id)
      await refreshExecutions(job.workflow_id)
    }
  } catch (err) {
    error.value = err.message || String(err)
    activeJobId.value = jobId
  }
}

async function bindFromRoute() {
  const qExec = String(route.query.execution_id || route.query.executionId || '').trim()
  const qWf = String(route.query.workflow_id || route.query.workflowId || '').trim()
  const qJob = String(route.query.job_id || route.query.jobId || '').trim()
  const qCreate = String(route.query.create || '').trim()

  selectedExecutionId.value = qExec
  selectedWorkflowId.value = qWf
  showJobCreate.value = qCreate === '1' || qCreate === 'true' || qCreate === 'new'

  if (qJob) {
    await bindJobFromRoute(qJob)
    return
  }
  activeJobId.value = ''
  activeJobSourceMode.value = null
  activeJobExecutionMode.value = null

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

function openJobCreate() {
  showJobCreate.value = true
  const query = { ...route.query, create: '1' }
  router.replace({ name: 'production', query })
}

function closeJobCreate() {
  showJobCreate.value = false
  const query = { ...route.query }
  delete query.create
  router.replace({ name: 'production', query })
}

async function onJobStarted({ job, executionId: exId }) {
  showJobCreate.value = false
  activeJobId.value = job?.id || ''
  activeJobSourceMode.value = job?.source?.mode || null
  activeJobExecutionMode.value = job?.execution_mode || null
  const query = {}
  if (job?.id) query.job_id = job.id
  if (job?.workflow_id) {
    query.workflow_id = job.workflow_id
    selectedWorkflowId.value = job.workflow_id
  }
  if (exId) {
    query.execution_id = exId
    selectedExecutionId.value = exId
  }
  await router.replace({ name: 'production', query })
  if (job?.id) void refreshJobCost(job.id)
  if (exId) {
    await hydrateFromExecution(exId)
    await refreshExecutions(job?.workflow_id || selectedWorkflowId.value)
  } else if (job?.workflow_id) {
    await loadWorkflow(job.workflow_id)
    await refreshExecutions(job.workflow_id)
  }
}

function formatCostAmount(amount, currency = 'USD') {
  if (amount == null || Number.isNaN(Number(amount))) return '—'
  const n = Number(amount)
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: currency || 'USD',
      maximumFractionDigits: 4,
    }).format(n)
  } catch {
    return `${n.toFixed(4)} ${currency || ''}`.trim()
  }
}

const costStageRows = computed(() => {
  const byStage = jobCost.value?.by_stage || {}
  return Object.entries(byStage).map(([key, row]) => ({
    key,
    generations: row?.generations ?? 0,
    cost: row?.cost ?? 0,
  }))
})

const costInstanceRows = computed(() => {
  const byInst = jobCost.value?.by_provider_instance || {}
  return Object.entries(byInst).map(([key, row]) => ({
    key,
    label: row?.provider_instance_id || row?.provider_id || key,
    generations: row?.generations ?? 0,
    cost: row?.cost ?? 0,
  }))
})

function onJobCreated({ job }) {
  activeJobId.value = job?.id || ''
  activeJobSourceMode.value = job?.source?.mode || null
  activeJobExecutionMode.value = job?.execution_mode || null
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
  focusedStageKey.value = stage?.key ?? null
}

/* ------------------------------------------------------------------
   Keyboard control of the step list (step 0.3).

   Roving tabindex: exactly one row is in the tab order, and the arrow
   keys move which one. `focused` is where the cursor is; `selected` is
   what the detail panel shows — Enter and Space are what turn one into
   the other.
   ------------------------------------------------------------------ */

/**
 * Exactly one row is reachable by Tab. Before the cursor has moved that is the
 * first row, so Tab always lands somewhere useful.
 */
function stageTabIndex(stage, index) {
  if (focusedStageKey.value == null) return index === 0 ? 0 : -1
  return focusedStageKey.value === stage.key ? 0 : -1
}

function focusStageAt(index) {
  const list = visibleStages.value
  if (!list.length) return
  const clamped = Math.max(0, Math.min(list.length - 1, index))
  focusedStageKey.value = list[clamped].key
  void nextTick(() => {
    const row = stageListEl.value?.children?.[clamped]
    if (row && typeof row.focus === 'function') row.focus()
  })
}

function moveStageFocus(delta) {
  const list = visibleStages.value
  if (!list.length) return
  const current = list.findIndex((s) => s.key === focusedStageKey.value)
  if (current < 0) {
    focusStageAt(delta > 0 ? 0 : list.length - 1)
    return
  }
  focusStageAt(current + delta)
}

/** Space toggles: pressing it on the open row closes the detail panel. */
function toggleStageSelection(stage) {
  selectedStageKey.value = selectedStageKey.value === stage.key ? null : stage.key
  focusedStageKey.value = stage.key
}

/** R on the focused step: the same `run` action the detail panel offers. */
async function runFocusedStage() {
  const stage = focusedStage.value || selectedStage.value
  if (!stage || actionRunning.value) return
  selectStage(stage)
  await onStageRun({ action: 'run', body: null })
}

onShortcut((event) => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    // With nothing to move through, the arrows stay the page's scroll keys.
    if (!visibleStages.value.length) return false
    moveStageFocus(event.key === 'ArrowDown' ? 1 : -1)
    return true
  }
  if (event.key === 'Escape') {
    if (!selectedStageKey.value) return false
    selectedStageKey.value = null
    return true
  }
  if (event.key === 'e' || event.key === 'E') {
    openTimelineEditor()
    return true
  }
  if (event.key === 'r' || event.key === 'R') {
    void runFocusedStage()
    return true
  }
  const stage = focusedStage.value
  if (!stage) return false
  if (event.key === 'Enter') {
    selectStage(stage)
    return true
  }
  if (event.key === ' ') {
    toggleStageSelection(stage)
    return true
  }
  return false
})

/**
 * Editor and Library open beside Production, never over it (step 14.4). A Job
 * keeps running while you cut the timeline, and the SSE stream this page owns
 * would be torn down by a route change — which is why these stay windows even
 * though Library is a nav destination in its own right (step 1.1).
 */
function openTimelineEditor() {
  openAppWindow('editor', { query: { project: projectId.value || '' } })
}

function openExportLibrary() {
  openAppWindow('library', { query: { project: projectId.value || '' } })
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
    if (activeJobId.value) query.job_id = activeJobId.value
    await router.replace({ name: 'production', query })
    await refreshExecutions(query.workflow_id)
  } catch {
    // actionError is already set on the composable.
  }
}

/**
 * Test Node panel submit (step 4.2).
 *
 * When a Job is bound, posts to /api/jobs/<id>/test-node so status / stage /
 * artifacts never change. Without a Job, falls back to /api/workflow/run with
 * node_isolated (or node_with_deps when the picker chose run_deps).
 */
async function onTestRun(payload) {
  const nodeId = payload?.nodeId
  if (!nodeId) return
  actionError.value = ''
  actionMessage.value = ''
  actionRunning.value = true
  testResult.value = null
  try {
    let executionId = null
    if (payload.currentJobId || activeJobId.value) {
      const jobId = payload.currentJobId || activeJobId.value
      const data = await testJobNode(jobId, {
        target_node_ids: [nodeId],
        input_bindings: payload.inputBindings || undefined,
        provider_instance_id: payload.providerInstanceId || undefined,
        force: false,
      })
      executionId = data.execution_id
      actionMessage.value = `Test started (Job ${jobId} unchanged) → ${data.execution_id}`
    } else {
      const body = {
        run_mode: payload.runMode || 'node_isolated',
        target_node_ids: [nodeId],
        force: false,
        input_bindings: payload.inputBindings || undefined,
        provider_instance_id: payload.providerInstanceId || undefined,
      }
      if (payload.workflowId || workflowId.value || selectedWorkflowId.value) {
        body.workflow_id = payload.workflowId || workflowId.value || selectedWorkflowId.value
      } else if (payload.workflow || workflowDocument.value) {
        body.workflow = payload.workflow || workflowDocument.value
      } else {
        throw new Error('No workflow selected for Test Node')
      }
      const data = await runWorkflow(body)
      executionId = data.execution_id
      actionMessage.value = `Test started → ${data.execution_id}`
    }

    if (executionId) {
      // Brief poll for a terminal snapshot so the panel can show
      // from_sample_data. Do NOT hydrate the Production stage list from a
      // test execution — that would look like Job progress.
      const deadline = Date.now() + 8000
      let settled = false
      while (Date.now() < deadline && !settled) {
        try {
          const execData = await getExecution(executionId)
          const execution = execData?.execution || execData
          const nodeRec = execution?.nodes?.[nodeId] || {}
          const status = execution?.status || 'queued'
          testResult.value = {
            status: nodeRec.status || status,
            from_sample_data: Boolean(nodeRec.from_sample_data),
            outputs_summary: nodeRec.outputs_summary || {},
            error: nodeRec.error || null,
            execution_id: executionId,
            // Step 13.2 records which instance ran and why on the node's cost
            // block; 13.3 shows it so two back-to-back tests are told apart.
            provider_instance_id: nodeRec.cost?.provider_instance_id || '',
            selection_reason: nodeRec.cost?.selection_reason || '',
          }
          if (['succeeded', 'failed', 'cancelled', 'partial'].includes(status)) {
            settled = true
            break
          }
        } catch {
          testResult.value = {
            status: 'queued',
            from_sample_data: false,
            outputs_summary: {},
            error: null,
            execution_id: executionId,
          }
        }
        await new Promise((r) => setTimeout(r, 200))
      }
    }
  } catch (err) {
    actionError.value = err?.message || String(err)
  } finally {
    actionRunning.value = false
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
  () => [
    route.query.execution_id,
    route.query.executionId,
    route.query.workflow_id,
    route.query.workflowId,
    route.query.job_id,
    route.query.jobId,
    route.query.create,
  ],
  () => {
    void bindFromRoute()
  },
)

onMounted(async () => {
  await refreshWorkflows()
  try {
    const registry = await getNodeTypes()
    nodeTypes.value = registry?.node_types || {}
  } catch {
    nodeTypes.value = {}
  }
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
        <p v-if="activeJobExecutionMode" class="meta-line">
          Execution mode: {{ activeJobExecutionMode }}
        </p>
      </div>
      <div class="actions">
        <button type="button" class="primary" @click="openJobCreate">
          New Job
        </button>
        <button
          type="button"
          class="ghost"
          :disabled="!workflowId && !selectedWorkflowId"
          @click="openWorkflowCanvas"
        >
          Open Workflow
        </button>
        <button
          type="button"
          class="ghost"
          title="Open the Timeline Editor in its own window"
          @click="openTimelineEditor"
        >
          Timeline Editor ↗
        </button>
        <button
          type="button"
          class="ghost"
          title="Open the Library in its own window"
          @click="openExportLibrary"
        >
          Library ↗
        </button>
      </div>
    </header>

    <JobCreatePanel
      v-if="showJobCreate"
      :initial-workflow-id="selectedWorkflowId || workflowId || ''"
      @cancel="closeJobCreate"
      @created="onJobCreated"
      @started="onJobStarted"
    />

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

    <!-- Step 9.3: Job cost accounting (generations + cost by stage / instance) -->
    <section
      v-if="activeJobId && (jobCost || jobCostLoading || jobCostError)"
      class="cost-panel"
      aria-label="Job cost report"
    >
      <header class="cost-header">
        <h2>Cost</h2>
        <span v-if="jobCostLoading" class="muted cost-meta">Loading…</span>
        <span
          v-else-if="jobCost?.reconcile"
          class="cost-meta"
          :class="jobCost.reconcile.ok ? 'reconcile-ok' : 'reconcile-warn'"
          :title="jobCost.reconcile.ok
            ? 'budget_spent matches provenance records'
            : 'budget_spent diverges from provenance sum'"
        >
          {{ jobCost.reconcile.ok ? 'Reconciled' : 'Out of sync' }}
        </span>
      </header>
      <p v-if="jobCostError" class="error" role="alert">{{ jobCostError }}</p>
      <template v-else-if="jobCost">
        <div class="cost-totals">
          <div class="cost-stat">
            <span class="cost-stat-label">Generations</span>
            <strong class="cost-stat-value">{{ jobCost.totals?.generations ?? 0 }}</strong>
          </div>
          <div class="cost-stat">
            <span class="cost-stat-label">Cost</span>
            <strong class="cost-stat-value">
              {{ formatCostAmount(jobCost.totals?.cost, jobCost.currency) }}
            </strong>
          </div>
          <div
            v-if="jobCost.budget?.max_generations != null || jobCost.budget?.max_cost != null"
            class="cost-stat"
          >
            <span class="cost-stat-label">Ceiling</span>
            <strong class="cost-stat-value ceiling">
              <template v-if="jobCost.budget?.max_generations != null">
                {{ jobCost.budget.max_generations }} gen
              </template>
              <template v-if="jobCost.budget?.max_cost != null">
                · {{ formatCostAmount(jobCost.budget.max_cost, jobCost.budget.currency || jobCost.currency) }}
              </template>
            </strong>
          </div>
        </div>
        <div v-if="costStageRows.length" class="cost-breakdown">
          <h3>By stage</h3>
          <table>
            <thead>
              <tr>
                <th>Stage</th>
                <th>Generations</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in costStageRows" :key="row.key">
                <td>{{ row.key }}</td>
                <td>{{ row.generations }}</td>
                <td>{{ formatCostAmount(row.cost, jobCost.currency) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="costInstanceRows.length" class="cost-breakdown">
          <h3>By provider instance</h3>
          <table>
            <thead>
              <tr>
                <th>Instance</th>
                <th>Generations</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in costInstanceRows" :key="row.key">
                <td class="mono">{{ row.label }}</td>
                <td>{{ row.generations }}</td>
                <td>{{ formatCostAmount(row.cost, jobCost.currency) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <p v-if="loading" class="muted">Loading stages…</p>

    <div v-else-if="hasStages" class="stage-layout">
      <div class="stage-column">
        <div class="stage-filter">
          <input
            v-model="stageFilter"
            type="search"
            class="stage-filter-input"
            placeholder="Filter steps…"
            aria-label="Filter production steps"
            data-shortcut-search
          />
          <span class="stage-filter-count">
            {{ visibleStages.length }} / {{ stages.length }}
          </span>
        </div>

        <ol
          ref="stageListEl"
          class="stage-list"
          role="listbox"
          aria-label="Production stages"
        >
          <li
            v-for="(stage, index) in visibleStages"
            :key="stage.key"
            class="stage-row"
            role="option"
            :tabindex="stageTabIndex(stage, index)"
            :aria-selected="String(selectedStageKey === stage.key)"
            :data-stage-key="stage.key"
            :class="[
              `status-${stage.status || 'idle'}`,
              {
                selected: selectedStageKey === stage.key,
                'kb-focus': focusedStageKey === stage.key,
              },
            ]"
            @click="selectStage(stage)"
            @focus="focusedStageKey = stage.key"
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
                <span
                  v-if="(stage.issues || []).length"
                  class="issue-count"
                  :title="(stage.issues || []).join(', ')"
                >
                  {{ stage.issues.length }} issue{{ stage.issues.length === 1 ? '' : 's' }}
                </span>
              </span>
            </div>
            <span class="status-badge" :data-status="stage.status || 'idle'">
              {{ statusLabel(stage.status) }}
            </span>
          </li>
          <li v-if="!visibleStages.length" class="stage-empty muted">
            No step matches “{{ stageFilter }}”.
          </li>
        </ol>
      </div>

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
        :script-source-mode="activeJobSourceMode"
        :script-provider-required="scriptProviderVisible"
        :job-id="activeJobId"
        :node-types="nodeTypes"
        :test-result="testResult"
        @run="onStageRun"
        @inspect="onStageInspect"
        @test-run="onTestRun"
      />
    </div>

    <div v-else-if="!loading" class="empty muted">
      <p v-if="!selectedWorkflowId && !showJobCreate">
        Create a Job (Step 0) or choose a workflow to project its Production
        stages. The list is computed on the backend from the graph — never
        hardcoded here.
      </p>
      <p v-else-if="selectedWorkflowId">
        This workflow has no production stages to project.
      </p>
    </div>
  </section>
</template>

<style scoped>
.production-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px 20px 48px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 20px;
}

h1 {
  margin: 0 0 6px;
  font-family: var(--display);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: var(--text);
}

.lede {
  margin: 0;
  max-width: 640px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--muted);
}

.meta-line {
  margin: 7px 0 0;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.2px;
  font-variant-numeric: tabular-nums;
  color: var(--faint);
}

.actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* Secondary button. */
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-grad);
  color: var(--text);
  border-radius: var(--r-s);
  padding: 9px 14px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.16s, border-color 0.16s, color 0.14s,
    box-shadow 0.16s, transform 0.12s var(--ease-spring);
}

button:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  transform: translateY(-1px);
  box-shadow: var(--hairline-top), 0 4px 12px -4px rgba(0, 0, 0, 0.5);
}

button:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--hairline-top), inset 0 2px 4px rgba(0, 0, 0, 0.35);
}

/* Primary button — the duotone appears here and on active states only. */
button.primary {
  background: var(--accent-grad);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast);
}

button.primary:hover:not(:disabled) {
  filter: brightness(1.07) saturate(1.05);
  border-color: transparent;
  background: var(--accent-grad);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
}

/* Ghost button. */
button.ghost {
  background: transparent;
  box-shadow: none;
}

button.ghost:hover:not(:disabled) {
  background: var(--panel);
  box-shadow: var(--hairline-top);
}

button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

.pickers {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: flex-end;
  margin-bottom: 20px;
}

.picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 224px;
  flex: 1 1 224px;
}

/* Micro-label. */
.picker-label {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.picker select {
  width: 100%;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text);
  padding: 9px 11px;
  font-family: var(--body);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.picker select:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.picker select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Live SSE marker — a running status badge, not an accent. */
.live-pill {
  align-self: center;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 20px;
  white-space: nowrap;
  color: var(--run);
  background: var(--run-dim);
  box-shadow: inset 0 0 0 1px var(--run-line);
  animation: pulse 1.6s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

@media (prefers-reduced-motion: reduce) {
  .live-pill {
    animation: none;
  }
}

/* Advisory banners: status wash + status hairline. */
.error {
  margin: 0 0 16px;
  padding: 11px 13px;
  border-radius: var(--r-s);
  background: var(--fail-dim);
  border: 1px solid var(--fail-line);
  color: var(--fail-text);
  font-size: 12.5px;
  line-height: 1.55;
}

.stream-warn {
  margin: 0 0 12px;
  padding: 11px 13px;
  border-radius: var(--r-s);
  background: var(--warn-dim);
  border: 1px solid var(--warn-line);
  color: var(--warn-text);
  font-size: 12.5px;
  line-height: 1.55;
}

.muted {
  color: var(--muted);
}

.stage-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

@media (max-width: 820px) {
  .stage-layout {
    grid-template-columns: 1fr;
  }

  .page-header {
    flex-direction: column;
  }

  .actions {
    flex-wrap: wrap;
  }
}

.stage-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.stage-filter {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stage-filter-input {
  flex: 1 1 auto;
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text);
  font-family: var(--body);
  font-size: 12.5px;
  padding: 7px 10px;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.stage-filter-input::placeholder {
  color: var(--faint);
}

.stage-filter-input:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.stage-filter-count {
  flex: none;
  font-family: var(--mono);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
}

.stage-empty {
  padding: 20px 4px;
  font-size: 12.5px;
}

.stage-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Raised card — lit from above, with a status spine on the left edge. */
.stage-row {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 13px;
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  padding: 12px 14px 12px 15px;
  cursor: pointer;
  transition: background 0.18s, border-color 0.18s, box-shadow 0.18s;
}

.stage-row::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--faint);
  opacity: 0;
  transition: opacity 0.18s;
}

.stage-row:hover {
  border-color: var(--line-2);
  box-shadow: var(--hairline-top), 0 8px 24px -12px rgba(0, 0, 0, 0.65);
}

/* The keyboard cursor. Deliberately a ring rather than a fill, so it can sit
   on a row that is not selected without claiming to be. */
.stage-row.kb-focus,
.stage-row:focus-visible {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: var(--hairline-top), 0 0 0 2px var(--accent);
}

/* Selected is the only other place the accent appears. */
.stage-row.selected {
  border-color: var(--accent-line-2);
  background: var(--accent-wash);
  box-shadow: var(--hairline-top), inset 0 0 0 1px var(--accent-line);
}

.stage-row.status-running::before {
  background: var(--run);
  opacity: 1;
}

.stage-row.status-succeeded::before {
  background: var(--ok);
  opacity: 1;
}

.stage-row.status-failed::before {
  background: var(--fail);
  opacity: 1;
}

.stage-row.status-invalid::before,
.stage-row.status-stale::before {
  background: var(--warn);
  opacity: 1;
}

.stage-row.status-awaiting_approval::before {
  background: var(--sched);
  opacity: 1;
}

.ordinal {
  flex: none;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--faint);
  min-width: 22px;
  text-align: right;
}

.stage-body {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.stage-label {
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
  color: var(--text);
}

.stage-sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--muted);
}

.provider-meta {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-2);
}

.muted-meta {
  color: var(--faint);
}

.node-count {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--muted);
}

/* Step 11.4: open ReviewIssues attached to the stage by the projection. */
.issue-count {
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 20px;
  color: var(--warn);
  background: var(--warn-dim);
  box-shadow: inset 0 0 0 1px var(--warn-line);
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

.status-badge[data-status='cancelled'],
.status-badge[data-status='skipped'] {
  color: var(--faint);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line);
}

.empty {
  padding: 32px 0;
  font-size: 13px;
  line-height: 1.6;
}

/* Step 9.3 cost report — a raised card. */
.cost-panel {
  margin: 0 0 20px;
  padding: 14px 16px 16px;
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
}

.cost-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.cost-header h2 {
  margin: 0;
  font-family: var(--display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: var(--text);
}

.cost-meta {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}

.reconcile-ok {
  color: var(--ok);
}

.reconcile-warn {
  color: var(--warn);
}

.cost-totals {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  margin-bottom: 14px;
}

.cost-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 88px;
  padding: 2px 18px 2px 0;
  margin-right: 18px;
  border-right: 1px solid var(--line-soft);
}

.cost-stat:last-child {
  border-right: none;
  margin-right: 0;
}

.cost-stat-label {
  font-family: var(--mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.cost-stat-value {
  margin-top: 6px;
  font-family: var(--display);
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.5px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}

.cost-stat-value.ceiling {
  margin-top: 8px;
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0;
  color: var(--text-2);
}

.cost-breakdown {
  margin-top: 14px;
}

.cost-breakdown h3 {
  margin: 0 0 8px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.cost-breakdown table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.cost-breakdown th,
.cost-breakdown td {
  text-align: left;
  padding: 7px 9px;
  border-bottom: 1px solid var(--line-soft);
}

.cost-breakdown th {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.cost-breakdown td {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.cost-breakdown tbody tr:last-child td {
  border-bottom: none;
}

.cost-breakdown td.mono {
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text);
  /* Instance ids have no spaces; without this they push the table wider than
     a 375px viewport and take a horizontal scrollbar with them. */
  overflow-wrap: anywhere;
}
</style>

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
import { computed, onMounted, ref, watch } from 'vue'
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

const selectedStage = computed(() =>
  stages.value.find((s) => s.key === selectedStageKey.value) || null,
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

button.primary {
  background: var(--accent, #3b6fd9);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
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

/* Step 11.4: open ReviewIssues attached to the stage by the projection. */
.issue-count {
  color: var(--accent-active, #ff9f43);
  font-weight: 600;
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

.cost-panel {
  margin: 0 0 1.25rem;
  padding: 0.9rem 1rem 1rem;
  background: var(--bg-surface, #161d2a);
  border: 1px solid var(--border, #1e2a3a);
  border-radius: 10px;
}

.cost-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.65rem;
}

.cost-header h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
}

.cost-meta {
  font-size: 0.75rem;
  font-family: var(--font-mono, monospace);
}

.reconcile-ok {
  color: var(--accent-ready, #26de81);
}

.reconcile-warn {
  color: var(--accent-active, #ff9f43);
}

.cost-totals {
  display: flex;
  flex-wrap: wrap;
  gap: 1.25rem;
  margin-bottom: 0.75rem;
}

.cost-stat {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 5.5rem;
}

.cost-stat-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted, #6b7f93);
}

.cost-stat-value {
  font-size: 1.15rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.cost-stat-value.ceiling {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-secondary, #8899aa);
}

.cost-breakdown {
  margin-top: 0.65rem;
}

.cost-breakdown h3 {
  margin: 0 0 0.35rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-secondary, #8899aa);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.cost-breakdown table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.cost-breakdown th,
.cost-breakdown td {
  text-align: left;
  padding: 0.3rem 0.45rem;
  border-bottom: 1px solid var(--border, #1e2a3a);
}

.cost-breakdown th {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-muted, #6b7f93);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.cost-breakdown td.mono {
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
}
</style>

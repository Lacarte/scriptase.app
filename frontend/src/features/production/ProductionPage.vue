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
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  deleteJob,
  duplicateJob,
  getExecution,
  getJob,
  getNodeTypes,
  listJobs,
  listExecutions,
  listWorkflows,
  pauseJob,
  resumeJob,
  retryFailedJobs,
  retryJob,
  runWorkflow,
  startJob,
  testJobNode,
} from './api.js'
import { useUndoableAction } from '@/shared/composables/useUndoableAction.js'
import JobCreatePanel from './components/JobCreatePanel.vue'
import StepDetailPanel from './components/StepDetailPanel.vue'
import { useProductionStages } from './composables/useProductionStages.js'
import { ACTION_LABELS } from './stageActions.js'
import {
  EXECUTION_MODE_CATALOG,
  sourceModeLabel,
  sourceModeRequiresProvider,
} from './sourceModes.js'
import { statusLabel } from './stageStatus.js'
import { onShortcut } from '@/shared/composables/useShortcuts.js'
import { channelAccent, channelInitials } from '@/shared/utils/channelIdentity.js'
import { openAppWindow } from '@/shared/utils/openWindow.js'
import ArchiveCalendar from '@/shared/components/ArchiveCalendar.vue'

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
const activeJob = ref(null)
const activeJobSourceMode = ref(null)
const activeJobExecutionMode = ref(null)
/** Registry definitions for the Test Node panel port list (step 4.2). */
const nodeTypes = ref({})
/** Last Test Node result shown in the detail panel. */
const testResult = ref(null)
const pauseActionRunning = ref(false)
const pauseActionError = ref('')
const jobs = ref([])
const jobsLoading = ref(false)
const jobsError = ref('')
const jobSearch = ref('')
const jobActionRunning = ref('')
const jobActionError = ref('')
const channelFilter = ref('')
const statusFilter = ref(null)
const selectedJobIds = ref(new Set())
const undoable = useUndoableAction()

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

const RUNNING_STATUSES = new Set(['running', 'paused', 'awaiting_approval'])
const COMPLETED_STATUSES = new Set(['completed', 'succeeded'])

const jobCounts = computed(() => {
  const counts = { total: jobs.value.length, running: 0, queued: 0, completed: 0, failed: 0 }
  for (const job of jobs.value) {
    const status = String(job.status || '')
    if (RUNNING_STATUSES.has(status)) counts.running += 1
    else if (status === 'queued') counts.queued += 1
    else if (COMPLETED_STATUSES.has(status)) counts.completed += 1
    else if (status === 'failed') counts.failed += 1
  }
  return counts
})

const jobChannels = computed(() => {
  const seen = new Map()
  for (const job of jobs.value) {
    const id = job.channel_id
    if (!id || seen.has(id)) continue
    seen.set(id, job.channel_name || id)
  }
  return [...seen.entries()].map(([id, name]) => ({ id, name }))
})

const filteredJobs = computed(() => jobs.value.filter((job) => {
  if (channelFilter.value && job.channel_id !== channelFilter.value) return false
  const status = String(job.status || '')
  if (statusFilter.value === 'running' && !RUNNING_STATUSES.has(status)) return false
  if (statusFilter.value === 'queued' && status !== 'queued') return false
  if (statusFilter.value === 'completed' && !COMPLETED_STATUSES.has(status)) return false
  if (statusFilter.value === 'failed' && status !== 'failed') return false
  return true
}))

/** Finished Jobs alone age into the archive; queued/running/failed work stays visible. */
const calendarJobs = computed(() => filteredJobs.value.map(job => ({
  ...job,
  name: job.name || job.title || job.source_name || job.id,
  archive_at: COMPLETED_STATUSES.has(job.status) ? (job.completed_at || job.created_at) : null,
})))

const selectedJobs = computed(() =>
  jobs.value.filter((job) => selectedJobIds.value.has(job.id)),
)

const batchLive = computed(() => jobCounts.value.running > 0)

async function refreshJobs() {
  jobsLoading.value = true
  jobsError.value = ''
  try {
    const data = await listJobs({ limit: 500 })
    jobs.value = data.jobs || []
  } catch (err) {
    jobsError.value = err?.message || String(err)
  } finally {
    jobsLoading.value = false
  }
}

async function runJobAction(action, job) {
  if (!job?.id || jobActionRunning.value) return
  jobActionRunning.value = `${action}:${job.id}`
  jobActionError.value = ''
  try {
    if (action === 'retry') await retryJob(job.id)
    else if (action === 'duplicate') await duplicateJob(job.id)
    else if (action === 'remove') {
      await deleteJob(job.id)
      if (activeJobId.value === job.id) {
        activeJob.value = null
        await router.replace({ name: 'production', query: {} })
      }
    }
    await refreshJobs()
  } catch (err) {
    jobActionError.value = err?.message || String(err)
  } finally {
    jobActionRunning.value = ''
  }
}

async function retryAllFailed() {
  if (jobActionRunning.value) return
  jobActionRunning.value = 'retry-failed'
  jobActionError.value = ''
  try {
    await retryFailedJobs()
    await refreshJobs()
  } catch (err) {
    jobActionError.value = err?.message || String(err)
  } finally {
    jobActionRunning.value = ''
  }
}

function toggleStatusFilter(key) {
  statusFilter.value = statusFilter.value === key ? null : key
}

function jobChecked(job) {
  return selectedJobIds.value.has(job.id)
}

function toggleJobCheck(job, event) {
  event?.stopPropagation()
  const next = new Set(selectedJobIds.value)
  if (next.has(job.id)) next.delete(job.id)
  else next.add(job.id)
  selectedJobIds.value = next
}

function clearSelection() {
  selectedJobIds.value = new Set()
}

async function runBatch() {
  const queued = jobs.value.filter((job) => job.status === 'queued')
  if (!queued.length || jobActionRunning.value) return
  jobActionRunning.value = 'run-batch'
  jobActionError.value = ''
  try {
    // Serial drain lives on the backend. Starting each queued Job is enough;
    // the engine will not run two at once (step 13.1).
    for (const job of queued) {
      await startJob(job.id, { force: false })
    }
    await refreshJobs()
  } catch (err) {
    jobActionError.value = err?.message || String(err)
  } finally {
    jobActionRunning.value = ''
  }
}

async function stopBatch() {
  const live = jobs.value.filter((job) => ['running', 'paused'].includes(job.status))
  if (!live.length || jobActionRunning.value) return
  jobActionRunning.value = 'stop-batch'
  jobActionError.value = ''
  try {
    for (const job of live) {
      if (job.status === 'running') await pauseJob(job.id)
    }
    await refreshJobs()
  } catch (err) {
    jobActionError.value = err?.message || String(err)
  } finally {
    jobActionRunning.value = ''
  }
}

function clearCompleted() {
  const done = jobs.value.filter((job) => COMPLETED_STATUSES.has(job.status))
  if (!done.length || jobActionRunning.value) return
  const snapshot = [...jobs.value]
  const ids = new Set(done.map((job) => job.id))
  jobs.value = jobs.value.filter((job) => !ids.has(job.id))
  undoable.run({
    message: `Cleared ${done.length} completed job${done.length === 1 ? '' : 's'}`,
    commit: async () => {
      for (const job of done) await deleteJob(job.id)
    },
    undo: () => { jobs.value = snapshot },
    onError: (err) => { jobActionError.value = err?.message || String(err) },
  })
}

function cancelAll() {
  const affected = jobs.value.filter((job) =>
    ['queued', 'running', 'paused', 'awaiting_approval'].includes(job.status),
  )
  if (!affected.length || jobActionRunning.value) return
  const snapshot = [...jobs.value]
  const ids = new Set(affected.map((job) => job.id))
  jobs.value = jobs.value.filter((job) => !ids.has(job.id))
  undoable.run({
    message: `Cancelled ${affected.length} job${affected.length === 1 ? '' : 's'}`,
    commit: async () => {
      for (const job of affected) {
        if (job.status === 'running') {
          try { await pauseJob(job.id) } catch { /* still remove */ }
        }
        await deleteJob(job.id)
      }
    },
    undo: () => { jobs.value = snapshot },
    onError: (err) => { jobActionError.value = err?.message || String(err) },
  })
}

async function startSelected() {
  const targets = selectedJobs.value.filter((job) =>
    ['queued', 'cancelled', 'failed'].includes(job.status),
  )
  if (!targets.length || jobActionRunning.value) return
  jobActionRunning.value = 'start-selected'
  jobActionError.value = ''
  try {
    for (const job of targets) {
      if (job.status === 'failed') await retryJob(job.id)
      else await startJob(job.id, { force: false })
    }
    clearSelection()
    await refreshJobs()
  } catch (err) {
    jobActionError.value = err?.message || String(err)
  } finally {
    jobActionRunning.value = ''
  }
}

async function duplicateSelected() {
  const targets = selectedJobs.value
  if (!targets.length || jobActionRunning.value) return
  jobActionRunning.value = 'dup-selected'
  jobActionError.value = ''
  try {
    for (const job of targets) await duplicateJob(job.id)
    clearSelection()
    await refreshJobs()
  } catch (err) {
    jobActionError.value = err?.message || String(err)
  } finally {
    jobActionRunning.value = ''
  }
}

function removeSelected() {
  const targets = selectedJobs.value
  if (!targets.length || jobActionRunning.value) return
  const snapshot = [...jobs.value]
  const ids = new Set(targets.map((job) => job.id))
  jobs.value = jobs.value.filter((job) => !ids.has(job.id))
  clearSelection()
  undoable.run({
    message: `Removed ${targets.length} job${targets.length === 1 ? '' : 's'}`,
    commit: async () => {
      for (const job of targets) await deleteJob(job.id)
    },
    undo: () => { jobs.value = snapshot },
    onError: (err) => { jobActionError.value = err?.message || String(err) },
  })
}

function openJob(job) {
  router.push({ name: 'production', query: { job_id: job.id } })
}

function jobDate(job) {
  const value = job.completed_at || job.started_at || job.created_at
  if (!value) return ''
  const date = new Date(value)
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date)
    : ''
}

/* ------------------------------------------------------------------
   The job row (§3.1, prototype `.job`).

   Expanding a row *is* binding that Job: the detail's stage rail draws
   the same backend projection the step list below draws, over the same
   SSE stream. That is why only one row is open at a time — a second
   open row would need a second projection and a second stream, and the
   rail would stop being the projection.
   ------------------------------------------------------------------ */

function jobExpanded(job) {
  return Boolean(job?.id) && job.id === activeJobId.value
}

function toggleJobExpand(job) {
  if (jobExpanded(job)) {
    const query = { ...route.query }
    delete query.job_id
    delete query.jobId
    router.replace({ name: 'production', query })
    return
  }
  openJob(job)
}

/** Full payload for the open row; the list carries summaries only. */
function jobDetail(job) {
  return jobExpanded(job) && activeJob.value?.id === job.id ? activeJob.value : job
}

function executionModeLabel(mode) {
  const text = String(mode || '').trim()
  if (!text) return ''
  return EXECUTION_MODE_CATALOG.find((entry) => entry.mode === text)?.label || text
}

/**
 * A stage key read back for display. The keys are the backend's; only the
 * capitalisation is ours, so this invents no stage the projection did not send.
 */
function humanizeStageKey(key) {
  const text = String(key || '').trim()
  if (!text) return ''
  return text.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

/** Prefer the projection's own label for the open Job; fall back to the key. */
function stageKeyLabel(job, key) {
  if (!key) return ''
  if (jobExpanded(job)) {
    const match = stages.value.find((stage) => stage.key === key)
    if (match?.label) return match.label
  }
  return humanizeStageKey(key)
}

const STAGE_DONE_STATUSES = new Set(['succeeded', 'skipped'])

/** Completed share of the open Job's projected stages. Null when unknown. */
const activeStageProgress = computed(() => {
  const list = stages.value
  if (!list.length) return null
  const done = list.filter((stage) => STAGE_DONE_STATUSES.has(String(stage.status || ''))).length
  return Math.round((done / list.length) * 100)
})

/**
 * The row's compact stage line. A percentage is shown only where the
 * projection supplies one — a running Job with no projection to hand gets the
 * indeterminate bar rather than an invented number.
 */
function jobStageLine(job) {
  const status = String(job?.status || '')
  const pct = jobExpanded(job) ? activeStageProgress.value : null
  const stage = stageKeyLabel(job, job?.current_stage)
  if (status === 'completed' || status === 'succeeded') return { name: 'Export complete', pct: 100, fill: 100 }
  if (status === 'failed') {
    const label = job?.failure?.stage_label || stage
    return { name: label ? `Failed · ${label}` : 'Failed', pct, fill: pct ?? 0 }
  }
  if (status === 'cancelled') return { name: 'Cancelled', pct: null, fill: 0 }
  if (status === 'queued') return { name: 'Waiting for a slot', pct: null, fill: 0 }
  if (status === 'paused') {
    return { name: stage ? `Paused · ${stage}` : 'Paused', pct, fill: pct ?? 0 }
  }
  if (status === 'awaiting_approval') {
    return { name: stage ? `Awaiting approval · ${stage}` : 'Awaiting approval', pct, fill: pct ?? 0 }
  }
  return {
    name: stage || 'Running',
    pct,
    fill: pct ?? 0,
    indeterminate: pct == null,
  }
}

/** Stage status → the prototype's rail vocabulary. */
function railState(stage) {
  const status = String(stage?.status || 'idle')
  if (status === 'failed') return 'failed'
  if (status === 'succeeded') return 'done'
  if (status === 'skipped') return 'skipped'
  // The rail has no separate "held" state; a stage waiting on a person is
  // still the stage the Job is on, so it reads as active.
  if (['running', 'paused', 'awaiting_approval'].includes(status)) return 'active'
  return 'pending'
}

function railGlyph(stage) {
  const state = railState(stage)
  if (state === 'done') return '✓'
  if (state === 'failed') return '✕'
  return stageOrdinal(stage)
}

/** Only shown where there is something to say — never a bare "Skipped". */
function railTip(job, stage) {
  const issues = Array.isArray(stage?.issues) ? stage.issues : []
  if (issues.length) return issues.join(' · ')
  const failure = jobDetail(job)?.failure
  if (railState(stage) === 'failed' && failure?.code) return failure.code
  return ''
}

/** Live clock, running only while a Job is. */
const nowMs = ref(Date.now())
let elapsedTimer = null

watch(
  () => jobs.value.some((job) => job.status === 'running'),
  (live) => {
    if (elapsedTimer) {
      clearInterval(elapsedTimer)
      elapsedTimer = null
    }
    if (!live) return
    elapsedTimer = setInterval(() => {
      nowMs.value = Date.now()
    }, 1000)
  },
)

onUnmounted(() => {
  if (elapsedTimer) clearInterval(elapsedTimer)
})

function msOf(value) {
  if (!value) return null
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? ms : null
}

function jobElapsed(job) {
  const started = msOf(job?.started_at)
  if (started == null) return '—'
  const ended = msOf(job?.completed_at) ?? (job?.status === 'running' ? nowMs.value : null)
  if (ended == null || ended < started) return '—'
  const total = Math.floor((ended - started) / 1000)
  const seconds = String(total % 60).padStart(2, '0')
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes}:${seconds}`
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${seconds}`
}

function jobTimestamp(value) {
  const ms = msOf(value)
  if (ms == null) return '—'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(ms))
}

function languageAdvisory(job) {
  return (job?.advisories || []).find((advisory) => advisory.code === 'LANGUAGE_MISMATCH') || null
}

function openJobInEditor(job) {
  openAppWindow('editor', { query: { project: job?.project_id || job?.id || '' } })
}

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

async function toggleJobPause() {
  if (!activeJobId.value || pauseActionRunning.value) return
  pauseActionRunning.value = true
  pauseActionError.value = ''
  try {
    const paused = executionStatus.value === 'paused'
    const data = paused
      ? await resumeJob(activeJobId.value)
      : await pauseJob(activeJobId.value)
    const execution = data?.execution_id || data?.job?.execution_id || executionId.value
    if (execution) await hydrateFromExecution(execution)
  } catch (err) {
    pauseActionError.value = err?.message || String(err)
  } finally {
    pauseActionRunning.value = false
  }
}

async function bindJobFromRoute(jobId) {
  if (!jobId) {
    activeJobId.value = ''
    activeJob.value = null
    activeJobSourceMode.value = null
    activeJobExecutionMode.value = null
    return
  }
  try {
    const data = await getJob(jobId)
    const job = data.job || data
    activeJob.value = job
    activeJobId.value = job.id || jobId
    activeJobSourceMode.value = job.source?.mode || null
    activeJobExecutionMode.value = job.execution_mode || null
    if (job.workflow_id) {
      selectedWorkflowId.value = job.workflow_id
    }
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
  activeJob.value = null
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
  activeJob.value = job || null
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
  if (exId) {
    await hydrateFromExecution(exId)
    await refreshExecutions(job?.workflow_id || selectedWorkflowId.value)
  } else if (job?.workflow_id) {
    await loadWorkflow(job.workflow_id)
    await refreshExecutions(job.workflow_id)
  }
  await refreshJobs()
}

function onJobCreated({ job }) {
  activeJobId.value = job?.id || ''
  activeJob.value = job || null
  activeJobSourceMode.value = job?.source?.mode || null
  activeJobExecutionMode.value = job?.execution_mode || null
  void refreshJobs()
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

function openJobInLibrary(job) {
  openAppWindow('library', { query: { project: job?.project_id || job?.id || '' } })
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
  await Promise.all([refreshWorkflows(), refreshJobs()])
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
    <JobCreatePanel
      :initial-script-id="String(route.query.script || '')"
      :initial-channel-id="String(route.query.channel || '')"
      :auto-start="false"
      @created="onJobCreated"
      @started="onJobStarted"
    />

    <main class="sheet">
      <div class="sheet-head">
        <div class="sheet-title-row">
          <h1>Production Batch</h1>
          <span class="sheet-kicker">Orchestrate &amp; monitor — S1 owns scripts &amp; TTS</span>
          <span
            v-if="active"
            class="live-pill"
            title="Receiving live execution events over SSE"
          >Live</span>
          <div class="spacer" />
          <div class="page-header">
          <div class="actions sheet-actions">
            <button
              v-if="activeJobId && ['running', 'paused'].includes(executionStatus)"
              type="button"
              class="btn sm ghost"
              :disabled="pauseActionRunning"
              :aria-label="executionStatus === 'paused' ? 'Resume job' : 'Pause job'"
              @click="toggleJobPause"
            >
              {{ pauseActionRunning
                ? (executionStatus === 'paused' ? 'Resuming…' : 'Pausing…')
                : (executionStatus === 'paused' ? 'Resume' : 'Pause') }}
            </button>
            <button
              type="button"
              class="btn sm ghost"
              title="Open the Timeline Editor in its own window"
              @click="openTimelineEditor"
            >
              Timeline Editor ↗
            </button>
            <button
              type="button"
              class="btn sm ghost"
              title="Open the Library in its own window"
              @click="openExportLibrary"
            >
              Library ↗
            </button>
          </div>
          </div>
        </div>

        <div class="summary" role="group" aria-label="Batch totals">
          <button
            type="button"
            class="stat total clickable"
            :class="{ 'active-filter': statusFilter === null }"
            @click="statusFilter = null"
          >
            <span class="num">{{ jobCounts.total }}</span>
            <span class="lbl">Jobs</span>
          </button>
          <button
            type="button"
            class="stat running clickable"
            :class="{ 'active-filter': statusFilter === 'running' }"
            @click="toggleStatusFilter('running')"
          >
            <span class="num"><span class="sd" :style="{ background: 'var(--run)' }" />{{ jobCounts.running }}</span>
            <span class="lbl">Running</span>
          </button>
          <button
            type="button"
            class="stat queued clickable"
            :class="{ 'active-filter': statusFilter === 'queued' }"
            @click="toggleStatusFilter('queued')"
          >
            <span class="num"><span class="sd" :style="{ background: 'var(--queue)' }" />{{ jobCounts.queued }}</span>
            <span class="lbl">Queued</span>
          </button>
          <button
            type="button"
            class="stat done clickable"
            :class="{ 'active-filter': statusFilter === 'completed' }"
            @click="toggleStatusFilter('completed')"
          >
            <span class="num"><span class="sd" :style="{ background: 'var(--ok)' }" />{{ jobCounts.completed }}</span>
            <span class="lbl">Completed</span>
          </button>
          <button
            type="button"
            class="stat failed clickable"
            :class="{ 'active-filter': statusFilter === 'failed' }"
            @click="toggleStatusFilter('failed')"
          >
            <span class="num"><span class="sd" :style="{ background: 'var(--fail)' }" />{{ jobCounts.failed }}</span>
            <span class="lbl">Failed</span>
          </button>
        </div>

        <div class="toolbar">
          <label class="search job-search">
            <span class="sr-only">Search jobs, titles, channels</span>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
            <input v-model="jobSearch" type="search" placeholder="Search jobs, titles, channels." />
          </label>
          <select v-model="channelFilter" class="filter-select" aria-label="Filter by channel">
            <option value="">All channels</option>
            <option v-for="channel in jobChannels" :key="channel.id" :value="channel.id">
              {{ channel.name }}
            </option>
          </select>
          <div class="spacer" />
          <div class="batch-controls">
            <button
              type="button"
              class="btn sm"
              :class="{ 'is-live': batchLive }"
              :disabled="!jobCounts.queued || Boolean(jobActionRunning)"
              @click="runBatch"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polygon points="6 3 20 12 6 21 6 3"/></svg>
              <span class="rb-label">Run Batch</span>
            </button>
            <button
              type="button"
              class="btn sm warnb"
              :disabled="!jobCounts.running || Boolean(jobActionRunning)"
              @click="stopBatch"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
              Stop
            </button>
            <button
              type="button"
              class="btn sm retry-failed"
              :disabled="!jobCounts.failed || Boolean(jobActionRunning)"
              @click="retryAllFailed"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg>
              Retry Failed
            </button>
            <button
              type="button"
              class="btn sm ghost"
              :disabled="!jobCounts.completed || Boolean(jobActionRunning)"
              @click="clearCompleted"
            >Clear Done</button>
            <button
              type="button"
              class="btn sm danger"
              :disabled="!(jobCounts.queued || jobCounts.running) || Boolean(jobActionRunning)"
              @click="cancelAll"
            >Cancel All</button>
          </div>
        </div>
      </div>

      <div class="selbar" :class="{ show: selectedJobs.length }">
        <span><span class="cnt">{{ selectedJobs.length }}</span> selected</span>
        <div class="spacer" />
        <button type="button" class="btn xs" :disabled="Boolean(jobActionRunning)" @click="duplicateSelected">Duplicate</button>
        <button type="button" class="btn xs" :disabled="Boolean(jobActionRunning)" @click="startSelected">Start</button>
        <button type="button" class="btn xs danger" :disabled="Boolean(jobActionRunning)" @click="removeSelected">Remove</button>
        <button type="button" class="btn xs ghost" @click="clearSelection">Clear</button>
      </div>

      <p v-if="headerMeta" class="meta-line sheet-meta">{{ headerMeta }}</p>
      <p v-if="jobActionError" class="error sheet-error" role="alert">{{ jobActionError }}</p>
      <p v-if="jobsLoading && !jobs.length" class="muted sheet-note">Loading jobs…</p>
      <p v-else-if="jobsError" class="error sheet-error" role="alert">{{ jobsError }}</p>

      <div v-if="!jobsLoading && !jobs.length" class="empty show">
        <div class="ic">
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4v5"/></svg>
        </div>
        <h3>No jobs in the batch</h3>
        <p>Pick a channel and script source on the left, then <b>Add to Batch</b>. Queue as many as you like before running.</p>
      </div>

      <div v-else-if="!jobsLoading && !jobsError && !calendarJobs.length" class="empty show">
        <div class="ic">
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4v5"/></svg>
        </div>
        <h3>No matching jobs</h3>
        <p>Nothing matches the current search or filter. <b>Clear filters</b> to see the full batch.</p>
      </div>

      <div v-else class="joblist">
      <ArchiveCalendar
        :items="calendarJobs"
        :search-query="jobSearch"
        timestamp-key="archive_at"
        item-key="id"
        :search-keys="['name', 'id', 'channel_id', 'channel_name', 'status']"
        noun="job"
        items-class="joblist-items"
      >
        <template #item="{ item, archived }">
          <article
            class="job"
            :class="[`st-${item.status}`, { expanded: jobExpanded(item), 'sel-checked': jobChecked(item) }]"
          >
            <!-- Clicking anywhere on the row toggles it, but the chevron is
                 the control. A role="button" here would nest the quick
                 actions inside an interactive element. -->
            <div class="job-main" @click="toggleJobExpand(item)">
              <button
                type="button"
                class="job-check"
                :aria-label="`Select ${item.id}`"
                :aria-pressed="String(jobChecked(item))"
                @click="toggleJobCheck(item, $event)"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
              </button>
              <div class="job-id mono">{{ item.id }}</div>
              <div class="job-ch">
                <span
                  class="ch-avatar"
                  :style="{ background: channelAccent(item.channel_id) }"
                  aria-hidden="true"
                >{{ channelInitials(item.channel_name || item.channel_id) }}</span>
                <div class="job-ch-txt">
                  <div class="nm">{{ item.channel_name || item.channel_id }}</div>
                  <div class="src">{{ sourceModeLabel(item.source_mode) }}</div>
                </div>
              </div>
              <div class="job-title">
                <div class="t">
                  {{ item.name }}
                  <span v-if="languageAdvisory(item)" class="language-badge" title="Script language differs from the Channel">
                    {{ languageAdvisory(item).script_language }} ⚠
                  </span>
                </div>
                <div class="sub">
                  <span>{{ executionModeLabel(item.execution_mode) }}</span>
                  <span v-if="item.failure" class="failed-stage">Failed · {{ item.failure.stage_label }}</span>
                  <span v-else-if="archived" class="archived-label">Archived</span>
                  <time v-else-if="jobDate(item)">{{ jobDate(item) }}</time>
                </div>
              </div>
              <div class="job-stage">
                <div class="cur">
                  <span class="nm">{{ jobStageLine(item).name }}</span>
                  <span v-if="jobStageLine(item).pct != null" class="pct">{{ jobStageLine(item).pct }}%</span>
                </div>
                <div class="progress" :class="{ indet: jobStageLine(item).indeterminate }">
                  <div class="fill" :style="{ width: `${jobStageLine(item).fill}%` }" />
                </div>
              </div>
              <div class="job-status">
                <span class="badge" :class="`b-${item.status}`" :data-status="item.status">
                  <span class="bd" />{{ statusLabel(item.status) }}
                </span>
              </div>
              <div class="job-elapsed mono">{{ jobElapsed(item) }}</div>
              <div v-if="['completed', 'succeeded'].includes(item.status)" class="job-quick">
                <!-- The icon is the button below 1240px, where the label
                     collapses, so the title carries the name at every width. -->
                <button type="button" class="quick-btn" title="Open in Editor" @click.stop="openJobInEditor(item)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>
                  <span>Editor</span>
                </button>
                <button type="button" class="quick-btn" title="Open in Library" @click.stop="openJobInLibrary(item)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
                  <span>Library</span>
                </button>
              </div>
              <button
                type="button"
                class="job-expand-btn"
                :aria-label="`Toggle details for ${item.id}`"
                :aria-expanded="String(jobExpanded(item))"
                @click.stop="toggleJobExpand(item)"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
              </button>
            </div>

            <div v-if="jobExpanded(item)" class="job-detail">
              <div class="rail-wrap">
                <div class="rl-lbl">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 12h16M4 12l4-4M4 12l4 4"/></svg>
                  Production pipeline
                  <span class="rl-hint">· hover a dimmed stage to see why it's skipped</span>
                </div>
                <p v-if="loading" class="muted rail-note">Loading stages…</p>
                <p v-else-if="!stages.length" class="muted rail-note">
                  No stages projected for this Job yet.
                </p>
                <div v-else class="stagerail">
                  <div
                    v-for="stage in stages"
                    :key="stage.key"
                    class="srstage"
                    :class="railState(stage)"
                  >
                    <div class="connector" />
                    <div v-if="railTip(item, stage)" class="skip-tip">{{ railTip(item, stage) }}</div>
                    <div class="node">{{ railGlyph(stage) }}</div>
                    <div class="nm">{{ stage.label }}</div>
                    <!-- A stage that fans out over several nodes says so; one
                         that does not would only be saying "1". -->
                    <div
                      v-if="(stage.node_ids || []).length > 1"
                      class="sub"
                      :title="`${stage.node_ids.length} nodes`"
                    >×{{ stage.node_ids.length }}</div>
                  </div>
                </div>
              </div>

              <div v-if="jobDetail(item).failure" class="err-banner">
                <span class="ic" aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>
                </span>
                <div class="msg">
                  {{ jobDetail(item).failure.message }}
                  <div class="code">
                    {{ jobDetail(item).failure.code }} · {{ jobDetail(item).failure.node_id }}
                  </div>
                </div>
              </div>

              <div class="detail-grid">
                <div class="detail-cell">
                  <h4><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg> Script · S1</h4>
                  <div class="dkv"><span class="k">Mode</span><span class="v">{{ sourceModeLabel(jobDetail(item).source?.mode || item.source_mode) }}</span></div>
                  <div class="dkv"><span class="k">Channel</span><span class="v">{{ item.channel_name || item.channel_id }}</span></div>
                  <div v-if="jobDetail(item).source?.script_id" class="dkv">
                    <span class="k">Script</span><span class="v mono">{{ jobDetail(item).source.script_id }}</span>
                  </div>
                  <div class="dkv"><span class="k">Workflow</span><span class="v mono">{{ item.workflow_id || '—' }}</span></div>
                </div>
                <div class="detail-cell">
                  <h4><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2v20M6 8v8M18 8v8M2 11v2M22 11v2"/></svg> Narration · TTS</h4>
                  <div class="dkv">
                    <span class="k">Status</span>
                    <span class="v">
                      <span v-if="jobDetail(item).source?.narration_artifact_id" class="mini-tag mini-ok">Ready</span>
                      <span v-else class="mini-tag mini-wait">Pending</span>
                    </span>
                  </div>
                  <div class="dkv"><span class="k">Duration</span><span class="v mono">{{ jobDetail(item).source?.narration_duration_s ? `${jobDetail(item).source.narration_duration_s}s` : '—' }}</span></div>
                  <div class="dkv"><span class="k">Language</span><span class="v mono">{{ jobDetail(item).source?.language || '—' }}</span></div>
                </div>
                <div class="detail-cell">
                  <h4><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg> Production</h4>
                  <div class="dkv"><span class="k">Current stage</span><span class="v">{{ stageKeyLabel(item, item.current_stage) || '—' }}</span></div>
                  <div class="dkv"><span class="k">Progress</span><span class="v mono">{{ activeStageProgress == null ? '—' : `${activeStageProgress}%` }}</span></div>
                  <div class="dkv"><span class="k">Execution</span><span class="v">{{ executionModeLabel(item.execution_mode) || '—' }}</span></div>
                  <div class="dkv"><span class="k">Generations</span><span class="v mono">{{ item.budget_spent?.generations ?? 0 }}</span></div>
                </div>
              </div>

              <div class="detail-foot">
                <div class="ts"><span class="k">Created</span><span class="v">{{ jobTimestamp(item.created_at) }}</span></div>
                <div class="ts"><span class="k">Started</span><span class="v">{{ jobTimestamp(item.started_at) }}</span></div>
                <div class="ts"><span class="k">Completed</span><span class="v">{{ jobTimestamp(item.completed_at) }}</span></div>
                <div class="ts"><span class="k">Elapsed</span><span class="v">{{ jobElapsed(item) }}</span></div>
                <div class="spacer" />
                <div class="job-actions">
                  <button v-if="item.status === 'failed'" type="button" class="btn xs primary" :disabled="Boolean(jobActionRunning)" @click.stop="runJobAction('retry', item)">Retry</button>
                  <button type="button" class="btn xs" :disabled="Boolean(jobActionRunning)" @click.stop="runJobAction('duplicate', item)">Duplicate</button>
                  <button type="button" class="btn xs danger" :disabled="Boolean(jobActionRunning)" @click.stop="runJobAction('remove', item)">Remove</button>
                </div>
              </div>
            </div>
          </article>
        </template>
        <template #empty>
          <p class="muted job-empty">No jobs match “{{ jobSearch }}”.</p>
        </template>
      </ArchiveCalendar>
      </div>

    <p v-if="error" class="error sheet-error" role="alert">{{ error }}</p>
    <p v-if="pauseActionError" class="error" role="alert">{{ pauseActionError }}</p>
    <p v-if="streamError && !error" class="stream-warn" role="status">{{ streamError }}</p>

    <aside
      v-if="activeJob?.advisories?.some(a => a.code === 'LANGUAGE_MISMATCH')"
      class="language-banner"
      role="status"
    >
      <strong>Language mismatch — advisory only.</strong>
      {{ activeJob.advisories.find(a => a.code === 'LANGUAGE_MISMATCH').message }}
      Production can still run; narration remains authoritative.
    </aside>

    <p v-if="loading && hasStages" class="muted sheet-note">Loading stages…</p>

    <!-- The prototype has no separate step list: stages live on the job rail,
         and a stage is inspected by clicking its node there.

         This projection is the app's own surface — a filterable listbox with a
         roving tabindex, per-stage issue counts, and the StepDetailPanel that
         drives test-node runs. It carried a `Step projection · N stages`
         disclosure on the page, which is chrome the prototype was drawn
         without, so the disclosure is gone.

         `hidden` rather than deleted: the behaviour behind it is real and
         covered (stage selection, issue display, keyboard navigation), and it
         has no other entry point yet. Step 6.10 moves selection onto the rail
         nodes, and this block goes with it. Until then it is out of the view
         and out of the accessibility tree — the same posture it already had
         behind a collapsed <details>, minus the line of text. -->
    <div v-if="hasStages" class="stage-advanced sr-only" hidden>
      <div class="stage-layout">
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
    </div>
    </main>
  </section>
</template>

<style scoped>
.production-page {
  display: grid;
  grid-template-columns: var(--rail-w) minmax(0, 1fr);
  min-height: 0;
  height: 100%;
  overflow: hidden;
  max-width: none;
  margin: 0;
  padding: 0;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.sheet {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
}

.sheet-head {
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, var(--bg-2), rgba(14, 17, 22, 0.6));
  padding: 14px 24px 0;
  position: sticky;
  top: 0;
  z-index: 20;
}

.sheet-title-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.sheet-title-row h1 {
  margin: 0;
  font-family: var(--display);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.4px;
}

.sheet-kicker { color: var(--muted); font-size: 12.5px; }
.sheet-title-row .spacer,
.toolbar .spacer,
.selbar .spacer { flex: 1; }

.sheet-actions { display: flex; align-items: center; gap: 7px; flex-shrink: 0; }

.summary {
  display: flex;
  align-items: stretch;
  gap: 0;
  margin: 14px 0 12px;
}

.summary .stat {
  background: transparent;
  border: 0;
  text-align: left;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 14px;
  flex-wrap: wrap;
}

.search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  padding: 7px 11px;
  min-width: 210px;
}

.search:focus-within {
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.search input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-size: 13px;
  width: 100%;
  font-family: var(--body);
}

.search input::placeholder { color: var(--faint); }
.search svg { color: var(--muted); flex: none; }

.filter-select {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text-2);
  font-size: 12.5px;
  padding: 7px 10px;
  font-family: var(--body);
  cursor: pointer;
}

.filter-select:focus { outline: none; border-color: var(--accent-line-2); }

.batch-controls { display: flex; align-items: center; gap: 7px; }

.is-live {
  color: var(--run);
  border-color: var(--run);
  background: var(--run-dim);
}

.selbar {
  display: none;
  align-items: center;
  gap: 10px;
  padding: 8px 24px;
  border-bottom: 1px solid var(--line);
  background: var(--accent-wash);
  font-size: 13px;
}

.selbar.show { display: flex; animation: slidedown 0.18s ease; }

@keyframes slidedown {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: none; }
}

.selbar .cnt { font-weight: 600; color: var(--accent); }

.joblist {
  flex: none;
  min-width: 0;
  overflow: visible;
  padding: 14px 24px 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 2px 2px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.8px;
  text-transform: uppercase;
}

.group-head .line { flex: 1; height: 1px; background: var(--line-soft); }

.sheet-meta,
.sheet-error,
.sheet-note { padding: 8px 24px 0; }

.empty {
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 48px 24px;
  color: var(--muted);
}

.empty.show { display: flex; }

.empty .ic {
  width: 66px;
  height: 66px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  background: var(--panel);
  box-shadow: inset 0 0 0 1px var(--line);
  color: var(--faint);
  margin-bottom: 20px;
}

.empty h3 { margin: 0 0 8px; font-size: 17px; color: var(--text); }
.empty p { margin: 0; font-size: 13px; max-width: 360px; line-height: 1.6; }

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 20px;
}

.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.job-index { display: grid; gap: 12px; margin: 0 0 20px; padding: 16px; border: 1px solid var(--line); border-radius: var(--r); background: var(--panel-grad); }
.job-index-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.job-index-head h2 { margin: 0 0 3px; font-family: var(--display); font-size: 15px; }
.job-index-head p { margin: 0; color: var(--muted); font-size: 11.5px; }
.job-search { width: min(280px, 100%); display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--bg-2); color: var(--muted); }
.job-search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-dim); }
.job-search input { width: 100%; border: 0; outline: 0; background: transparent; color: var(--text); font: 12px var(--body); }
/* ================================================================
   The job row (prototype `.job` / `.srstage`, step 6.2).

   Ported in tokens rather than the prototype's inline literals, so the
   row follows whichever accent is in scope — the same rule the shared
   primitives follow.

   `.drag-handle` / `.dragging` / `.drag-over` (queue reordering) and
   `.job-menu-btn` (a context menu) stay unported: JobStatus has no
   draft/preparing/stopping members and the row menu is not a product
   surface yet. Batch selection (`.job-check` / `.sel-checked`) and
   the sheet scroller (`.joblist`) are live.

   `.job.kb-focus` and `.job:focus-visible` go with them. They ring a
   row the prototype's arrow-key navigation has landed on; here the
   row is not a tab stop at all — the chevron is the control, and it
   takes the shared `:focus-visible` treatment.
   ================================================================ */
.job {
  position: relative;
  flex: none;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: var(--panel-grad);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, .3);
  color: var(--text);
  transition: border-color .18s, box-shadow .18s, transform .18s var(--ease-spring);
}

/* The status spine: three pixels of colour on the left edge, lit only when
   the status is worth looking at. */
.job::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--faint);
  opacity: 0;
  transition: opacity .18s;
}

.job:hover { border-color: var(--line-2); box-shadow: var(--hairline-top), 0 8px 24px -12px rgba(0, 0, 0, .65); }

/* The open row wears the accent, because opening it is what bound the Job.
   It sits above the status rules deliberately: a running row that is also
   open keeps its run glow and takes only the accent border. */
.job.expanded { border-color: var(--accent-line-2); box-shadow: var(--hairline-top), inset 0 0 0 1px var(--accent-line); }

.job.st-running { box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, .3), inset 3px 0 12px -6px var(--run-glow); }
.job.st-running::before { background: var(--run); opacity: 1; box-shadow: var(--run-cast); }
.job.st-completed::before { background: var(--ok); opacity: .7; }
.job.st-failed::before { background: var(--fail); opacity: 1; }
.job.st-paused::before, .job.st-awaiting_approval::before { background: var(--sched); opacity: .8; }
.job.st-queued::before { background: var(--queue); opacity: .35; }
.job.st-cancelled::before { background: var(--faint); opacity: .5; }
.job.sel-checked { border-color: var(--accent-line-2); box-shadow: 0 0 0 1px var(--accent-line), 0 6px 20px -10px var(--accent-cast); }

.job-check {
  width: 17px;
  height: 17px;
  border-radius: 5px;
  border: 1.5px solid var(--line);
  flex: none;
  display: grid;
  place-items: center;
  cursor: pointer;
  padding: 0;
  background: var(--bg-2);
  color: transparent;
  box-shadow: none;
  transition: all 0.12s;
}

.job-check:hover { border-color: var(--line-2); transform: none; }
.job.sel-checked .job-check { background: var(--accent); border-color: var(--accent); color: #fff; }

.job-main {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 12px 14px 12px 15px;
  cursor: pointer;
}

.job-id { flex: none; width: 92px; font-family: var(--mono); font-size: 11px; letter-spacing: .2px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* The prototype's flex row: the shared `.ch-avatar` beside a text column
   (step 6.4). The avatar is derived from the channel id, so a job row and the
   Channels rail always show the same plate for the same channel. */
.job-ch { flex: none; width: 150px; min-width: 0; display: flex; align-items: center; gap: 9px; }
.job-ch .ch-avatar { width: 28px; height: 28px; font-size: 12px; border-radius: 7px; }
.job-ch .job-ch-txt { min-width: 0; }
.job-ch .nm { font-size: 12.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.job-ch .src { margin-top: 1px; font-family: var(--mono); font-size: 9.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.job-title { flex: 1; min-width: 0; }
.job-title .t { font-size: 13.5px; font-weight: 500; letter-spacing: -.1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.job-title .sub { display: flex; align-items: center; gap: 6px; margin-top: 2px; font-size: 11px; color: var(--muted); }

/* The compact stage indicator: what it is on, and how far in. */
.job-stage { flex: none; width: 168px; }
.job-stage .cur { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 5px; font-family: var(--mono); font-size: 11px; }
.job-stage .cur .nm { color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.job-stage .cur .pct { flex: none; font-weight: 600; color: var(--run); }
.job.st-completed .job-stage .cur .pct { color: var(--ok); }
.job.st-failed .job-stage .cur .pct { color: var(--fail); }
.job.st-completed .progress .fill { background: var(--ok); }
.job.st-failed .progress .fill { background: var(--fail); }
.job.st-paused .progress .fill, .job.st-awaiting_approval .progress .fill { background: var(--sched); }

.job-status { flex: none; width: 108px; display: flex; justify-content: flex-end; }

.job-elapsed { flex: none; width: 66px; text-align: right; font-family: var(--mono); font-size: 11px; color: var(--muted); }

/* Inline quick actions on completed rows — the two destinations that open
   beside Production rather than over it. */
.job-quick { flex: none; display: flex; align-items: center; gap: 5px; }

.quick-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  color: var(--text-2);
  font-family: var(--body);
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: border-color .13s, background .13s, color .13s;
}

.quick-btn:hover { border-color: var(--accent-line-2); background: var(--accent-dim); color: var(--text); }
.quick-btn svg { flex: none; }

/* Narrow enough that the row needs the width back: the label goes and the
   icon stands alone. It comes back at 820px, where the row has reflowed
   and .job-quick owns a line of its own. */
@media (max-width: 1240px) {
  .quick-btn span { display: none; }
  .quick-btn { padding: 6px; }
}

.job-expand-btn {
  flex: none;
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: transform .14s, color .14s;
}

.job-expand-btn:hover { color: var(--text); }
.job.expanded .job-expand-btn { transform: rotate(180deg); color: var(--text-2); }

/* ---------- Expanded detail ---------- */
.job-detail { border-top: 1px solid var(--line-soft); background: var(--bg-2); animation: job-detail-pop .18s ease; }

@keyframes job-detail-pop {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}

/* The stage rail — the signature element. Every node here is one stage of
   the backend projection; nothing in this block invents a stage. */
.rail-wrap { padding: 16px 18px 6px; }
.rail-wrap .rl-lbl { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; font-family: var(--mono); font-size: 10px; letter-spacing: .8px; text-transform: uppercase; color: var(--muted); }
.rail-wrap .rl-hint { color: var(--faint); }
.rail-note { margin: 0 0 12px; font-size: 12px; }

.stagerail { display: flex; align-items: flex-start; gap: 0; overflow-x: auto; padding-bottom: 6px; }

.srstage { position: relative; flex: 1 1 0; min-width: 62px; display: flex; flex-direction: column; align-items: center; gap: 7px; }

.srstage .node {
  position: relative;
  z-index: 2;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--raise);
  box-shadow: inset 0 0 0 1px var(--line);
  color: var(--faint);
  font-family: var(--mono);
  font-size: 13px;
  transition: background .3s, box-shadow .3s, color .3s;
}

.srstage .connector { position: absolute; z-index: 1; top: 15px; left: 50%; width: 100%; height: 2px; background: var(--line); }
.srstage:last-child .connector { display: none; }
.srstage .nm { font-family: var(--mono); font-size: 9.5px; letter-spacing: .2px; text-align: center; color: var(--muted); }
.srstage .sub { font-family: var(--mono); font-size: 8.5px; color: var(--faint); }

.srstage.done .node { background: var(--ok-dim); box-shadow: inset 0 0 0 1px var(--ok-line); color: var(--ok); }
.srstage.done .connector { background: linear-gradient(90deg, var(--ok), var(--line)); }
.srstage.active .node { background: var(--run-dim); box-shadow: inset 0 0 0 1.5px var(--run), 0 0 0 4px var(--run-ring); color: var(--run); animation: nodepulse 1.8s infinite; }
.srstage.active .nm { color: var(--run); }
.srstage.failed .node { background: var(--fail-dim); box-shadow: inset 0 0 0 1.5px var(--fail); color: var(--fail); }
.srstage.failed .nm { color: var(--fail); }
.srstage.skipped .node { background: var(--bg); border: 1px dashed var(--line); box-shadow: none; color: var(--faint); opacity: .5; }
.srstage.skipped .nm { color: var(--faint); opacity: .7; text-decoration: line-through; }
.srstage.pending .node { opacity: .55; }

@keyframes nodepulse {
  0%, 100% { box-shadow: inset 0 0 0 1.5px var(--run), 0 0 0 4px var(--run-ring); }
  50% { box-shadow: inset 0 0 0 1.5px var(--run), 0 0 0 7px transparent; }
}

/* Why a node is dimmed or red, on hover — never a bare restatement of the
   state the colour already carries. */
.skip-tip {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 30;
  width: 150px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--bg);
  box-shadow: var(--shadow);
  color: var(--text-2);
  font-family: var(--body);
  font-size: 11px;
  text-align: center;
  pointer-events: none;
  opacity: 0;
  transition: opacity .14s;
}

.srstage.skipped:hover .skip-tip, .srstage.failed:hover .skip-tip { opacity: 1; }
.skip-tip::after { content: ""; position: absolute; top: 100%; left: 50%; transform: translateX(-50%); border: 5px solid transparent; border-top-color: var(--line); }

/* Detail grid — three cells divided by hairlines, not three cards. */
.detail-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; margin-top: 10px; background: var(--line-soft); border-top: 1px solid var(--line-soft); }
.detail-cell { padding: 14px 18px; background: var(--bg-2); }
.detail-cell h4 { display: flex; align-items: center; gap: 7px; margin-bottom: 11px; font-family: var(--mono); font-size: 10px; font-weight: 500; letter-spacing: .8px; text-transform: uppercase; color: var(--muted); }

.dkv { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 4px 0; font-size: 12.5px; }
.dkv .k { color: var(--muted); }
.dkv .v { max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; font-weight: 500; color: var(--text); }
.dkv .v.mono { font-family: var(--mono); font-size: 11.5px; }

.mini-tag { font-family: var(--mono); font-size: 9.5px; letter-spacing: .3px; text-transform: uppercase; padding: 2px 7px; border-radius: 5px; }
.mini-ok { color: var(--ok); background: var(--ok-dim); }
.mini-skip { color: var(--muted); background: var(--bg); box-shadow: inset 0 0 0 1px var(--line); }
.mini-run { color: var(--run); background: var(--run-dim); }
.mini-wait { color: var(--faint); background: var(--bg); }

.detail-foot { display: flex; align-items: center; flex-wrap: wrap; gap: 18px; padding: 12px 18px; border-top: 1px solid var(--line-soft); background: var(--bg-2); }
.ts { display: flex; flex-direction: column; gap: 1px; }
.ts .k { font-family: var(--mono); font-size: 9px; letter-spacing: .6px; text-transform: uppercase; color: var(--faint); }
.ts .v { font-family: var(--mono); font-size: 11px; color: var(--text-2); }
.detail-foot .spacer { flex: 1; }
.job-actions { display: flex; align-items: center; gap: 7px; }

/* The failure, beside the rail node that carries it. */
.err-banner { display: flex; align-items: flex-start; gap: 10px; margin: 0 18px 14px; padding: 11px 13px; border: 1px solid var(--fail-line); border-radius: var(--r-s); background: var(--fail-dim); }
.err-banner .ic { flex: none; margin-top: 1px; color: var(--fail); }
.err-banner .msg { font-size: 12.5px; color: var(--fail-text); }
.err-banner .msg .code { margin-top: 3px; font-family: var(--mono); font-size: 10.5px; color: var(--fail); }

.failed-stage { color: var(--fail); font-weight: 600; }
.archived-label, .job-title .sub time { font-family: var(--mono); font-size: 10px; }
.language-badge { margin-left: 5px; padding: 1px 6px; border-radius: 5px; background: var(--warn-dim); box-shadow: inset 0 0 0 1px var(--warn-line); color: var(--warn); font-family: var(--mono); font-size: 9.5px; font-weight: 600; letter-spacing: .3px; text-transform: uppercase; white-space: nowrap; }
.language-banner { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin: 0 0 16px; padding: 12px 14px; border: 1px solid var(--warn-line); border-radius: var(--r-s); background: var(--warn-dim); color: var(--text); }
.language-banner strong { color: var(--warn); }
.job-empty { margin: 4px 0; text-align: center; }

/* The row reflows rather than truncating: title first, then the stage bar
   and the actions on their own lines. */
@media (max-width: 1180px) {
  .job-stage { width: 130px; }
  .job-ch { width: 120px; }
  .detail-grid { grid-template-columns: 1fr; }
}

@media (max-width: 980px) {
  .job-ch { display: none; }
  .job-elapsed { display: none; }
}

@media (max-width: 820px) {
  .job-main { flex-wrap: wrap; row-gap: 8px; padding: 12px; }
  .job-id { order: 0; width: auto; }
  .job-title { order: 1; flex: 1 1 60%; min-width: 140px; }
  .job-status { order: 2; width: auto; margin-left: auto; }
  .job-elapsed { order: 2; width: auto; display: block; }
  .job-expand-btn { order: 2; }
  .job-stage { order: 3; flex: 1 1 100%; width: auto; }
  .job-quick { order: 3; flex: 1 1 100%; }
  .job-quick .quick-btn { flex: 1; justify-content: center; }
  .job-quick .quick-btn span { display: inline; }
}

@media (max-width: 820px) {
  .production-page {
    grid-template-columns: 1fr;
    height: auto;
    overflow: auto;
  }
  .toolbar { row-gap: 8px; }
  .batch-controls { flex-wrap: wrap; }
  .summary { flex-wrap: wrap; row-gap: 12px; }
  .sheet-head { padding: 12px 14px 0; }
  .joblist { padding: 12px 14px 60px; }
  .sheet-title-row { flex-wrap: wrap; }
}

@media (max-width: 720px) {
  .job-index-head { align-items: stretch; flex-direction: column; }
  .job-search { width: auto; min-width: 0; }
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

.stage-advanced {
  display: none !important;
}

.stage-layout,
.cost-panel,
.language-banner,
.stage-empty-page {
  padding-left: 24px;
  padding-right: 24px;
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

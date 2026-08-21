<script setup>
/**
 * Schema (steps 1.2, 1.3) — the workflow graph as the engine holds it, and
 * the running Job reflected on it.
 *
 * Read-only by construction. The node registry says what each node is, the
 * workflow document says which nodes exist and how they wire, the stage
 * projection says which Production stage each one reports to, and the
 * execution stream says what is happening right now. Nothing on this page
 * edits or saves the graph, and no node or edge list is authored here:
 * change the backend's answer and the picture changes with it.
 *
 * **Freeze view holds this picture still and nothing else.** It closes no
 * stream, cancels no run and issues no request — the events keep arriving and
 * the badge counts how far behind the view has fallen. Pausing production is
 * the Production row's job, and this page has no endpoint that could do it.
 *
 * Step 1.4 adds Test with a provider override, Locate, and Retry around the
 * projection. Test is an exploratory execution and never advances the Job.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useToast } from '@/shared/composables/useToast.js'
import { statusLabel } from '@/features/production/stageStatus.js'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
import { AVAILABLE } from '@/features/providers/availability.js'
import SchemaCanvas from './components/SchemaCanvas.vue'
import SchemaInspector from './components/SchemaInspector.vue'
import { useSchemaGraph } from './composables/useSchemaGraph.js'
import { useSchemaLive } from './composables/useSchemaLive.js'
import {
  buildNodeStates,
  currentStageLabel,
  inspectorModel,
  nodeFailures,
  runProgress,
} from './live.js'
import {
  getExecution,
  listFailedJobs,
  listJobs,
  runWorkflow,
  testJobNode,
} from './api.js'

defineOptions({ name: 'SchemaPage' })

const route = useRoute()
const router = useRouter()
const toast = useToast()

const {
  workflows,
  runs,
  selectedWorkflowId,
  workflowDocument,
  templateId,
  projection,
  loading,
  error,
  stageError,
  nodes,
  edges,
  hasGraph,
  sourceLabel,
  load,
  loadRegistry,
  refreshWorkflows,
  refreshRuns,
  selectWorkflow,
  selectExecution,
} = useSchemaGraph()

const {
  jobId: liveJobId,
  job: liveJob,
  executionId: liveExecutionId,
  executionStatus: liveStatus,
  streamError,
  records: liveRecords,
  frozen,
  behind,
  running: liveRunning,
  attach: attachExecution,
  loadJob,
  toggleFreeze,
  detach: detachLive,
} = useSchemaLive()

const catalog = useProviderCatalogStore()

const canvasRef = ref(null)
const selectedNodeId = ref('')
const testOpen = ref(false)
const testRunning = ref(false)
const testResult = ref(null)
const failedJobs = ref([])

// ---------------------------------------------------------------------------
// The running Job, reflected
// ---------------------------------------------------------------------------

/**
 * Step 7.3: resolve the provider that would run each node, so the card names
 * the instance rather than the category.  Reads from the same catalog
 * `selectedProvider` the executor follows — change the selection and the card
 * changes with it, without touching the node registry.
 */
const enrichedNodes = computed(() => {
  return nodes.value.map((node) => {
    if (!node.providerDomain) return node
    const provider = catalog.selectedProvider(node.providerDomain)
    if (!provider) return node
    return {
      ...node,
      providerLabel: provider.label || provider.id || '',
      providerAvailable: provider.availability === AVAILABLE,
    }
  })
})

/** Every card's look, derived from the run — never authored here. */
const nodeStates = computed(() => buildNodeStates(nodes.value, liveRecords.value))
const progress = computed(() => runProgress(nodes.value, nodeStates.value))

const bound = computed(() => Boolean(liveExecutionId.value))

/**
 * The stage the run is standing in. The graph knows it live; the Job knows it
 * between runs. Both name it from the projection, so neither invents a stage.
 */
const stageNow = computed(() => {
  const fromGraph = currentStageLabel(nodes.value, nodeStates.value)
  if (fromGraph) return fromGraph
  const key = liveJob.value?.current_stage
  if (!key) return ''
  const stage = (projection.value?.stages || []).find((s) => s.key === key)
  return stage?.label || key
})

/**
 * Prototype `sch-live` tones. `paused` covers both a Production pause and an
 * approval gate; `cancelled` stays unmapped so it reads neutral like the
 * prototype, not as "waiting".
 */
const PILL_TONE = Object.freeze({
  running: 'on',
  queued: 'on',
  waiting: 'on',
  paused: 'paused',
  awaiting_approval: 'paused',
  succeeded: 'done',
  partial: 'done',
  failed: 'fail',
  invalid: 'fail',
})

/**
 * What the topbar pill says. `name` is the thing being watched and goes in the
 * prototype's `<b>`; the rest is where the run has got to.
 */
const pill = computed(() => {
  if (!bound.value) {
    return { name: '', text: 'Idle · no active job', tone: '' }
  }
  const status = String(liveStatus.value || '')
  const tone = PILL_TONE[status] || ''
  const bits = []
  if (stageNow.value) bits.push(stageNow.value)
  bits.push(`${progress.value.percent}%`)
  // Terminal runs and durable pauses name their status; an active run does not.
  if (!liveRunning.value || tone === 'paused') bits.push(statusLabel(status))
  return {
    name: liveJobId.value ? `Job ${liveJobId.value}` : `Run ${liveExecutionId.value}`,
    text: bits.join(' · '),
    tone,
  }
})

const selectedNode = computed(
  () => nodes.value.find((node) => node.id === selectedNodeId.value) || null,
)

const inspector = computed(() => inspectorModel(
  selectedNode.value,
  liveRecords.value[selectedNodeId.value] || null,
))

const failures = computed(() => nodeFailures(nodes.value, liveRecords.value))
// Which failure the detail panel is showing. Follows the list selection;
// defaults to the first when the set changes.
const activeFailureNodeId = ref('')
const currentFailure = computed(() => {
  const list = failures.value
  if (!list.length) return null
  return list.find((f) => f.nodeId === activeFailureNodeId.value) || list[0]
})
// When the failure set changes, keep a valid selection (default to the first).
watch(failures, (list) => {
  if (!list.some((f) => f.nodeId === activeFailureNodeId.value)) {
    activeFailureNodeId.value = list[0]?.nodeId || ''
  }
})

function selectFailure(failure) {
  if (!failure?.nodeId) return
  activeFailureNodeId.value = failure.nodeId
  // Indicate it on the canvas: select the node and pan/zoom to it.
  locateNode(failure.nodeId)
}
const errorCount = computed(() => {
  const ids = new Set(failedJobs.value.map((job) => job?.id).filter(Boolean))
  // The stream can paint a failure a fraction before the Job listing persists
  // it. Count the bound Job immediately without double-counting it later.
  if (currentFailure.value && liveJobId.value) ids.add(liveJobId.value)
  return ids.size
})

function onSelectNode(nodeId) {
  if (nodeId !== selectedNodeId.value) {
    testOpen.value = false
    testResult.value = null
  }
  selectedNodeId.value = nodeId || ''
}

function locateNode(nodeId) {
  if (!nodeId) return
  selectedNodeId.value = nodeId
  canvasRef.value?.locateNode(nodeId)
}

function resultForNode(execution, nodeId, fallback = {}) {
  const record = execution?.nodes?.[nodeId] || {}
  return {
    status: record.status || execution?.status || fallback.status || 'queued',
    from_sample_data: Boolean(record.from_sample_data),
    outputs_summary: record.outputs_summary || {},
    error: record.error || null,
    execution_id: execution?.execution_id || fallback.execution_id || '',
    provider_instance_id: record.cost?.provider_instance_id
      || fallback.provider_instance_id
      || '',
    selection_reason: record.cost?.selection_reason || '',
  }
}

/** Run Test beside the Job, never through the Job's production execution. */
async function onTestRun(payload) {
  const nodeId = payload?.nodeId
  if (!nodeId) return
  testRunning.value = true
  testResult.value = null
  try {
    let data
    if (liveJobId.value) {
      data = await testJobNode(liveJobId.value, {
        target_node_ids: [nodeId],
        input_bindings: payload.inputBindings || undefined,
        provider_instance_id: payload.providerInstanceId || undefined,
        force: false,
        wait: true,
        timeout: 120,
      })
    } else {
      if (!workflowDocument.value) throw new Error('No workflow is open for this test')
      data = await runWorkflow({
        workflow: workflowDocument.value,
        run_mode: payload.runMode || 'node_isolated',
        target_node_ids: [nodeId],
        input_bindings: payload.inputBindings || undefined,
        provider_instance_id: payload.providerInstanceId || undefined,
        force: false,
      })
    }

    let execution = data?.execution || null
    if (!execution && data?.execution_id) {
      const read = await getExecution(data.execution_id).catch(() => null)
      execution = read?.execution || read || null
    }
    testResult.value = resultForNode(execution, nodeId, data || {})
    toast.success(
      liveJobId.value
        ? `Test finished. Job ${liveJobId.value} was not advanced.`
        : 'Exploratory test started.',
    )
  } catch (err) {
    testResult.value = {
      status: 'failed',
      error: { code: err?.code || 'TEST_FAILED', message: err?.message || 'Test failed' },
      outputs_summary: {},
    }
    toast.error(err?.message || 'Node test failed')
  } finally {
    testRunning.value = false
  }
}

async function onRetryNode(nodeId = selectedNodeId.value) {
  if (!nodeId || !workflowDocument.value) return
  try {
    const data = await runWorkflow({
      workflow: workflowDocument.value,
      run_mode: 'retry_failed',
      target_node_ids: [nodeId],
      current_job_id: liveJobId.value || undefined,
      force: false,
    })
    toast.success(`Retry started for ${nodeId}`)
    if (data?.execution_id) {
      await bindRun(data.execution_id)
      await pushQuery({ run: data.execution_id, job: '' })
    }
  } catch (err) {
    toast.error(err?.message || 'Retry could not start')
  }
}

async function refreshFailedJobs() {
  try {
    const data = await listFailedJobs({ limit: 500 })
    failedJobs.value = data?.jobs || []
  } catch {
    failedJobs.value = []
  }
}

const LIVE_FOCUS = new Set(['running', 'paused', 'awaiting_approval'])

/**
 * The job the prototype would draw: a live one, else the first failure,
 * else the most recent completed. Schema never starts anything — it only
 * decides which existing run the canvas is watching.
 */
async function findFocusJob() {
  try {
    const data = await listJobs({ limit: 200 })
    const jobs = data?.jobs || []
    return jobs.find((job) => LIVE_FOCUS.has(job.status))
      || jobs.find((job) => job.status === 'failed')
      || jobs.find((job) => job.status === 'completed' || job.status === 'succeeded')
      || null
  } catch {
    return null
  }
}

/** One click: open the first failed Job, select its failed node, and centre it. */
async function onErrorBadge() {
  if (currentFailure.value) {
    locateNode(currentFailure.value.nodeId)
    return
  }
  const failed = failedJobs.value[0]
  if (!failed?.id) return
  try {
    await bindJob(failed.id)
    await pushQuery({ job: failed.id, run: '' })
    await nextTick()
    const target = failures.value[0]
    if (target) locateNode(target.nodeId)
    else toast.warning(`Job ${failed.id} failed, but its execution has no failed node record.`)
  } catch (err) {
    toast.error(err?.message || 'Could not locate that failed Job')
  }
}

function onToggleFreeze() {
  toast.info(
    toggleFreeze()
      ? 'View frozen. The job keeps running.'
      : 'View live again.',
    2200,
  )
}

// ---------------------------------------------------------------------------
// What is on screen
// ---------------------------------------------------------------------------

const stageCount = computed(() => {
  const keys = new Set()
  for (const node of nodes.value) {
    if (node.stageKey) keys.add(node.stageKey)
  }
  return keys.size
})

const meta = computed(() => {
  const bits = []
  if (sourceLabel.value) bits.push(sourceLabel.value)
  bits.push(`${nodes.value.length} nodes`)
  if (stageCount.value) bits.push(`${stageCount.value} stages`)
  return bits.join(' · ')
})

/** Deep-link state, so a reload lands back on the same graph and the same run. */
function pushQuery(patch) {
  const query = { ...route.query, ...patch }
  for (const [key, value] of Object.entries(query)) {
    if (!value) delete query[key]
  }
  return router.replace({ name: 'schema', query })
}

async function onPickWorkflow(event) {
  const id = event.target.value
  if (!id || id === selectedWorkflowId.value) return
  try {
    detachLive()
    selectedNodeId.value = ''
    await selectWorkflow(id)
    await refreshRuns(id)
    await pushQuery({ workflow: id, run: '', job: '' })
  } catch (err) {
    toast.error(err?.message || 'Could not open that workflow')
  }
}

async function onPickRun(event) {
  const id = event.target.value
  if (id === liveExecutionId.value) return
  if (!id) {
    detachLive()
    selectedNodeId.value = ''
    await pushQuery({ run: '', job: '' })
    return
  }
  try {
    await bindRun(id)
    await pushQuery({ run: id, job: '' })
  } catch (err) {
    toast.error(err?.message || 'Could not open that run')
  }
}

/** Draw a run's snapshot and follow it live. */
async function bindRun(executionId) {
  const execution = await selectExecution(executionId)
  attachExecution(execution)
  return execution
}

/**
 * Follow a Job: the pill names it, and its execution is what the graph
 * animates. A Job with no run yet still shows its workflow, idle.
 */
async function bindJob(jobId) {
  const job = await loadJob(jobId)
  if (job?.execution_id) {
    await bindRun(job.execution_id)
    await refreshRuns(job.workflow_id || selectedWorkflowId.value)
    return job
  }
  if (job?.workflow_id) {
    await selectWorkflow(job.workflow_id)
    await refreshRuns(job.workflow_id)
  }
  return job
}

function onRealign({ message }) {
  if (message) toast.info(message, 2000)
}

/**
 * Open what the URL asks for: a Job, else a run, else a workflow, else
 * whatever `load` finds. The Job wins because it is the thing a person is
 * actually watching; the run and the workflow are how it is addressed.
 */
async function openFromRoute() {
  const jobId = typeof route.query.job === 'string' ? route.query.job : ''
  const runId = typeof route.query.run === 'string' ? route.query.run : ''
  const workflowId = typeof route.query.workflow === 'string' ? route.query.workflow : ''

  if (jobId || runId) {
    // A run still needs the registry to know what its nodes *are*, and the
    // workflow list to fill the picker. `load` fetches both on its own path;
    // the run path would otherwise draw unlabelled, uncoloured cards.
    try {
      await loadRegistry()
    } catch {
      return // surfaced through `error` — there is no picture without it
    }
    await refreshWorkflows()
  }

  if (jobId) {
    try {
      await bindJob(jobId)
      return
    } catch (err) {
      toast.error(err?.message || 'Could not open that job')
    }
  }
  if (runId) {
    try {
      await bindRun(runId)
      await refreshRuns(selectedWorkflowId.value)
      return
    } catch {
      // Reported through `error`; fall through to the workflow it belongs to.
    }
  }
  if (workflowId) {
    await load(workflowId).catch(() => null)
    await refreshRuns(selectedWorkflowId.value)
    return
  }

  // Bare Schema follows the batch, the way the prototype's schemaFocusJob does.
  const focus = await findFocusJob()
  if (focus?.id) {
    try {
      await loadRegistry()
      await refreshWorkflows()
      await bindJob(focus.id)
      return
    } catch {
      // Fall through to the idle default graph.
    }
  }
  await load('').catch(() => null)
  await refreshRuns(selectedWorkflowId.value)
}

onMounted(() => {
  void catalog.loadCatalog()
  void refreshFailedJobs()
  void openFromRoute()
})

// Following the deep link keeps Schema addressable from Production and the
// Library without this page owning a second navigation model.
watch(
  () => [route.query.workflow, route.query.run, route.query.job],
  async ([workflowId, runId, jobId]) => {
    if (jobId && jobId !== liveJobId.value) {
      await bindJob(jobId).catch(() => null)
      return
    }
    if (runId && runId !== liveExecutionId.value) {
      await bindRun(runId).catch(() => null)
      return
    }
    if (typeof workflowId === 'string' && workflowId && workflowId !== selectedWorkflowId.value) {
      await selectWorkflow(workflowId).catch(() => null)
      await refreshRuns(workflowId)
    }
  },
)
</script>

<template>
  <section class="schema-page schema-view">
    <header class="sch-topbar">
      <div class="sch-title">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <rect x="3" y="3" width="7" height="5" rx="1" />
          <rect x="14" y="8" width="7" height="5" rx="1" />
          <rect x="3" y="16" width="7" height="5" rx="1" />
          <path d="M10 5.5h2a2 2 0 0 1 2 2v3M10 18.5h2a2 2 0 0 0 2-2v-3" />
        </svg>
        <h1>Workflow Schema</h1>
        <span class="sch-sub">Read-only overview · nodes animate live as a job runs</span>
      </div>

      <div class="spacer" />

      <button
        v-if="errorCount"
        class="sch-errbadge"
        type="button"
        :aria-label="`Locate first of ${errorCount} failed jobs`"
        @click="onErrorBadge"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" />
        </svg>
        {{ errorCount }} error{{ errorCount === 1 ? '' : 's' }}
      </button>

      <p class="sch-live" :class="pill.tone" role="status">
        <span class="dot" aria-hidden="true" />
        <b v-if="pill.name">{{ pill.name }}</b>
        {{ pill.text }}
      </p>

      <button
        class="sch-pause"
        type="button"
        :class="{ on: frozen }"
        :aria-pressed="String(frozen)"
        title="Freeze the canvas animation — does not pause the jobs (use the job row's Pause for that)"
        @click="onToggleFreeze"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <rect x="6" y="5" width="4" height="14" rx="1" />
          <rect x="14" y="5" width="4" height="14" rx="1" />
        </svg>
        <span>{{ frozen ? `Frozen · ${behind}` : 'Freeze view' }}</span>
      </button>

      <div class="sch-zoom" role="group" aria-label="Zoom">
        <button class="sch-zbtn" type="button" aria-label="Zoom out" @click="canvasRef?.zoomStep(-1)">−</button>
        <button class="sch-zbtn" type="button" @click="canvasRef?.fit()">Fit</button>
        <button class="sch-zbtn" type="button" aria-label="Zoom in" @click="canvasRef?.zoomStep(1)">+</button>
      </div>
    </header>

    <p v-if="templateId" class="banner info sch-banner">
      No saved workflow yet — showing the built-in <strong>{{ sourceLabel }}</strong>.
    </p>
    <p v-if="stageError" class="banner warn sch-banner">
      Stage projection unavailable, so nodes show their category instead of a stage:
      {{ stageError }}
    </p>
    <p v-if="error" class="banner error sch-banner">{{ error }}</p>
    <p v-if="streamError && !error" class="banner warn sch-banner" role="status">
      {{ streamError }}
    </p>
    <p v-if="frozen" class="banner info sch-banner" role="status">
      View frozen — the job is still running. {{ behind }} update{{ behind === 1 ? '' : 's' }}
      waiting.
    </p>

    <div v-if="hasGraph" class="sch-stage">
      <SchemaCanvas
        ref="canvasRef"
        :nodes="enrichedNodes"
        :edges="edges"
        :node-states="nodeStates"
        :selected-id="selectedNodeId"
        :percent="bound ? progress.percent : null"
        :bound="bound"
        @realign="onRealign"
        @select="onSelectNode"
      />
      <SchemaInspector
        :model="inspector"
        :bound="bound"
        :job-id="liveJobId"
        :test-open="testOpen"
        :test-running="testRunning"
        :test-result="testResult"
        @close="onSelectNode('')"
        @locate="locateNode(selectedNodeId)"
        @retry="onRetryNode(selectedNodeId)"
        @open-test="testOpen = true"
        @close-test="testOpen = false"
        @test-run="onTestRun"
      />

      <aside class="sch-err" :class="{ show: Boolean(currentFailure) }" aria-label="Workflow error">
        <template v-if="currentFailure">
          <div class="se-head">
            <span class="se-ic" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" />
              </svg>
            </span>
            <div class="se-t">
              {{ failures.length > 1 ? `${failures.length} workflow errors` : 'Workflow error' }}
              <span class="se-node">{{ currentFailure.name }}</span>
            </div>
          </div>

          <!-- When more than one node failed, list them; click to indicate on
               the canvas and show that error's detail below. -->
          <ul v-if="failures.length > 1" class="se-list" aria-label="Failed nodes">
            <li
              v-for="failure in failures"
              :key="failure.nodeId"
            >
              <button
                type="button"
                class="se-list-item"
                :class="{ on: failure.nodeId === currentFailure.nodeId }"
                @click="selectFailure(failure)"
              >
                <span class="se-dot" aria-hidden="true"></span>
                <span class="se-li-name">{{ failure.name }}</span>
                <span class="se-li-code">{{ failure.code || 'FAILED' }}</span>
              </button>
            </li>
          </ul>
          <div class="se-body">
            <div class="se-row"><span class="k">Node</span><span class="v">{{ currentFailure.name }}</span></div>
            <div class="se-row"><span class="k">Stage</span><span class="v">{{ currentFailure.stageLabel || '—' }}</span></div>
            <div class="se-row">
              <span class="k">Job</span>
              <span class="v mono">{{ liveJobId || 'Unbound run' }}</span>
            </div>
            <p class="se-why">{{ currentFailure.message || 'The node failed.' }}</p>
            <p v-if="currentFailure.code" class="se-code">{{ currentFailure.code }}</p>
          </div>
          <div class="se-foot">
            <button class="btn xs" type="button" @click="locateNode(currentFailure.nodeId)">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" />
              </svg>
              Locate node
            </button>
            <button class="btn xs primary" type="button" @click="onRetryNode(currentFailure.nodeId)">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" />
              </svg>
              Retry
            </button>
          </div>
        </template>
      </aside>
    </div>
    <div v-else class="sch-empty">
      <p v-if="loading">Loading the graph…</p>
      <p v-else>
        No workflow graph to project. Create one from a template in the workflow
        builder, then come back.
      </p>
    </div>
  </section>
</template>

<style scoped>
.schema-page,
.schema-view {
  display: flex;
  flex-direction: column;
  grid-template-columns: 1fr;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.sch-topbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 22px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, var(--bg-2), rgba(14, 17, 22, 0.6));
  z-index: 5;
}

.sch-title {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.sch-title svg { color: var(--muted); flex: none; }

.sch-title h1 {
  margin: 0;
  font-family: var(--display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: var(--text);
  white-space: nowrap;
}

.sch-sub {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}

.spacer {
  flex: 1 1 auto;
}

.sch-meta {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.sch-errbadge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid rgba(240, 97, 109, 0.4);
  border-radius: 20px;
  background: var(--fail-dim);
  color: var(--fail);
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.sch-errbadge:hover {
  background: rgba(240, 97, 109, 0.22);
}

.sch-errbadge svg {
  color: var(--fail);
}

.sch-zoom {
  display: flex;
  gap: 4px;
}

.sch-zbtn {
  width: 30px;
  height: 30px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}

.sch-zbtn:hover {
  background: var(--panel-2);
  color: var(--text);
}

/* The prototype's `sch-pause` freezes the canvas animation and says so in its
   own tooltip; here it freezes the whole view. Neither pauses a job — that is
   the Production row's control, and this page has no endpoint for it. */
.sch-pause {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text-2);
  font-family: var(--body);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
}

.sch-pause:hover {
  background: var(--panel-2);
  color: var(--text);
}

/* Held still is a state worth seeing from across the room — someone who
   forgot they froze the view would otherwise read a stalled job. */
.sch-pause.on {
  color: var(--warn);
  border-color: rgba(224, 164, 74, 0.4);
  background: var(--warn-dim);
}

.sch-pause.on svg { color: var(--warn); }

/* The run, named: job, stage, percent. */
.sch-live {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 5px 12px 5px 10px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--panel);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.sch-live .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--faint);
}

.sch-live b {
  color: var(--text-2);
  font-weight: 600;
}

.sch-live.on {
  color: var(--run);
  border-color: rgba(88, 166, 255, 0.4);
  background: var(--run-dim);
}

.sch-live.on .dot {
  background: var(--run);
  animation: schlivepulse 1.6s infinite;
}

.sch-live.on b { color: var(--run); }

.sch-live.done {
  color: var(--ok);
  border-color: rgba(63, 182, 139, 0.4);
  background: var(--ok-dim);
}

.sch-live.done .dot { background: var(--ok); }

.sch-live.fail {
  color: var(--fail);
  border-color: rgba(240, 97, 109, 0.4);
  background: var(--fail-dim);
}

.sch-live.fail .dot { background: var(--fail); }

.sch-live.paused {
  color: var(--sched);
  border-color: rgba(185, 139, 255, 0.4);
  background: var(--sched-dim);
}

.sch-live.paused .dot { background: var(--sched); }
.sch-live.paused b { color: var(--sched); }

@keyframes schlivepulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

@media (prefers-reduced-motion: reduce) {
  .sch-live.on .dot { animation: none; }
}

/* The canvas and the panel that opens over it. */
.sch-stage {
  position: relative;
  flex: 1 1 auto;
  display: flex;
  min-height: 0;
}

/* Bottom-right of the canvas: which node failed, and why. Mounted and hidden
   like the prototype, so opening it is a class change. */
.sch-err {
  display: none;
  position: absolute;
  right: 16px;
  bottom: 14px;
  z-index: 8;
  width: 320px;
  max-width: calc(100% - 32px);
  overflow: hidden;
  border: 1px solid rgba(240, 97, 109, 0.45);
  border-radius: var(--r);
  background: rgba(10, 13, 18, 0.94);
  backdrop-filter: blur(8px);
  box-shadow: 0 18px 44px -14px rgba(0, 0, 0, 0.85), 0 0 0 1px rgba(240, 97, 109, 0.1);
  animation: schpop 0.18s ease;
}

.sch-err.show { display: block; }

@keyframes schpop {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
}

/* The inspector owns the right edge when it is open. */
.sch-inspect.show ~ .sch-err {
  right: 348px;
}

.se-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(240, 97, 109, 0.2);
  background: var(--fail-dim);
}

.se-ic {
  flex: none;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: rgba(240, 97, 109, 0.2);
  color: var(--fail);
}

/* Clickable list of every failed node (shown when there is more than one). */
.se-list {
  margin: 0; padding: 6px; list-style: none;
  max-height: 168px; overflow-y: auto;
  border-bottom: 1px solid var(--line-soft);
}
.se-list li { margin: 0; }
.se-list-item {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 7px 9px; border: 0; border-radius: 7px;
  background: transparent; color: var(--text-2); font: inherit; font-size: 12px;
  text-align: left; cursor: pointer; transition: background .12s, color .12s;
}
.se-list-item:hover { background: var(--raise); color: var(--text); }
.se-list-item.on { background: var(--fail-dim); color: var(--fail-text, var(--text)); }
.se-dot { flex: none; width: 7px; height: 7px; border-radius: 50%; background: var(--fail); }
.se-li-name { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
.se-li-code { flex: none; font-family: var(--mono); font-size: 9px; letter-spacing: .3px; color: var(--muted); }
.se-list-item.on .se-li-code { color: var(--fail); }

.se-t {
  font-family: var(--display);
  font-size: 13px;
  font-weight: 600;
  color: var(--fail-text);
}

.se-t .se-node {
  display: block;
  margin-top: 1px;
  color: var(--fail);
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.2px;
}

.se-body {
  padding: 12px 14px;
}

.se-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 4px 0;
  font-size: 12px;
}

.se-row .k {
  flex: none;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.4px;
  text-transform: uppercase;
}

.se-row .v {
  min-width: 0;
  color: var(--text);
  font-weight: 500;
  text-align: right;
  overflow-wrap: anywhere;
}

.se-row .v.mono {
  font-family: var(--mono);
  font-size: 11px;
}

.se-why {
  margin: 9px 0 0;
  color: var(--fail-text);
  font-size: 12.5px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.se-code {
  margin: 9px 0 0;
  padding: 7px 9px;
  border-radius: 6px;
  background: rgba(240, 97, 109, 0.08);
  color: var(--fail);
  font-family: var(--mono);
  font-size: 10.5px;
  word-break: break-word;
}

.se-foot {
  display: flex;
  gap: 8px;
  padding: 11px 14px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg-2);
}

.se-foot .btn { flex: 1; }

@media (prefers-reduced-motion: reduce) {
  .sch-err { animation: none; }
}

.sch-banner {
  flex: none;
  margin: 10px 22px 0;
}

.sch-empty {
  flex: 1 1 auto;
  display: grid;
  place-items: center;
  padding: 40px 22px;
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

@media (max-width: 980px) {
  .sch-sub { display: none; }
}

@media (max-width: 820px) {
  .sch-topbar {
    flex-wrap: wrap;
    gap: 10px;
    padding: 10px 14px;
  }

  .sch-meta {
    order: 3;
    width: 100%;
  }

  .sch-live {
    order: 2;
  }

  .sch-inspect.show ~ .sch-err {
    right: 16px;
    bottom: calc(55% + 24px);
  }
}
</style>

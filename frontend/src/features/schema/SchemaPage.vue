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
import SchemaCanvas from './components/SchemaCanvas.vue'
import SchemaInspector from './components/SchemaInspector.vue'
import { useSchemaGraph } from './composables/useSchemaGraph.js'
import { useSchemaLive } from './composables/useSchemaLive.js'
import {
  buildNodeStates,
  currentStageLabel,
  flowingEdgeIds,
  inspectorModel,
  nodeFailures,
  runProgress,
} from './live.js'
import {
  getExecution,
  listFailedJobs,
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

const canvasRef = ref(null)
const selectedNodeId = ref('')
const testOpen = ref(false)
const testRunning = ref(false)
const testResult = ref(null)
const failedJobs = ref([])

// ---------------------------------------------------------------------------
// The running Job, reflected
// ---------------------------------------------------------------------------

/** Every card's look, derived from the run — never authored here. */
const nodeStates = computed(() => buildNodeStates(nodes.value, liveRecords.value))
const flowingEdges = computed(() => flowingEdgeIds(edges.value, nodeStates.value))
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

const pill = computed(() => {
  if (!bound.value) return null
  const bits = []
  bits.push(liveJobId.value ? `Job ${liveJobId.value}` : `Run ${liveExecutionId.value}`)
  if (stageNow.value) bits.push(stageNow.value)
  bits.push(`${progress.value.percent}%`)
  return {
    text: bits.join(' · '),
    live: liveRunning.value,
    status: statusLabel(liveStatus.value),
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
const currentFailure = computed(() => failures.value[0] || null)
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
  await load(workflowId).catch(() => null)
  await refreshRuns(selectedWorkflowId.value)
}

onMounted(() => {
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
  <section class="schema-page">
    <header class="sch-topbar">
      <div class="sch-title">
        <h1>Workflow Schema</h1>
        <p class="sch-sub">
          Read-only graph. Test and Retry create separate engine executions; they never edit it.
        </p>
      </div>

      <div class="spacer" />

      <button
        v-if="errorCount"
        class="sch-errbadge"
        type="button"
        :aria-label="`Locate first of ${errorCount} failed jobs`"
        @click="onErrorBadge"
      >
        <span aria-hidden="true">!</span>
        {{ errorCount }} error{{ errorCount === 1 ? '' : 's' }}
      </button>

      <p v-if="pill" class="sch-live-pill" :class="{ running: pill.live }" role="status">
        <span v-if="pill.live" class="dot" aria-hidden="true" />
        {{ pill.text }}
        <span v-if="!pill.live" class="pill-status">· {{ pill.status }}</span>
      </p>

      <label v-if="workflows.length" class="sch-pick">
        <span class="sr-only">Workflow</span>
        <select :value="selectedWorkflowId" @change="onPickWorkflow">
          <option v-for="wf in workflows" :key="wf.workflow_id" :value="wf.workflow_id">
            {{ wf.name || wf.workflow_id }}
          </option>
        </select>
      </label>

      <label v-if="runs.length" class="sch-pick">
        <span class="sr-only">Run</span>
        <select :value="liveExecutionId" @change="onPickRun">
          <option value="">No run — idle graph</option>
          <option v-for="run in runs" :key="run.execution_id" :value="run.execution_id">
            {{ run.execution_id }}<template v-if="run.status"> — {{ statusLabel(run.status) }}</template>
          </option>
        </select>
      </label>

      <div v-if="meta" class="sch-meta">{{ meta }}</div>

      <button
        v-if="bound"
        class="sch-zbtn freeze"
        type="button"
        :class="{ on: frozen }"
        :aria-pressed="String(frozen)"
        title="Hold this view still. The job keeps running."
        @click="onToggleFreeze"
      >
        {{ frozen ? `Frozen · ${behind}` : 'Freeze view' }}
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
        :nodes="nodes"
        :edges="edges"
        :node-states="nodeStates"
        :flowing-edges="flowingEdges"
        :selected-id="selectedNodeId"
        :percent="bound ? progress.percent : null"
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

      <aside v-if="currentFailure" class="sch-error-panel" aria-label="Workflow error">
        <header>
          <span class="se-icon" aria-hidden="true">!</span>
          <strong>Workflow error</strong>
          <span>{{ currentFailure.name }}</span>
        </header>
        <dl>
          <div><dt>Node</dt><dd>{{ currentFailure.name }}</dd></div>
          <div><dt>Stage</dt><dd>{{ currentFailure.stageLabel || 'â€”' }}</dd></div>
          <div><dt>Job</dt><dd class="mono">{{ liveJobId || 'Unbound run' }}</dd></div>
        </dl>
        <p>{{ currentFailure.message || 'The node failed.' }}</p>
        <code>{{ currentFailure.code || 'ERROR' }}</code>
        <footer>
          <button type="button" @click="locateNode(currentFailure.nodeId)">Locate node</button>
          <button class="primary" type="button" @click="onRetryNode(currentFailure.nodeId)">Retry</button>
        </footer>
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
.schema-page {
  display: flex;
  flex-direction: column;
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

.sch-title h1 {
  margin: 0;
  font-family: var(--display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.2px;
  color: var(--text);
}

.sch-sub {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--muted);
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
  border: 1px solid var(--fail-line);
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
  filter: brightness(1.15);
}

.sch-pick select {
  height: 30px;
  max-width: 220px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text-2);
  font-family: var(--body);
  font-size: 12px;
}

.sch-zoom {
  display: flex;
  gap: 4px;
}

.sch-zbtn {
  width: 34px;
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

.sch-zbtn.freeze {
  width: auto;
  padding: 0 11px;
  white-space: nowrap;
}

/* Held still is a state worth seeing from across the room — someone who
   forgot they froze the view would otherwise read a stalled job. */
.sch-zbtn.freeze.on {
  color: var(--warn-text);
  background: var(--warn-dim);
  border-color: var(--warn-line);
}

/* The run, named: job, stage, percent. */
.sch-live-pill {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0;
  padding: 5px 12px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--bg-2);
  font-family: var(--mono);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.3px;
  white-space: nowrap;
  color: var(--text-2);
}

.sch-live-pill.running {
  color: var(--run);
  background: var(--run-dim);
  border-color: var(--run-line);
}

.sch-live-pill .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: sch-pulse 1.6s ease-in-out infinite;
}

.sch-live-pill .pill-status {
  color: var(--faint);
}

@keyframes sch-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

@media (prefers-reduced-motion: reduce) {
  .sch-live-pill .dot {
    animation: none;
  }
}

/* The canvas and the panel that opens over it. */
.sch-stage {
  position: relative;
  flex: 1 1 auto;
  display: flex;
  min-height: 0;
}

.sch-error-panel {
  position: absolute;
  right: 12px;
  bottom: 12px;
  z-index: 7;
  width: 330px;
  max-width: calc(100% - 24px);
  padding: 13px 14px;
  border: 1px solid var(--fail-line);
  border-radius: var(--r);
  background: color-mix(in srgb, var(--fail-dim) 72%, var(--bg-2));
  box-shadow: var(--hairline-top), var(--shadow);
  color: var(--text-2);
}

.sch-inspector + .sch-error-panel {
  right: 344px;
}

.sch-error-panel header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.sch-error-panel header strong,
.sch-error-panel .se-icon,
.sch-error-panel code {
  color: var(--fail-text);
}

.sch-error-panel header span:last-child {
  color: var(--muted);
}

.sch-error-panel dl {
  margin: 11px 0;
}

.sch-error-panel dl div {
  display: flex;
  gap: 10px;
  margin-top: 5px;
}

.sch-error-panel dt {
  width: 44px;
  flex: none;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 9.5px;
  text-transform: uppercase;
}

.sch-error-panel dd,
.sch-error-panel p {
  margin: 0;
  font-size: 11.5px;
  overflow-wrap: anywhere;
}

.sch-error-panel code {
  display: block;
  margin-top: 8px;
  font-family: var(--mono);
  font-size: 10.5px;
}

.sch-error-panel footer {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.sch-error-panel footer button {
  min-height: 30px;
  padding: 0 11px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel-grad);
  color: var(--text-2);
  font: 600 11.5px var(--body);
  cursor: pointer;
}

.sch-error-panel footer button.primary {
  border-color: transparent;
  background: var(--accent-grad);
  color: #fff;
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

  .sch-live-pill {
    order: 2;
  }

  .sch-inspector + .sch-error-panel {
    right: 12px;
    bottom: calc(55% + 22px);
  }
}
</style>

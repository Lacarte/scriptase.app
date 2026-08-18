<script setup>
/**
 * Schema (steps 1.2, 1.3) — the workflow graph as the engine holds it, and
 * the running Job reflected on it.
 *
 * Read-only by construction. The node registry says what each node is, the
 * workflow document says which nodes exist and how they wire, the stage
 * projection says which Production stage each one reports to, and the
 * execution stream says what is happening right now. Nothing on this page
 * runs, edits or saves anything, and no node or edge list is authored here:
 * change the backend's answer and the picture changes with it.
 *
 * **Freeze view holds this picture still and nothing else.** It closes no
 * stream, cancels no run and issues no request — the events keep arriving and
 * the badge counts how far behind the view has fallen. Pausing production is
 * the Production row's job, and this page has no endpoint that could do it.
 *
 * Node actions — Test with a provider override, Locate, Retry — arrive in 1.4.
 */
import { computed, onMounted, ref, watch } from 'vue'
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
  runProgress,
} from './live.js'

defineOptions({ name: 'SchemaPage' })

const route = useRoute()
const router = useRouter()
const toast = useToast()

const {
  workflows,
  runs,
  selectedWorkflowId,
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

function onSelectNode(nodeId) {
  selectedNodeId.value = nodeId || ''
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

onMounted(openFromRoute)

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
          Read-only projection of the node graph. Schema watches the engine; it never runs it.
        </p>
      </div>

      <div class="spacer" />

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
      <SchemaInspector :model="inspector" :bound="bound" @close="onSelectNode('')" />
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
}
</style>

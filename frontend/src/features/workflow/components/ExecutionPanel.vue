<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useWorkflowStore } from '../stores/workflow.js'

const store = useWorkflowStore()
const router = useRouter()
const expanded = ref({})
const retrying = ref(false)
const actionMessage = ref('')
const cancellingQueueId = ref(null)
const panelCollapsedKey = 'sts.workflow.execution-panel-collapsed'
const panelCollapsed = ref(false)

try {
  panelCollapsed.value = window.localStorage.getItem(panelCollapsedKey) === '1'
} catch {
  // Storage can be unavailable in privacy-restricted browser contexts.
}

watch(panelCollapsed, (collapsed) => {
  try {
    window.localStorage.setItem(panelCollapsedKey, collapsed ? '1' : '0')
  } catch {
    // Collapsing still works for this session when storage is unavailable.
  }
})

const queueItems = computed(() => {
  const active = store.runQueue.filter((item) => ['pending', 'running'].includes(item.status))
  const recent = store.runQueue.filter((item) => !['pending', 'running'].includes(item.status))
  return [...active, ...recent].slice(0, Math.max(8, active.length))
})

const history = computed(() => {
  const items = [...store.executionHistory]
  const current = store.currentExecution
  if (current?.execution_id && !items.some((item) => item.execution_id === current.execution_id)) {
    items.unshift(current)
  }
  return items
})

const executionNodes = computed(() => {
  const execution = store.currentExecution
  if (!execution) return []
  const snapshotNodes = execution.workflow_snapshot?.nodes || store.nodes
  const maximum = Math.max(
    1,
    ...Object.values(execution.nodes || {}).map((record) => record.duration_ms || 0),
  )
  return snapshotNodes.map((node, index) => {
    const record = execution.nodes?.[node.id] || store.nodeExecution(node.id)
    return {
      id: node.id,
      name: node.name || node.id,
      type: node.type,
      index,
      record,
      width: record.duration_ms ? Math.max(4, (record.duration_ms / maximum) * 100) : 0,
    }
  })
})

const selectedNode = computed(() => executionNodes.value.find(
  (item) => item.id === store.selectedExecutionNodeId,
))

const canRetry = computed(() =>
  selectedNode.value?.record.status === 'failed'
  && !store.executionActive
  && store.nodes.some((node) => node.id === selectedNode.value.id),
)

watch(() => store.workflowId, (workflowId) => {
  if (workflowId) {
    void Promise.all([
      store.refreshExecutionHistory(workflowId),
      store.refreshRunQueue(workflowId),
    ]).catch(() => {})
  } else {
    store.clearExecutionHistory()
    store.clearRunQueue()
  }
}, { immediate: true })

watch(() => store.selectedExecutionNodeId, () => {
  expanded.value = {}
  actionMessage.value = ''
})

function duration(value) {
  if (!Number.isFinite(value)) return '—'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`
}

function runDuration(execution) {
  if (!execution?.started_at) return '—'
  const end = execution.finished_at ? Date.parse(execution.finished_at) : Date.now()
  const start = Date.parse(execution.started_at)
  return Number.isFinite(end - start) ? duration(Math.max(0, end - start)) : '—'
}

function dateTime(value) {
  if (!value) return 'Not finished'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString()
}

function errorText(error) {
  if (!error) return ''
  return error.message || error.code || 'Node failed'
}

function reasonText(reason) {
  return String(reason || 'not evaluated').replaceAll('_', ' ')
}

function preview(value) {
  if (value === undefined) return 'No data recorded'
  const text = JSON.stringify(value)
  if (!text || text === '{}') return 'No data recorded'
  return text.length > 150 ? `${text.slice(0, 147)}…` : text
}

function toggle(section) {
  expanded.value = { ...expanded.value, [section]: !expanded.value[section] }
}

async function inspect(executionId) {
  actionMessage.value = ''
  try {
    await store.inspectExecution(executionId)
  } catch (error) {
    actionMessage.value = error?.message || 'Could not load that run'
  }
}

async function refreshHistory() {
  if (!store.workflowId) return
  await Promise.all([store.refreshExecutionHistory(), store.refreshRunQueue()]).catch(() => {})
}

async function cancelPending(executionId) {
  cancellingQueueId.value = executionId
  actionMessage.value = ''
  try {
    await store.cancelPendingRun(executionId)
    actionMessage.value = `Cancelled pending run ${executionId}.`
  } catch (error) {
    actionMessage.value = store.runQueueError || error?.message || 'Pending run could not be cancelled'
  } finally {
    cancellingQueueId.value = null
  }
}

async function retry(mode) {
  if (!canRetry.value) return
  retrying.value = true
  actionMessage.value = ''
  try {
    const nodeId = selectedNode.value.id
    await store.runWorkflow({ runMode: mode, targetNodeIds: [nodeId] })
    actionMessage.value = mode === 'retry_failed'
      ? 'Retry started for the failed node only.'
      : 'Retry started for the failed node and its downstream nodes.'
  } catch (error) {
    actionMessage.value = store.executionError || error?.message || 'Retry could not start'
  } finally {
    retrying.value = false
  }
}

function openEditor() {
  if (store.editorProjectId) {
    router.push({ path: '/editor', query: { project: store.editorProjectId } })
  }
}
</script>

<template>
  <footer class="execution-panel" :class="{ collapsed: panelCollapsed }">
    <div class="execution-head">
      <div class="execution-heading">
        <span class="execution-title">Runs & diagnostics</span>
        <span v-if="store.currentExecution" class="execution-id">
          {{ store.currentExecution.execution_id }} · {{ store.currentExecution.status }}
        </span>
      </div>
      <div class="execution-actions">
        <span v-if="actionMessage" class="action-message" role="status">{{ actionMessage }}</span>
        <button
          class="quiet-button"
          :disabled="!store.workflowId || store.executionHistoryLoading"
          @click="refreshHistory"
        >{{ store.executionHistoryLoading ? 'Refreshing…' : 'Refresh history' }}</button>
        <button
          v-if="store.editorProjectId"
          class="execution-open"
          @click="openEditor"
        >Open in Timeline Editor</button>
        <button
          type="button"
          class="execution-collapse-toggle"
          :aria-expanded="!panelCollapsed"
          aria-controls="workflow-execution-panel-content"
          :aria-label="panelCollapsed ? 'Expand runs and diagnostics' : 'Collapse runs and diagnostics'"
          :title="panelCollapsed ? 'Expand runs and diagnostics' : 'Collapse runs and diagnostics'"
          @click="panelCollapsed = !panelCollapsed"
        >
          <span aria-hidden="true">{{ panelCollapsed ? '⌃' : '⌄' }}</span>
        </button>
      </div>
    </div>

    <div id="workflow-execution-panel-content" v-show="!panelCollapsed" class="execution-body">
      <div v-if="store.executionError || store.executionHistoryError || store.runQueueError" class="execution-stream-error" role="status">
        {{ store.executionError || store.executionHistoryError || store.runQueueError }}
      </div>

      <section class="queue-pane" aria-label="Run queue">
      <span class="pane-title">Run queue <b>{{ store.runQueueTotal }}</b></span>
      <span v-if="!queueItems.length" class="queue-empty">No queued runs.</span>
      <article
        v-for="item in queueItems"
        :key="item.execution_id"
        class="queue-item"
        :class="`status-${item.status}`"
      >
        <span class="execution-dot" />
        <code>{{ item.execution_id }}</code>
        <span>{{ item.source }} · {{ item.requested_run_mode }}</span>
        <strong>{{ item.status }}</strong>
        <button
          v-if="item.status === 'pending'"
          :disabled="cancellingQueueId === item.execution_id"
          @click="cancelPending(item.execution_id)"
        >{{ cancellingQueueId === item.execution_id ? 'Cancelling…' : 'Cancel' }}</button>
      </article>
      </section>

      <div class="execution-content">
      <aside class="history-pane" aria-label="Run history">
        <div class="pane-title">
          Run history
          <span v-if="store.executionHistoryTotal">{{ store.executionHistoryTotal }}</span>
        </div>
        <div v-if="!history.length" class="execution-empty">
          {{ store.workflowId ? 'No runs recorded for this workflow.' : 'Save the workflow to keep run history.' }}
        </div>
        <button
          v-for="run in history"
          :key="run.execution_id"
          class="history-row"
          :class="[`status-${run.status}`, { selected: run.execution_id === store.currentExecution?.execution_id }]"
          :disabled="store.executionActive && run.execution_id !== store.currentExecution?.execution_id"
          @click="inspect(run.execution_id)"
        >
          <span class="execution-dot" />
          <span class="history-main">
            <span class="history-id">{{ run.execution_id }}</span>
            <span class="history-date">{{ dateTime(run.started_at) }}</span>
          </span>
          <span class="history-meta">
            <span>{{ run.status }}</span>
            <span>{{ run.run_mode || 'full' }} · {{ runDuration(run) }}</span>
          </span>
        </button>
      </aside>

      <section class="timeline-pane" aria-label="Node timeline">
        <div class="pane-title">Node timeline</div>
        <div v-if="!store.currentExecution" class="execution-empty">
          Select a run to inspect its node timeline.
        </div>
        <button
          v-for="item in executionNodes"
          :key="item.id"
          class="execution-row"
          :class="[`status-${item.record.status}`, { selected: store.selectedExecutionNodeId === item.id }]"
          :disabled="!['succeeded', 'failed', 'cancelled', 'skipped'].includes(item.record.status)"
          @click="store.selectExecutionNode(item.id)"
        >
          <span class="timeline-order">{{ item.index + 1 }}</span>
          <span class="execution-dot" />
          <span class="execution-name">
            {{ item.name }}
            <small>{{ item.type }}</small>
          </span>
          <span v-if="item.record.from_sample_data" class="execution-sample">sample</span>
          <span class="timeline-track"><i :style="{ width: `${item.width}%` }" /></span>
          <span class="execution-status">{{ item.record.status }}</span>
          <span class="execution-duration">{{ duration(item.record.duration_ms) }}</span>
          <span class="attempt-count">{{ item.record.attempts || 0 }} attempt{{ item.record.attempts === 1 ? '' : 's' }}</span>
        </button>
      </section>

      <section class="detail-pane" aria-label="Selected node diagnostics">
        <template v-if="selectedNode">
          <div class="detail-heading">
            <div>
              <strong>{{ selectedNode.name }}</strong>
              <span>{{ selectedNode.record.status }} · {{ duration(selectedNode.record.duration_ms) }}</span>
            </div>
            <div v-if="selectedNode.record.status === 'failed'" class="retry-actions">
              <button :disabled="!canRetry || retrying" @click="retry('retry_failed')">Retry failed</button>
              <button :disabled="!canRetry || retrying" @click="retry('retry_failed_desc')">Retry + downstream</button>
            </div>
          </div>

          <div class="diagnostic-grid">
            <section class="metric-card">
              <span>Cache decision</span>
              <strong :class="selectedNode.record.cache?.hit ? 'cache-hit' : 'cache-miss'">
                {{ selectedNode.record.cache?.hit ? 'Hit' : 'Miss' }}
              </strong>
              <small>{{ reasonText(selectedNode.record.cache?.reason) }}</small>
            </section>
            <section class="metric-card">
              <span>Attempts</span>
              <strong>{{ selectedNode.record.attempts || 0 }}</strong>
              <small>{{ selectedNode.record.artifact_refs?.length || 0 }} artifacts</small>
            </section>
          </div>

          <section v-if="selectedNode.record.error" class="error-card">
            <div><strong>{{ selectedNode.record.error.code || 'NODE_FAILED' }}</strong> · attempt {{ selectedNode.record.error.attempt || selectedNode.record.attempts }}</div>
            <p>{{ errorText(selectedNode.record.error) }}</p>
            <small v-if="selectedNode.record.error.recovery_suggestion">{{ selectedNode.record.error.recovery_suggestion }}</small>
            <button @click="toggle('error')">{{ expanded.error ? 'Hide details' : 'Show structured error' }}</button>
            <pre v-if="expanded.error">{{ JSON.stringify(selectedNode.record.error, null, 2) }}</pre>
          </section>

          <section v-for="section in [
            { key: 'inputs', title: 'Resolved inputs', value: selectedNode.record.resolved_inputs_summary || {} },
            { key: 'outputs', title: 'Outputs', value: selectedNode.record.outputs_summary || {} },
            { key: 'artifacts', title: 'Artifact references', value: selectedNode.record.artifact_refs || [] },
          ]" :key="section.key" class="value-section">
            <div class="value-head">
              <span>{{ section.title }}</span>
              <button @click="toggle(section.key)">{{ expanded[section.key] ? 'Collapse' : 'Expand JSON' }}</button>
            </div>
            <code v-if="!expanded[section.key]">{{ preview(section.value) }}</code>
            <pre v-else>{{ JSON.stringify(section.value, null, 2) }}</pre>
          </section>

          <section class="logs-section">
            <div class="value-head">
              <span>Logs ({{ selectedNode.record.logs?.length || 0 }})</span>
              <button v-if="selectedNode.record.logs?.length > 4" @click="toggle('logs')">
                {{ expanded.logs ? 'Show latest' : 'Show all' }}
              </button>
            </div>
            <div v-if="!selectedNode.record.logs?.length" class="no-data">No logs recorded.</div>
            <div
              v-for="(log, index) in (expanded.logs ? selectedNode.record.logs : selectedNode.record.logs?.slice(-4))"
              :key="`${log.ts}-${index}`"
              class="log-row"
              :class="`log-${log.level}`"
            >
              <time>{{ dateTime(log.ts) }}</time><span>{{ log.level }}</span><p>{{ log.message }}</p>
            </div>
          </section>

          <section v-if="selectedNode.record.attempt_errors?.length" class="attempt-errors">
            <div class="value-head"><span>Attempt errors ({{ selectedNode.record.attempt_errors.length }})</span></div>
            <details v-for="failure in selectedNode.record.attempt_errors" :key="failure.attempt">
              <summary>Attempt {{ failure.attempt }} · {{ failure.code }}</summary>
              <p>{{ failure.message }}</p>
              <small>{{ failure.recovery_suggestion }}</small>
            </details>
          </section>
        </template>
        <div v-else class="execution-empty">Select a finished node to inspect inputs, outputs, logs, errors, attempts, and cache decisions.</div>
      </section>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.execution-panel { height: 300px; min-height: 220px; overflow: hidden; border-top: 1px solid var(--border); background: var(--bg-darkest); display: flex; flex-direction: column; color: var(--text-secondary); transition: height .18s ease, min-height .18s ease; }
.execution-panel.collapsed { height: 40px; min-height: 40px; }
.execution-panel.collapsed .execution-head { border-bottom-color: transparent; }
.execution-head { min-height: 38px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 5px 12px; border-bottom: 1px solid var(--border); }
.execution-body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.execution-heading, .execution-actions { display: flex; align-items: center; gap: 9px; min-width: 0; }
.execution-title, .pane-title { font-size: 9px; font-weight: 750; text-transform: uppercase; letter-spacing: .14em; color: var(--text-muted); }
.execution-id, .action-message { font-size: 9px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.execution-actions { justify-content: flex-end; }
.quiet-button, .execution-open, .retry-actions button, .value-head button, .error-card button { border: 1px solid var(--border); border-radius: 5px; background: rgba(255,255,255,.035); color: var(--text-secondary); font-size: 9px; padding: 4px 7px; cursor: pointer; }
.execution-collapse-toggle { width: 26px; height: 26px; flex: 0 0 26px; display: grid; place-items: center; padding: 0; border: 1px solid var(--border); border-radius: 6px; background: rgba(255,255,255,.035); color: var(--text-secondary); cursor: pointer; }
.execution-collapse-toggle span { display: block; height: 16px; font-size: 16px; line-height: 12px; }
.execution-collapse-toggle:hover { border-color: rgba(78,205,196,.45); background: rgba(78,205,196,.08); color: var(--accent); }
.execution-collapse-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
button:disabled { cursor: default; opacity: .45; }
.execution-open { border-color: rgba(78,205,196,.45); color: var(--accent); }
.execution-stream-error { padding: 3px 12px; border-bottom: 1px solid rgba(251,113,133,.3); background: rgba(68,20,30,.65); color: #fecdd3; font-size: 9px; }
.queue-pane { min-height: 34px; display: flex; align-items: center; gap: 6px; padding: 3px 9px; overflow-x: auto; border-bottom: 1px solid var(--border); }
.queue-pane > .pane-title { position: static; flex: 0 0 auto; padding: 0 6px 0 0; background: transparent; gap: 5px; }
.queue-pane > .pane-title b { color: var(--text-secondary); }
.queue-empty { color: var(--text-muted); font-size: 9px; }
.queue-item { --status-color: #64748b; flex: 0 0 auto; display: grid; grid-template-columns: 7px auto auto auto auto; align-items: center; gap: 5px; padding: 3px 5px; border: 1px solid var(--border); border-radius: 5px; font-size: 8px; }
.queue-item code { color: var(--text); }.queue-item span { color: var(--text-muted); }.queue-item strong { color: var(--status-color); text-transform: capitalize; }
.queue-item button { border: 1px solid rgba(245,158,11,.45); border-radius: 4px; background: transparent; color: #fbbf24; font-size: 8px; cursor: pointer; }
.execution-content { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(190px, .6fr) minmax(380px, 1.25fr) minmax(330px, 1.15fr); }
.history-pane, .timeline-pane, .detail-pane { min-width: 0; overflow: auto; }
.history-pane, .timeline-pane { border-right: 1px solid var(--border); }
.pane-title { position: sticky; top: 0; z-index: 1; display: flex; justify-content: space-between; padding: 7px 9px 5px; background: var(--bg-darkest); }
.pane-title span { font-variant-numeric: tabular-nums; }
.execution-empty { padding: 14px 10px; color: var(--text-muted); font-size: 10px; line-height: 1.45; }
.history-row, .execution-row { width: calc(100% - 10px); margin: 1px 5px; border: 0; border-radius: 5px; background: transparent; color: var(--text-secondary); text-align: left; }
.history-row { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 7px; padding: 6px; cursor: pointer; }
.history-row:hover:not(:disabled), .history-row.selected, .execution-row:hover:not(:disabled), .execution-row.selected { background: rgba(255,255,255,.06); color: var(--text); }
.execution-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--status-color, #64748b); }
.history-main, .history-meta, .execution-name { min-width: 0; display: flex; flex-direction: column; }
.history-id { font: 9px/1.3 var(--font-mono, monospace); color: var(--text); }
.history-date, .history-meta { font-size: 8px; color: var(--text-muted); }
.history-date, .history-meta span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.history-meta { align-items: flex-end; text-transform: capitalize; }
.execution-row { display: grid; grid-template-columns: 18px 8px minmax(105px, 1fr) auto minmax(48px, .55fr) 60px 48px 60px; align-items: center; gap: 6px; padding: 4px 6px; font-size: 9px; }
.timeline-order { color: var(--text-muted); text-align: right; font-variant-numeric: tabular-nums; }
.execution-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.execution-name small { color: var(--text-muted); font-size: 7px; overflow: hidden; text-overflow: ellipsis; }
.timeline-track { height: 3px; border-radius: 3px; background: rgba(255,255,255,.07); overflow: hidden; }
.timeline-track i { display: block; height: 100%; border-radius: inherit; background: var(--status-color, #64748b); }
.execution-status { color: var(--status-color, var(--text-muted)); text-transform: capitalize; }
.execution-duration, .attempt-count { color: var(--text-muted); text-align: right; font-variant-numeric: tabular-nums; }
.execution-sample { color: #c4b5fd; border: 1px solid rgba(196,181,253,.35); border-radius: 4px; padding: 0 3px; font-size: 7px; text-transform: uppercase; }
.detail-pane { padding: 8px 10px 14px; font-size: 9px; }
.detail-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 7px; }
.detail-heading > div:first-child { display: flex; flex-direction: column; }
.detail-heading strong { color: var(--text); font-size: 11px; }
.detail-heading span { color: var(--text-muted); text-transform: capitalize; }
.retry-actions { display: flex; gap: 4px; }
.retry-actions button:first-child { border-color: rgba(251,113,133,.4); color: #fda4af; }
.diagnostic-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; margin-bottom: 6px; }
.metric-card { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; border: 1px solid var(--border); border-radius: 5px; padding: 5px 7px; background: rgba(255,255,255,.018); }
.metric-card span { color: var(--text-muted); }.metric-card strong { color: var(--text); }.metric-card small { grid-column: 1 / -1; color: var(--text-muted); text-transform: capitalize; }
.cache-hit { color: #34d399 !important; }.cache-miss { color: #fb923c !important; }
.error-card { border: 1px solid rgba(251,113,133,.3); border-radius: 5px; background: rgba(68,20,30,.35); padding: 6px 7px; margin-bottom: 6px; color: #fecdd3; }
.error-card p { margin: 3px 0; }.error-card small { display: block; color: #fda4af; margin-bottom: 5px; }
.value-section, .logs-section, .attempt-errors { border-top: 1px solid var(--border); padding: 6px 0; }
.value-head { display: flex; justify-content: space-between; align-items: center; color: var(--text-muted); font-weight: 700; text-transform: uppercase; letter-spacing: .07em; }
.value-head button { padding: 2px 5px; }
.value-section code { display: block; margin-top: 4px; color: #a5b4c7; font: 8px/1.4 var(--font-mono, monospace); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
pre { max-height: 180px; overflow: auto; margin: 5px 0 0; padding: 6px; border-radius: 4px; background: rgba(0,0,0,.18); color: #cbd5e1; font: 8px/1.45 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.log-row { display: grid; grid-template-columns: 105px 42px 1fr; gap: 6px; padding: 3px 0; border-bottom: 1px solid rgba(255,255,255,.025); }
.log-row time, .log-row span { color: var(--text-muted); }.log-row p { margin: 0; color: var(--text-secondary); }
.log-error p, .log-error span { color: #fda4af; }.log-warning p, .log-warning span { color: #fbbf24; }
.no-data { color: var(--text-muted); padding-top: 5px; }
.attempt-errors details { margin-top: 4px; color: #fca5a5; }.attempt-errors p { margin: 3px 0; }.attempt-errors small { color: var(--text-muted); }
.status-idle, .status-queued, .status-pending { --status-color: #64748b; }.status-running { --status-color: #38bdf8; }.status-waiting { --status-color: #a78bfa; }.status-succeeded, .status-done { --status-color: #34d399; }.status-failed { --status-color: #fb7185; }.status-cancelled { --status-color: #f59e0b; }.status-skipped { --status-color: #94a3b8; }.status-stale { --status-color: #fb923c; }.status-partial { --status-color: #f59e0b; }
@media (max-width: 1100px) { .execution-content { grid-template-columns: 180px minmax(330px, 1fr) minmax(300px, 1fr); }.execution-row { grid-template-columns: 16px 7px minmax(90px, 1fr) auto 45px 55px 42px; }.attempt-count { display: none; } }
</style>

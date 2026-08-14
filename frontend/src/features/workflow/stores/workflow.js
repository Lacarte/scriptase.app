import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/shared/api/client.js'
import { apiErrorText } from '@/shared/api/errors.js'
import { validateConnection } from '../validation.js'
import { nodeIssues } from '../schema.js'
import { createExecutionEventStream } from '../composables/useExecutionEvents.js'
import { makeWorkflowFragment, parseWorkflowFragment } from '../fragments.js'

/**
 * Workflow builder store — the domain model behind the canvas.
 * Nodes/edges are stored in the persisted document shape (contracts.md §4);
 * WorkflowPage maps them to Vue Flow elements. Vue Flow runtime props never
 * enter this store.
 */

// Draft autosave (step 2.4). Drafts live in localStorage — not the backend —
// so a synchronous flush during beforeunload/visibilitychange can never be
// lost to an in-flight network call, and the frozen API surface stays intact.
export const DRAFT_STORAGE_KEY = 'sts-workflow-draft'
export const DRAFT_DEBOUNCE_MS = 1000
export const RECENT_NODE_TYPES_KEY = 'sts-workflow-recent-node-types'
export const RECENT_NODE_TYPES_LIMIT = 5

export const useWorkflowStore = defineStore('workflow', () => {
  // ── Registry (served by the backend, loaded once) ─────────────────────
  const registryVersion = ref(null)
  const nodeTypes = ref({})
  const categories = ref({})
  const portTypes = ref([])
  const samplePayloads = ref({})
  const registryLoading = ref(false)
  const registryError = ref('')
  const devReloadEnabled = ref(false)
  let devReloadSource = null

  async function loadNodeTypes({ force = false } = {}) {
    if (registryLoading.value || (!force && registryVersion.value !== null)) return
    registryLoading.value = true
    registryError.value = ''
    try {
      const data = await api.get('/api/workflow/node-types')
      registryVersion.value = data.registry_version
      nodeTypes.value = data.node_types || {}
      categories.value = data.categories || {}
      portTypes.value = data.port_types || []
      samplePayloads.value = data.sample_payloads || {}
      devReloadEnabled.value = data.dev_reload_enabled === true
    } catch (err) {
      registryError.value = apiErrorText(err, 'Failed to load node types')
    } finally {
      registryLoading.value = false
    }
  }

  function watchNodeTypeReloads({ EventSourceImpl = globalThis.EventSource } = {}) {
    if (!devReloadEnabled.value || devReloadSource || !EventSourceImpl) return null
    devReloadSource = new EventSourceImpl('/api/workflow/dev-reload/events')
    devReloadSource.addEventListener('registry-reload', () => loadNodeTypes({ force: true }))
    return devReloadSource
  }

  function closeNodeTypeReloads() {
    devReloadSource?.close()
    devReloadSource = null
  }

  // ── Document state (persisted shape only) ─────────────────────────────
  const workflowId = ref(null)
  const workflowName = ref('Untitled workflow')
  const workflowDescription = ref('')
  const nodes = ref([])   // {id, type, type_version, name, position, configuration, disabled}
  const edges = ref([])   // {id, source_node, source_port, target_node, target_port, edge_type}
  const viewport = ref({ x: 0, y: 0, zoom: 1 })
  const variables = ref({})
  const settings = ref({ on_error: 'stop' })
  const extensions = ref({})
  const createdAt = ref(null)
  const updatedAt = ref(null)
  const readOnly = ref(false)
  const loadWarnings = ref([])
  const migrationTrail = ref([])
  const dirty = ref(false)
  const draftSavedAt = ref(null)
  const recentNodeTypes = ref(loadRecentNodeTypes())

  function loadRecentNodeTypes() {
    try {
      const value = JSON.parse(globalThis.localStorage?.getItem(RECENT_NODE_TYPES_KEY) || '[]')
      return Array.isArray(value) ? value.filter((item) => typeof item === 'string').slice(0, RECENT_NODE_TYPES_LIMIT) : []
    } catch {
      return []
    }
  }

  function recordNodeUse(typeKey) {
    if (!nodeTypes.value[typeKey]) return false
    recentNodeTypes.value = [
      typeKey,
      ...recentNodeTypes.value.filter((item) => item !== typeKey),
    ].slice(0, RECENT_NODE_TYPES_LIMIT)
    try {
      globalThis.localStorage?.setItem(RECENT_NODE_TYPES_KEY, JSON.stringify(recentNodeTypes.value))
    } catch {
      /* storage unavailable: the session-local list still works */
    }
    return true
  }

  function clearRecentNodeTypes() {
    recentNodeTypes.value = []
    try {
      globalThis.localStorage?.removeItem(RECENT_NODE_TYPES_KEY)
    } catch {
      /* storage unavailable: the session-local list is still cleared */
    }
  }

  // Undo/redo is intentionally runtime-only. Commands capture a bounded,
  // complete graph-editing state, never enter workflow JSON, and make nested
  // mutations (add-with-stubs, stub replacement) one atomic history entry.
  const undoStack = ref([])
  const redoStack = ref([])
  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)
  const undoLabel = computed(() => undoStack.value.at(-1)?.label || '')
  const redoLabel = computed(() => redoStack.value.at(-1)?.label || '')
  const COMMAND_HISTORY_LIMIT = 100
  let commandDepth = 0

  function commandSnapshot() {
    return plain({
      nodes: nodes.value,
      edges: edges.value,
      settings: settings.value,
      extensions: extensions.value,
      staleNodeIds: staleNodeIds.value,
      selectedNodeId: selectedNodeId.value,
      dirty: dirty.value,
    })
  }

  function restoreCommandSnapshot(snapshot) {
    nodes.value = plain(snapshot.nodes)
    edges.value = plain(snapshot.edges)
    settings.value = plain(snapshot.settings)
    extensions.value = plain(snapshot.extensions)
    staleNodeIds.value = plain(snapshot.staleNodeIds)
    selectedNodeId.value = snapshot.selectedNodeId && nodeById(snapshot.selectedNodeId)
      ? snapshot.selectedNodeId
      : null
    dirty.value = Boolean(snapshot.dirty)
    if (dirty.value) scheduleDraftAutosave()
    else clearDraft()
  }

  function clearCommandHistory() {
    undoStack.value = []
    redoStack.value = []
  }

  function executeCommand(label, mutate) {
    if (readOnly.value) return false
    if (commandDepth > 0) return mutate()
    const before = commandSnapshot()
    commandDepth += 1
    let result
    try {
      result = mutate()
    } finally {
      commandDepth -= 1
    }
    const after = commandSnapshot()
    if (JSON.stringify(before) !== JSON.stringify(after)) {
      undoStack.value.push({
        label,
        kind: result?.detachedStub ? 'stub-detach' : null,
        before,
        after,
      })
      if (undoStack.value.length > COMMAND_HISTORY_LIMIT) undoStack.value.shift()
      redoStack.value = []
    }
    return result
  }

  function undo() {
    const command = undoStack.value.pop()
    if (!command) return false
    restoreCommandSnapshot(command.before)
    redoStack.value.push(command)
    return true
  }

  function redo() {
    const command = redoStack.value.pop()
    if (!command) return false
    restoreCommandSnapshot(command.after)
    undoStack.value.push(command)
    return true
  }

  // Live execution state (step 3.6). This is deliberately separate from the
  // persisted workflow document, so status updates never make a graph dirty.
  const currentExecution = ref(null)
  const executionLoading = ref(false)
  const executionError = ref('')
  const executionHistory = ref([])
  const executionHistoryTotal = ref(0)
  const executionHistoryLoading = ref(false)
  const executionHistoryError = ref('')
  const runQueue = ref([])
  const runQueueTotal = ref(0)
  const runQueueLoading = ref(false)
  const runQueueError = ref('')
  const selectedExecutionNodeId = ref(null)
  const staleNodeIds = ref([])
  let executionStream = null

  const executionActive = computed(() =>
    ['queued', 'running', 'cancelling'].includes(currentExecution.value?.status),
  )

  function emptyNodeExecution(status = 'idle') {
    return {
      status,
      attempts: 0,
      duration_ms: null,
      from_sample_data: false,
      fingerprint: null,
      cache: null,
      resolved_inputs_summary: {},
      outputs_summary: {},
      artifact_refs: [],
      logs: [],
      attempt_errors: [],
      error: null,
    }
  }

  function executionSummary(execution) {
    return {
      execution_id: execution.execution_id,
      workflow_id: execution.workflow_id,
      project_id: execution.project_id,
      run_mode: execution.run_mode,
      status: execution.status,
      started_at: execution.started_at,
      finished_at: execution.finished_at,
    }
  }

  function upsertExecutionHistory(execution) {
    if (!execution?.execution_id || !execution?.workflow_id) return
    const summary = executionSummary(execution)
    const remaining = executionHistory.value.filter(
      (item) => item.execution_id !== summary.execution_id,
    )
    executionHistory.value = [summary, ...remaining].sort((left, right) =>
      String(right.started_at || '').localeCompare(String(left.started_at || '')),
    )
    executionHistoryTotal.value = Math.max(executionHistoryTotal.value, executionHistory.value.length)
  }

  function nodeExecution(nodeId) {
    const record = currentExecution.value?.nodes?.[nodeId] || emptyNodeExecution()
    return staleNodeIds.value.includes(nodeId) ? { ...record, status: 'stale' } : record
  }

  function descendantsOf(seedIds, sourceEdges = edges.value) {
    const pending = [...seedIds]
    const found = new Set(seedIds)
    while (pending.length) {
      const source = pending.pop()
      for (const edge of sourceEdges) {
        if (edge.source_node !== source || found.has(edge.target_node)) continue
        found.add(edge.target_node)
        pending.push(edge.target_node)
      }
    }
    return found
  }

  function markNodesStale(seedIds, sourceEdges = edges.value) {
    if (!currentExecution.value) return
    const stale = new Set(staleNodeIds.value)
    for (const nodeId of descendantsOf(seedIds, sourceEdges)) stale.add(nodeId)
    staleNodeIds.value = [...stale]
  }

  function closeExecutionStream() {
    executionStream?.close()
    executionStream = null
  }

  function clearExecution() {
    closeExecutionStream()
    currentExecution.value = null
    selectedExecutionNodeId.value = null
    executionError.value = ''
    staleNodeIds.value = []
  }

  function clearExecutionHistory() {
    executionHistory.value = []
    executionHistoryTotal.value = 0
    executionHistoryError.value = ''
  }

  function clearRunQueue() {
    runQueue.value = []
    runQueueTotal.value = 0
    runQueueError.value = ''
  }

  async function refreshRunQueue(id = workflowId.value, { limit = 100 } = {}) {
    if (!id) {
      clearRunQueue()
      return []
    }
    runQueueLoading.value = true
    runQueueError.value = ''
    try {
      const data = await api.get('/api/workflow/queue', {
        params: { workflow_id: id, limit },
      })
      runQueue.value = plain(data.queue || [])
      runQueueTotal.value = Number.isInteger(data.total) ? data.total : runQueue.value.length
      return runQueue.value
    } catch (err) {
      runQueueError.value = apiErrorText(err, 'Failed to load run queue')
      throw err
    } finally {
      runQueueLoading.value = false
    }
  }

  async function cancelPendingRun(executionId) {
    runQueueError.value = ''
    try {
      const data = await api.post(
        `/api/workflow/queue/${encodeURIComponent(executionId)}/cancel`,
        { body: {} },
      )
      const item = runQueue.value.find((entry) => entry.execution_id === executionId)
      if (item) {
        item.status = data.status || 'cancelled'
        item.finished_at ||= new Date().toISOString()
      }
      if (currentExecution.value?.execution_id === executionId) {
        currentExecution.value.status = data.status || 'cancelled'
      }
      return data
    } catch (err) {
      runQueueError.value = apiErrorText(err, 'Failed to cancel pending run')
      throw err
    }
  }

  function applyExecutionSnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') return
    currentExecution.value = plain(snapshot)
    upsertExecutionHistory(snapshot)
    if (
      selectedExecutionNodeId.value
      && !currentExecution.value.nodes?.[selectedExecutionNodeId.value]
    ) selectedExecutionNodeId.value = null
  }

  async function refreshExecution(executionId = currentExecution.value?.execution_id) {
    if (!executionId) return null
    try {
      const data = await api.get(`/api/workflow/executions/${encodeURIComponent(executionId)}`)
      applyExecutionSnapshot(data.execution)
      return data.execution
    } catch (err) {
      executionError.value = apiErrorText(err, 'Failed to refresh execution')
      throw err
    }
  }

  async function refreshExecutionHistory(id = workflowId.value, { limit = 100 } = {}) {
    if (!id) {
      clearExecutionHistory()
      return []
    }
    executionHistoryLoading.value = true
    executionHistoryError.value = ''
    try {
      const data = await api.get('/api/workflow/executions', {
        params: { workflow_id: id, limit },
      })
      executionHistory.value = plain(data.executions || [])
      executionHistoryTotal.value = Number.isInteger(data.total)
        ? data.total
        : executionHistory.value.length
      return executionHistory.value
    } catch (err) {
      executionHistoryError.value = apiErrorText(err, 'Failed to load run history')
      throw err
    } finally {
      executionHistoryLoading.value = false
    }
  }

  async function inspectExecution(executionId) {
    if (!executionId) return null
    if (executionActive.value && executionId !== currentExecution.value?.execution_id) {
      throw new Error('Wait for the current run to finish before inspecting another run')
    }
    selectedExecutionNodeId.value = null
    executionError.value = ''
    return refreshExecution(executionId)
  }

  function applyExecutionEvent(event) {
    if (!event || typeof event !== 'object') return
    if (event.snapshot) applyExecutionSnapshot(event.snapshot)
    const execution = currentExecution.value
    if (!execution) return

    if (event.node_id) {
      execution.nodes ||= {}
      const record = execution.nodes[event.node_id] ||= emptyNodeExecution('queued')
      if (event.status) record.status = event.status
      if (Number.isFinite(event.attempt)) record.attempts = event.attempt
      if (Number.isFinite(event.duration_ms)) record.duration_ms = event.duration_ms
      if (typeof event.from_sample_data === 'boolean') {
        record.from_sample_data = event.from_sample_data
      }
      if (event.error) record.error = plain(event.error)
      if (['queued', 'running', 'succeeded', 'failed', 'cancelled', 'skipped'].includes(event.status)) {
        staleNodeIds.value = staleNodeIds.value.filter((id) => id !== event.node_id)
      }
    } else if (event.status && event.status !== 'reset') {
      execution.status = event.status
    }

    if (['succeeded', 'failed', 'cancelled', 'partial'].includes(event.status) && !event.node_id) {
      closeExecutionStream()
      // The terminal record contains output summaries/artifact refs that are
      // intentionally not repeated in every SSE event.
      void refreshExecution(execution.execution_id)
        .then(() => Promise.all([
          refreshExecutionHistory(execution.workflow_id),
          refreshRunQueue(execution.workflow_id),
        ]))
        .catch(() => {})
    }
  }

  function watchExecution(executionId, { EventSourceImpl } = {}) {
    closeExecutionStream()
    executionStream = createExecutionEventStream(executionId, {
      onEvent: applyExecutionEvent,
      onError: (err) => {
        // EventSource reports transient reconnects through onerror too. Keep
        // the current state visible and expose a small, non-destructive hint.
        executionError.value = err?.message || 'Execution event stream interrupted'
      },
      ...(EventSourceImpl ? { EventSourceImpl } : {}),
    })
    return executionStream
  }

  async function runWorkflow({
    runMode = 'full',
    targetNodeIds = [],
    EventSourceImpl,
    inputBindings = null,
    inputOverrides = null,
    currentJobId = null,
  } = {}) {
    executionLoading.value = true
    executionError.value = ''
    selectedExecutionNodeId.value = null
    closeExecutionStream()
    try {
      const payload = workflowId.value && !dirty.value
        ? { workflow_id: workflowId.value }
        : { workflow: toDocument() }
      const body = {
        ...payload,
        run_mode: runMode,
        target_node_ids: [...targetNodeIds],
        force: false,
      }
      // Standalone input picker (step 4.1): optional bindings / overrides.
      if (inputBindings && typeof inputBindings === 'object') {
        body.input_bindings = inputBindings
      }
      if (inputOverrides && typeof inputOverrides === 'object') {
        body.input_overrides = inputOverrides
      }
      if (currentJobId) {
        body.current_job_id = currentJobId
      }
      const data = await api.post('/api/workflow/run', {
        body,
      })
      currentExecution.value = {
        schema_version: 1,
        execution_id: data.execution_id,
        workflow_id: workflowId.value || '',
        workflow_snapshot: plain(toDocument()),
        project_id: data.project_id,
        run_mode: runMode,
        // The server persists the authoritative expanded scope. Until the
        // first snapshot arrives, show the requested targets (or every node
        // for a complete run) as queued.
        scope_node_ids: runMode === 'full'
          ? nodes.value.map((node) => node.id)
          : [...targetNodeIds],
        status: data.status || 'queued',
        started_at: new Date().toISOString(),
        finished_at: null,
        nodes: Object.fromEntries(nodes.value.map((node) => [
          node.id,
          emptyNodeExecution(
            runMode === 'full' || targetNodeIds.includes(node.id) ? 'queued' : 'idle',
          ),
        ])),
      }
      upsertExecutionHistory(currentExecution.value)
      if (workflowId.value) void refreshRunQueue(workflowId.value).catch(() => {})
      watchExecution(data.execution_id, { EventSourceImpl })
      return data
    } catch (err) {
      executionError.value = apiErrorText(err, 'Failed to start workflow')
      throw err
    } finally {
      executionLoading.value = false
    }
  }

  async function stopExecution() {
    const executionId = currentExecution.value?.execution_id
    if (!executionId || !executionActive.value) return null
    executionError.value = ''
    try {
      const data = await api.post(
        `/api/workflow/executions/${encodeURIComponent(executionId)}/stop`,
        { body: {} },
      )
      currentExecution.value.status = data.status || 'cancelling'
      return data
    } catch (err) {
      executionError.value = apiErrorText(err, 'Failed to stop execution')
      throw err
    }
  }

  function selectExecutionNode(nodeId) {
    const record = currentExecution.value?.nodes?.[nodeId]
    selectedExecutionNodeId.value = record && ['succeeded', 'failed', 'cancelled', 'skipped'].includes(record.status)
      ? nodeId
      : null
  }

  const selectedExecutionNode = computed(() =>
    selectedExecutionNodeId.value
      ? currentExecution.value?.nodes?.[selectedExecutionNodeId.value] || null
      : null,
  )

  const editorProjectId = computed(() => {
    const execution = currentExecution.value
    if (!execution) return null
    for (const node of execution.workflow_snapshot?.nodes || nodes.value) {
      const def = nodeTypes.value[node.type]
      const editorPorts = (def?.outputs || []).filter((port) => port.type === 'editor_project')
      const outputs = execution.nodes?.[node.id]?.outputs_summary || {}
      for (const port of editorPorts) {
        // String values are intentionally reduced to {chars:n} in persisted
        // summaries. The exact, validated project ID lives at record level.
        if (outputs[port.id] !== undefined && execution.project_id) return execution.project_id
      }
    }
    return null
  })

  // ── Draft autosave (step 2.4) ─────────────────────────────────────────
  let draftTimer = null

  function cancelDraftAutosave() {
    if (draftTimer !== null) {
      clearTimeout(draftTimer)
      draftTimer = null
    }
  }

  function scheduleDraftAutosave() {
    cancelDraftAutosave()
    draftTimer = setTimeout(() => {
      draftTimer = null
      flushDraft()
    }, DRAFT_DEBOUNCE_MS)
  }

  /** Every mutation that makes the document diverge from disk funnels here. */
  function markDocumentDirty() {
    if (readOnly.value) return false
    dirty.value = true
    scheduleDraftAutosave()
    return true
  }

  /** Write the draft immediately (no-op when there is nothing unsaved). */
  function flushDraft() {
    cancelDraftAutosave()
    if (!dirty.value) return false
    try {
      const payload = {
        version: 1,
        saved_at: new Date().toISOString(),
        document: toDocument(),
      }
      globalThis.localStorage?.setItem(DRAFT_STORAGE_KEY, JSON.stringify(payload))
      draftSavedAt.value = payload.saved_at
      return true
    } catch {
      // Quota exceeded / storage disabled: autosave is best-effort, the
      // explicit Save path and dirty indicator still protect the user.
      return false
    }
  }

  /** Read the stored draft without applying it. Corrupt drafts are dropped. */
  function peekDraft() {
    let raw = null
    try {
      raw = globalThis.localStorage?.getItem(DRAFT_STORAGE_KEY)
    } catch {
      return null
    }
    if (!raw) return null
    try {
      const draft = JSON.parse(raw)
      if (!draft || typeof draft !== 'object') throw new Error('not an object')
      if (!draft.document || typeof draft.document !== 'object') throw new Error('no document')
      return draft
    } catch {
      clearDraft()
      return null
    }
  }

  function clearDraft() {
    cancelDraftAutosave()
    draftSavedAt.value = null
    try {
      globalThis.localStorage?.removeItem(DRAFT_STORAGE_KEY)
    } catch {
      /* storage unavailable — nothing to clear */
    }
  }

  /** Apply the stored draft as the (still unsaved) working document. */
  function recoverDraft() {
    const draft = peekDraft()
    if (!draft) return false
    applyDocument(draft.document, { markDirty: true })
    draftSavedAt.value = draft.saved_at || null
    return true
  }

  const workflowList = ref([])
  const templates = ref([])
  const persistenceLoading = ref(false)
  const persistenceError = ref('')

  // ── Invalid editor fields (step 6.4) ──────────────────────────────────
  // Invalid text lives only inside mounted widgets (a JSON textarea whose
  // content does not parse never reaches the document), so saving would
  // silently persist the last *valid* value while the user believes their
  // edit was included. Widgets register here so Save can refuse honestly.
  const invalidConfigFields = ref({}) // key → user-facing reason

  function reportInvalidField(key, reason = '') {
    if (!key) return
    if (reason) {
      invalidConfigFields.value = { ...invalidConfigFields.value, [key]: reason }
    } else if (Object.hasOwn(invalidConfigFields.value, key)) {
      const next = { ...invalidConfigFields.value }
      delete next[key]
      invalidConfigFields.value = next
    }
  }

  function clearInvalidFields(prefix = '') {
    invalidConfigFields.value = prefix
      ? Object.fromEntries(
        Object.entries(invalidConfigFields.value)
          .filter(([key]) => !key.startsWith(prefix)),
      )
      : {}
  }

  const saveBlockedReason = computed(() => {
    if (readOnly.value) {
      return loadWarnings.value[0]?.message
        || 'This workflow uses newer node versions and is read-only.'
    }
    const reasons = Object.values(invalidConfigFields.value)
    if (!reasons.length) return ''
    return reasons.length === 1
      ? reasons[0]
      : `${reasons[0]} (and ${reasons.length - 1} more invalid field${reasons.length > 2 ? 's' : ''})`
  })

  let idCounter = 0
  function nextNodeId() {
    idCounter += 1
    let candidate = `n_${idCounter}`
    while (nodes.value.some((n) => n.id === candidate)) {
      idCounter += 1
      candidate = `n_${idCounter}`
    }
    return candidate
  }

  function defaultsFor(typeKey) {
    const def = nodeTypes.value[typeKey]
    const configuration = {}
    for (const field of def?.config_schema || []) {
      const value = field.default ?? null
      // Registry defaults are plain JSON; structuredClone would choke on
      // the reactive proxies wrapping them.
      configuration[field.name] = value === null ? null : JSON.parse(JSON.stringify(value))
    }
    return configuration
  }

  function addNode(typeKey, position) {
    return executeCommand('Add node', () => {
      const def = nodeTypes.value[typeKey]
      if (!def) return null
      const node = {
        id: nextNodeId(),
        type: typeKey,
        type_version: def.type_version,
        name: def.display_name,
        position: {
          x: Math.round((position?.x ?? 0) / 20) * 20,
          y: Math.round((position?.y ?? 0) / 20) * 20,
        },
        configuration: defaultsFor(typeKey),
        disabled: false,
        on_error: { policy: 'stop' },
      }
      nodes.value.push(node)
      markDocumentDirty()
      return node
    })
  }

  const notes = computed(() => Array.isArray(extensions.value.notes) ? extensions.value.notes : [])
  let noteCounter = 0

  function nextNoteId() {
    noteCounter += 1
    let candidate = `note_${noteCounter}`
    while (notes.value.some((note) => note.id === candidate) || nodeById(candidate)) {
      noteCounter += 1
      candidate = `note_${noteCounter}`
    }
    return candidate
  }

  function addNote(position, text = 'New note') {
    return executeCommand('Add note', () => {
      const note = {
        id: nextNoteId(),
        text: String(text).slice(0, 4000),
        position: {
          x: Math.round((position?.x ?? 0) / 20) * 20,
          y: Math.round((position?.y ?? 0) / 20) * 20,
        },
        color: 'yellow',
      }
      extensions.value = { ...extensions.value, notes: [...notes.value, note] }
      markDocumentDirty()
      return note
    })
  }

  function updateNote(noteId, patch) {
    return executeCommand('Edit note', () => {
      const current = notes.value.find((note) => note.id === noteId)
      if (!current) return false
      const next = {
        ...current,
        ...(Object.hasOwn(patch || {}, 'text') ? { text: String(patch.text).slice(0, 4000) } : {}),
        ...(Object.hasOwn(patch || {}, 'color') && ['yellow', 'blue', 'green', 'pink'].includes(patch.color)
          ? { color: patch.color }
          : {}),
      }
      if (JSON.stringify(current) === JSON.stringify(next)) return false
      extensions.value = {
        ...extensions.value,
        notes: notes.value.map((note) => note.id === noteId ? next : note),
      }
      markDocumentDirty()
      return true
    })
  }

  function moveNotes(moves) {
    return executeCommand('Move note', () => {
      const byId = new Map((moves || []).map((move) => [move.id, move.position]))
      let changed = false
      const next = notes.value.map((note) => {
        const position = byId.get(note.id)
        if (!position || (position.x === note.position.x && position.y === note.position.y)) return note
        changed = true
        return { ...note, position: { x: position.x, y: position.y } }
      })
      if (!changed) return false
      extensions.value = { ...extensions.value, notes: next }
      markDocumentDirty()
      return true
    })
  }

  function removeNotes(noteIds) {
    return executeCommand('Delete note', () => {
      const doomed = new Set(noteIds || [])
      const next = notes.value.filter((note) => !doomed.has(note.id))
      if (next.length === notes.value.length) return false
      extensions.value = { ...extensions.value, notes: next }
      markDocumentDirty()
      return true
    })
  }

  function noteById(noteId) {
    return notes.value.find((note) => note.id === noteId) || null
  }

  function moveNode(nodeId, position) {
    return moveNodes([{ id: nodeId, position }])
  }

  function moveNodes(moves) {
    return executeCommand('Move node', () => {
      let changed = false
      for (const move of moves || []) {
        const node = nodes.value.find((n) => n.id === move.id)
        if (!node || !move.position) continue
        if (node.position.x === move.position.x && node.position.y === move.position.y) continue
        node.position = { x: move.position.x, y: move.position.y }
        changed = true
      }
      if (changed) markDocumentDirty()
      return changed
    })
  }

  function renameNode(nodeId, name) {
    return executeCommand('Rename node', () => {
      const node = nodes.value.find((n) => n.id === nodeId)
      if (!node || node.name === name) return false
      node.name = name
      markDocumentDirty()
      return true
    })
  }

  function removeNodes(nodeIds) {
    return executeCommand('Delete node', () => {
      const doomed = new Set(nodeIds)
      if (!doomed.size || !nodes.value.some((node) => doomed.has(node.id))) return false

      // Sample inputs and result viewers are lifecycle children of the main
      // node they were attached to. Remove an adjacent stub only when every
      // graph connection it has belongs to the requested deletion set; a
      // shared stub must survive for the other node that still consumes it.
      const requestedMainNodes = new Set(
        nodes.value
          .filter((node) => doomed.has(node.id) && !['stub.input', 'stub.output'].includes(node.type))
          .map((node) => node.id),
      )
      for (const node of nodes.value) {
        if (doomed.has(node.id) || !['stub.input', 'stub.output'].includes(node.type)) continue
        const incidentEdges = edges.value.filter(
          (edge) => edge.source_node === node.id || edge.target_node === node.id,
        )
        const neighbourIds = incidentEdges.map(
          (edge) => edge.source_node === node.id ? edge.target_node : edge.source_node,
        )
        if (
          neighbourIds.some((id) => requestedMainNodes.has(id))
          && neighbourIds.every((id) => doomed.has(id))
        ) {
          doomed.add(node.id)
        }
      }

      const oldEdges = [...edges.value]
      const affected = oldEdges.filter((e) => doomed.has(e.source_node)).map((e) => e.target_node)
      markNodesStale(affected, oldEdges)
      nodes.value = nodes.value.filter((n) => !doomed.has(n.id))
      edges.value = edges.value.filter(
        (e) => !doomed.has(e.source_node) && !doomed.has(e.target_node),
      )
      if (doomed.has(selectedNodeId.value)) selectedNodeId.value = null
      markDocumentDirty()
      return true
    })
  }

  let edgeCounter = 0
  function nextEdgeId() {
    edgeCounter += 1
    let candidate = `e_${edgeCounter}`
    while (edges.value.some((e) => e.id === candidate)) {
      edgeCounter += 1
      candidate = `e_${edgeCounter}`
    }
    return candidate
  }

  /**
   * Validate + create a connection. Returns the validation result;
   * on success the edge is appended in the persisted shape.
   *
   * Step 2.5: when a REAL edge lands on an input currently fed by a Sample
   * Input stub, the stub edge (and the stub itself, unless it still feeds
   * other inputs) is removed first — undoably via undoStubDetach().
   */
  function connectNodes({ sourceNode, sourcePort, targetNode, targetPort }) {
    return executeCommand('Connect nodes', () => {
      const sourceIsStub = nodeById(sourceNode)?.type === 'stub.input'
      const stubEdge = sourceIsStub
        ? null
        : edges.value.find(
          (e) => e.target_node === targetNode && e.target_port === targetPort
            && nodeById(e.source_node)?.type === 'stub.input',
        )
      // Validate against the graph as it would look after the stub detaches,
      // so replacing sample data with a real edge is never "input occupied".
      const candidateEdges = stubEdge
        ? edges.value.filter((e) => e.id !== stubEdge.id)
        : edges.value
      const verdict = validateConnection(
        { nodes: nodes.value, edges: candidateEdges, nodeTypes: nodeTypes.value, portTypes: portTypes.value },
        { sourceNode, sourcePort, targetNode, targetPort },
      )
      if (!verdict.ok) return verdict

      if (stubEdge) {
        const stubNode = nodeById(stubEdge.source_node)
        const stillFeedsOthers = edges.value.some(
          (e) => e.source_node === stubNode.id && e.id !== stubEdge.id,
        )
        edges.value = edges.value.filter((e) => e.id !== stubEdge.id)
        if (!stillFeedsOthers) {
          nodes.value = nodes.value.filter((n) => n.id !== stubNode.id)
          if (selectedNodeId.value === stubNode.id) selectedNodeId.value = null
        }
      }

      const edge = {
        id: nextEdgeId(),
        source_node: sourceNode,
        source_port: sourcePort,
        target_node: targetNode,
        target_port: targetPort,
        edge_type: verdict.edgeType,
      }
      edges.value.push(edge)
      markNodesStale([targetNode])
      markDocumentDirty()
      return { ...verdict, detachedStub: Boolean(stubEdge) }
    })
  }

  function removeEdges(edgeIds) {
    return executeCommand('Disconnect nodes', () => {
      const doomed = new Set(edgeIds)
      if (!doomed.size || !edges.value.some((edge) => doomed.has(edge.id))) return false
      const oldEdges = [...edges.value]
      const affected = oldEdges.filter((e) => doomed.has(e.id)).map((e) => e.target_node)
      markNodesStale(affected, oldEdges)
      edges.value = edges.value.filter((e) => !doomed.has(e.id))
      markDocumentDirty()
      return true
    })
  }

  // ── Sample-data stubs (step 2.5) ──────────────────────────────────────
  // Compatibility aliases retained for the step 2.5 API and its tests.
  const canUndoStubDetach = computed(() => undoStack.value.at(-1)?.kind === 'stub-detach')

  const autoAttachStubs = computed(() => settings.value.auto_attach_stubs !== false)

  function setAutoAttachStubs(enabled) {
    return executeCommand('Change workflow settings', () => {
      const value = Boolean(enabled)
      if (settings.value.auto_attach_stubs === value) return false
      settings.value = { ...settings.value, auto_attach_stubs: value }
      markDocumentDirty()
      return true
    })
  }

  function setSchedules(nextSchedules) {
    return executeCommand('Change scheduled runs', () => {
      const value = plain(Array.isArray(nextSchedules) ? nextSchedules : [])
      if (JSON.stringify(settings.value.schedules || []) === JSON.stringify(value)) return false
      settings.value = { ...settings.value, schedules: value }
      markDocumentDirty()
      return true
    })
  }

  function setWatchFolder(nextWatchFolder) {
    return executeCommand('Change watch folder', () => {
      const value = plain(nextWatchFolder)
      if (JSON.stringify(settings.value.watch_folder || null) === JSON.stringify(value)) return false
      settings.value = { ...settings.value, watch_folder: value }
      markDocumentDirty()
      return true
    })
  }

  function setWebhook(nextWebhook) {
    return executeCommand('Change webhook trigger', () => {
      const value = plain(nextWebhook)
      if (JSON.stringify(settings.value.webhook || null) === JSON.stringify(value)) return false
      settings.value = { ...settings.value, webhook: value }
      markDocumentDirty()
      return true
    })
  }

  function setNotifications(nextNotifications) {
    return executeCommand('Change run notifications', () => {
      const value = plain(nextNotifications)
      if (JSON.stringify(settings.value.notifications || null) === JSON.stringify(value)) return false
      settings.value = { ...settings.value, notifications: value }
      markDocumentDirty()
      return true
    })
  }

  function isStubType(typeKey) {
    return nodeTypes.value[typeKey]?.category === 'testing'
  }

  function samplePayloadFor(portType) {
    const sample = samplePayloads.value[portType]
    return sample === undefined ? {} : plain(sample)
  }

  /** Resolve one endpoint's port type, honouring dynamic stub ports. */
  function endpointPortType(node, kind, portId) {
    const port = (nodeTypes.value[node?.type]?.[kind] || []).find((p) => p.id === portId)
    if (!port) return null
    if (port.type !== 'dynamic') return port.type
    return node.configuration?.port_type || 'generic_json'
  }

  /**
   * Spawn one pre-connected Sample Input per still-unconnected required
   * data input of `nodeId`. Returns the created stub nodes.
   */
  function attachSampleInputs(nodeId) {
    return executeCommand('Attach sample inputs', () => {
    const node = nodeById(nodeId)
    const def = nodeTypes.value[node?.type]
    if (!node || !def || !nodeTypes.value['stub.input']) return []
    const created = []
    let slot = 0
    for (const port of def.inputs || []) {
      if (!port.required || port.type === 'control') continue
      const connected = edges.value.some(
        (e) => e.target_node === nodeId && e.target_port === port.id,
      )
      if (connected) continue
      const stub = addNode('stub.input', {
        x: node.position.x - 260,
        y: node.position.y + slot * 80,
      })
      stub.name = `Sample ${port.id}`
      stub.configuration.port_type = port.type
      stub.configuration.payload = samplePayloadFor(port.type)
      edges.value.push({
        id: nextEdgeId(),
        source_node: stub.id,
        source_port: 'value',
        target_node: nodeId,
        target_port: port.id,
        edge_type: 'data',
      })
      created.push(stub)
      slot += 1
    }
    if (created.length) markDocumentDirty()
    return created
    })
  }

  /** Attach a Result Viewer to the node's principal (first data) output. */
  function attachResultViewer(nodeId) {
    return executeCommand('Attach result viewer', () => {
    const node = nodeById(nodeId)
    const def = nodeTypes.value[node?.type]
    if (!node || !def || !nodeTypes.value['stub.output']) return null
    const port = (def.outputs || []).find((p) => p.type !== 'control')
    if (!port) return null
    const stub = addNode('stub.output', {
      x: node.position.x + 260,
      y: node.position.y,
    })
    stub.name = `View ${port.id}`
    stub.configuration.port_type = port.type
    edges.value.push({
      id: nextEdgeId(),
      source_node: nodeId,
      source_port: port.id,
      target_node: stub.id,
      target_port: 'value',
      edge_type: 'data',
    })
    markDocumentDirty()
    return stub
    })
  }

  /**
   * Palette-drop entry point: add the node and — when the workflow-level
   * auto-attach setting is on and the node is not itself a testing stub —
   * wire up sample inputs and a result viewer.
   */
  function addNodeWithStubs(typeKey, position) {
    return executeCommand('Add node', () => {
      const node = addNode(typeKey, position)
      if (!node) return null
      recordNodeUse(typeKey)
      if (autoAttachStubs.value && !isStubType(typeKey)) {
        attachSampleInputs(node.id)
        attachResultViewer(node.id)
      }
      return node
    })
  }

  /** Undo the most recent stub detach: drop the real edge, restore the stub. */
  function undoStubDetach() {
    return canUndoStubDetach.value ? undo() : false
  }

  function setViewport(vp) {
    // Viewport is cosmetic state: remember it for the next save, but merely
    // panning/zooming must not flag unsaved changes or arm discard prompts.
    viewport.value = { x: vp.x, y: vp.y, zoom: vp.zoom }
  }

  function plain(value) {
    return JSON.parse(JSON.stringify(value))
  }

  function toDocument() {
    const document = {
      schema_version: 1,
      name: workflowName.value.trim() || 'Untitled workflow',
      description: workflowDescription.value,
      nodes: plain(nodes.value),
      edges: plain(edges.value),
      variables: plain(variables.value),
      viewport: plain(viewport.value),
      settings: plain(settings.value),
      extensions: plain(extensions.value),
    }
    if (workflowId.value) document.workflow_id = workflowId.value
    if (createdAt.value) document.created_at = createdAt.value
    if (updatedAt.value) document.updated_at = updatedAt.value
    return document
  }

  function resetCounters() {
    idCounter = 0
    edgeCounter = 0
    noteCounter = 0
  }

  function applyDocument(document, {
    markDirty = false,
    preserveSelection = false,
    preserveExecution = false,
    readOnly: nextReadOnly = false,
    warnings = [],
    migrations = [],
  } = {}) {
    if (!preserveExecution) {
      clearExecution()
      clearExecutionHistory()
    }
    workflowId.value = document.workflow_id || null
    workflowName.value = document.name || 'Untitled workflow'
    workflowDescription.value = document.description || ''
    nodes.value = plain(document.nodes || [])
    edges.value = plain(document.edges || [])
    variables.value = plain(document.variables || {})
    viewport.value = plain(document.viewport || { x: 0, y: 0, zoom: 1 })
    settings.value = plain(document.settings || { on_error: 'stop' })
    extensions.value = plain(document.extensions || {})
    createdAt.value = document.created_at || null
    updatedAt.value = document.updated_at || null
    readOnly.value = Boolean(nextReadOnly)
    loadWarnings.value = plain(warnings || [])
    migrationTrail.value = plain(migrations || [])
    resetCounters()
    clearCommandHistory()
    // Editor widgets remount against the new document; any invalid text they
    // held is gone with them.
    clearInvalidFields()
    if (!preserveSelection || !nodeById(selectedNodeId.value)) selectedNodeId.value = null
    if (markDirty && !readOnly.value) {
      // Unsaved content (template/import-as-draft, draft recovery): keep the
      // autosave loop armed so the new document is protected too.
      markDocumentDirty()
    } else {
      // A clean document from disk supersedes any stored draft.
      dirty.value = false
      clearDraft()
    }
  }

  function newWorkflow(name = 'Untitled workflow') {
    applyDocument({
      schema_version: 1,
      name,
      description: '',
      nodes: [],
      edges: [],
      variables: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      settings: { on_error: 'stop' },
      extensions: {},
    })
  }

  async function refreshWorkflowList() {
    try {
      const data = await api.get('/api/workflows', { params: { limit: 200 } })
      workflowList.value = data.workflows || []
      return workflowList.value
    } catch (err) {
      persistenceError.value = apiErrorText(err, 'Failed to load workflow list')
      throw err
    }
  }

  async function loadTemplates() {
    try {
      const data = await api.get('/api/workflow/templates')
      templates.value = data.templates || []
      return templates.value
    } catch (err) {
      persistenceError.value = apiErrorText(err, 'Failed to load workflow templates')
      throw err
    }
  }

  async function openWorkflow(id) {
    persistenceLoading.value = true
    persistenceError.value = ''
    try {
      const data = await api.get(`/api/workflows/${encodeURIComponent(id)}`)
      const migrations = data.migration_trail || []
      applyDocument(data.workflow, {
        markDirty: migrations.length > 0,
        readOnly: data.read_only === true,
        warnings: data.warnings || [],
        migrations,
      })
      return data.workflow
    } catch (err) {
      persistenceError.value = apiErrorText(err, 'Failed to open workflow')
      throw err
    } finally {
      persistenceLoading.value = false
    }
  }

  function assertSaveNotBlocked() {
    if (!saveBlockedReason.value) return
    persistenceError.value = saveBlockedReason.value
    throw Object.assign(new Error(saveBlockedReason.value), { code: 'INVALID_EDITOR_FIELD' })
  }

  async function saveWorkflow() {
    assertSaveNotBlocked()
    persistenceLoading.value = true
    persistenceError.value = ''
    try {
      const document = toDocument()
      const data = workflowId.value
        ? await api.put(`/api/workflows/${encodeURIComponent(workflowId.value)}`, {
          body: { workflow: document, expected_updated_at: updatedAt.value },
        })
        : await api.post('/api/workflows', { body: { workflow: document } })
      applyDocument(data.workflow, { preserveSelection: true, preserveExecution: true })
      await refreshWorkflowList()
      return data.workflow
    } catch (err) {
      persistenceError.value = apiErrorText(err, 'Failed to save workflow')
      throw err
    } finally {
      persistenceLoading.value = false
    }
  }

  async function saveAs(name) {
    assertSaveNotBlocked()
    persistenceLoading.value = true
    persistenceError.value = ''
    try {
      const document = toDocument()
      delete document.workflow_id
      delete document.created_at
      delete document.updated_at
      document.name = name?.trim() || `${workflowName.value} copy`
      const data = await api.post('/api/workflows', { body: { workflow: document } })
      applyDocument(data.workflow, { preserveSelection: true })
      await refreshWorkflowList()
      return data.workflow
    } catch (err) {
      persistenceError.value = apiErrorText(err, 'Failed to save workflow copy')
      throw err
    } finally {
      persistenceLoading.value = false
    }
  }

  async function importDocument(document) {
    persistenceLoading.value = true
    persistenceError.value = ''
    try {
      const data = await api.post('/api/workflows/import', {
        body: { workflow: document, on_conflict: 'new_id' },
      })
      applyDocument(data.workflow)
      await refreshWorkflowList()
      return data.workflow
    } catch (err) {
      persistenceError.value = apiErrorText(err, 'Failed to import workflow')
      throw err
    } finally {
      persistenceLoading.value = false
    }
  }

  function applyTemplate(templateId) {
    const template = templates.value.find((item) => item.template_id === templateId)
    if (!template) return false
    applyDocument(template.workflow, { markDirty: true })
    return true
  }

  function nodeById(nodeId) {
    return nodes.value.find((n) => n.id === nodeId) || null
  }

  const nodeCount = computed(() => nodes.value.length)

  // Per-node editing issues (step 2.2) — recomputed on every graph change.
  const issuesByNode = computed(() => {
    const map = {}
    for (const node of nodes.value) {
      const issues = nodeIssues(node, nodeTypes.value[node.type], edges.value)
      if (issues.length) map[node.id] = issues
    }
    return map
  })

  // ── Selection + inspector editing (step 2.1) ──────────────────────────
  const selectedNodeId = ref(null)
  const selectedNode = computed(() => nodeById(selectedNodeId.value))

  function selectNode(nodeId) {
    selectedNodeId.value = nodeById(nodeId) ? nodeId : null
  }

  function clearSelection() {
    selectedNodeId.value = null
  }

  function updateNodeConfig(nodeId, name, value) {
    return executeCommand('Change node configuration', () => {
    const node = nodeById(nodeId)
    if (!node) return false
    const previous = node.configuration[name] === undefined
      ? undefined
      : plain(node.configuration[name])
    if (JSON.stringify(previous) === JSON.stringify(value)) return false
    node.configuration[name] = value === undefined ? undefined : plain(value)
    markNodesStale([nodeId])
    // Retyping a stub retargets its dynamic port: reseed the editable sample
    // payload and drop edges that no longer type-match (contracts §3 —
    // dynamic ports obey exact-match once resolved).
    if (
      name === 'port_type'
      && (node.type === 'stub.input' || node.type === 'stub.output')
    ) {
      if (node.type === 'stub.input') {
        node.configuration.payload = samplePayloadFor(value)
      }
      edges.value = edges.value.filter((e) => {
        if (e.source_node === nodeId && e.source_port === 'value') {
          const target = nodeById(e.target_node)
          return endpointPortType(target, 'inputs', e.target_port) === value
        }
        if (e.target_node === nodeId && e.target_port === 'value') {
          const source = nodeById(e.source_node)
          return endpointPortType(source, 'outputs', e.source_port) === value
        }
        return true
      })
    }
    markDocumentDirty()
    return true
    })
  }

  function updateVariables(value) {
    return executeCommand('Change workflow variables', () => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return false
      if (JSON.stringify(variables.value) === JSON.stringify(value)) return false
      variables.value = plain(value)
      markNodesStale(nodes.value.map((node) => node.id))
      markDocumentDirty()
      return true
    })
  }

  function setNodeDisabled(nodeId, disabled) {
    return executeCommand('Disable node', () => {
    const node = nodeById(nodeId)
    const value = Boolean(disabled)
    if (!node || node.disabled === value) return false
    node.disabled = value
    markNodesStale([nodeId])
    markDocumentDirty()
    return true
    })
  }

  function updateNodeErrorPolicy(nodeId, patch) {
    return executeCommand('Change error policy', () => {
    const node = nodeById(nodeId)
    if (!node) return false
    const next = { ...(node.on_error || { policy: 'stop' }), ...plain(patch) }
    if (JSON.stringify(node.on_error) === JSON.stringify(next)) return false
    node.on_error = next
    markDocumentDirty()
    return true
    })
  }

  function duplicateNode(nodeId) {
    return duplicateNodes([nodeId])[0] || null
  }

  function copyFragment(nodeIds) {
    return makeWorkflowFragment(nodes.value, edges.value, nodeIds)
  }

  function pasteFragment(value, { position, label = 'Paste nodes' } = {}) {
    return executeCommand(label, () => {
      const fragment = parseWorkflowFragment(value)
      if (!fragment?.nodes.length) return []
      if (fragment.nodes.some((node) => {
        const definition = nodeTypes.value[node.type]
        return !definition || definition.type_version !== node.type_version
      })) return []

      const minX = Math.min(...fragment.nodes.map((node) => node.position?.x ?? 0))
      const minY = Math.min(...fragment.nodes.map((node) => node.position?.y ?? 0))
      const offsetX = position ? position.x - minX : 40
      const offsetY = position ? position.y - minY : 40
      const ids = new Map()
      const pasted = fragment.nodes.map((source) => {
        const copy = plain(source)
        copy.id = nextNodeId()
        copy.position = {
          x: Math.max(-1_000_000, Math.min(1_000_000, (source.position?.x ?? 0) + offsetX)),
          y: Math.max(-1_000_000, Math.min(1_000_000, (source.position?.y ?? 0) + offsetY)),
        }
        ids.set(source.id, copy.id)
        return copy
      })
      nodes.value.push(...pasted)
      for (const source of fragment.edges) {
        if (!ids.has(source.source_node) || !ids.has(source.target_node)) continue
        edges.value.push({
          ...plain(source),
          id: nextEdgeId(),
          source_node: ids.get(source.source_node),
          target_node: ids.get(source.target_node),
        })
      }
      markDocumentDirty()
      selectedNodeId.value = pasted.at(-1)?.id || null
      return pasted
    })
  }

  function duplicateNodes(nodeIds) {
    const fragment = copyFragment(nodeIds)
    if (!fragment) return []
    for (const source of fragment.nodes) {
      const suffix = ' copy'
      source.name = `${source.name.slice(0, 120 - suffix.length).trimEnd()}${suffix}`
    }
    return pasteFragment(fragment, { label: nodeIds.length === 1 ? 'Duplicate node' : 'Duplicate nodes' })
  }

  function replacementPlan(nodeId, typeKey) {
    const node = nodeById(nodeId)
    const definition = nodeTypes.value[typeKey]
    if (!node || !definition || node.type === typeKey) return null
    const defaults = defaultsFor(typeKey)
    const compatible = Object.fromEntries(
      Object.keys(defaults)
        .filter((name) => Object.hasOwn(node.configuration || {}, name))
        .map((name) => [name, plain(node.configuration[name])]),
    )
    const candidate = {
      ...plain(node), type: typeKey, type_version: definition.type_version,
      configuration: { ...defaults, ...compatible },
    }
    const keptEdges = []
    const droppedEdges = []
    const inputCounts = new Map()
    for (const edge of edges.value) {
      if (edge.source_node !== nodeId && edge.target_node !== nodeId) continue
      let compatible = true
      if (edge.source_node === nodeId) {
        compatible = endpointPortType(candidate, 'outputs', edge.source_port)
          === endpointPortType(nodeById(edge.target_node), 'inputs', edge.target_port)
      } else {
        const port = (definition.inputs || []).find((item) => item.id === edge.target_port)
        const count = inputCounts.get(edge.target_port) || 0
        compatible = endpointPortType(nodeById(edge.source_node), 'outputs', edge.source_port)
          === endpointPortType(candidate, 'inputs', edge.target_port)
          && Boolean(port?.multiple || count === 0)
        if (compatible) inputCounts.set(edge.target_port, count + 1)
      }
      ;(compatible ? keptEdges : droppedEdges).push(edge)
    }
    return { keptEdges: plain(keptEdges), droppedEdges: plain(droppedEdges) }
  }

  function replaceNode(nodeId, typeKey, { configuration, keepEdges = true } = {}) {
    return executeCommand('Replace node', () => {
      const node = nodeById(nodeId)
      const def = nodeTypes.value[typeKey]
      if (!node || !def || node.type === typeKey) return null
      const previous = plain(node.configuration || {})
      const previousEdges = plain(edges.value)
      const defaults = defaultsFor(typeKey)
      const compatible = Object.fromEntries(
        Object.keys(defaults)
          .filter((name) => Object.hasOwn(previous, name))
          .map((name) => [name, previous[name]]),
      )
      const plan = replacementPlan(nodeId, typeKey)
      node.type = typeKey
      node.type_version = def.type_version
      node.configuration = configuration === undefined
        ? { ...defaults, ...compatible }
        : plain(configuration)
      node.on_error = { policy: 'stop' }
      edges.value = edges.value.filter((edge) => {
        if (!keepEdges && (edge.source_node === nodeId || edge.target_node === nodeId)) return false
        if (edge.source_node === nodeId || edge.target_node === nodeId) {
          return plan.keptEdges.some((kept) => kept.id === edge.id)
        }
        return true
      })
      markNodesStale([nodeId], previousEdges)
      markDocumentDirty()
      return node
    })
  }

  function insertNodeAndConnect(typeKey, position, start, candidatePort) {
    return executeCommand('Insert connected node', () => {
      const wasDirty = dirty.value
      const previousStale = plain(staleNodeIds.value)
      const node = addNode(typeKey, position)
      if (!node) return null
      recordNodeUse(typeKey)
      if (nodeTypes.value[typeKey]?.category === 'testing') {
        node.configuration.port_type = start.portType
        if (typeKey === 'stub.input') node.configuration.payload = samplePayloadFor(start.portType)
      }
      const connection = start.handleType === 'target'
        ? { sourceNode: node.id, sourcePort: candidatePort, targetNode: start.nodeId, targetPort: start.handleId }
        : { sourceNode: start.nodeId, sourcePort: start.handleId, targetNode: node.id, targetPort: candidatePort }
      const verdict = connectNodes(connection)
      if (!verdict.ok) {
        nodes.value = nodes.value.filter((item) => item.id !== node.id)
        dirty.value = wasDirty
        staleNodeIds.value = previousStale
        return null
      }
      selectedNodeId.value = node.id
      return node
    })
  }

  return {
    // registry
    registryVersion, nodeTypes, categories, portTypes, samplePayloads,
    registryLoading, registryError, devReloadEnabled, loadNodeTypes,
    watchNodeTypeReloads, closeNodeTypeReloads,
    // document
    workflowId, workflowName, workflowDescription, nodes, edges, viewport,
    variables, updateVariables, settings, extensions, createdAt, updatedAt, dirty, nodeCount,
    readOnly, loadWarnings, migrationTrail,
    notes, addNote, updateNote, moveNotes, removeNotes, noteById,
    recentNodeTypes, recordNodeUse, clearRecentNodeTypes,
    workflowList, templates, persistenceLoading, persistenceError,
    // invalid editor fields (step 6.4)
    invalidConfigFields, reportInvalidField, clearInvalidFields, saveBlockedReason,
    addNode, moveNode, moveNodes, renameNode, removeNodes, removeEdges, connectNodes,
    replaceNode, replacementPlan, insertNodeAndConnect,
    setViewport, nodeById, defaultsFor, toDocument, applyDocument, newWorkflow,
    refreshWorkflowList, loadTemplates, openWorkflow, saveWorkflow, saveAs,
    importDocument, applyTemplate,
    // draft autosave (step 2.4)
    draftSavedAt, markDocumentDirty, flushDraft, peekDraft, clearDraft, recoverDraft,
    // selection + inspector
    selectedNodeId, selectedNode, selectNode, clearSelection,
    updateNodeConfig, updateNodeErrorPolicy, setNodeDisabled, duplicateNode, duplicateNodes,
    copyFragment, pasteFragment,
    // undo/redo command stack (step 5.1)
    canUndo, canRedo, undoLabel, redoLabel, undo, redo, clearCommandHistory,
    // validation (step 2.2)
    issuesByNode,
    // sample-data stubs (step 2.5)
    autoAttachStubs, setAutoAttachStubs, setSchedules, setWatchFolder, setWebhook, setNotifications, isStubType, samplePayloadFor,
    addNodeWithStubs, attachSampleInputs, attachResultViewer,
    canUndoStubDetach, undoStubDetach,
    // live execution (step 3.6)
    currentExecution, executionLoading, executionError, executionActive,
    executionHistory, executionHistoryTotal, executionHistoryLoading, executionHistoryError,
    runQueue, runQueueTotal, runQueueLoading, runQueueError,
    staleNodeIds, markNodesStale,
    selectedExecutionNodeId, selectedExecutionNode, editorProjectId,
    nodeExecution, runWorkflow, stopExecution, refreshExecution,
    refreshExecutionHistory, inspectExecution, clearExecutionHistory,
    refreshRunQueue, cancelPendingRun, clearRunQueue,
    applyExecutionEvent, watchExecution, closeExecutionStream, clearExecution,
    selectExecutionNode,
  }
})

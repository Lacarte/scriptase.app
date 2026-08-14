<script setup>
import { computed, markRaw, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { VueFlow, useVueFlow, MarkerType } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import dagre from '@dagrejs/dagre'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import { api } from '@/shared/api/client.js'
import { useWorkflowStore } from '../stores/workflow.js'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
import { DRAG_MIME } from '../constants.js'
import { validateConnection } from '../validation.js'
import { compatibleInsertions, parseWorkflowFragment } from '../fragments.js'
import { createCanvasNodeProjector, LARGE_CANVAS_NODE_THRESHOLD } from '../canvasElements.js'
import { useToast } from '@/shared/composables/useToast.js'
import NodeLibrary from '../components/NodeLibrary.vue'
import NodeCard from '../components/NodeCard.vue'
import StickyNote from '../components/StickyNote.vue'
import NodeInspector from '../components/NodeInspector.vue'
import ExecutionPanel from '../components/ExecutionPanel.vue'
import ScheduleSettings from '../components/ScheduleSettings.vue'
import WatchFolderSettings from '../components/WatchFolderSettings.vue'
import WebhookSettings from '../components/WebhookSettings.vue'
import NotificationCenter from '../components/NotificationCenter.vue'
import AssetGarbageCollection from '../components/AssetGarbageCollection.vue'
import ProjectArchiveManager from '../components/ProjectArchiveManager.vue'

const store = useWorkflowStore()
const catalog = useProviderCatalogStore()
const toast = useToast()
const {
  screenToFlowCoordinate,
  fitView,
  setViewport: setFlowViewport,
  setNodes: setFlowNodes,
} = useVueFlow()
const importInput = ref(null)
const canvasSelection = ref(new Set())
const runMode = ref('full')
const schedulesOpen = ref(false)
const watchFolderOpen = ref(false)
const webhookOpen = ref(false)
const notificationsOpen = ref(false)
const assetGcOpen = ref(false)
const projectArchiveOpen = ref(false)
const notificationUnseen = ref(0)
const INSPECTOR_COLLAPSED_KEY = 'sts.workflow.inspector-collapsed'
const inspectorCollapsed = ref(false)

try {
  inspectorCollapsed.value = localStorage.getItem(INSPECTOR_COLLAPSED_KEY) === '1'
} catch {
  // Storage is an optional convenience; panel interaction still works without it.
}

watch(inspectorCollapsed, (collapsed) => {
  try {
    localStorage.setItem(INSPECTOR_COLLAPSED_KEY, collapsed ? '1' : '0')
  } catch {
    // Ignore unavailable/private storage.
  }
})

async function refreshNotificationBadge() {
  if (!store.workflowId) {
    notificationUnseen.value = 0
    return
  }
  try {
    const workflowId = encodeURIComponent(store.workflowId)
    const data = await api.get(`/api/workflow/notifications?workflow_id=${workflowId}&limit=1`)
    notificationUnseen.value = data.unseen || 0
  } catch {
    // The badge is supplementary; normal editor errors remain authoritative.
  }
}

watch(
  () => [store.workflowId, store.currentExecution?.status],
  ([workflowId, status], previous = []) => {
    if (workflowId !== previous[0] || ['succeeded', 'partial', 'failed'].includes(status)) {
      refreshNotificationBadge()
    }
  },
)

onMounted(async () => {
  try {
    await Promise.all([
      store.loadNodeTypes(),
      store.refreshWorkflowList(),
      store.loadTemplates(),
      // Node cards name their selected provider, so the catalog has to be
      // there before the canvas paints, not only when the inspector opens.
      catalog.loadCatalog(),
    ])
  } catch (err) {
    toast.error(err?.message || 'Failed to load workflow data')
  }
  store.watchNodeTypeReloads()
  await maybeRecoverDraft()
  window.addEventListener('beforeunload', onBeforeUnload)
  document.addEventListener('visibilitychange', onVisibilityChange)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  store.closeNodeTypeReloads()
  window.removeEventListener('beforeunload', onBeforeUnload)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('keydown', onKeydown)
  // The component is going away (in-app navigation): persist any pending
  // debounced edits so nothing is lost while the user is elsewhere.
  store.flushDraft()
})

function onKeydown(event) {
  const target = event.target
  if (target instanceof HTMLElement
    && (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)) {
    return
  }
  if (!(event.ctrlKey || event.metaKey)) return
  const key = event.key.toLowerCase()
  if (key === 'z') {
    const changed = event.shiftKey ? store.redo() : store.undo()
    if (changed) {
      event.preventDefault()
      toast.info(event.shiftKey ? 'Redone' : 'Undone')
    }
  } else if (key === 'c') {
    if (copySelection()) event.preventDefault()
  } else if (key === 'v') {
    event.preventDefault()
    pasteClipboard()
  } else if (key === 'd') {
    const ids = selectedCanvasNodeIds()
    if (ids.length) {
      event.preventDefault()
      selectCanvasNodes(store.duplicateNodes(ids).map((node) => node.id))
    }
  }
}

let internalClipboard = null

function selectedCanvasNodeIds() {
  const ids = [...canvasSelection.value].filter((id) => store.nodeById(id))
  if (!ids.length && store.selectedNodeId) ids.push(store.selectedNodeId)
  return ids
}

function selectCanvasNodes(ids) {
  canvasSelection.value = new Set(ids)
  if (ids.length) store.selectNode(ids.at(-1))
}

function copySelection(nodeIds = selectedCanvasNodeIds()) {
  const fragment = store.copyFragment(nodeIds)
  if (!fragment) return false
  internalClipboard = fragment
  navigator.clipboard?.writeText(JSON.stringify(fragment)).catch(() => {})
  toast.info(`${fragment.nodes.length} node${fragment.nodes.length === 1 ? '' : 's'} copied`)
  return true
}

async function readClipboardFragment() {
  try {
    const text = await navigator.clipboard?.readText()
    return parseWorkflowFragment(text) || internalClipboard
  } catch {
    return internalClipboard
  }
}

async function pasteClipboard(position) {
  const fragment = await readClipboardFragment()
  const pasted = store.pasteFragment(fragment, { position })
  if (!pasted.length) {
    toast.warning('The clipboard does not contain compatible workflow nodes')
    return []
  }
  selectCanvasNodes(pasted.map((node) => node.id))
  toast.info(`${pasted.length} node${pasted.length === 1 ? '' : 's'} pasted`)
  return pasted
}

// ── Draft autosave protection (step 2.4) ───────────────────────────────
async function maybeRecoverDraft() {
  const draft = store.peekDraft()
  if (!draft) return
  const name = draft.document?.name || 'Untitled workflow'
  const when = draft.saved_at ? ` (autosaved ${new Date(draft.saved_at).toLocaleString()})` : ''
  if (window.confirm(`Recover unsaved draft "${name}"${when}?`)) {
    store.recoverDraft()
    // Deliberately not restoreViewport(): the recovered document is unsaved
    // and must stay dirty until the user explicitly saves it.
    await setFlowViewport(store.viewport)
    toast.info('Draft recovered — save to keep it')
  } else {
    store.clearDraft()
  }
}

function onBeforeUnload(event) {
  // Synchronous flush: this is what makes a killed tab lose nothing.
  store.flushDraft()
  if (store.dirty) {
    event.preventDefault()
    event.returnValue = ''
  }
}

function onVisibilityChange() {
  if (document.visibilityState === 'hidden') store.flushDraft()
}

onBeforeRouteLeave(() => {
  if (!store.dirty) return true
  store.flushDraft()
  return window.confirm(
    'You have unsaved workflow changes. A draft has been kept — leave the workflow builder?',
  )
})

const nodeTypes = { sts: markRaw(NodeCard), note: markRaw(StickyNote) }

// Store (persisted shape) → Vue Flow elements. Vue Flow runtime props stay here.
const projectCanvasNodes = createCanvasNodeProjector()
const flowNodes = computed(() => projectCanvasNodes(
  store.nodes,
  store.notes,
  canvasSelection.value,
))
const cullOffscreenElements = computed(
  () => flowNodes.value.length >= LARGE_CANVAS_NODE_THRESHOLD,
)

const flowEdges = computed(() =>
  store.edges.map((e) => {
    const sourceExecution = store.nodeExecution(e.source_node)
    const summary = sourceExecution.status === 'succeeded'
      ? sourceExecution.outputs_summary?.[e.source_port]
      : undefined
    return {
      id: e.id,
      source: e.source_node,
      target: e.target_node,
      sourceHandle: e.source_port,
      targetHandle: e.target_port,
      markerEnd: MarkerType.ArrowClosed,
      animated: sourceExecution.status === 'running',
      label: summary === undefined ? '' : edgeSummary(summary),
      class: [
        e.edge_type === 'control' ? 'wf-edge-control' : 'wf-edge-data',
        `wf-edge-${sourceExecution.status}`,
        sourceExecution.from_sample_data ? 'wf-edge-sample' : '',
      ].filter(Boolean).join(' '),
    }
  }),
)

function edgeSummary(value) {
  let text
  if (typeof value === 'string') text = value
  else if (value === null) text = 'null'
  else if (Array.isArray(value)) text = `${value.length} items`
  else if (typeof value === 'object') {
    const keys = Object.keys(value)
    text = keys.length ? keys.slice(0, 3).join(', ') : '{}'
  } else text = String(value)
  return text.length > 42 ? `${text.slice(0, 39)}…` : text
}

// ── Palette drop → add node at canvas position ─────────────────────────
function onDragOver(event) {
  if (event.dataTransfer?.types?.includes(DRAG_MIME)) {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }
}

function onDrop(event) {
  const typeKey = event.dataTransfer?.getData(DRAG_MIME)
  if (!typeKey) return
  const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  // Auto-spawns pre-connected sample stubs when the workflow setting is on.
  store.addNodeWithStubs(typeKey, position)
}

function addNoteAt(position) {
  const note = store.addNote(position)
  if (note) canvasSelection.value = new Set([note.id])
  return note
}

// ── Auto-align: magnet a dropped node into a neighbor's row/column ─────
const ALIGN_TOLERANCE = 12

function magnetAlign(id, position) {
  const aligned = { x: position.x, y: position.y }
  let bestDx = ALIGN_TOLERANCE + 1
  let bestDy = ALIGN_TOLERANCE + 1
  for (const other of [...store.nodes, ...store.notes]) {
    if (other.id === id) continue
    const dx = Math.abs(other.position.x - position.x)
    const dy = Math.abs(other.position.y - position.y)
    if (dx <= ALIGN_TOLERANCE && dx < bestDx) { bestDx = dx; aligned.x = other.position.x }
    if (dy <= ALIGN_TOLERANCE && dy < bestDy) { bestDy = dy; aligned.y = other.position.y }
  }
  return aligned
}

// ── Sync Vue Flow interactions back into the store ─────────────────────
function onNodeDragStop({ node, nodes: draggedNodes }) {
  // Multi-select/box drags carry every moved node in `nodes`; persisting
  // only the grab target would snap the rest back on the next re-render.
  const moved = draggedNodes?.length ? draggedNodes : [node]
  const moves = moved.map((dragged) => ({
    id: dragged.id,
    position: { x: dragged.position.x, y: dragged.position.y },
  }))
  // Single-node drags magnet-align to the nearest neighbor; group drags
  // keep their internal spacing untouched.
  if (moves.length === 1) {
    moves[0].position = magnetAlign(moves[0].id, moves[0].position)
  }
  store.moveNodes(moves.filter((move) => store.nodeById(move.id)))
  store.moveNotes(moves.filter((move) => store.noteById(move.id)))
}

function onNodesChange(changes) {
  const selectionChanges = changes.filter((change) => change.type === 'select')
  if (selectionChanges.length) {
    const next = new Set(canvasSelection.value)
    for (const change of selectionChanges) {
      if (change.selected) next.add(change.id)
      else next.delete(change.id)
    }
    canvasSelection.value = next
  }
  const removed = changes.filter((c) => c.type === 'remove').map((c) => c.id)
  if (removed.length) {
    store.removeNodes(removed.filter((id) => store.nodeById(id)))
    store.removeNotes(removed.filter((id) => store.noteById(id)))
    canvasSelection.value = new Set(
      [...canvasSelection.value].filter((nodeId) => !removed.includes(nodeId)),
    )
    // Vue Flow only generated a remove change for the user-selected main node.
    // The store may also have removed its owned sample stubs, so replace Vue
    // Flow's internal node collection after its default handler finishes. This
    // prevents those already-deleted stubs from remaining as visual ghosts.
    queueMicrotask(() => setFlowNodes(flowNodes.value))
  }
}

function onEdgesChange(changes) {
  const removed = changes.filter((c) => c.type === 'remove').map((c) => c.id)
  if (!removed.length) return

  // Vue Flow emits connected-edge removals immediately before the associated
  // node removal. Defer the edge-only action by one microtask so removeNodes()
  // can still see the intact relationships and include default sample stubs in
  // the same atomic deletion. A genuinely standalone edge removal is applied
  // once the event sequence has finished.
  queueMicrotask(() => {
    const remaining = removed.filter((edgeId) => store.edges.some((edge) => edge.id === edgeId))
    if (remaining.length) store.removeEdges(remaining)
  })
}

function onViewportChangeEnd(vp) {
  store.setViewport(vp)
}

// ── Connections (validated, contracts §3) ──────────────────────────────
function toConnectionShape(params) {
  return {
    sourceNode: params.source,
    sourcePort: params.sourceHandle,
    targetNode: params.target,
    targetPort: params.targetHandle,
    // Present only when Vue Flow re-validates an existing edge; interactive
    // connection params carry no id.
    edgeId: params.id,
  }
}

function onConnect(params) {
  connectionCompleted = true
  const verdict = store.connectNodes(toConnectionShape(params))
  if (!verdict.ok) {
    toast.error(verdict.reason)
  } else if (verdict.detachedStub) {
    toast.info('Sample input replaced by the real connection — Ctrl+Z restores it')
  }
}

// ── Node context menu: manual stub attachment (step 2.5) ───────────────
const contextMenu = ref(null) // {kind, nodeId|edgeId, x, y, flowPosition}
const insertionPalette = ref(null)
let connectionStart = null
let connectionCompleted = false

function onNodeContextMenu({ event, node }) {
  event.preventDefault()
  // Fixed positioning: viewport coordinates work regardless of panel layout.
  contextMenu.value = {
    kind: store.noteById(node.id) ? 'note' : 'node',
    nodeId: node.id,
    x: event.clientX,
    y: event.clientY,
  }
  insertionPalette.value = null
}

function onEdgeContextMenu({ event, edge }) {
  event.preventDefault()
  contextMenu.value = { kind: 'edge', edgeId: edge.id, x: event.clientX, y: event.clientY }
  insertionPalette.value = null
}

function onPaneContextMenu(event) {
  event.preventDefault()
  contextMenu.value = {
    kind: 'pane', x: event.clientX, y: event.clientY,
    flowPosition: screenToFlowCoordinate({ x: event.clientX, y: event.clientY }),
  }
  insertionPalette.value = null
}

function closeContextMenu() {
  contextMenu.value = null
}

function onContextCopy() {
  copySelection([contextMenu.value.nodeId])
  closeContextMenu()
}

function onContextDuplicate() {
  const copies = store.duplicateNodes([contextMenu.value.nodeId])
  selectCanvasNodes(copies.map((node) => node.id))
  closeContextMenu()
}

function onContextDelete() {
  if (contextMenu.value.kind === 'edge') store.removeEdges([contextMenu.value.edgeId])
  else if (contextMenu.value.kind === 'note') store.removeNotes([contextMenu.value.nodeId])
  else store.removeNodes([contextMenu.value.nodeId])
  closeContextMenu()
}

async function onContextPaste() {
  const position = contextMenu.value.flowPosition
  closeContextMenu()
  await pasteClipboard(position)
}

function onContextDisable() {
  const node = store.nodeById(contextMenu.value.nodeId)
  store.setNodeDisabled(node.id, !node.disabled)
  closeContextMenu()
}

function onContextReplace(typeKey) {
  const nodeId = contextMenu.value.nodeId
  const plan = store.replacementPlan(nodeId, typeKey)
  if (!plan) return
  if (plan.droppedEdges.length) {
    const count = plan.droppedEdges.length
    if (!window.confirm(`Replacing this node will remove ${count} incompatible connection${count === 1 ? '' : 's'}. Continue?`)) return
  }
  store.replaceNode(nodeId, typeKey)
  closeContextMenu()
}

const replacementTypes = computed(() => {
  if (contextMenu.value?.kind !== 'node') return []
  const current = store.nodeById(contextMenu.value.nodeId)?.type
  return Object.values(store.nodeTypes)
    .filter((definition) => definition.type !== current)
    .sort((left, right) => left.display_name.localeCompare(right.display_name))
})

function onConnectStart(params) {
  connectionStart = params
  connectionCompleted = false
  insertionPalette.value = null
}

function pointerCoordinates(event) {
  const point = event?.changedTouches?.[0] || event
  return point && Number.isFinite(point.clientX) ? { x: point.clientX, y: point.clientY } : null
}

function onConnectEnd(event) {
  const start = connectionStart
  connectionStart = null
  if (connectionCompleted || !start?.nodeId || !start.handleId) return
  const point = pointerCoordinates(event)
  if (!point || !event.target?.closest?.('.vue-flow__pane')) return
  const candidates = compatibleInsertions({
    nodeTypes: store.nodeTypes,
    node: store.nodeById(start.nodeId),
    handleId: start.handleId,
    handleType: start.handleType,
  })
  if (!candidates.length) return
  const palette = {
    x: point.x, y: point.y,
    position: screenToFlowCoordinate(point),
    start: { ...start, portType: candidates[0].portType },
    candidates,
  }
  requestAnimationFrame(() => { insertionPalette.value = palette })
}

function chooseInsertion(candidate) {
  const palette = insertionPalette.value
  const node = store.insertNodeAndConnect(
    candidate.type, palette.position, palette.start, candidate.portId,
  )
  insertionPalette.value = null
  if (!node) toast.error('That node could not be connected')
  else selectCanvasNodes([node.id])
}

function onAttachSampleInputs() {
  const created = store.attachSampleInputs(contextMenu.value.nodeId)
  closeContextMenu()
  toast.info(created.length
    ? `Attached ${created.length} sample input${created.length > 1 ? 's' : ''}`
    : 'Every required input is already connected')
}

function onAttachResultViewer() {
  const stub = store.attachResultViewer(contextMenu.value.nodeId)
  closeContextMenu()
  toast.info(stub ? 'Result viewer attached' : 'This node has no data output to view')
}

function isFailedNode(nodeId) {
  return store.nodeExecution(nodeId).status === 'failed'
}

function targetsForMode(mode, nodeId = store.selectedNodeId) {
  if (mode === 'full') return []
  if (mode === 'selected') return [...canvasSelection.value]
  return nodeId ? [nodeId] : []
}

function canRun(mode, nodeId = store.selectedNodeId) {
  if (store.readOnly || !store.nodeCount || store.executionLoading || store.executionActive) return false
  const targets = targetsForMode(mode, nodeId)
  if (mode === 'full') return true
  if (mode === 'selected') return targets.length > 0
  if (targets.length !== 1) return false
  if (mode === 'retry_failed' || mode === 'retry_failed_desc') {
    return isFailedNode(targets[0])
  }
  return true
}

// Live feedback while dragging a connection: valid targets highlight,
// invalid ones show the not-allowed cursor.
function isValidConnection(params) {
  return validateConnection(
    { nodes: store.nodes, edges: store.edges, nodeTypes: store.nodeTypes, portTypes: store.portTypes },
    toConnectionShape(params),
  ).ok
}

// ── Minimap colored by category ────────────────────────────────────────
function minimapColor(node) {
  if (node.type === 'note') return '#f5d86e'
  const def = store.nodeTypes[node.data?.nodeType]
  return store.categories[def?.category]?.color || '#4b5563'
}

// ── Dagre tidy-up ──────────────────────────────────────────────────────
function tidyUp() {
  if (!store.nodes.length) return
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const node of store.nodes) {
    g.setNode(node.id, { width: 200, height: 60 })
  }
  for (const edge of store.edges) {
    g.setEdge(edge.source_node, edge.target_node)
  }
  dagre.layout(g)
  const moves = []
  for (const node of store.nodes) {
    const pos = g.node(node.id)
    if (pos) {
      moves.push({
        id: node.id,
        position: {
          x: Math.round((pos.x - 100) / 20) * 20,
          y: Math.round((pos.y - 30) / 20) * 20,
        },
      })
    }
  }
  store.moveNodes(moves)
  requestAnimationFrame(() => fitView({ padding: 0.15 }))
}

const validating = ref(false)

async function onValidate() {
  validating.value = true
  try {
    const data = await api.post('/api/workflow/validate', {
      body: { workflow: store.toDocument() },
    })
    if (data.valid && !data.warnings.length) {
      toast.success('Workflow is valid')
    } else if (data.valid) {
      toast.warning(`Valid, with ${data.warnings.length} warning(s): ${data.warnings[0]?.message}`)
    } else {
      const first = data.problems[0]?.message || 'see node badges'
      toast.error(`${data.problems.length} problem(s) — ${first}`)
    }
  } catch (err) {
    toast.error(err?.message || 'Validation request failed')
  } finally {
    validating.value = false
  }
}

function confirmDiscard() {
  return !store.dirty || window.confirm('Discard unsaved workflow changes?')
}

async function restoreViewport() {
  await setFlowViewport(store.viewport)
  store.dirty = false
}

async function onNew() {
  if (!confirmDiscard()) return
  store.newWorkflow()
  await restoreViewport()
}

async function onOpen(event) {
  const id = event.target.value
  event.target.value = ''
  if (!id || !confirmDiscard()) return
  try {
    await store.openWorkflow(id)
    await restoreViewport()
    toast.success(`Opened ${store.workflowName}`)
  } catch (err) {
    toast.error(store.persistenceError || err.message)
  }
}

async function onSave() {
  try {
    if (!store.workflowId && store.workflowName === 'Untitled workflow') {
      const name = window.prompt('Workflow name', store.workflowName)
      if (!name?.trim()) return
      store.workflowName = name.trim()
    }
    await store.saveWorkflow()
    toast.success('Workflow saved')
  } catch (err) {
    toast.error(store.persistenceError || err.message)
  }
}

async function onSaveAs() {
  const name = window.prompt('Save workflow as', `${store.workflowName} copy`)
  if (!name?.trim()) return
  try {
    await store.saveAs(name)
    toast.success('Workflow copy saved')
  } catch (err) {
    toast.error(store.persistenceError || err.message)
  }
}

async function onDuplicate() {
  try {
    await store.saveAs(`${store.workflowName} copy`)
    toast.success('Workflow duplicated')
  } catch (err) {
    toast.error(store.persistenceError || err.message)
  }
}

async function onTemplate(event) {
  const templateId = event.target.value
  event.target.value = ''
  if (!templateId || !confirmDiscard()) return
  if (store.applyTemplate(templateId)) {
    requestAnimationFrame(() => fitView({ padding: 0.1 }))
    toast.info('Template loaded — add your script and save when ready')
  }
}

async function onImportFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !confirmDiscard()) return
  if (file.size > 2 * 1024 * 1024) {
    toast.error('Workflow JSON exceeds the 2 MiB limit')
    return
  }
  try {
    const document = JSON.parse(await file.text())
    await store.importDocument(document)
    await restoreViewport()
    toast.success('Workflow imported')
  } catch (err) {
    toast.error(store.persistenceError || err?.message || 'Invalid workflow JSON')
  }
}

function onExport() {
  if (!store.workflowId) {
    toast.warning('Save the workflow before exporting it')
    return
  }
  const anchor = document.createElement('a')
  anchor.href = `/api/workflows/${encodeURIComponent(store.workflowId)}/export`
  anchor.download = `${store.workflowId}.json`
  anchor.click()
}

async function onProjectRestored(workflowId, projectId) {
  projectArchiveOpen.value = false
  try {
    await store.refreshWorkflowList()
    await store.openWorkflow(workflowId)
    await restoreViewport()
    toast.success(`Project ${projectId} restored`)
  } catch (err) {
    toast.error(store.persistenceError || err?.message || 'Project restored, but could not be opened')
  }
}

async function onRun(mode = runMode.value, nodeId = store.selectedNodeId) {
  const targets = targetsForMode(mode, nodeId)
  if (!canRun(mode, nodeId)) {
    const message = mode === 'selected'
      ? 'Select one or more canvas nodes first'
      : mode.startsWith('retry_')
        ? 'Choose a node that failed in the current execution'
        : 'Choose a node first'
    toast.warning(message)
    return
  }
  try {
    await store.runWorkflow({ runMode: mode, targetNodeIds: targets })
    toast.success('Workflow run started')
  } catch (err) {
    toast.error(store.executionError || err?.message || 'Failed to run workflow')
  }
}

async function onContextRun(mode) {
  const nodeId = contextMenu.value?.nodeId
  closeContextMenu()
  await onRun(mode, nodeId)
}

async function onStop() {
  try {
    await store.stopExecution()
    toast.info('Stopping workflow…')
  } catch (err) {
    toast.error(store.executionError || err?.message || 'Failed to stop workflow')
  }
}
</script>

<template>
  <div class="workflow-page">
    <!-- Top — toolbar -->
    <header class="wf-toolbar">
      <div class="wf-toolbar-identity">
        <div class="wf-title-row">
          <span class="wf-title">{{ store.workflowName }}</span>
          <span v-if="store.dirty" class="wf-unsaved" title="Unsaved changes">Unsaved</span>
          <span v-else-if="store.workflowId" class="wf-saved" title="All changes saved">Saved</span>
          <span class="wf-badge">Workflow</span>
        </div>
        <span
          v-if="store.saveBlockedReason"
          class="wf-save-blocked"
          role="alert"
        >{{ store.saveBlockedReason }}</span>
        <span
          v-else-if="store.dirty && store.draftSavedAt"
          class="wf-draft-hint"
          :title="`Draft autosaved ${new Date(store.draftSavedAt).toLocaleTimeString()}`"
        >Draft safely autosaved</span>
      </div>

      <nav class="wf-toolbar-actions" aria-label="Workflow commands">
        <div class="wf-action-group" role="group" aria-label="Workflow files">
          <button class="wf-btn" :disabled="store.persistenceLoading" @click="onNew">New</button>
          <select class="wf-select wf-open-select" :disabled="store.persistenceLoading" aria-label="Open workflow" @change="onOpen">
            <option value="">Open…</option>
            <option v-for="item in store.workflowList" :key="item.workflow_id" :value="item.workflow_id">
              {{ item.name }}
            </option>
          </select>
          <button
            class="wf-btn primary"
            :disabled="store.persistenceLoading || !!store.saveBlockedReason || (!!store.workflowId && !store.dirty)"
            :title="store.saveBlockedReason || ''"
            @click="onSave"
          >
            Save
          </button>
          <details class="wf-more-menu">
            <summary class="wf-btn" aria-label="More workflow actions">More <span class="wf-menu-chevron" aria-hidden="true">⌄</span></summary>
            <div class="wf-more-popover wf-file-popover">
              <div class="wf-menu-heading">Create</div>
              <select class="wf-select wf-menu-select" :disabled="store.persistenceLoading" aria-label="Create from template" @change="onTemplate">
                <option value="">Choose template…</option>
                <option v-for="item in store.templates" :key="item.template_id" :value="item.template_id">
                  {{ item.workflow.name }}
                </option>
              </select>
              <div class="wf-menu-divider" />
              <div class="wf-menu-heading">File</div>
              <button :disabled="store.persistenceLoading || !!store.saveBlockedReason" :title="store.saveBlockedReason || ''" @click="onSaveAs">Save as…</button>
              <button :disabled="store.persistenceLoading || !!store.saveBlockedReason" :title="store.saveBlockedReason || ''" @click="onDuplicate">Duplicate workflow</button>
              <button :disabled="store.persistenceLoading" @click="importInput?.click()">Import JSON…</button>
              <button :disabled="!store.workflowId" @click="onExport">Export JSON</button>
            </div>
          </details>
          <input ref="importInput" class="wf-file-input" type="file" accept="application/json,.json" @change="onImportFile" />
        </div>

        <div class="wf-action-group wf-action-group-compact" role="group" aria-label="Edit history">
          <button
            class="wf-btn"
            :disabled="!store.canUndo"
            :title="store.undoLabel ? `Undo ${store.undoLabel} (Ctrl+Z)` : 'Nothing to undo'"
            @click="store.undo()"
          >Undo</button>
          <button
            class="wf-btn"
            :disabled="!store.canRedo"
            :title="store.redoLabel ? `Redo ${store.redoLabel} (Ctrl+Shift+Z)` : 'Nothing to redo'"
            @click="store.redo()"
          >Redo</button>
        </div>

        <div class="wf-action-group wf-action-group-compact" role="group" aria-label="Workflow quality">
          <button class="wf-btn validate" :disabled="!store.nodeCount || validating" title="Validate workflow on the server" @click="onValidate">
            {{ validating ? 'Checking…' : 'Validate' }}
          </button>
        </div>

        <div class="wf-action-group wf-run-group" role="group" aria-label="Run workflow">
          <select
            v-if="!store.executionActive"
            v-model="runMode"
            class="wf-select wf-run-select"
            aria-label="Run mode"
            title="Choose which part of the workflow to run"
          >
            <option value="full">Full workflow</option>
            <option value="node_with_deps">Node + dependencies</option>
            <option value="node_isolated">Node in isolation</option>
            <option value="selected">Selected + dependencies</option>
            <option value="from_node">From node downstream</option>
            <option value="retry_failed">Retry failed node</option>
            <option value="retry_failed_desc">Retry failed + downstream</option>
          </select>
          <button
            v-if="!store.executionActive"
            class="wf-btn run"
            :disabled="!canRun(runMode)"
            :title="`Run mode: ${runMode}`"
            @click="onRun()"
          ><span aria-hidden="true">▶</span> Run</button>
          <button
            v-else
            class="wf-btn stop"
            :disabled="store.currentExecution?.status === 'cancelling'"
            title="Cooperatively stop the current run"
            @click="onStop"
          >{{ store.currentExecution?.status === 'cancelling' ? 'Stopping…' : '■ Stop' }}</button>
        </div>

        <div class="wf-action-group wf-utility-group" role="group" aria-label="Additional workflow tools">
          <details class="wf-more-menu">
            <summary class="wf-btn">
              Automate
              <span v-if="notificationUnseen" class="wf-unseen" aria-label="unseen notifications">{{ notificationUnseen }}</span>
              <span class="wf-menu-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div class="wf-more-popover">
              <div class="wf-menu-heading">Triggers</div>
              <button :disabled="store.readOnly" @click="schedulesOpen = true">Schedule runs…</button>
              <button :disabled="store.readOnly" @click="watchFolderOpen = true">Watch folder…</button>
              <button :disabled="store.readOnly" @click="webhookOpen = true">Webhook…</button>
              <div class="wf-menu-divider" />
              <button class="wf-notification-button" @click="notificationsOpen = true">
                Notifications <span v-if="notificationUnseen" class="wf-unseen" aria-hidden="true">{{ notificationUnseen }}</span>
              </button>
            </div>
          </details>

          <details class="wf-more-menu">
            <summary class="wf-btn">View <span class="wf-menu-chevron" aria-hidden="true">⌄</span></summary>
            <div class="wf-more-popover">
              <div class="wf-menu-heading">Canvas</div>
              <button :disabled="!store.nodeCount || store.readOnly" @click="tidyUp">Tidy layout</button>
              <button :disabled="!store.nodeCount" @click="fitView({ padding: 0.15 })">Fit all nodes</button>
              <div class="wf-menu-divider" />
              <label class="wf-menu-toggle" title="Auto-attach editable sample stubs when dropping unconnected nodes">
                <span>Auto-attach stubs</span>
                <input
                  type="checkbox"
                  :disabled="store.readOnly"
                  :checked="store.autoAttachStubs"
                  @change="store.setAutoAttachStubs($event.target.checked)"
                />
              </label>
            </div>
          </details>

          <details class="wf-more-menu">
            <summary class="wf-btn">Tools <span class="wf-menu-chevron" aria-hidden="true">⌄</span></summary>
            <div class="wf-more-popover">
              <div class="wf-menu-heading">Project</div>
              <button @click="projectArchiveOpen = true">Archive and restore…</button>
              <button @click="assetGcOpen = true">Clean unused assets…</button>
            </div>
          </details>
        </div>
      </nav>
    </header>

    <div v-if="store.readOnly" class="wf-read-only-warning" role="alert">
      <strong>View only.</strong>
      {{ store.loadWarnings[0]?.message || 'This workflow contains node versions newer than this installation.' }}
      Update Scriptase before editing or running it.
    </div>

    <div class="wf-body">
      <!-- Left — node library -->
      <aside class="wf-library">
        <div class="wf-panel-header">Nodes</div>
        <NodeLibrary />
      </aside>

      <!-- Center — canvas -->
      <main class="wf-canvas" @dragover="onDragOver" @drop="onDrop">
        <VueFlow
          :nodes="flowNodes"
          :edges="flowEdges"
          :node-types="nodeTypes"
          :min-zoom="0.1"
          :max-zoom="1.5"
          :snap-to-grid="true"
          :snap-grid="[20, 20]"
          :delete-key-code="store.readOnly ? null : 'Delete'"
          :nodes-draggable="!store.readOnly"
          :nodes-connectable="!store.readOnly"
          :only-render-visible-elements="cullOffscreenElements"
          :multi-selection-key-code="'Control'"
          :is-valid-connection="isValidConnection"
          fit-view-on-init
          @connect="onConnect"
          @connect-start="onConnectStart"
          @connect-end="onConnectEnd"
          @node-click="({ node }) => store.nodeById(node.id) ? store.selectNode(node.id) : store.clearSelection()"
          @node-context-menu="onNodeContextMenu"
          @edge-context-menu="onEdgeContextMenu"
          @pane-context-menu="onPaneContextMenu"
          @pane-click="store.clearSelection(); closeContextMenu()"
          @node-drag-stop="onNodeDragStop"
          @nodes-change="onNodesChange"
          @edges-change="onEdgesChange"
          @viewport-change-end="onViewportChangeEnd"
        >
          <Background pattern-color="rgba(255,255,255,0.12)" :gap="20" />
          <Controls position="bottom-left" />
          <MiniMap
            position="bottom-right"
            pannable
            zoomable
            :node-color="minimapColor"
            mask-color="rgba(6, 8, 14, 0.65)"
            mask-stroke-color="rgba(94, 234, 212, 0.35)"
            :mask-border-radius="4"
          />
          <div v-if="!flowNodes.length" class="wf-canvas-hint">
            Drag a node from the library to start building
          </div>
        </VueFlow>

        <!-- Node, edge, and pane context menus. -->
        <template v-if="contextMenu">
          <div class="wf-context-backdrop" @click="closeContextMenu" @contextmenu.prevent="closeContextMenu" />
          <div class="wf-context-menu" :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }">
            <template v-if="contextMenu.kind === 'pane'">
              <button class="wf-context-item" @click="onContextPaste">Paste here</button>
              <button class="wf-context-item" @click="addNoteAt(contextMenu.flowPosition); closeContextMenu()">Add note</button>
              <div class="wf-context-divider" />
              <button class="wf-context-item" :disabled="!store.nodeCount" @click="tidyUp(); closeContextMenu()">Auto arrange</button>
            </template>
            <template v-else-if="contextMenu.kind === 'edge'">
              <button class="wf-context-item danger" @click="onContextDelete">Disconnect</button>
            </template>
            <template v-else-if="contextMenu.kind === 'note'">
              <button class="wf-context-item danger" @click="onContextDelete">Delete note</button>
            </template>
            <template v-else>
              <button class="wf-context-item" @click="onContextCopy">Copy</button>
              <button class="wf-context-item" @click="onContextDuplicate">Duplicate</button>
              <button class="wf-context-item" @click="onContextDisable">
                {{ store.nodeById(contextMenu.nodeId)?.disabled ? 'Enable' : 'Disable' }}
              </button>
              <details class="wf-context-submenu">
                <summary>Replace with…</summary>
                <div class="wf-context-replacements">
                  <button
                    v-for="definition in replacementTypes"
                    :key="definition.type"
                    class="wf-context-item"
                    @click="onContextReplace(definition.type)"
                  >{{ definition.display_name }}</button>
                </div>
              </details>
              <div class="wf-context-divider" />
              <button class="wf-context-item" @click="onContextRun('node_with_deps')">Run node + dependencies</button>
              <button class="wf-context-item" @click="onContextRun('node_isolated')">Run node in isolation</button>
              <button class="wf-context-item" @click="onContextRun('from_node')">Run from node downstream</button>
              <button
                class="wf-context-item"
                :disabled="!isFailedNode(contextMenu.nodeId)"
                @click="onContextRun('retry_failed')"
              >Retry failed node</button>
              <button
                class="wf-context-item"
                :disabled="!isFailedNode(contextMenu.nodeId)"
                @click="onContextRun('retry_failed_desc')"
              >Retry failed + downstream</button>
              <template v-if="!store.isStubType(store.nodeById(contextMenu.nodeId)?.type)">
                <button class="wf-context-item" @click="onAttachSampleInputs">Attach sample inputs</button>
                <button class="wf-context-item" @click="onAttachResultViewer">Attach result viewer</button>
              </template>
              <div class="wf-context-divider" />
              <button class="wf-context-item danger" @click="onContextDelete">Delete</button>
            </template>
          </div>
        </template>

        <template v-if="insertionPalette">
          <div class="wf-context-backdrop" @click="insertionPalette = null" @contextmenu.prevent="insertionPalette = null" />
          <div class="wf-context-menu wf-insert-palette" :style="{ left: `${insertionPalette.x}px`, top: `${insertionPalette.y}px` }">
            <div class="wf-context-heading">Insert compatible node</div>
            <button
              v-for="candidate in insertionPalette.candidates"
              :key="`${candidate.type}:${candidate.portId}`"
              class="wf-context-item"
              @click="chooseInsertion(candidate)"
            >{{ candidate.displayName }} <small>· {{ candidate.portId }}</small></button>
          </div>
        </template>
      </main>

      <!-- Right — node inspector -->
      <aside
        class="wf-inspector"
        :class="{ collapsed: inspectorCollapsed, 'wf-inspector-read-only': store.readOnly }"
      >
        <div class="wf-panel-header wf-inspector-header">
          <span class="wf-inspector-title">Inspector</span>
          <button
            type="button"
            class="wf-inspector-toggle"
            :aria-expanded="String(!inspectorCollapsed)"
            aria-controls="workflow-inspector-content"
            :title="inspectorCollapsed ? 'Expand inspector' : 'Collapse inspector'"
            @click="inspectorCollapsed = !inspectorCollapsed"
          >
            <span aria-hidden="true">{{ inspectorCollapsed ? '‹' : '›' }}</span>
            <span class="wf-sr-only">{{ inspectorCollapsed ? 'Expand inspector' : 'Collapse inspector' }}</span>
          </button>
        </div>
        <div id="workflow-inspector-content" v-show="!inspectorCollapsed" class="wf-inspector-content">
          <NodeInspector />
        </div>
      </aside>
    </div>

    <!-- Bottom — live execution inspector (step 3.6) -->
    <ExecutionPanel />
    <ScheduleSettings v-if="schedulesOpen" @close="schedulesOpen = false" />
    <WatchFolderSettings v-if="watchFolderOpen" @close="watchFolderOpen = false" />
    <WebhookSettings v-if="webhookOpen" @close="webhookOpen = false" />
    <NotificationCenter
      v-if="notificationsOpen"
      @close="notificationsOpen = false"
      @seen="notificationUnseen = 0"
    />
    <AssetGarbageCollection v-if="assetGcOpen" @close="assetGcOpen = false" />
    <ProjectArchiveManager
      v-if="projectArchiveOpen"
      @close="projectArchiveOpen = false"
      @restored="onProjectRestored"
    />
  </div>
</template>

<style scoped>
.workflow-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-dark);
  color: var(--text);
}

.wf-read-only-warning {
  flex: 0 0 auto;
  padding: 9px 14px;
  border-bottom: 1px solid rgba(245, 158, 11, 0.38);
  background: rgba(245, 158, 11, 0.13);
  color: #fcd38d;
  font-size: 12px;
}

.wf-inspector-read-only .wf-inspector-content :deep(input),
.wf-inspector-read-only .wf-inspector-content :deep(textarea),
.wf-inspector-read-only .wf-inspector-content :deep(select),
.wf-inspector-read-only .wf-inspector-content :deep(button) {
  pointer-events: none;
  opacity: 0.65;
}

.wf-toolbar {
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
  gap: 8px;
  padding: 10px 12px 9px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, color-mix(in srgb, var(--bg-darkest) 92%, #17283a), var(--bg-darkest));
  position: relative;
  z-index: 20;
}

.wf-toolbar-identity,
.wf-title-row {
  display: flex;
  align-items: center;
}

.wf-toolbar-identity {
  justify-content: space-between;
  min-height: 20px;
  gap: 16px;
  padding: 0 3px;
}

.wf-title-row {
  min-width: 0;
  gap: 8px;
}

.wf-toolbar-actions {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 7px;
}

.wf-action-group {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  padding: 4px;
  border: 1px solid rgba(111, 137, 168, 0.16);
  border-radius: 11px;
  background: rgba(7, 16, 27, 0.52);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025);
}

.wf-action-group > * {
  flex: 0 0 auto;
}

.wf-action-label {
  padding: 0 5px 0 3px;
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  user-select: none;
}

.wf-title {
  font-family: var(--font-display);
  overflow: hidden;
  color: var(--text);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -0.02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-unsaved,
.wf-saved {
  border-radius: 999px;
  padding: 2px 7px;
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.wf-unsaved {
  color: #ffd38a;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.wf-saved {
  color: #8dd9b0;
  background: rgba(52, 211, 153, 0.09);
  border: 1px solid rgba(52, 211, 153, 0.18);
}

.wf-draft-hint {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}

.wf-save-blocked {
  font-size: 10px;
  font-weight: 600;
  color: #f87171;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 340px;
}

.wf-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--accent) 80%, white);
  border: 1px solid rgba(78, 205, 196, 0.25);
  background: rgba(78, 205, 196, 0.07);
  border-radius: 999px;
  padding: 2px 7px;
}

.wf-btn {
  min-height: 30px;
  background: rgba(20, 34, 51, 0.78);
  border: 1px solid rgba(111, 137, 168, 0.24);
  border-radius: 7px;
  color: var(--text-secondary);
  font: inherit;
  font-size: 11px;
  font-weight: 650;
  line-height: 1;
  padding: 7px 10px;
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.14s ease, border-color 0.14s ease, background 0.14s ease, transform 0.14s ease;
}

.wf-notification-button { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.wf-unseen { min-width: 17px; padding: 2px 5px; border-radius: 999px; color: #21070d; background: #fb7185; font-size: 9px; text-align: center; }

.wf-btn:hover:not(:disabled) {
  color: var(--text);
  border-color: rgba(78, 205, 196, 0.55);
  background: rgba(28, 47, 69, 0.95);
}

.wf-btn:active:not(:disabled) {
  transform: translateY(1px);
}

.wf-btn:focus-visible,
.wf-select:focus-visible,
.wf-more-menu summary:focus-visible,
.wf-toggle input:focus-visible,
.wf-menu-toggle input:focus-visible,
.wf-menu-link:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent) 75%, white);
  outline-offset: 2px;
}

.wf-btn.primary {
  color: var(--bg-darkest);
  background: var(--accent);
  border-color: var(--accent);
  box-shadow: 0 4px 14px rgba(78, 205, 196, 0.16);
}

.wf-btn.primary:hover:not(:disabled) {
  color: var(--bg-darkest);
  background: color-mix(in srgb, var(--accent) 86%, white);
}

.wf-btn.validate { color: #a8c9ed; }
.wf-btn.run {
  color: #062318;
  border-color: #48d7a0;
  background: #48d7a0;
  box-shadow: 0 4px 14px rgba(52, 211, 153, 0.17);
}
.wf-btn.run:hover:not(:disabled) { color: #041b12; border-color: #75e4ba; background: #75e4ba; }
.wf-btn.stop { color: #fda4af; border-color: rgba(251,113,133,.5); background: rgba(251,113,133,.09); }

.wf-select {
  min-height: 30px;
  max-width: 145px;
  background: rgba(20, 34, 51, 0.78);
  border: 1px solid rgba(111, 137, 168, 0.24);
  border-radius: 7px;
  color: var(--text-secondary);
  font: inherit;
  font-size: 11px;
  padding: 6px 26px 6px 8px;
  cursor: pointer;
}

.wf-open-select { width: 112px; }
.wf-run-select { width: 156px; max-width: 156px; }

.wf-more-menu {
  position: relative;
}

.wf-more-menu > summary {
  display: flex;
  align-items: center;
  gap: 5px;
  list-style: none;
}

.wf-menu-chevron {
  color: var(--text-muted);
  font-size: 10px;
  transition: transform 0.15s ease;
}

.wf-more-menu[open] .wf-menu-chevron { transform: rotate(180deg); }

.wf-more-menu > summary::-webkit-details-marker { display: none; }

.wf-more-menu[open] > summary {
  color: var(--text);
  border-color: rgba(78, 205, 196, 0.55);
  background: rgba(28, 47, 69, 0.95);
}

.wf-more-popover {
  position: absolute;
  top: calc(100% + 7px);
  right: 0;
  z-index: 80;
  display: flex;
  flex-direction: column;
  width: 210px;
  padding: 5px;
  border: 1px solid rgba(111, 137, 168, 0.3);
  border-radius: 10px;
  background: #0d1826;
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.42);
}

.wf-file-popover { width: 230px; }

.wf-menu-heading {
  padding: 7px 10px 5px;
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.wf-menu-divider {
  height: 1px;
  margin: 5px 7px;
  background: rgba(111, 137, 168, 0.2);
}

.wf-menu-select {
  width: calc(100% - 10px);
  max-width: none;
  margin: 0 5px 5px;
}

.wf-more-popover button,
.wf-menu-link {
  display: flex;
  align-items: center;
  width: 100%;
  box-sizing: border-box;
  padding: 9px 10px;
  border: 0;
  border-radius: 6px;
  color: var(--text-secondary);
  background: transparent;
  font: inherit;
  font-size: 11px;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.wf-more-popover button:hover:not(:disabled),
.wf-menu-link:hover {
  color: var(--text);
  background: rgba(255, 255, 255, 0.06);
}

.wf-more-popover button:disabled {
  opacity: 0.38;
  cursor: default;
}

.wf-file-input {
  display: none;
}

.wf-btn:disabled {
  opacity: 0.34;
  cursor: default;
  box-shadow: none;
}

.wf-utility-group {
  margin-left: auto;
  background: rgba(7, 16, 27, 0.3);
}

.wf-menu-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

@media (max-width: 1180px) {
  .wf-toolbar-actions { flex-wrap: wrap; }
  .wf-toolbar-actions { gap: 5px; }
  .wf-action-group { padding: 3px; }
  .wf-utility-group { margin-left: 0; }
}

@media (max-width: 820px) {
  .wf-toolbar { padding-inline: 8px; }
  .wf-toolbar-identity { align-items: flex-start; }
  .wf-draft-hint { display: none; }
  .wf-action-group { max-width: 100%; }
  .wf-run-group { order: -1; }
}

.wf-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.wf-library {
  width: 240px;
  min-width: 240px;
  border-right: 1px solid var(--border);
  background: var(--bg-darkest);
  display: flex;
  flex-direction: column;
}

.wf-inspector {
  width: 300px;
  min-width: 300px;
  box-sizing: border-box;
  border-left: 1px solid var(--border);
  background: var(--bg-darkest);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.18s ease, min-width 0.18s ease;
}

.wf-inspector.collapsed {
  width: 42px;
  min-width: 42px;
}

.wf-inspector-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 38px;
  box-sizing: border-box;
  padding: 7px 8px 6px 14px;
}

.wf-inspector-title { white-space: nowrap; }

.wf-inspector-toggle {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid rgba(111, 137, 168, 0.24);
  border-radius: 7px;
  color: var(--text-secondary);
  background: rgba(20, 34, 51, 0.72);
  font: 700 19px/1 inherit;
  cursor: pointer;
  transition: color 0.14s ease, border-color 0.14s ease, background 0.14s ease;
}

.wf-inspector-toggle:hover {
  color: var(--text);
  border-color: rgba(78, 205, 196, 0.55);
  background: rgba(28, 47, 69, 0.95);
}

.wf-inspector-toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent) 75%, white);
  outline-offset: 2px;
}

.wf-inspector-content {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

.wf-inspector.collapsed .wf-inspector-header {
  flex: 1;
  flex-direction: column;
  justify-content: flex-start;
  gap: 12px;
  padding: 7px;
}

.wf-inspector.collapsed .wf-inspector-toggle { order: -1; }

.wf-inspector.collapsed .wf-inspector-title {
  writing-mode: vertical-rl;
  text-orientation: mixed;
}

.wf-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.wf-canvas {
  flex: 1;
  min-width: 0;
  position: relative;
}

/* Vue Flow applies a grab cursor to every draggable node wrapper. Notes use
   their own small drag handle, so keep the rest of the note cursor neutral. */
.wf-canvas :deep(.vue-flow__node-note.draggable),
.wf-canvas :deep(.vue-flow__node-note.draggable.dragging) {
  cursor: default;
}

.wf-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 650;
  color: var(--text-secondary);
  white-space: nowrap;
  cursor: pointer;
  padding: 0 5px 0 3px;
}

.wf-toggle input,
.wf-menu-toggle input {
  appearance: none;
  position: relative;
  width: 28px;
  height: 16px;
  margin: 0;
  border: 1px solid rgba(111, 137, 168, 0.38);
  border-radius: 999px;
  background: rgba(111, 137, 168, 0.18);
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.wf-toggle input::after,
.wf-menu-toggle input::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--text-muted);
  transition: transform 0.15s ease, background 0.15s ease;
}

.wf-toggle input:checked,
.wf-menu-toggle input:checked {
  border-color: rgba(78, 205, 196, 0.6);
  background: rgba(78, 205, 196, 0.22);
}

.wf-toggle input:checked::after,
.wf-menu-toggle input:checked::after {
  background: var(--accent);
  transform: translateX(12px);
}

.wf-menu-toggle input:disabled { opacity: 0.4; cursor: default; }

.wf-context-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
}

.wf-context-menu {
  position: fixed;
  z-index: 41;
  min-width: 180px;
  background: var(--bg-darkest);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  padding: 4px;
  display: flex;
  flex-direction: column;
  max-height: min(70vh, 520px);
}

.wf-context-item {
  background: transparent;
  border: none;
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: 12px;
  text-align: left;
  padding: 7px 10px;
  cursor: pointer;
}

.wf-context-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text);
}

.wf-context-item:disabled {
  opacity: 0.4;
  cursor: default;
}

.wf-context-item.danger {
  color: #fda4af;
}

.wf-context-divider {
  height: 1px;
  margin: 4px 6px;
  background: var(--border);
}

.wf-context-heading {
  padding: 7px 10px 5px;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.wf-context-submenu summary {
  list-style: none;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 7px 10px;
  cursor: pointer;
}

.wf-context-submenu summary::-webkit-details-marker { display: none; }

.wf-context-replacements {
  display: flex;
  flex-direction: column;
  max-height: 240px;
  overflow-y: auto;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.wf-insert-palette {
  width: 250px;
  overflow-y: auto;
}

.wf-insert-palette small {
  color: var(--text-muted);
}

.wf-canvas-hint {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: var(--text-muted);
  font-size: 13px;
  pointer-events: none;
  opacity: 0.6;
}

.wf-panel-header {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--text-muted);
  padding: 10px 14px 6px;
}

.wf-panel-empty {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 14px;
  opacity: 0.7;
}

:deep(.wf-edge-control .vue-flow__edge-path) {
  stroke-dasharray: 5 4;
  opacity: 0.7;
}

:deep(.wf-edge-running .vue-flow__edge-path) { stroke: #38bdf8; }
:deep(.wf-edge-succeeded .vue-flow__edge-path) { stroke: rgba(52,211,153,.8); }
:deep(.wf-edge-failed .vue-flow__edge-path) { stroke: #fb7185; }
:deep(.wf-edge-cancelled .vue-flow__edge-path) { stroke: #f59e0b; }
:deep(.wf-edge-sample .vue-flow__edge-path) { stroke-dasharray: 3 4; }
:deep(.vue-flow__edge-text) { fill: var(--text-secondary); font-size: 9px; }
:deep(.vue-flow__edge-textbg) { fill: var(--bg-darkest); fill-opacity: .88; }

:deep(.vue-flow__minimap) {
  background: var(--bg-darkest);
  border: 1px solid var(--border);
  border-radius: 8px;
}
:deep(.vue-flow__minimap-node) { stroke: none; }

:deep(.vue-flow__controls) {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: none;
}
:deep(.vue-flow__controls-button) {
  background: var(--bg-darkest);
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
}
:deep(.vue-flow__controls-button:last-child) { border-bottom: none; }
:deep(.vue-flow__controls-button:hover) { background: rgba(255, 255, 255, 0.06); }
:deep(.vue-flow__controls-button svg) { fill: var(--text-secondary); }
</style>

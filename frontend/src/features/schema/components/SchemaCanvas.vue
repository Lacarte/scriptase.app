<script setup>
/**
 * Read-only workflow canvas (steps 1.2, 1.3).
 *
 * Nodes and edges arrive as props from the backend projection; this component
 * only decides where they sit on screen. It has no connect handles, no delete,
 * no palette and no run control, because a projection that could edit the graph
 * would be a second execution model — the one thing the project forbids.
 *
 * Navigation follows the prototype: drag the background to pan, two-finger
 * scroll to pan, Ctrl/pinch-wheel to zoom anchored on the cursor, drag a card
 * to reposition it, right-click to realign.
 *
 * Step 1.3: `nodeStates` and `flowingEdges` are how a running Job reaches the
 * picture. Both are derived from execution records upstream — this component
 * decides how a state *looks*, never what it is.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import NodeIcon from '@/shared/components/NodeIcon.vue'
import { NODE_H, NODE_W, edgePath, worldSize, zoomAt } from '../graph.js'
import { useSchemaCanvas } from '../composables/useSchemaCanvas.js'
import SchemaContextMenu from './SchemaContextMenu.vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  /** node_id → {status, visual} for the bound run (see ../live.js). */
  nodeStates: { type: Object, default: () => ({}) },
  /** Ids of the edges carrying work into an active node — those flow. */
  flowingEdges: { type: Object, default: () => new Set() },
  /** Card the inspector is open on. */
  selectedId: { type: String, default: '' },
  /** The run's live percent, shown on whatever is active. */
  percent: { type: Number, default: null },
})

const emit = defineEmits(['realign', 'select'])

const canvasEl = ref(null)

function viewport() {
  const el = canvasEl.value
  if (!el || typeof el.getBoundingClientRect !== 'function') return { width: 0, height: 0 }
  const box = el.getBoundingClientRect()
  return { width: box.width, height: box.height }
}

const nodesRef = computed(() => props.nodes)
const edgesRef = computed(() => props.edges)

const canvas = useSchemaCanvas({ nodes: nodesRef, edges: edgesRef, viewport })
const { positions, view } = canvas

const world = computed(() => worldSize(positions.value))

const worldStyle = computed(() => ({
  width: `${world.value.width}px`,
  height: `${world.value.height}px`,
  transform: `translate(${view.value.panX}px, ${view.value.panY}px) scale(${view.value.zoom})`,
}))

const edgeGeometry = computed(() => props.edges.map((edge) => ({
  id: edge.id,
  edgeType: edge.edgeType,
  flowing: props.flowingEdges?.has?.(edge.id) || false,
  d: edgePath(positions.value[edge.source], positions.value[edge.target]),
})))

function nodeStyle(node) {
  const point = positions.value[node.id] || { x: 0, y: 0 }
  return {
    left: `${point.x}px`,
    top: `${point.y}px`,
    width: `${NODE_W}px`,
    minHeight: `${NODE_H}px`,
    '--ac': node.accent,
  }
}

/** `pending` before a run is bound, so an unbound graph is not painted live. */
function nodeVisual(node) {
  return props.nodeStates?.[node.id]?.visual || 'pending'
}

/**
 * The live percent belongs to the run, not to the card — the engine records
 * per-node status, not per-node progress. An active card shows it because an
 * active card is what the run is currently doing.
 */
function nodePercent(node) {
  if (!Number.isFinite(props.percent)) return null
  return nodeVisual(node) === 'active' ? `${props.percent}%` : null
}

// ---------------------------------------------------------------------------
// Pan / drag
// ---------------------------------------------------------------------------

let panDrag = null
let nodeDrag = null
const panning = ref(false)
const draggingId = ref('')

/**
 * Below this, a mouse-up is a click rather than a drag. Without it, the two
 * pixels of travel in an ordinary click would swallow every card selection.
 */
const CLICK_SLOP = 4

function onCanvasDown(event) {
  if (event.button !== 0) return
  if (event.target.closest('.sch-node, .sch-legend, .ctx-menu')) return
  cancelOpeningFit()
  panDrag = {
    x: event.clientX,
    y: event.clientY,
    panX: view.value.panX,
    panY: view.value.panY,
    moved: false,
  }
  panning.value = true
}

function onNodeDown(nodeId, event) {
  // Left-drag repositions; right-click is the realign menu.
  if (event.button !== 0) return
  event.stopPropagation()
  cancelOpeningFit()
  const point = positions.value[nodeId]
  if (!point) return
  nodeDrag = {
    id: nodeId,
    x: event.clientX,
    y: event.clientY,
    ox: point.x,
    oy: point.y,
    moved: false,
  }
  draggingId.value = nodeId
}

function travelled(drag, event) {
  return Math.abs(event.clientX - drag.x) > CLICK_SLOP
    || Math.abs(event.clientY - drag.y) > CLICK_SLOP
}

function onWindowMove(event) {
  if (nodeDrag) {
    if (travelled(nodeDrag, event)) nodeDrag.moved = true
    const dx = (event.clientX - nodeDrag.x) / view.value.zoom
    const dy = (event.clientY - nodeDrag.y) / view.value.zoom
    canvas.moveNode(nodeDrag.id, Math.max(0, nodeDrag.ox + dx), Math.max(0, nodeDrag.oy + dy))
    return
  }
  if (panDrag) {
    if (travelled(panDrag, event)) panDrag.moved = true
    canvas.setView({
      zoom: view.value.zoom,
      panX: panDrag.panX + (event.clientX - panDrag.x),
      panY: panDrag.panY + (event.clientY - panDrag.y),
    })
  }
}

function onWindowUp() {
  // A card that was pressed and not dragged was clicked: open its panel.
  // Pressing the background the same way closes it again.
  if (nodeDrag && !nodeDrag.moved) emit('select', nodeDrag.id)
  else if (panDrag && !panDrag.moved) emit('select', '')
  panDrag = null
  nodeDrag = null
  panning.value = false
  draggingId.value = ''
}

/** Keyboard equivalent of clicking a card. */
function onNodeKey(nodeId, event) {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  emit('select', props.selectedId === nodeId ? '' : nodeId)
}

function onWheel(event) {
  event.preventDefault()
  cancelOpeningFit()
  const el = canvasEl.value
  const box = el?.getBoundingClientRect?.() || { left: 0, top: 0 }
  if (event.ctrlKey || event.metaKey) {
    // Trackpad pinch arrives as ctrl+wheel. Anchor on the cursor so the point
    // under the pointer stays put.
    canvas.setView(zoomAt(
      view.value,
      Math.exp(-event.deltaY * 0.01),
      event.clientX - box.left,
      event.clientY - box.top,
    ))
    return
  }
  // Two-finger scroll pans. Shift makes a vertical-only wheel scroll sideways.
  if (event.shiftKey && !event.deltaX) canvas.panBy(-event.deltaY, 0)
  else canvas.panBy(-event.deltaX, -event.deltaY)
}

/**
 * The opening fit waits a frame, because nothing has a box on the first tick.
 * Any navigation inside that frame cancels it: an automatic framing must never
 * yank the view back from someone already driving it.
 */
let openingFit = 0

function cancelOpeningFit() {
  if (!openingFit) return
  cancelAnimationFrame(openingFit)
  openingFit = 0
}

onMounted(() => {
  window.addEventListener('mousemove', onWindowMove)
  window.addEventListener('mouseup', onWindowUp)
  openingFit = requestAnimationFrame(() => {
    openingFit = 0
    canvas.fit()
  })
})

onBeforeUnmount(() => {
  cancelOpeningFit()
  window.removeEventListener('mousemove', onWindowMove)
  window.removeEventListener('mouseup', onWindowUp)
})

// ---------------------------------------------------------------------------
// Realign menu
// ---------------------------------------------------------------------------

const menu = ref({ open: false, x: 0, y: 0, node: null })

function openMenu(event, node) {
  event.preventDefault()
  event.stopPropagation()
  menu.value = { open: true, x: event.clientX, y: event.clientY, node }
}

function closeMenu() {
  menu.value = { ...menu.value, open: false, node: null }
}

const REALIGN_MESSAGES = {
  'auto-align': 'Auto-aligned layout',
  'snap-grid': 'Snapped to grid',
  'reset-layout': 'Positions reset',
  'reset-node': 'Node position reset',
  'center-node': 'Centred on node',
  fit: 'View fitted',
}

function onMenuSelect({ action, nodeId }) {
  if (action === 'auto-align') canvas.autoAlign()
  else if (action === 'snap-grid') canvas.snapAll()
  else if (action === 'reset-layout') canvas.resetLayout()
  else if (action === 'reset-node') canvas.resetNode(nodeId)
  else if (action === 'center-node') canvas.centerNode(nodeId)
  else if (action === 'fit') canvas.fit()
  else return
  emit('realign', { action, message: REALIGN_MESSAGES[action] })
}

defineExpose({
  // The topbar drives these, and driving them means the opening fit has been
  // overtaken.
  fit: () => {
    cancelOpeningFit()
    canvas.fit()
  },
  zoomStep: (direction) => {
    cancelOpeningFit()
    canvas.zoomStep(direction)
  },
  autoAlign: canvas.autoAlign,
  snapAll: canvas.snapAll,
  resetLayout: canvas.resetLayout,
  centerNode: canvas.centerNode,
  positions,
  view,
  onMenuSelect,
})
</script>

<template>
  <div
    ref="canvasEl"
    class="sch-canvas"
    :class="{ grabbing: panning, 'node-grabbing': Boolean(draggingId) }"
    @mousedown="onCanvasDown"
    @wheel="onWheel"
    @contextmenu="openMenu($event, null)"
  >
    <div class="sch-world" :style="worldStyle">
      <svg
        class="sch-edges"
        :viewBox="`0 0 ${world.width} ${world.height}`"
        :width="world.width"
        :height="world.height"
        aria-hidden="true"
      >
        <path
          v-for="edge in edgeGeometry"
          :key="edge.id"
          class="sch-edge"
          :class="{ 'e-control': edge.edgeType === 'control', flowing: edge.flowing }"
          :data-edge-id="edge.id"
          :d="edge.d"
        />
      </svg>

      <div class="sch-nodes" role="listbox" aria-label="Workflow nodes">
        <div
          v-for="node in nodes"
          :key="node.id"
          class="sch-node"
          :class="[
            `role-${node.role}`,
            `vis-${nodeVisual(node)}`,
            {
              dragging: draggingId === node.id,
              disabled: node.disabled,
              selected: selectedId === node.id,
            },
          ]"
          role="option"
          tabindex="0"
          :aria-selected="String(selectedId === node.id)"
          :data-node-id="node.id"
          :data-stage="node.stageKey || ''"
          :data-visual="nodeVisual(node)"
          :style="nodeStyle(node)"
          :title="`${node.name} · ${node.subtitle}`"
          @mousedown="onNodeDown(node.id, $event)"
          @keydown="onNodeKey(node.id, $event)"
          @contextmenu="openMenu($event, node)"
        >
          <span class="sch-ic"><NodeIcon :icon="node.icon" /></span>
          <span class="sch-nt">
            <span class="nm">{{ node.name }}</span>
            <span class="sb">{{ node.subtitle }}</span>
          </span>
          <span v-if="nodePercent(node)" class="sch-pct">{{ nodePercent(node) }}</span>
          <span class="sch-io in" aria-hidden="true" />
          <span class="sch-io out" aria-hidden="true" />
        </div>
      </div>
    </div>

    <div class="sch-legend">
      <span class="sl"><span class="sd d-stage" /> Stage</span>
      <span class="sl"><span class="sd d-flow" /> Infrastructure</span>
      <span class="sl">{{ nodes.length }} nodes · {{ edges.length }} edges</span>
    </div>

    <SchemaContextMenu
      :open="menu.open"
      :x="menu.x"
      :y="menu.y"
      :node="menu.node"
      @select="onMenuSelect"
      @close="closeMenu"
    />
  </div>
</template>

<style scoped>
.sch-canvas {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  cursor: grab;
  background:
    radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.045) 1px, transparent 0) 0 0 / 26px 26px,
    var(--bg);
}

.sch-canvas.grabbing,
.sch-canvas.node-grabbing {
  cursor: grabbing;
}

.sch-world {
  position: absolute;
  top: 40px;
  left: 40px;
  transform-origin: 0 0;
}

.sch-edges {
  position: absolute;
  top: 0;
  left: 0;
  overflow: visible;
  pointer-events: none;
}

.sch-edge {
  fill: none;
  stroke: var(--line);
  stroke-width: 1.5;
  transition: stroke 0.3s;
}

.sch-edge.e-control {
  stroke-dasharray: 3 4;
}

/* Work arriving at whatever is running now. The dash flows towards the
   active card, which is the direction the data is going. */
.sch-edge.flowing {
  stroke: var(--run);
  stroke-width: 2;
  stroke-dasharray: 6 6;
  animation: sch-flow 0.9s linear infinite;
}

@keyframes sch-flow {
  to { stroke-dashoffset: -12; }
}

.sch-nodes {
  position: absolute;
  top: 0;
  left: 0;
}

.sch-node {
  position: absolute;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 50%), var(--panel);
  box-shadow: 0 4px 14px -8px rgba(0, 0, 0, 0.6);
  cursor: grab;
  user-select: none;
  transition: border-color 0.25s, box-shadow 0.25s, transform 0.12s, opacity 0.25s;
}

.sch-node:hover {
  border-color: var(--accent-line);
}

.sch-node:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--accent), 0 4px 14px -8px rgba(0, 0, 0, 0.6);
}

/* ---- The running Job, reflected (step 1.3) ---------------------------- */

/* Not reached yet. Dim rather than hidden — the shape of what is coming is
   part of what makes a running graph readable. */
.sch-node.vis-pending {
  opacity: 0.5;
}

.sch-node.vis-active {
  border-color: var(--run-line);
  box-shadow: 0 0 0 1px var(--run-line), 0 0 22px -4px var(--run);
  animation: sch-glow 1.6s ease-in-out infinite;
}

.sch-node.vis-done {
  border-color: var(--ok-line);
}

.sch-node.vis-failed {
  border-color: var(--fail-line);
  box-shadow: 0 0 0 1px var(--fail-line), 0 0 18px -6px var(--fail);
}

/* Waiting on a person, not on a worker. */
.sch-node.vis-blocked {
  border-color: var(--sched-line);
}

/* Deliberately not run. Struck through says "this did not happen" in a way
   that dimming alone does not. */
.sch-node.vis-skipped {
  border-style: dashed;
  border-color: var(--line);
  opacity: 0.55;
}

.sch-node.vis-skipped .nm {
  text-decoration: line-through;
  color: var(--muted);
}

@keyframes sch-glow {
  0%, 100% { box-shadow: 0 0 0 1px var(--run-line), 0 0 22px -4px var(--run); }
  50% { box-shadow: 0 0 0 1px var(--run-line), 0 0 10px -6px var(--run); }
}

/* The card the inspector is open on. */
.sch-node.selected {
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 2px var(--accent), 0 8px 22px -10px rgba(0, 0, 0, 0.7);
}

.sch-pct {
  flex: none;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--run);
}

.sch-node.dragging {
  z-index: 30;
  cursor: grabbing;
  box-shadow: 0 10px 28px -8px rgba(0, 0, 0, 0.8), 0 0 0 1px var(--accent);
  transition: none;
}

/* Infrastructure — trigger, project setup, workflow output. Real graph
   members that the Production spine deliberately does not name as a step. */
.sch-node.role-flow {
  border-style: dashed;
}

.sch-node.role-flow .sch-ic {
  border-radius: 50%;
}

.sch-node.disabled {
  opacity: 0.5;
}

.sch-ic {
  display: grid;
  flex: none;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: color-mix(in srgb, var(--ac) 18%, transparent);
  color: var(--ac);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ac) 35%, transparent);
}

.sch-ic :deep(svg) {
  width: 14px;
  height: 14px;
}

.sch-nt {
  display: block;
  flex: 1;
  min-width: 0;
}

.sch-nt .nm,
.sch-nt .sb {
  display: block;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.sch-nt .nm {
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
  color: var(--text);
}

.sch-nt .sb {
  margin-top: 1px;
  font-family: var(--mono);
  font-size: 8.5px;
  color: var(--muted);
}

.sch-io {
  position: absolute;
  top: 50%;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--line);
  box-shadow: 0 0 0 2px var(--bg);
  transform: translateY(-50%);
}

.sch-io.in { left: -4px; }
.sch-io.out { right: -4px; }

.sch-legend {
  position: absolute;
  bottom: 14px;
  left: 16px;
  z-index: 6;
  display: flex;
  gap: 14px;
  padding: 8px 13px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: rgba(10, 13, 18, 0.85);
  backdrop-filter: blur(6px);
}

.sch-legend .sl {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
}

.sch-legend .sd {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.sch-legend .d-stage { background: var(--accent); }
.sch-legend .d-flow { background: var(--faint); }

/* Step 0.3: nothing loops for someone who asked for no motion. The state is
   still legible — colour, border and the struck-through name carry it — so
   only the animation goes, never the information. */
@media (prefers-reduced-motion: reduce) {
  .sch-edge.flowing,
  .sch-node.vis-active {
    animation: none;
  }
}

@media (max-width: 820px) {
  .sch-legend {
    gap: 10px;
    padding: 6px 10px;
  }
}
</style>

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
 * Step 1.3: `nodeStates` is how a running Job reaches the picture. It is
 * derived from execution records upstream — this component decides how a state
 * *looks*, never what it is.
 *
 * Step 6.6 ports the prototype's `sch-*` family: cards by role, the five `s-*`
 * status treatments with their corner pill, the `e-*` edge states, and the
 * animation on the one edge that is actually carrying work.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import NodeIcon from '@/shared/components/NodeIcon.vue'
import { edgePath, worldSize, zoomAt } from '../graph.js'
import { edgeStateClasses, stateBadge, stateClass } from '../live.js'
import { useSchemaCanvas } from '../composables/useSchemaCanvas.js'
import SchemaContextMenu from './SchemaContextMenu.vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  /** node_id → {status, visual, error} for the bound run (see ../live.js). */
  nodeStates: { type: Object, default: () => ({}) },
  /** Card the inspector is open on. */
  selectedId: { type: String, default: '' },
  /** The run's live percent, shown on whatever is active. */
  percent: { type: Number, default: null },
  /** False when no run is being watched — that is `s-idle`, not `s-pending`. */
  bound: { type: Boolean, default: false },
})

const emit = defineEmits(['realign', 'select'])

const canvasEl = ref(null)
const flashId = ref('')
let flashTimer = 0

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

const edgeClasses = computed(() => edgeStateClasses(props.edges, props.nodeStates))

const edgeGeometry = computed(() => props.edges.map((edge) => ({
  id: edge.id,
  edgeType: edge.edgeType,
  state: edgeClasses.value[edge.id] || '',
  d: edgePath(positions.value[edge.source], positions.value[edge.target]),
})))

/**
 * Position and category accent only. The card's box is the prototype's
 * `.sch-node` rule, which `NODE_W`/`NODE_H` mirror for the edge geometry —
 * setting it here as well would be a second copy free to drift from it.
 */
function nodeStyle(node) {
  const point = positions.value[node.id] || { x: 0, y: 0 }
  return {
    left: `${point.x}px`,
    top: `${point.y}px`,
    '--ac': node.accent,
  }
}

/** `pending` before a run is bound, so an unbound graph is not painted live. */
function nodeVisual(node) {
  return props.nodeStates?.[node.id]?.visual || 'pending'
}

/**
 * The corner pill: the run's percent while active, then the prototype's glyph
 * for whatever the node settled as. Empty for every other state, and the pill
 * is `display: none` until it is not.
 */
function nodeBadge(node) {
  return stateBadge(nodeVisual(node), props.percent)
}

/** The narration settings the TTS card shows at a glance, as two tags. */
function narration(node) {
  const settings = node.narrationProcessing
  if (!settings) return null
  return {
    trim: settings.removeSilence === true,
    // 1× is the absence of a setting, and the prototype chips nothing for it.
    speed: Number(settings.speed) === 1 ? '' : `${Number(settings.speed).toLocaleString('en-US', {
      maximumFractionDigits: 2,
    })}×`,
    inherited: Boolean(settings.inherited),
  }
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
  if (flashTimer) clearTimeout(flashTimer)
  window.removeEventListener('mousemove', onWindowMove)
  window.removeEventListener('mouseup', onWindowUp)
})

/** Centre and briefly pulse a card, used by both Locate and the error badge. */
function locateNode(nodeId) {
  if (!positions.value[nodeId]) return
  cancelOpeningFit()
  canvas.centerNode(nodeId)
  flashId.value = nodeId
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => { flashId.value = '' }, 1200)
}

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
  locateNode,
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
          :class="[edge.state, { 'e-control': edge.edgeType === 'control' }]"
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
            stateClass(nodeVisual(node), bound),
            {
              dragging: draggingId === node.id,
              disabled: node.disabled,
              picked: selectedId === node.id,
              flash: flashId === node.id,
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

          <span class="sch-io in" aria-hidden="true" />
          <span class="sch-io out" aria-hidden="true" />

          <span class="sch-state" :class="stateClass(nodeVisual(node), bound)">
            {{ nodeBadge(node) }}
          </span>

          <span v-if="narration(node)" class="sch-tags">
            <span
              v-if="narration(node).trim"
              class="sch-tag"
              :title="`Silence removed${narration(node).inherited ? ' · inherited' : ''}`"
            >
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true">
                <path d="M4 12h6l3-7 3 14 2-7h2" />
              </svg>
            </span>
            <span
              v-if="narration(node).speed"
              class="sch-tag chip"
              :title="`Narration speed${narration(node).inherited ? ' · inherited' : ''}`"
            >{{ narration(node).speed }}</span>
          </span>

          <!-- The prototype tooltips only the card that failed, and says the
               engine's code and message — never assembled prose. -->
          <span
            class="sch-node-err"
            :class="{ show: nodeVisual(node) === 'failed' }"
            role="tooltip"
          >
            <template v-if="nodeVisual(node) === 'failed'">
              <span class="ne-h">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
                  <circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" />
                </svg>
                Error · {{ node.name }}
              </span>
              <span class="ne-msg">{{ nodeStates[node.id]?.error?.message || 'The node failed.' }}</span>
              <span v-if="nodeStates[node.id]?.error?.code" class="ne-code">
                {{ nodeStates[node.id].error.code }}
              </span>
            </template>
          </span>
        </div>
      </div>
    </div>

    <div class="sch-legend">
      <span class="sl"><span class="sd d-pending" /> Pending</span>
      <span class="sl"><span class="sd d-active" /> Active</span>
      <span class="sl"><span class="sd d-done" /> Done</span>
      <span class="sl"><span class="sd d-failed" /> Failed</span>
      <span class="sl"><span class="sd d-skip" /> Skipped</span>
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

/* Control-only wiring, which carries no payload. App-only: the prototype's
   one graph has no control edges to distinguish. */
.sch-edge.e-control {
  stroke-dasharray: 3 4;
}

/* Work has crossed this edge. */
.sch-edge.e-done {
  stroke: rgba(63, 182, 139, 0.55);
}

/* Work is crossing it right now. The dash flows towards the active card,
   which is the direction the data is going. */
.sch-edge.e-active {
  stroke: var(--run);
  stroke-width: 2;
  stroke-dasharray: 5 5;
  animation: schflow 0.6s linear infinite;
}

.sch-edge.e-fail {
  stroke: rgba(240, 97, 109, 0.5);
}

@keyframes schflow {
  to { stroke-dashoffset: -20; }
}

.sch-nodes {
  position: absolute;
  top: 0;
  left: 0;
}

.sch-node {
  position: absolute;
  box-sizing: border-box;
  width: 150px;
  min-height: 48px;
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

.sch-node.dragging {
  z-index: 30;
  cursor: grabbing;
  box-shadow: 0 10px 28px -8px rgba(0, 0, 0, 0.8), 0 0 0 1px var(--accent);
  transition: none;
}

/* ---- Role ------------------------------------------------------------- */

/* Routes control down one of several paths, so its outline is provisional. */
.sch-node.role-branch {
  border-style: dashed;
}

/* Infrastructure — trigger, project setup, workflow output. Real graph
   members that the Production spine deliberately does not name as a step;
   the round icon plate is what says so. */
.sch-node.role-flow .sch-ic {
  border-radius: 50%;
}

.sch-node.disabled {
  opacity: 0.5;
}

/* ---- The running Job, reflected (steps 1.3, 6.6) ---------------------- */

/* Not reached yet. Dim rather than hidden — the shape of what is coming is
   part of what makes a running graph readable. `s-idle` is the quieter of
   the two: nothing is being watched at all. */
.sch-node.s-pending { opacity: 0.5; }
.sch-node.s-idle { opacity: 0.85; }

.sch-node.s-done {
  border-color: rgba(63, 182, 139, 0.45);
}

.sch-node.s-done .sch-io.in,
.sch-node.s-done .sch-io.out {
  background: var(--ok);
}

.sch-node.s-active {
  border-color: var(--run);
  box-shadow: 0 0 0 1px var(--run), 0 0 22px -4px rgba(88, 166, 255, 0.6);
  transform: translateY(-1px);
  animation: schpulse 1.8s infinite;
}

.sch-node.s-active .sch-ic {
  background: var(--run-dim);
  color: var(--run);
  box-shadow: inset 0 0 0 1px var(--run);
}

@keyframes schpulse {
  0%, 100% { box-shadow: 0 0 0 1px var(--run), 0 0 22px -6px rgba(88, 166, 255, 0.5); }
  50% { box-shadow: 0 0 0 1px var(--run), 0 0 28px -2px rgba(88, 166, 255, 0.85); }
}

.sch-node.s-failed {
  z-index: 4;
  border-color: var(--fail);
  box-shadow: 0 0 0 1px var(--fail), 0 0 20px -6px rgba(240, 97, 109, 0.6);
}

.sch-node.s-failed .sch-ic {
  background: var(--fail-dim);
  color: var(--fail);
  box-shadow: inset 0 0 0 1px var(--fail);
}

/* Deliberately not run. Struck through says "this did not happen" in a way
   that dimming alone does not. */
.sch-node.s-skip {
  opacity: 0.4;
  border-style: dashed;
}

.sch-node.s-skip .sch-nt .nm {
  text-decoration: line-through;
}

/* App-only: waiting on a person, not on a worker. The prototype has no
   approval gate, so there is no rule of its to port. */
.sch-node.s-blocked {
  border-color: var(--sched-line);
}

.sch-node.flash {
  animation: schflash 1.2s ease;
}

@keyframes schflash {
  0%, 100% { box-shadow: 0 0 0 1px var(--fail); }
  30% { box-shadow: 0 0 0 3px var(--fail), 0 0 30px 2px rgba(240, 97, 109, 0.7); }
}

/* The card the inspector is open on. */
.sch-node.picked {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent), 0 8px 22px -8px rgba(106, 140, 255, 0.6);
}

/* ---- Corner status pill ------------------------------------------------ */

.sch-state {
  position: absolute;
  top: -8px;
  right: -8px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  display: none;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 0 2px var(--bg);
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 700;
}

.sch-state.s-active,
.sch-state.s-done,
.sch-state.s-failed,
.sch-state.s-skip {
  display: inline-flex;
}

.sch-state.s-done {
  background: var(--ok-dim);
  color: var(--ok);
  box-shadow: 0 0 0 2px var(--bg), inset 0 0 0 1px rgba(63, 182, 139, 0.4);
}

.sch-state.s-active {
  background: var(--run-dim);
  color: var(--run);
  box-shadow: 0 0 0 2px var(--bg), inset 0 0 0 1px rgba(88, 166, 255, 0.5);
}

.sch-state.s-failed {
  background: var(--fail-dim);
  color: var(--fail);
  box-shadow: 0 0 0 2px var(--bg), inset 0 0 0 1px rgba(240, 97, 109, 0.5);
}

.sch-state.s-skip {
  background: var(--bg-2);
  color: var(--muted);
  box-shadow: 0 0 0 2px var(--bg), inset 0 0 0 1px var(--line);
  font-size: 8px;
}

/* ---- Per-node parameter tags (narration processing) -------------------- */

.sch-tags {
  position: absolute;
  bottom: -9px;
  left: 10px;
  z-index: 3;
  display: flex;
  gap: 4px;
}

.sch-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 16px;
  padding: 0 5px;
  border-radius: 5px;
  background: var(--panel-2);
  box-shadow: 0 0 0 2px var(--bg), inset 0 0 0 1px rgba(106, 140, 255, 0.4);
  color: var(--accent);
  font-family: var(--mono);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.2px;
}

.sch-tag svg { display: block; }

.sch-tag.chip {
  color: var(--warn);
  box-shadow: 0 0 0 2px var(--bg), inset 0 0 0 1px rgba(240, 173, 75, 0.45);
}

/* ---- Inline error tooltip on the failing card -------------------------- */

.sch-node-err {
  display: none;
  position: absolute;
  top: calc(100% + 10px);
  left: 50%;
  z-index: 20;
  width: 210px;
  padding: 9px 11px;
  border: 1px solid rgba(240, 97, 109, 0.45);
  border-radius: 8px;
  background: #0a0e13;
  box-shadow: 0 12px 30px -10px rgba(0, 0, 0, 0.8);
  transform: translateX(-50%);
  pointer-events: none;
}

.sch-node-err.show { display: block; }

.sch-node-err::before {
  content: "";
  position: absolute;
  bottom: 100%;
  left: 50%;
  border: 6px solid transparent;
  border-bottom-color: rgba(240, 97, 109, 0.45);
  transform: translateX(-50%);
}

.sch-node-err .ne-h {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  color: var(--fail);
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.sch-node-err .ne-msg {
  display: block;
  color: var(--fail-text);
  font-size: 11px;
  line-height: 1.45;
}

.sch-node-err .ne-code {
  display: block;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(240, 97, 109, 0.25);
  color: var(--fail);
  font-family: var(--mono);
  font-size: 9.5px;
  word-break: break-word;
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

.sch-legend .d-pending { background: var(--faint); }
.sch-legend .d-active { background: var(--run); }
.sch-legend .d-done { background: var(--ok); }
.sch-legend .d-failed { background: var(--fail); }
.sch-legend .d-skip { background: var(--muted); }

/* Step 0.3: nothing loops for someone who asked for no motion. The state is
   still legible — colour, border and the struck-through name carry it — so
   only the animation goes, never the information. */
@media (prefers-reduced-motion: reduce) {
  .sch-edge.e-active,
  .sch-node.s-active,
  .sch-node.flash {
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

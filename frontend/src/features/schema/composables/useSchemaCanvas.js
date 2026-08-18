/**
 * Cosmetic canvas state for the Schema view (step 1.2): where each card sits
 * and where the viewport is looking.
 *
 * Everything here is presentation. `positions` seeds from the workflow's
 * authored coordinates and never travels back to the backend, so dragging a
 * card or auto-aligning the whole graph changes the picture and nothing else.
 * Structure — which nodes exist and how they wire — is owned by
 * `useSchemaGraph` and is not editable from this view at all.
 */

import { ref, watch } from 'vue'

import {
  DEFAULT_VIEW,
  autoLayoutPositions,
  centerOnNode,
  clampZoom,
  fitView,
  homePositions,
  snapPositions,
  zoomAt,
} from '../graph.js'

const ZOOM_STEP = 0.15

/**
 * @param {object}   options
 * @param {import('vue').Ref<object[]>} options.nodes
 * @param {import('vue').Ref<object[]>} options.edges
 * @param {() => {width: number, height: number}} options.viewport
 *   Canvas client box. Injectable so the geometry is testable without layout.
 */
export function useSchemaCanvas({ nodes, edges, viewport }) {
  /** node_id → {x, y} currently drawn. */
  const positions = ref({})
  /** The authored layout "Reset positions" restores. */
  const home = ref({})
  const view = ref({ ...DEFAULT_VIEW })

  const measure = viewport || (() => ({ width: 0, height: 0 }))

  /**
   * Re-seed when the graph itself changes. Keyed on the node id list rather
   * than the array identity: a re-render of the same graph must not throw away
   * a layout the user just arranged.
   */
  watch(
    () => (nodes.value || []).map((node) => node.id).join('\u0000'),
    () => {
      home.value = homePositions(nodes.value || [])
      positions.value = { ...home.value }
      // A different graph would otherwise inherit the previous one's camera
      // and open somewhere off-screen.
      fit()
    },
    { immediate: true },
  )

  function setPositions(next) {
    positions.value = next
  }

  function moveNode(id, x, y) {
    if (!(id in positions.value)) return
    positions.value = {
      ...positions.value,
      [id]: { x: Math.round(x), y: Math.round(y) },
    }
  }

  // ---- Realign -----------------------------------------------------------

  function autoAlign() {
    setPositions(autoLayoutPositions(nodes.value || [], edges.value || []))
    fit()
  }

  function snapAll() {
    setPositions(snapPositions(positions.value))
  }

  function resetLayout() {
    setPositions({ ...home.value })
    fit()
  }

  function resetNode(id) {
    const origin = home.value[id]
    if (!origin) return
    positions.value = { ...positions.value, [id]: { ...origin } }
  }

  // ---- Navigate ----------------------------------------------------------

  function fit() {
    view.value = fitView(positions.value, measure())
  }

  function centerNode(id) {
    const point = positions.value[id]
    if (!point) return
    view.value = centerOnNode(point, measure(), view.value.zoom)
  }

  /**
   * Zoom the topbar buttons drive. Anchored on the middle of the canvas
   * through the same helper the cursor-anchored wheel uses, so the two cannot
   * drift apart on the world inset.
   */
  function zoomStep(direction) {
    const box = measure()
    const zoom = clampZoom(view.value.zoom + direction * ZOOM_STEP)
    if (zoom === view.value.zoom) return
    view.value = zoomAt(view.value, zoom / view.value.zoom, box.width / 2, box.height / 2)
  }

  function setView(next) {
    view.value = {
      zoom: clampZoom(next?.zoom),
      panX: Number.isFinite(next?.panX) ? next.panX : view.value.panX,
      panY: Number.isFinite(next?.panY) ? next.panY : view.value.panY,
    }
  }

  function panBy(dx, dy) {
    view.value = {
      ...view.value,
      panX: view.value.panX + dx,
      panY: view.value.panY + dy,
    }
  }

  return {
    positions,
    home,
    view,
    moveNode,
    autoAlign,
    snapAll,
    resetLayout,
    resetNode,
    fit,
    centerNode,
    zoomStep,
    setView,
    panBy,
  }
}

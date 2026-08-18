/**
 * Schema graph model and canvas geometry (step 1.2) — pure functions, no Vue.
 *
 * Two rules shape this module:
 *
 * 1. **Structure is backend truth.** `buildSchemaGraph` only ever reshapes what
 *    the node registry, the workflow document and the stage projection already
 *    said. There is no node list, edge list or stage list authored here, and a
 *    node type this file has never heard of still renders.
 * 2. **Positions are cosmetic.** Every layout helper returns a fresh
 *    `{id: {x, y}}` map that the canvas holds in component state. Nothing is
 *    written back to the workflow, so realigning the view cannot change what
 *    the engine runs.
 */

import dagre from '@dagrejs/dagre'

/** Node card box, matching the prototype's `.sch-node`. */
export const NODE_W = 150
export const NODE_H = 48

/** Realign grid, and the canvas dot-grid it lines up with. */
export const GRID = 20

/** `.sch-world` sits inset from the canvas corner; pan is measured from there. */
export const WORLD_INSET = 40

export const MIN_ZOOM = 0.4
export const MAX_ZOOM = 1.8

/** Padding kept around the graph when fitting it to the viewport. */
const FIT_PADDING = 48

/** Category colour for a node whose category the registry does not describe. */
const FALLBACK_ACCENT = '#9CA3AF'

export const DEFAULT_VIEW = Object.freeze({ zoom: 1, panX: 0, panY: 0 })

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

/**
 * node_id → the stage projection row that claims it.
 *
 * Nodes absent from every stage are infrastructure (trigger, project setup,
 * workflow output): real graph members that the Production spine deliberately
 * does not name as a step.
 *
 * @param {object} projection  StageProjection document (contracts §10)
 * @returns {Record<string, {key: string, label: string, ordinal: number}>}
 */
export function stageIndexByNode(projection) {
  const index = {}
  for (const stage of projection?.stages || []) {
    for (const nodeId of stage?.node_ids || []) {
      if (typeof nodeId === 'string' && nodeId && !(nodeId in index)) {
        index[nodeId] = {
          key: stage.key,
          label: stage.label,
          ordinal: stage.ordinal,
        }
      }
    }
  }
  return index
}

function finite(value, fallback = 0) {
  return Number.isFinite(value) ? value : fallback
}

/**
 * The provider domain a node picks an instance from, or `''` for a node that
 * runs locally (step 1.4).
 *
 * Read off the registry's own provider field, which the engine generates from
 * a domain id alone. A stage-key → domain table here would be a second catalog
 * to keep in step with the engine's, and would have to name stages this
 * feature is forbidden to know.
 *
 * @param {object} definition  one entry of the registry's `node_types`
 * @returns {string}
 */
export function providerDomainOf(definition) {
  for (const field of definition?.config_schema || []) {
    if (field?.type === 'provider' && typeof field.provider_domain === 'string') {
      return field.provider_domain
    }
  }
  return ''
}

/**
 * True when the registry says this node routes control down one of several
 * paths (step 6.6).
 *
 * The prototype dashes such cards as `role-branch`. The signal is the
 * registry's own `conditional` output flag, so a branching node type added
 * tomorrow gets the treatment without this file learning its name — a list of
 * branching types here would be exactly the hardcoded node knowledge this
 * feature forbids.
 *
 * @param {object} definition  one entry of the registry's `node_types`
 */
export function branchesControl(definition) {
  return (definition?.outputs || []).some((output) => output?.conditional === true)
}

/** Resolved by backend orchestration and carried on the execution snapshot. */
export function narrationProcessingFor(workflow, node, providerDomain) {
  if (providerDomain !== 'tts') return null
  const stamped = workflow?.extensions?.narration_processing?.[node?.id]
  const config = node?.configuration || {}
  const source = stamped && typeof stamped === 'object' ? stamped : config
  const speed = Number(source.speed)
  return {
    removeSilence: source.remove_silence === true,
    speed: Number.isFinite(speed) && speed > 0 ? speed : 1,
    inherited: Boolean(stamped?.inherited),
  }
}

export function narrationBadge(settings) {
  if (!settings) return ''
  const silence = settings.removeSilence ? 'Trim' : 'Pauses'
  return `${silence} · ${Number(settings.speed).toLocaleString('en-US', {
    maximumFractionDigits: 2,
  })}×`
}

/**
 * Reshape backend truth into what the canvas draws.
 *
 * @param {object}   source
 * @param {object}   source.workflow    workflow document (`nodes`, `edges`)
 * @param {object}   source.registry    GET /api/workflow/node-types payload
 * @param {object}   [source.projection] StageProjection for the same workflow
 * @returns {{nodes: object[], edges: object[]}}
 */
export function buildSchemaGraph({ workflow, registry, projection } = {}) {
  const definitions = registry?.node_types || {}
  const categories = registry?.categories || {}
  const stages = stageIndexByNode(projection)

  const nodes = []
  for (const node of workflow?.nodes || []) {
    if (!node || typeof node.id !== 'string' || !node.id) continue
    const definition = definitions[node.type] || {}
    const category = definition.category || ''
    const stage = stages[node.id] || null
    const providerDomain = providerDomainOf(definition)
    const narrationProcessing = narrationProcessingFor(workflow, node, providerDomain)
    nodes.push({
      id: node.id,
      type: node.type || '',
      name: node.name || definition.display_name || node.type || node.id,
      // The one thing Schema knows that the workflow document does not: which
      // Production stage this node reports into.
      stageKey: stage ? stage.key : null,
      stageLabel: stage ? stage.label : null,
      // A node the projection never claims is graph infrastructure, not a
      // step. A node that routes control is a branch whichever of the two it
      // is, because that is what its card has to say.
      role: branchesControl(definition) ? 'branch' : (stage ? 'stage' : 'flow'),
      subtitle: stage ? stage.label : (categories[category]?.label || 'Infrastructure'),
      icon: definition.icon || '',
      accent: categories[category]?.color || FALLBACK_ACCENT,
      category,
      // What Test needs to ask for this node (step 1.4): the ports it takes
      // input on, and the domain a one-shot provider override would come from.
      // Both are the registry's answer, carried rather than restated.
      inputs: Array.isArray(definition.inputs) ? definition.inputs : [],
      providerDomain,
      narrationProcessing,
      narrationBadge: narrationBadge(narrationProcessing),
      disabled: Boolean(node.disabled),
      x: finite(node.position?.x),
      y: finite(node.position?.y),
    })
  }

  const known = new Set(nodes.map((node) => node.id))
  const edges = []
  for (const edge of workflow?.edges || []) {
    if (!edge) continue
    const source = edge.source_node
    const target = edge.target_node
    // An edge to a node the document does not contain would draw to nowhere.
    if (!known.has(source) || !known.has(target)) continue
    edges.push({
      id: edge.id || `${source}->${target}:${edge.source_port || ''}`,
      source,
      target,
      edgeType: edge.edge_type || 'data',
    })
  }

  return { nodes, edges }
}

/** The authored layout, which "Reset positions" restores. */
export function homePositions(nodes) {
  const positions = {}
  for (const node of nodes || []) {
    positions[node.id] = { x: finite(node.x), y: finite(node.y) }
  }
  return positions
}

// ---------------------------------------------------------------------------
// Realign
// ---------------------------------------------------------------------------

/**
 * Hierarchical left-to-right layout over the real edges.
 *
 * Same engine the workflow canvas tidies with, so the two views agree about
 * what "auto-align" means.
 */
export function autoLayoutPositions(nodes, edges) {
  if (!nodes?.length) return {}
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90, marginx: 0, marginy: 0 })
  graph.setDefaultEdgeLabel(() => ({}))
  for (const node of nodes) {
    graph.setNode(node.id, { width: NODE_W, height: NODE_H })
  }
  for (const edge of edges || []) {
    graph.setEdge(edge.source, edge.target)
  }
  dagre.layout(graph)

  const raw = {}
  let minX = Infinity
  let minY = Infinity
  for (const node of nodes) {
    const laid = graph.node(node.id)
    // dagre positions by centre; the canvas positions by top-left corner.
    const x = laid ? laid.x - NODE_W / 2 : 0
    const y = laid ? laid.y - NODE_H / 2 : 0
    raw[node.id] = { x, y }
    if (x < minX) minX = x
    if (y < minY) minY = y
  }
  if (!Number.isFinite(minX)) return {}

  // Normalise to the origin so the result never lands behind the world inset.
  const shifted = {}
  for (const [id, point] of Object.entries(raw)) {
    shifted[id] = { x: point.x - minX, y: point.y - minY }
  }
  return snapPositions(shifted)
}

/** Round every position onto the canvas grid. */
export function snapPositions(positions, grid = GRID) {
  const step = grid > 0 ? grid : GRID
  const snapped = {}
  for (const [id, point] of Object.entries(positions || {})) {
    // `|| 0` normalises the negative zero `Math.round` returns just below the
    // origin, which would otherwise leak into every position comparison.
    snapped[id] = {
      x: Math.round(finite(point?.x) / step) * step || 0,
      y: Math.round(finite(point?.y) / step) * step || 0,
    }
  }
  return snapped
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

/** Bounding box of the laid-out cards, in world coordinates. */
export function graphBounds(positions) {
  const points = Object.values(positions || {})
  if (!points.length) {
    return { minX: 0, minY: 0, maxX: 0, maxY: 0, width: 0, height: 0 }
  }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const point of points) {
    const x = finite(point?.x)
    const y = finite(point?.y)
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (x + NODE_W > maxX) maxX = x + NODE_W
    if (y + NODE_H > maxY) maxY = y + NODE_H
  }
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY }
}

/** World box the transform is applied to — drives the SVG viewBox. */
export function worldSize(positions) {
  const bounds = graphBounds(positions)
  return {
    width: Math.max(bounds.maxX + 120, 1),
    height: Math.max(bounds.maxY + 120, 1),
  }
}

export function clampZoom(zoom) {
  if (!Number.isFinite(zoom)) return 1
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom))
}

/**
 * Zoom the whole graph into view and centre it.
 *
 * @param {Record<string, {x: number, y: number}>} positions
 * @param {{width: number, height: number}} viewport  canvas client box
 */
export function fitView(positions, viewport) {
  const width = finite(viewport?.width)
  const height = finite(viewport?.height)
  const bounds = graphBounds(positions)
  if (!bounds.width || !bounds.height || width <= 0 || height <= 0) {
    return { ...DEFAULT_VIEW }
  }
  const zoom = clampZoom(Math.min(
    (width - FIT_PADDING * 2) / bounds.width,
    (height - FIT_PADDING * 2) / bounds.height,
    1,
  ))
  return centerOnPoint(
    { x: bounds.minX + bounds.width / 2, y: bounds.minY + bounds.height / 2 },
    viewport,
    zoom,
  )
}

/** Pan so a world point sits in the middle of the canvas. */
export function centerOnPoint(point, viewport, zoom) {
  const scale = clampZoom(zoom)
  return {
    zoom: scale,
    panX: finite(viewport?.width) / 2 - WORLD_INSET - finite(point?.x) * scale,
    panY: finite(viewport?.height) / 2 - WORLD_INSET - finite(point?.y) * scale,
  }
}

/** Pan so a node card sits in the middle of the canvas ("Center on node"). */
export function centerOnNode(position, viewport, zoom) {
  return centerOnPoint(
    { x: finite(position?.x) + NODE_W / 2, y: finite(position?.y) + NODE_H / 2 },
    viewport,
    zoom,
  )
}

/**
 * Zoom around a canvas-relative point, keeping the world point under the
 * cursor exactly where it was. This is what makes pinch and Ctrl+wheel feel
 * anchored rather than yanking the graph toward the origin.
 */
export function zoomAt(view, factor, cursorX, cursorY) {
  const from = clampZoom(view?.zoom)
  const to = clampZoom(from * finite(factor, 1))
  if (to === from) return { zoom: from, panX: finite(view?.panX), panY: finite(view?.panY) }
  const ratio = to / from
  const px = finite(cursorX) - WORLD_INSET
  const py = finite(cursorY) - WORLD_INSET
  return {
    zoom: to,
    panX: px - (px - finite(view?.panX)) * ratio,
    panY: py - (py - finite(view?.panY)) * ratio,
  }
}

/** Cubic bezier from one card's output edge to the next card's input edge. */
export function edgePath(from, to) {
  const x1 = finite(from?.x) + NODE_W
  const y1 = finite(from?.y) + NODE_H / 2
  const x2 = finite(to?.x)
  const y2 = finite(to?.y) + NODE_H / 2
  const bend = Math.max(40, (x2 - x1) * 0.5)
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`
}

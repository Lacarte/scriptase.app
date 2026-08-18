/**
 * Step 1.2 — the Schema graph, projected from the engine.
 *
 * This file owns the pure half: reshaping backend truth into cards and edges,
 * and the canvas geometry behind every realign and navigation action.
 *
 * Guards:
 * - Structure is whatever the registry / workflow / projection said, including
 *   node types this code has never seen
 * - Positions are cosmetic — the layout helpers return new maps and never
 *   touch the workflow document
 * - Zoom stays anchored on the cursor, which is the whole point of `zoomAt`
 */
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_VIEW,
  MAX_ZOOM,
  MIN_ZOOM,
  NODE_H,
  NODE_W,
  WORLD_INSET,
  autoLayoutPositions,
  buildSchemaGraph,
  centerOnNode,
  clampZoom,
  edgePath,
  fitView,
  graphBounds,
  homePositions,
  narrationBadge,
  narrationProcessingFor,
  snapPositions,
  stageIndexByNode,
  worldSize,
  zoomAt,
} from '../graph.js'

/** A registry payload in the shape GET /api/workflow/node-types answers. */
const REGISTRY = {
  registry_version: 5,
  categories: {
    input: { label: 'Input', color: '#4ECDC4' },
    audio: { label: 'Audio', color: '#A78BFA' },
    utility: { label: 'Utility', color: '#9CA3AF' },
  },
  node_types: {
    'demo.start': { display_name: 'Start', category: 'input', icon: 'play' },
    'demo.speak': { display_name: 'Speak', category: 'audio', icon: 'mic' },
    'demo.finish': { display_name: 'Finish', category: 'utility', icon: 'flag' },
  },
}

const WORKFLOW = {
  workflow_id: 'wf_AAA111',
  name: 'Demo',
  nodes: [
    { id: 'n_start', type: 'demo.start', name: 'Start', position: { x: 0, y: 100 }, disabled: false },
    { id: 'n_speak', type: 'demo.speak', name: 'Speak', position: { x: 240, y: 100 }, disabled: false },
    { id: 'n_end', type: 'demo.finish', name: 'Finish', position: { x: 480, y: 100 }, disabled: true },
  ],
  edges: [
    { id: 'e1', source_node: 'n_start', target_node: 'n_speak', source_port: 'out', target_port: 'in', edge_type: 'data' },
    { id: 'e2', source_node: 'n_speak', target_node: 'n_end', source_port: 'out', target_port: 'in', edge_type: 'control' },
  ],
}

const PROJECTION = {
  workflow_id: 'wf_AAA111',
  stages: [
    { key: 'script', label: 'Script', ordinal: 0, node_ids: ['n_start'] },
    { key: 'voice', label: 'Voice', ordinal: 1, node_ids: ['n_speak'] },
  ],
}

describe('stageIndexByNode', () => {
  it('maps every member node onto its stage', () => {
    expect(stageIndexByNode(PROJECTION)).toEqual({
      n_start: { key: 'script', label: 'Script', ordinal: 0 },
      n_speak: { key: 'voice', label: 'Voice', ordinal: 1 },
    })
  })

  it('survives a missing or empty projection', () => {
    expect(stageIndexByNode(null)).toEqual({})
    expect(stageIndexByNode({ stages: [] })).toEqual({})
  })
})

describe('buildSchemaGraph', () => {
  it('renders exactly the nodes the workflow document contains', () => {
    const { nodes } = buildSchemaGraph({ workflow: WORKFLOW, registry: REGISTRY, projection: PROJECTION })
    expect(nodes.map((n) => n.id)).toEqual(['n_start', 'n_speak', 'n_end'])
  })

  it('takes label, icon and accent from the registry', () => {
    const { nodes } = buildSchemaGraph({ workflow: WORKFLOW, registry: REGISTRY, projection: PROJECTION })
    const speak = nodes.find((n) => n.id === 'n_speak')
    expect(speak.icon).toBe('mic')
    expect(speak.accent).toBe('#A78BFA')
    expect(speak.category).toBe('audio')
  })

  it('labels a node with the stage the projection puts it in', () => {
    const { nodes } = buildSchemaGraph({ workflow: WORKFLOW, registry: REGISTRY, projection: PROJECTION })
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
    expect(byId.n_start.stageKey).toBe('script')
    expect(byId.n_start.subtitle).toBe('Script')
    expect(byId.n_speak.subtitle).toBe('Voice')
  })

  it('treats a node no stage claims as infrastructure, not a step', () => {
    const { nodes } = buildSchemaGraph({ workflow: WORKFLOW, registry: REGISTRY, projection: PROJECTION })
    const end = nodes.find((n) => n.id === 'n_end')
    expect(end.stageKey).toBeNull()
    expect(end.role).toBe('flow')
    // Falls back to the registry category label rather than inventing a stage.
    expect(end.subtitle).toBe('Utility')
  })

  it('renders a node type it has never seen without special-casing it', () => {
    const { nodes } = buildSchemaGraph({
      workflow: {
        nodes: [{ id: 'n_new', type: 'brand.new', name: 'Brand New', position: { x: 5, y: 6 } }],
        edges: [],
      },
      registry: REGISTRY,
      projection: null,
    })
    expect(nodes).toHaveLength(1)
    expect(nodes[0].name).toBe('Brand New')
    expect(nodes[0].x).toBe(5)
  })

  it('carries edge direction and type through unchanged', () => {
    const { edges } = buildSchemaGraph({ workflow: WORKFLOW, registry: REGISTRY, projection: PROJECTION })
    expect(edges).toEqual([
      { id: 'e1', source: 'n_start', target: 'n_speak', edgeType: 'data' },
      { id: 'e2', source: 'n_speak', target: 'n_end', edgeType: 'control' },
    ])
  })

  it('drops an edge whose endpoint is not in the document', () => {
    const { edges } = buildSchemaGraph({
      workflow: {
        nodes: WORKFLOW.nodes,
        edges: [{ id: 'e9', source_node: 'n_start', target_node: 'n_ghost' }],
      },
      registry: REGISTRY,
    })
    expect(edges).toEqual([])
  })

  it('returns an empty graph rather than throwing on missing input', () => {
    expect(buildSchemaGraph()).toEqual({ nodes: [], edges: [] })
    expect(buildSchemaGraph({ workflow: {}, registry: {} })).toEqual({ nodes: [], edges: [] })
  })

  it('records disabled without hiding the node', () => {
    const { nodes } = buildSchemaGraph({ workflow: WORKFLOW, registry: REGISTRY })
    expect(nodes.find((n) => n.id === 'n_end').disabled).toBe(true)
  })

  it('carries the backend-resolved narration values onto a TTS badge', () => {
    const node = {
      id: 'n_tts',
      type: 'tts.generate',
      name: 'Text to Speech',
      position: { x: 0, y: 0 },
      configuration: { speed: 1 },
    }
    const workflow = {
      nodes: [node],
      edges: [],
      extensions: {
        narration_processing: {
          n_tts: { remove_silence: false, speed: 1.25, inherited: false },
        },
      },
    }
    const registry = {
      node_types: {
        'tts.generate': {
          category: 'audio',
          config_schema: [{ type: 'provider', provider_domain: 'tts' }],
        },
      },
      categories: REGISTRY.categories,
    }
    const settings = narrationProcessingFor(workflow, node, 'tts')
    expect(narrationBadge(settings)).toBe('Pauses · 1.25×')
    const { nodes } = buildSchemaGraph({ workflow, registry })
    expect(nodes[0].narrationBadge).toBe('Pauses · 1.25×')
  })
})

describe('layout helpers', () => {
  const { nodes, edges } = buildSchemaGraph({
    workflow: WORKFLOW,
    registry: REGISTRY,
    projection: PROJECTION,
  })

  it('seeds home positions from the workflow document', () => {
    expect(homePositions(nodes)).toEqual({
      n_start: { x: 0, y: 100 },
      n_speak: { x: 240, y: 100 },
      n_end: { x: 480, y: 100 },
    })
  })

  it('auto-aligns left to right along the edges', () => {
    const laid = autoLayoutPositions(nodes, edges)
    expect(Object.keys(laid).sort()).toEqual(['n_end', 'n_speak', 'n_start'])
    expect(laid.n_start.x).toBeLessThan(laid.n_speak.x)
    expect(laid.n_speak.x).toBeLessThan(laid.n_end.x)
    // Normalised to the origin so nothing lands behind the world inset.
    expect(Math.min(...Object.values(laid).map((p) => p.x))).toBe(0)
  })

  it('leaves the source nodes untouched — positions are cosmetic', () => {
    const before = JSON.stringify(WORKFLOW)
    autoLayoutPositions(nodes, edges)
    snapPositions(homePositions(nodes))
    expect(JSON.stringify(WORKFLOW)).toBe(before)
  })

  it('snaps every position onto the grid', () => {
    const snapped = snapPositions({ a: { x: 33, y: 47 }, b: { x: -7, y: 0 } })
    expect(snapped).toEqual({ a: { x: 40, y: 40 }, b: { x: 0, y: 0 } })
  })

  it('bounds the graph including the card box', () => {
    const bounds = graphBounds({ a: { x: 0, y: 0 }, b: { x: 200, y: 60 } })
    expect(bounds.minX).toBe(0)
    expect(bounds.maxX).toBe(200 + NODE_W)
    expect(bounds.maxY).toBe(60 + NODE_H)
  })

  it('gives an empty graph a usable world box', () => {
    expect(graphBounds({}).width).toBe(0)
    expect(worldSize({}).width).toBeGreaterThan(0)
  })
})

describe('navigation geometry', () => {
  const positions = { a: { x: 0, y: 0 }, b: { x: 600, y: 400 } }

  it('clamps zoom to the navigable range', () => {
    expect(clampZoom(99)).toBe(MAX_ZOOM)
    expect(clampZoom(0.01)).toBe(MIN_ZOOM)
    expect(clampZoom(Number.NaN)).toBe(1)
  })

  it('fits the graph inside the viewport and centres it', () => {
    const view = fitView(positions, { width: 400, height: 300 })
    expect(view.zoom).toBeLessThan(1)
    expect(view.zoom).toBeGreaterThanOrEqual(MIN_ZOOM)
    const bounds = graphBounds(positions)
    const centre = { x: bounds.minX + bounds.width / 2, y: bounds.minY + bounds.height / 2 }
    // The graph centre lands in the middle of the canvas.
    expect(WORLD_INSET + view.panX + centre.x * view.zoom).toBeCloseTo(200, 5)
    expect(WORLD_INSET + view.panY + centre.y * view.zoom).toBeCloseTo(150, 5)
  })

  it('never zooms past 1:1 when the graph already fits', () => {
    expect(fitView(positions, { width: 4000, height: 3000 }).zoom).toBe(1)
  })

  it('falls back to the default view without a measurable canvas', () => {
    expect(fitView(positions, { width: 0, height: 0 })).toEqual({ ...DEFAULT_VIEW })
    expect(fitView({}, { width: 800, height: 600 })).toEqual({ ...DEFAULT_VIEW })
  })

  it('centres the canvas on one node', () => {
    const view = centerOnNode({ x: 600, y: 400 }, { width: 800, height: 600 }, 1)
    expect(WORLD_INSET + view.panX + (600 + NODE_W / 2)).toBeCloseTo(400, 5)
    expect(WORLD_INSET + view.panY + (400 + NODE_H / 2)).toBeCloseTo(300, 5)
  })

  it('keeps the world point under the cursor fixed while zooming', () => {
    const before = { zoom: 1, panX: 30, panY: -20 }
    const cursor = { x: 260, y: 180 }
    const world = {
      x: (cursor.x - WORLD_INSET - before.panX) / before.zoom,
      y: (cursor.y - WORLD_INSET - before.panY) / before.zoom,
    }
    const after = zoomAt(before, 1.4, cursor.x, cursor.y)
    expect(after.zoom).toBeCloseTo(1.4, 5)
    expect(WORLD_INSET + after.panX + world.x * after.zoom).toBeCloseTo(cursor.x, 5)
    expect(WORLD_INSET + after.panY + world.y * after.zoom).toBeCloseTo(cursor.y, 5)
  })

  it('does not drift the pan when zoom is already at a limit', () => {
    const at = { zoom: MAX_ZOOM, panX: 12, panY: 34 }
    expect(zoomAt(at, 2, 100, 100)).toEqual(at)
  })
})

describe('edgePath', () => {
  it('leaves the source card on its right and enters the target on its left', () => {
    const d = edgePath({ x: 0, y: 0 }, { x: 300, y: 0 })
    expect(d.startsWith(`M ${NODE_W} ${NODE_H / 2}`)).toBe(true)
    expect(d.endsWith(`300 ${NODE_H / 2}`)).toBe(true)
  })

  it('keeps a minimum bend when the target sits to the left', () => {
    expect(edgePath({ x: 400, y: 0 }, { x: 0, y: 0 })).toContain('C 590')
  })
})

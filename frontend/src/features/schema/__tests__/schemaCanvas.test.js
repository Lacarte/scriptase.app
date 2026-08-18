/**
 * Step 1.2 — canvas state: drag to reposition, right-click to realign.
 *
 * Guards:
 * - Every realign action produces a new position map and leaves the graph
 *   structure alone — positions are cosmetic, structure is fixed
 * - "Reset positions" restores the workflow's authored layout
 * - Re-rendering the same graph does not throw away an arranged layout
 */
import { describe, expect, it } from 'vitest'
import { nextTick, ref } from 'vue'

import { NODE_H, NODE_W, WORLD_INSET } from '../graph.js'
import { useSchemaCanvas } from '../composables/useSchemaCanvas.js'

const VIEWPORT = { width: 800, height: 600 }

function setup(overrides = {}) {
  const nodes = ref(overrides.nodes || [
    { id: 'a', x: 0, y: 100, role: 'stage' },
    { id: 'b', x: 240, y: 100, role: 'stage' },
    { id: 'c', x: 480, y: 100, role: 'flow' },
  ])
  const edges = ref(overrides.edges || [
    { id: 'e1', source: 'a', target: 'b' },
    { id: 'e2', source: 'b', target: 'c' },
  ])
  const canvas = useSchemaCanvas({
    nodes,
    edges,
    viewport: () => overrides.viewport || VIEWPORT,
  })
  return { nodes, edges, canvas }
}

describe('useSchemaCanvas', () => {
  it('seeds positions from the workflow document', () => {
    const { canvas } = setup()
    expect(canvas.positions.value).toEqual({
      a: { x: 0, y: 100 },
      b: { x: 240, y: 100 },
      c: { x: 480, y: 100 },
    })
  })

  it('moves one node and leaves the rest alone', () => {
    const { canvas } = setup()
    canvas.moveNode('b', 300.4, 42.6)
    expect(canvas.positions.value.b).toEqual({ x: 300, y: 43 })
    expect(canvas.positions.value.a).toEqual({ x: 0, y: 100 })
  })

  it('ignores a move for a node that is not on the canvas', () => {
    const { canvas } = setup()
    canvas.moveNode('ghost', 10, 10)
    expect(canvas.positions.value.ghost).toBeUndefined()
  })

  it('restores the authored layout on reset', () => {
    const { canvas } = setup()
    canvas.moveNode('a', 999, 999)
    canvas.resetLayout()
    expect(canvas.positions.value.a).toEqual({ x: 0, y: 100 })
  })

  it('resets a single node without disturbing the others', () => {
    const { canvas } = setup()
    canvas.moveNode('a', 999, 999)
    canvas.moveNode('b', 555, 555)
    canvas.resetNode('a')
    expect(canvas.positions.value.a).toEqual({ x: 0, y: 100 })
    expect(canvas.positions.value.b).toEqual({ x: 555, y: 555 })
  })

  it('snaps every card onto the grid', () => {
    const { canvas } = setup()
    canvas.moveNode('a', 33, 47)
    canvas.snapAll()
    expect(canvas.positions.value.a).toEqual({ x: 40, y: 40 })
  })

  it('auto-aligns into edge order and refits the view', () => {
    const { canvas } = setup()
    canvas.moveNode('a', 900, 900)
    canvas.autoAlign()
    const { a, b, c } = canvas.positions.value
    expect(a.x).toBeLessThan(b.x)
    expect(b.x).toBeLessThan(c.x)
    expect(canvas.view.value.zoom).toBeGreaterThan(0)
  })

  it('fits the graph into the canvas', () => {
    const { canvas } = setup()
    canvas.fit()
    expect(canvas.view.value.zoom).toBeLessThanOrEqual(1)
    expect(Number.isFinite(canvas.view.value.panX)).toBe(true)
  })

  it('centres the view on one node', () => {
    const { canvas } = setup()
    canvas.centerNode('c')
    const { panX, panY, zoom } = canvas.view.value
    expect(WORLD_INSET + panX + (480 + NODE_W / 2) * zoom).toBeCloseTo(400, 5)
    expect(WORLD_INSET + panY + (100 + NODE_H / 2) * zoom).toBeCloseTo(300, 5)
  })

  it('steps zoom around the middle of the canvas', () => {
    const { canvas } = setup()
    canvas.setView({ zoom: 1, panX: 0, panY: 0 })
    const worldAtCentre = {
      x: (VIEWPORT.width / 2 - WORLD_INSET) / 1,
      y: (VIEWPORT.height / 2 - WORLD_INSET) / 1,
    }
    canvas.zoomStep(1)
    const { zoom, panX, panY } = canvas.view.value
    expect(zoom).toBeGreaterThan(1)
    expect(WORLD_INSET + panX + worldAtCentre.x * zoom).toBeCloseTo(VIEWPORT.width / 2, 5)
    expect(WORLD_INSET + panY + worldAtCentre.y * zoom).toBeCloseTo(VIEWPORT.height / 2, 5)
  })

  it('pans by a delta', () => {
    const { canvas } = setup()
    canvas.setView({ zoom: 1, panX: 10, panY: 10 })
    canvas.panBy(-5, 25)
    expect(canvas.view.value).toEqual({ zoom: 1, panX: 5, panY: 35 })
  })

  it('re-seeds when the graph itself changes', async () => {
    const { nodes, canvas } = setup()
    nodes.value = [{ id: 'z', x: 12, y: 34, role: 'stage' }]
    await nextTick()
    expect(canvas.positions.value).toEqual({ z: { x: 12, y: 34 } })
  })

  it('keeps an arranged layout when the same graph re-renders', async () => {
    const { nodes, canvas } = setup()
    canvas.moveNode('a', 700, 700)
    nodes.value = nodes.value.map((node) => ({ ...node }))
    await nextTick()
    expect(canvas.positions.value.a).toEqual({ x: 700, y: 700 })
  })
})

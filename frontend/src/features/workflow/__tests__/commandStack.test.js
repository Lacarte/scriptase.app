import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkflowStore } from '../stores/workflow.js'

const NODE_TYPES = {
  'script.input': {
    type: 'script.input', type_version: 1, display_name: 'Script Input', category: 'input',
    inputs: [], outputs: [{ id: 'script', type: 'script' }],
    config_schema: [{ name: 'text', type: 'textarea', default: '' }],
  },
  'text.transform': {
    type: 'text.transform', type_version: 2, display_name: 'Transform', category: 'utility',
    inputs: [{ id: 'script', type: 'script', required: true, multiple: false }],
    outputs: [{ id: 'script', type: 'script' }],
    config_schema: [
      { name: 'text', type: 'string', default: 'default' },
      { name: 'mode', type: 'string', default: 'upper' },
    ],
  },
  'stub.input': {
    type: 'stub.input', type_version: 1, display_name: 'Sample Input', category: 'testing',
    inputs: [], outputs: [{ id: 'value', type: 'dynamic' }],
    config_schema: [
      { name: 'port_type', type: 'options', default: 'generic_json' },
      { name: 'payload', type: 'json', default: {} },
    ],
  },
  'stub.output': {
    type: 'stub.output', type_version: 1, display_name: 'Result Viewer', category: 'testing',
    inputs: [{ id: 'value', type: 'dynamic', required: true, multiple: false }], outputs: [],
    config_schema: [{ name: 'port_type', type: 'options', default: 'generic_json' }],
  },
}

function seededStore() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = NODE_TYPES
  store.samplePayloads = { script: 'sample script' }
  return store
}

function graph(store) {
  return JSON.parse(JSON.stringify({ nodes: store.nodes, edges: store.edges }))
}

describe('workflow command stack', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('round-trips add and restores the clean state', () => {
    const store = seededStore()
    const node = store.addNode('script.input', { x: 13, y: 27 })
    expect(store.canUndo).toBe(true)
    expect(store.undoLabel).toBe('Add node')
    expect(store.undo()).toBe(true)
    expect(store.nodes).toEqual([])
    expect(store.dirty).toBe(false)
    expect(store.canRedo).toBe(true)
    expect(store.redo()).toBe(true)
    expect(store.nodes[0]).toMatchObject({ id: node.id, position: { x: 20, y: 20 } })
    expect(store.dirty).toBe(true)
  })

  it('coalesces a multi-node drag into one move command', () => {
    const store = seededStore()
    const a = store.addNode('script.input', { x: 0, y: 0 })
    const b = store.addNode('script.input', { x: 100, y: 0 })
    store.clearCommandHistory()
    const before = graph(store)

    store.moveNodes([
      { id: a.id, position: { x: 40, y: 60 } },
      { id: b.id, position: { x: 140, y: 60 } },
    ])
    expect(store.undoLabel).toBe('Move node')
    store.undo()
    expect(graph(store)).toEqual(before)
    expect(store.canUndo).toBe(false)
    store.redo()
    expect(store.nodeById(a.id).position).toEqual({ x: 40, y: 60 })
    expect(store.nodeById(b.id).position).toEqual({ x: 140, y: 60 })
  })

  it('round-trips delete with all incident edges', () => {
    const store = seededStore()
    const source = store.addNode('script.input', { x: 0, y: 0 })
    const target = store.addNode('text.transform', { x: 200, y: 0 })
    store.connectNodes({
      sourceNode: source.id, sourcePort: 'script', targetNode: target.id, targetPort: 'script',
    })
    store.clearCommandHistory()
    const before = graph(store)
    store.removeNodes([source.id])
    expect(store.edges).toEqual([])
    store.undo()
    expect(graph(store)).toEqual(before)
    store.redo()
    expect(store.nodes.map((node) => node.id)).toEqual([target.id])
  })

  it('round-trips connect and disconnect', () => {
    const store = seededStore()
    const source = store.addNode('script.input', { x: 0, y: 0 })
    const target = store.addNode('text.transform', { x: 200, y: 0 })
    store.clearCommandHistory()

    expect(store.connectNodes({
      sourceNode: source.id, sourcePort: 'script', targetNode: target.id, targetPort: 'script',
    }).ok).toBe(true)
    const edge = graph(store).edges[0]
    store.undo()
    expect(store.edges).toEqual([])
    store.redo()
    expect(graph(store).edges).toEqual([edge])

    store.removeEdges([edge.id])
    expect(store.undoLabel).toBe('Disconnect nodes')
    store.undo()
    expect(graph(store).edges).toEqual([edge])
  })

  it('round-trips configuration and disabled state', () => {
    const store = seededStore()
    const node = store.addNode('text.transform', { x: 0, y: 0 })
    store.clearCommandHistory()

    store.updateNodeConfig(node.id, 'mode', 'lower')
    store.setNodeDisabled(node.id, true)
    expect(store.nodeById(node.id)).toMatchObject({
      configuration: { mode: 'lower' }, disabled: true,
    })
    store.undo()
    expect(store.nodeById(node.id).disabled).toBe(false)
    store.undo()
    expect(store.nodeById(node.id).configuration.mode).toBe('upper')
    store.redo()
    store.redo()
    expect(store.nodeById(node.id)).toMatchObject({
      configuration: { mode: 'lower' }, disabled: true,
    })
  })

  it('round-trips replace while preserving identity, geometry, name, and compatible config', () => {
    const store = seededStore()
    const node = store.addNode('script.input', { x: 80, y: 40 })
    store.renameNode(node.id, 'My input')
    store.updateNodeConfig(node.id, 'text', 'hello')
    store.clearCommandHistory()
    const before = graph(store)

    store.replaceNode(node.id, 'text.transform')
    expect(store.nodeById(node.id)).toMatchObject({
      id: node.id,
      type: 'text.transform',
      type_version: 2,
      name: 'My input',
      position: { x: 80, y: 40 },
      configuration: { text: 'hello', mode: 'upper' },
    })
    store.undo()
    expect(graph(store)).toEqual(before)
    store.redo()
    expect(store.nodeById(node.id).type).toBe('text.transform')
  })

  it('treats add-with-stubs and real-edge stub replacement as atomic commands', () => {
    const store = seededStore()
    const target = store.addNodeWithStubs('text.transform', { x: 400, y: 0 })
    expect(store.nodes).toHaveLength(3)
    store.undo()
    expect(store.nodes).toEqual([])
    expect(store.edges).toEqual([])
    store.redo()
    expect(store.nodes).toHaveLength(3)

    const realSource = store.addNode('script.input', { x: 0, y: 200 })
    const stubId = store.edges.find((edge) => edge.target_node === target.id).source_node
    store.connectNodes({
      sourceNode: realSource.id, sourcePort: 'script', targetNode: target.id, targetPort: 'script',
    })
    expect(store.nodeById(stubId)).toBeNull()
    store.undo()
    expect(store.nodeById(stubId)).not.toBeNull()
    expect(store.edges.some((edge) => edge.source_node === realSource.id)).toBe(false)
    store.redo()
    expect(store.nodeById(stubId)).toBeNull()
  })

  it('clears redo on a divergent edit and clears all history on document load', () => {
    const store = seededStore()
    const node = store.addNode('script.input', { x: 0, y: 0 })
    store.moveNode(node.id, { x: 20, y: 0 })
    store.undo()
    expect(store.canRedo).toBe(true)
    store.renameNode(node.id, 'Diverged')
    expect(store.canRedo).toBe(false)

    const document = store.toDocument()
    store.applyDocument(document)
    expect(store.canUndo).toBe(false)
    expect(store.canRedo).toBe(false)
    expect(store.toDocument()).not.toHaveProperty('undoStack')
  })
})

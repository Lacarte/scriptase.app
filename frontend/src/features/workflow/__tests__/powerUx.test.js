import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkflowStore } from '../stores/workflow.js'
import { compatibleInsertions, parseWorkflowFragment } from '../fragments.js'

const TYPES = {
  source: {
    type: 'source', type_version: 1, display_name: 'Source', category: 'input',
    inputs: [], outputs: [{ id: 'value', type: 'text' }],
    config_schema: [{ name: 'shared', type: 'string', default: 'source' }],
  },
  transform: {
    type: 'transform', type_version: 1, display_name: 'Transform', category: 'utility',
    inputs: [{ id: 'value', type: 'text', required: true, multiple: false }],
    outputs: [{ id: 'value', type: 'text' }],
    config_schema: [
      { name: 'shared', type: 'string', default: 'transform' },
      { name: 'extra', type: 'string', default: 'new' },
    ],
  },
  incompatible: {
    type: 'incompatible', type_version: 2, display_name: 'Audio only', category: 'audio',
    inputs: [{ id: 'value', type: 'audio_file', required: true, multiple: false }],
    outputs: [{ id: 'value', type: 'audio_file' }], config_schema: [],
  },
}

function seededStore() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = TYPES
  store.portTypes = ['text', 'audio_file']
  store.settings = { on_error: 'stop', auto_attach_stubs: false }
  return store
}

describe('step 5.2 power UX domain operations', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('copies a minimal internal fragment and pastes it across workflows undoably', () => {
    const sourceStore = seededStore()
    const a = sourceStore.addNode('source', { x: 0, y: 0 })
    const b = sourceStore.addNode('transform', { x: 200, y: 0 })
    sourceStore.connectNodes({ sourceNode: a.id, sourcePort: 'value', targetNode: b.id, targetPort: 'value' })
    const fragment = sourceStore.copyFragment([a.id, b.id])
    expect(fragment).toMatchObject({ kind: 'scriptase.workflow-fragment', version: 1 })
    expect(fragment.edges).toHaveLength(1)
    expect(fragment).not.toHaveProperty('workflow_id')
    expect(parseWorkflowFragment(JSON.stringify(fragment))).toEqual(fragment)

    setActivePinia(createPinia())
    const targetStore = seededStore()
    const pasted = targetStore.pasteFragment(fragment, { position: { x: 500, y: 300 } })
    expect(pasted).toHaveLength(2)
    expect(pasted[0].position).toEqual({ x: 500, y: 300 })
    expect(targetStore.edges).toHaveLength(1)
    expect(targetStore.edges[0]).toMatchObject({
      source_node: pasted[0].id, target_node: pasted[1].id,
    })
    expect(targetStore.undoLabel).toBe('Paste nodes')
    targetStore.undo()
    expect(targetStore.nodes).toEqual([])
    expect(targetStore.edges).toEqual([])
    targetStore.redo()
    expect(targetStore.nodes).toHaveLength(2)
  })

  it('Ctrl+D domain operation duplicates a selected subgraph as one command', () => {
    const store = seededStore()
    const a = store.addNode('source', { x: 0, y: 0 })
    const b = store.addNode('transform', { x: 200, y: 0 })
    store.connectNodes({ sourceNode: a.id, sourcePort: 'value', targetNode: b.id, targetPort: 'value' })
    store.clearCommandHistory()
    const copies = store.duplicateNodes([a.id, b.id])
    expect(copies.map((node) => node.name)).toEqual(['Source copy', 'Transform copy'])
    expect(store.nodes).toHaveLength(4)
    expect(store.edges).toHaveLength(2)
    expect(store.undoLabel).toBe('Duplicate nodes')
    store.undo()
    expect(store.nodes).toHaveLength(2)
    expect(store.edges).toHaveLength(1)
  })

  it('replaces a node while preserving identity, name, position, compatible config and edges', () => {
    const store = seededStore()
    const source = store.addNode('source', { x: 0, y: 0 })
    const target = store.addNode('source', { x: 200, y: 40 })
    store.renameNode(target.id, 'Keep me')
    store.updateNodeConfig(target.id, 'shared', 'custom')
    store.connectNodes({ sourceNode: target.id, sourcePort: 'value', targetNode: store.addNode('transform', { x: 400, y: 0 }).id, targetPort: 'value' })
    store.clearCommandHistory()

    expect(store.replacementPlan(target.id, 'transform').droppedEdges).toHaveLength(0)
    store.replaceNode(target.id, 'transform')
    expect(store.nodeById(target.id)).toMatchObject({
      type: 'transform', name: 'Keep me', position: { x: 200, y: 40 },
      configuration: { shared: 'custom', extra: 'new' },
    })
    expect(store.edges).toHaveLength(1)
    store.undo()
    expect(store.nodeById(target.id).type).toBe('source')
    expect(store.nodeById(source.id)).not.toBeNull()
  })

  it('warns through the replacement plan for incompatible connections before dropping them', () => {
    const store = seededStore()
    const source = store.addNode('source', { x: 0, y: 0 })
    const target = store.addNode('transform', { x: 200, y: 0 })
    store.connectNodes({ sourceNode: source.id, sourcePort: 'value', targetNode: target.id, targetPort: 'value' })
    const plan = store.replacementPlan(target.id, 'incompatible')
    expect(plan.keptEdges).toHaveLength(0)
    expect(plan.droppedEdges).toHaveLength(1)
    store.clearCommandHistory()
    store.replaceNode(target.id, 'incompatible')
    expect(store.edges).toEqual([])
    store.undo()
    expect(store.edges).toHaveLength(1)
  })

  it('filters the connection-drop palette and inserts plus auto-connects in one command', () => {
    const store = seededStore()
    const source = store.addNode('source', { x: 0, y: 0 })
    const choices = compatibleInsertions({
      nodeTypes: store.nodeTypes, node: source, handleId: 'value', handleType: 'source',
    })
    expect(choices.map((choice) => choice.type)).toContain('transform')
    expect(choices.map((choice) => choice.type)).not.toContain('incompatible')
    const choice = choices.find((item) => item.type === 'transform')
    store.clearCommandHistory()
    const inserted = store.insertNodeAndConnect(
      choice.type, { x: 240, y: 80 },
      { nodeId: source.id, handleId: 'value', handleType: 'source', portType: 'text' },
      choice.portId,
    )
    expect(store.edges[0]).toMatchObject({ source_node: source.id, target_node: inserted.id })
    expect(store.undoLabel).toBe('Insert connected node')
    store.undo()
    expect(store.nodes).toEqual([source])
    expect(store.edges).toEqual([])
  })
})

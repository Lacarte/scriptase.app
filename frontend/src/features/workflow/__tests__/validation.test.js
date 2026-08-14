import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { validateConnection } from '../validation.js'
import { useWorkflowStore } from '../stores/workflow.js'

const NODE_TYPES = {
  'script.input': {
    type_version: 1,
    display_name: 'Script Input',
    config_schema: [],
    inputs: [{ id: 'trigger', type: 'control', required: false, multiple: false }],
    outputs: [{ id: 'control', type: 'control' }, { id: 'script', type: 'script' }],
  },
  'tts.generate': {
    type_version: 1,
    display_name: 'Text to Speech',
    config_schema: [],
    inputs: [
      { id: 'trigger', type: 'control', required: false, multiple: false },
      { id: 'script', type: 'script', required: true, multiple: false },
    ],
    outputs: [{ id: 'control', type: 'control' }, { id: 'audio', type: 'audio_file' }],
  },
  'stub.input': {
    type_version: 1,
    display_name: 'Sample Input',
    config_schema: [],
    inputs: [],
    outputs: [{ id: 'value', type: 'dynamic' }],
  },
}

function node(id, type, configuration = {}) {
  return { id, type, name: id, position: { x: 0, y: 0 }, configuration, disabled: false }
}

function ctx(nodes, edges = []) {
  return { nodes, edges, nodeTypes: NODE_TYPES }
}

const SCRIPT_TO_TTS = {
  sourceNode: 'a', sourcePort: 'script', targetNode: 'b', targetPort: 'script',
}

describe('validateConnection', () => {
  it('accepts a matching data connection', () => {
    const verdict = validateConnection(
      ctx([node('a', 'script.input'), node('b', 'tts.generate')]),
      SCRIPT_TO_TTS,
    )
    expect(verdict).toEqual({ ok: true, edgeType: 'data' })
  })

  it('classifies control connections as control edges', () => {
    const verdict = validateConnection(
      ctx([node('a', 'script.input'), node('b', 'tts.generate')]),
      { sourceNode: 'a', sourcePort: 'control', targetNode: 'b', targetPort: 'trigger' },
    )
    expect(verdict).toEqual({ ok: true, edgeType: 'control' })
  })

  it('rejects type mismatches in plain language', () => {
    const verdict = validateConnection(
      ctx([node('a', 'script.input'), node('b', 'tts.generate')]),
      { sourceNode: 'a', sourcePort: 'script', targetNode: 'b', targetPort: 'trigger' },
    )
    expect(verdict.ok).toBe(false)
    expect(verdict.reason).toMatch(/Type mismatch/)
  })

  it('rejects unknown ports and missing nodes', () => {
    const nodes = [node('a', 'script.input'), node('b', 'tts.generate')]
    expect(validateConnection(ctx(nodes),
      { ...SCRIPT_TO_TTS, sourcePort: 'nope' }).ok).toBe(false)
    expect(validateConnection(ctx(nodes),
      { ...SCRIPT_TO_TTS, targetPort: 'nope' }).ok).toBe(false)
    expect(validateConnection(ctx(nodes),
      { ...SCRIPT_TO_TTS, targetNode: 'ghost' }).ok).toBe(false)
  })

  it('rejects duplicates and occupied single-value inputs', () => {
    const nodes = [node('a', 'script.input'), node('a2', 'script.input'), node('b', 'tts.generate')]
    const existing = [{
      id: 'e_1', source_node: 'a', source_port: 'script',
      target_node: 'b', target_port: 'script', edge_type: 'data',
    }]
    const dup = validateConnection(ctx(nodes, existing), SCRIPT_TO_TTS)
    expect(dup.ok).toBe(false)
    expect(dup.reason).toMatch(/already connected/)
    const occupied = validateConnection(ctx(nodes, existing),
      { ...SCRIPT_TO_TTS, sourceNode: 'a2' })
    expect(occupied.ok).toBe(false)
    expect(occupied.reason).toMatch(/already has a connection/)
  })

  it('rejects self-loops and deeper cycles', () => {
    const nodes = [node('a', 'tts.generate'), node('b', 'tts.generate')]
    const selfLoop = validateConnection(ctx(nodes),
      { sourceNode: 'a', sourcePort: 'control', targetNode: 'a', targetPort: 'trigger' })
    expect(selfLoop.ok).toBe(false)
    const edges = [{
      id: 'e_1', source_node: 'a', source_port: 'control',
      target_node: 'b', target_port: 'trigger', edge_type: 'control',
    }]
    const cycle = validateConnection(ctx(nodes, edges),
      { sourceNode: 'b', sourcePort: 'control', targetNode: 'a', targetPort: 'trigger' })
    expect(cycle.ok).toBe(false)
    expect(cycle.reason).toMatch(/loop/i)
  })

  it('re-validating an existing edge by its own id passes (canvas render path)', () => {
    // Vue Flow re-runs isValidConnection over every edge on setEdges; the
    // edge must not collide with itself in duplicate/occupied/cycle checks.
    const nodes = [node('a', 'script.input'), node('b', 'tts.generate')]
    const edges = [{
      id: 'e_1', source_node: 'a', source_port: 'script',
      target_node: 'b', target_port: 'script', edge_type: 'data',
    }]
    const self = validateConnection(ctx(nodes, edges), { ...SCRIPT_TO_TTS, edgeId: 'e_1' })
    expect(self).toEqual({ ok: true, edgeType: 'data' })
    // A different edge to the same occupied port must still be rejected.
    const other = validateConnection(ctx(nodes, edges), { ...SCRIPT_TO_TTS, edgeId: 'e_999' })
    expect(other.ok).toBe(false)
  })

  it('resolves dynamic ports from configuration', () => {
    const nodes = [node('s', 'stub.input', { port_type: 'script' }), node('b', 'tts.generate')]
    const good = validateConnection(ctx(nodes),
      { sourceNode: 's', sourcePort: 'value', targetNode: 'b', targetPort: 'script' })
    expect(good).toEqual({ ok: true, edgeType: 'data' })
    const bad = validateConnection(
      ctx([node('s', 'stub.input', { port_type: 'audio_file' }), node('b', 'tts.generate')]),
      { sourceNode: 's', sourcePort: 'value', targetNode: 'b', targetPort: 'script' })
    expect(bad.ok).toBe(false)
  })

  it('rejects unsupported dynamic port types even when both ends match', () => {
    const dynamicOutput = {
      type_version: 1,
      inputs: [{ id: 'value', type: 'dynamic', required: true, multiple: false }],
      outputs: [],
    }
    const nodeTypes = { ...NODE_TYPES, 'workflow.output': dynamicOutput }
    const nodes = [
      node('s', 'stub.input', { port_type: 'not_a_real_type' }),
      node('o', 'workflow.output', { port_type: 'not_a_real_type' }),
    ]
    const verdict = validateConnection(
      { nodes, edges: [], nodeTypes, portTypes: ['script', 'generic_json'] },
      { sourceNode: 's', sourcePort: 'value', targetNode: 'o', targetPort: 'value' },
    )
    expect(verdict.ok).toBe(false)
    expect(verdict.reason).toMatch(/unsupported/i)
  })
})

describe('store.connectNodes', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('appends a persisted-shape edge on success and marks dirty', () => {
    const store = useWorkflowStore()
    store.registryVersion = 1
    store.nodeTypes = NODE_TYPES
    const a = store.addNode('script.input', { x: 0, y: 0 })
    const b = store.addNode('tts.generate', { x: 200, y: 0 })
    store.dirty = false
    const verdict = store.connectNodes({
      sourceNode: a.id, sourcePort: 'script', targetNode: b.id, targetPort: 'script',
    })
    expect(verdict.ok).toBe(true)
    expect(store.edges).toHaveLength(1)
    expect(store.edges[0]).toMatchObject({
      source_node: a.id, source_port: 'script',
      target_node: b.id, target_port: 'script', edge_type: 'data',
    })
    expect(store.edges[0].id).toMatch(/^e_\d+$/)
    expect(store.dirty).toBe(true)
  })

  it('does not append on rejection', () => {
    const store = useWorkflowStore()
    store.registryVersion = 1
    store.nodeTypes = NODE_TYPES
    const a = store.addNode('script.input', { x: 0, y: 0 })
    const b = store.addNode('tts.generate', { x: 200, y: 0 })
    const verdict = store.connectNodes({
      sourceNode: a.id, sourcePort: 'script', targetNode: b.id, targetPort: 'trigger',
    })
    expect(verdict.ok).toBe(false)
    expect(store.edges).toHaveLength(0)
  })
})

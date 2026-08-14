import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkflowStore } from '../stores/workflow.js'
import { validateStubPayload } from '../stubPayloads.js'
import { nodeIssues } from '../schema.js'

/** Step 2.5 — sample-data stubs: auto-attach, detach-on-real-edge, undo,
 *  and per-port-type payload validation. */

const FAKE_TYPES = {
  'segment.run': {
    type: 'segment.run',
    type_version: 1,
    display_name: 'Segmenter',
    category: 'timing',
    inputs: [
      { id: 'trigger', type: 'control', required: false, multiple: false },
      { id: 'alignment', type: 'alignment', required: true, multiple: false },
    ],
    outputs: [
      { id: 'control', type: 'control' },
      { id: 'segments', type: 'segments' },
    ],
    config_schema: [{ name: 'segment_config', type: 'json', default: {} }],
  },
  'timing.align': {
    type: 'timing.align',
    type_version: 1,
    display_name: 'Force Alignment',
    category: 'timing',
    inputs: [
      { id: 'audio', type: 'audio_file', required: true, multiple: false },
      { id: 'script', type: 'script', required: true, multiple: false },
    ],
    outputs: [{ id: 'alignment', type: 'alignment' }],
    config_schema: [],
  },
  'stub.input': {
    type: 'stub.input',
    type_version: 1,
    display_name: 'Sample Input',
    category: 'testing',
    inputs: [],
    outputs: [{ id: 'value', type: 'dynamic' }],
    config_schema: [
      { name: 'port_type', type: 'options', default: 'generic_json', required: true },
      { name: 'payload', type: 'json', default: {} },
    ],
  },
  'stub.output': {
    type: 'stub.output',
    type_version: 1,
    display_name: 'Result Viewer',
    category: 'testing',
    inputs: [{ id: 'value', type: 'dynamic', required: true, multiple: false }],
    outputs: [{ id: 'value', type: 'dynamic' }],
    config_schema: [
      { name: 'port_type', type: 'options', default: 'generic_json', required: true },
      { name: 'pinned', type: 'boolean', default: false },
      { name: 'payload', type: 'json', default: {}, display_options: { show: { pinned: [true] } } },
    ],
  },
}

const SAMPLES = {
  alignment: {
    transcript: 'hello there',
    alignment: [
      { word: 'hello', begin: 0.0, end: 0.2 },
      { word: 'there', begin: 0.2, end: 0.4 },
    ],
  },
  segments: { segments: [{ start: 0.0, end: 0.4, words: 'hello there', index: 0 }] },
  audio_file: { wav_path: 'media/voice.wav', duration_seconds: 8.0 },
  script: 'hello there',
}

function seededStore() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = FAKE_TYPES
  store.categories = { timing: { color: '#60A5FA' }, testing: { color: '#78716C' } }
  store.samplePayloads = SAMPLES
  return store
}

describe('sample-data stub auto-attach', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('dropping a lone Segmenter spawns a wired Sample Input and Result Viewer', () => {
    const store = seededStore()
    const seg = store.addNodeWithStubs('segment.run', { x: 400, y: 200 })

    const stubIn = store.nodes.find((n) => n.type === 'stub.input')
    const stubOut = store.nodes.find((n) => n.type === 'stub.output')
    expect(stubIn.configuration.port_type).toBe('alignment')
    expect(stubIn.configuration.payload).toEqual(SAMPLES.alignment)
    expect(stubOut.configuration.port_type).toBe('segments')

    expect(store.edges).toEqual([
      expect.objectContaining({
        source_node: stubIn.id, source_port: 'value',
        target_node: seg.id, target_port: 'alignment', edge_type: 'data',
      }),
      expect.objectContaining({
        source_node: seg.id, source_port: 'segments',
        target_node: stubOut.id, target_port: 'value', edge_type: 'data',
      }),
    ])
    // The stubbed graph carries no editing issues.
    expect(store.issuesByNode).toEqual({})
  })

  it('spawns one sample input per required data input', () => {
    const store = seededStore()
    store.addNodeWithStubs('timing.align', { x: 0, y: 0 })
    const stubs = store.nodes.filter((n) => n.type === 'stub.input')
    expect(stubs.map((s) => s.configuration.port_type).sort()).toEqual(['audio_file', 'script'])
    expect(stubs.find((s) => s.configuration.port_type === 'script').configuration.payload)
      .toBe('hello there')
  })

  it('respects the workflow-level auto-attach toggle', () => {
    const store = seededStore()
    store.setAutoAttachStubs(false)
    store.addNodeWithStubs('segment.run', { x: 0, y: 0 })
    expect(store.nodes).toHaveLength(1)
    expect(store.toDocument().settings.auto_attach_stubs).toBe(false)
  })

  it('never attaches stubs to a dropped stub', () => {
    const store = seededStore()
    store.addNodeWithStubs('stub.input', { x: 0, y: 0 })
    expect(store.nodes).toHaveLength(1)
    expect(store.edges).toHaveLength(0)
  })

  it('manual attach skips inputs that are already connected', () => {
    const store = seededStore()
    const seg = store.addNodeWithStubs('segment.run', { x: 0, y: 0 })
    expect(store.attachSampleInputs(seg.id)).toEqual([])
  })

  it('deletes a main node together with its attached sample nodes', () => {
    const store = seededStore()
    const seg = store.addNodeWithStubs('segment.run', { x: 0, y: 0 })

    expect(store.nodes).toHaveLength(3)
    expect(store.removeNodes([seg.id])).toBe(true)
    expect(store.nodes).toEqual([])
    expect(store.edges).toEqual([])

    expect(store.undo()).toBe(true)
    expect(store.nodes).toHaveLength(3)
    expect(store.edges).toHaveLength(2)
  })

  it('keeps a sample input that is still shared with another main node', () => {
    const store = seededStore()
    const seg = store.addNodeWithStubs('segment.run', { x: 0, y: 0 })
    const seg2 = store.addNode('segment.run', { x: 400, y: 0 })
    const stubIn = store.nodes.find((node) => node.type === 'stub.input')
    store.connectNodes({
      sourceNode: stubIn.id, sourcePort: 'value',
      targetNode: seg2.id, targetPort: 'alignment',
    })

    store.removeNodes([seg.id])

    expect(store.nodeById(stubIn.id)).not.toBeNull()
    expect(store.nodeById(seg2.id)).not.toBeNull()
    expect(store.nodes.some((node) => node.type === 'stub.output')).toBe(false)
    expect(store.edges).toEqual([
      expect.objectContaining({ source_node: stubIn.id, target_node: seg2.id }),
    ])
  })
})

describe('stub detach on real connection + undo', () => {
  beforeEach(() => setActivePinia(createPinia()))

  function stubbedSegmenter(store) {
    const seg = store.addNodeWithStubs('segment.run', { x: 400, y: 0 })
    const align = store.addNode('timing.align', { x: 0, y: 0 })
    const stubIn = store.nodes.find((n) => n.type === 'stub.input')
    return { seg, align, stubIn }
  }

  it('a real edge replaces the sample stub (undoably)', () => {
    const store = seededStore()
    const { seg, align, stubIn } = stubbedSegmenter(store)

    const verdict = store.connectNodes({
      sourceNode: align.id, sourcePort: 'alignment',
      targetNode: seg.id, targetPort: 'alignment',
    })
    expect(verdict.ok).toBe(true)
    expect(verdict.detachedStub).toBe(true)
    expect(store.nodes.some((n) => n.id === stubIn.id)).toBe(false)
    expect(store.edges.some(
      (e) => e.source_node === align.id && e.target_node === seg.id,
    )).toBe(true)
    expect(store.canUndoStubDetach).toBe(true)

    // Undo: the real edge goes away, the stub and its wiring come back.
    expect(store.undoStubDetach()).toBe(true)
    expect(store.edges.some((e) => e.source_node === align.id)).toBe(false)
    const restored = store.nodes.find((n) => n.type === 'stub.input')
    expect(restored.configuration.payload).toEqual(SAMPLES.alignment)
    expect(store.edges.some(
      (e) => e.source_node === restored.id && e.target_node === seg.id
        && e.target_port === 'alignment',
    )).toBe(true)
    expect(store.canUndoStubDetach).toBe(false)
  })

  it('keeps a stub that still feeds another input', () => {
    const store = seededStore()
    const { seg, align, stubIn } = stubbedSegmenter(store)
    const seg2 = store.addNode('segment.run', { x: 400, y: 200 })
    store.connectNodes({
      sourceNode: stubIn.id, sourcePort: 'value',
      targetNode: seg2.id, targetPort: 'alignment',
    })

    store.connectNodes({
      sourceNode: align.id, sourcePort: 'alignment',
      targetNode: seg.id, targetPort: 'alignment',
    })
    // Stub survives because seg2 still consumes it; only the edge moved.
    expect(store.nodes.some((n) => n.id === stubIn.id)).toBe(true)
    expect(store.edges.some(
      (e) => e.source_node === stubIn.id && e.target_node === seg.id,
    )).toBe(false)
  })

  it('a failing connection never detaches the stub', () => {
    const store = seededStore()
    const { seg, align } = stubbedSegmenter(store)
    const verdict = store.connectNodes({
      sourceNode: align.id, sourcePort: 'alignment',
      targetNode: seg.id, targetPort: 'trigger',   // control input: type mismatch
    })
    expect(verdict.ok).toBe(false)
    expect(store.nodes.some((n) => n.type === 'stub.input')).toBe(true)
  })

  it('stub connections themselves never trigger a detach', () => {
    const store = seededStore()
    const seg = store.addNode('segment.run', { x: 0, y: 0 })
    const stub = store.addNode('stub.input', { x: -260, y: 0 })
    stub.configuration.port_type = 'alignment'
    const verdict = store.connectNodes({
      sourceNode: stub.id, sourcePort: 'value',
      targetNode: seg.id, targetPort: 'alignment',
    })
    expect(verdict.ok).toBe(true)
    expect(verdict.detachedStub).toBe(false)
  })
})

describe('stub port_type editing', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('changing the type reseeds the payload and drops mismatched edges', () => {
    const store = seededStore()
    const seg = store.addNodeWithStubs('segment.run', { x: 0, y: 0 })
    const stubIn = store.nodes.find((n) => n.type === 'stub.input')

    store.updateNodeConfig(stubIn.id, 'port_type', 'script')
    expect(stubIn.configuration.payload).toBe('hello there')
    expect(store.edges.some((e) => e.source_node === stubIn.id)).toBe(false)
    // The viewer edge on the segmenter output is untouched.
    expect(store.edges.some((e) => e.source_node === seg.id)).toBe(true)
  })
})

describe('per-port-type payload validation', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('accepts the shipped samples', () => {
    for (const [portType, payload] of Object.entries(SAMPLES)) {
      expect(validateStubPayload(portType, payload)).toEqual([])
    }
  })

  it('rejects structural violations per type', () => {
    expect(validateStubPayload('script', '')).not.toEqual([])
    expect(validateStubPayload('project_id', 'nope')).not.toEqual([])
    expect(validateStubPayload('alignment', { transcript: 'x', alignment: [] })).not.toEqual([])
    expect(validateStubPayload('alignment', {
      transcript: 'x',
      alignment: [{ word: 'a', begin: 2, end: 1 }],
    })).not.toEqual([])
    expect(validateStubPayload('segments', {
      segments: [
        { start: 0, end: 2, words: 'a' },
        { start: 1, end: 3, words: 'b' },
      ],
    })).not.toEqual([])
    expect(validateStubPayload('storyboard_images', {
      total: 2, ready: 2, errors: 0,
      scene_statuses: { 0: { status: 'ready' } },
    })).not.toEqual([])
  })

  it('rejects file references that escape the fixture root', () => {
    for (const ref of ['../x.wav', '/etc/passwd', 'C:/x.wav', 'media/../../x']) {
      expect(validateStubPayload('audio_file', {
        wav_path: ref, duration_seconds: 1,
      })).not.toEqual([])
    }
  })

  it('surfaces payload problems as node issues in the inspector', () => {
    const node = {
      id: 'n_1',
      type: 'stub.input',
      type_version: 1,
      name: 'Sample',
      position: { x: 0, y: 0 },
      configuration: { port_type: 'alignment', payload: { transcript: '', alignment: [] } },
      disabled: false,
    }
    const issues = nodeIssues(node, FAKE_TYPES['stub.input'], [])
    expect(issues.some((issue) => issue.name === 'payload')).toBe(true)
  })
})

describe('cache staleness and Result Viewer pinning', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('marks a changed node and all descendants stale, but not unrelated nodes', () => {
    const store = seededStore()
    const seg = store.addNodeWithStubs('segment.run', { x: 400, y: 0 })
    const stubIn = store.nodes.find((node) => node.type === 'stub.input')
    const viewer = store.nodes.find((node) => node.type === 'stub.output')
    const unrelated = store.addNode('timing.align', { x: 0, y: 300 })
    store.currentExecution = {
      status: 'succeeded',
      nodes: Object.fromEntries(store.nodes.map((node) => [node.id, { status: 'succeeded' }])),
    }

    store.updateNodeConfig(stubIn.id, 'payload', { transcript: 'changed', alignment: [
      { word: 'changed', begin: 0, end: 1 },
    ] })

    expect(store.nodeExecution(stubIn.id).status).toBe('stale')
    expect(store.nodeExecution(seg.id).status).toBe('stale')
    expect(store.nodeExecution(viewer.id).status).toBe('stale')
    expect(store.nodeExecution(unrelated.id).status).toBe('succeeded')
  })

  it('persists pin state and validates an edited viewer payload by port type', () => {
    const store = seededStore()
    const viewer = store.addNode('stub.output', { x: 0, y: 0 })
    store.updateNodeConfig(viewer.id, 'port_type', 'segments')
    store.updateNodeConfig(viewer.id, 'pinned', true)
    store.updateNodeConfig(viewer.id, 'payload', {
      segments: [{ start: 0, end: 1, words: 'edited', index: 0 }],
    })
    expect(store.toDocument().nodes[0].configuration).toMatchObject({
      port_type: 'segments', pinned: true,
    })
    expect(store.issuesByNode[viewer.id].some((issue) => issue.name === 'payload')).toBe(false)

    store.updateNodeConfig(viewer.id, 'payload', { segments: [{ start: 2, end: 1, words: 'bad' }] })
    expect(store.issuesByNode[viewer.id].some((issue) => issue.name === 'payload')).toBe(true)
  })
})

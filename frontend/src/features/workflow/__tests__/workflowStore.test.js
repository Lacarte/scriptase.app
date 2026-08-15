import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkflowStore } from '../stores/workflow.js'
import { api } from '@/shared/api/client.js'

const FAKE_TYPES = {
  'script.input': {
    type: 'script.input',
    type_version: 1,
    display_name: 'Script Input',
    category: 'input',
    config_schema: [
      { name: 'text', type: 'textarea', default: '' },
    ],
  },
  'tts.generate': {
    type: 'tts.generate',
    type_version: 1,
    display_name: 'Text to Speech',
    category: 'audio',
    config_schema: [
      { name: 'engine', type: 'options', default: 'kokoro' },
      { name: 'provider_options', type: 'json', default: {} },
    ],
  },
}

function seededStore() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = FAKE_TYPES
  return store
}

describe('workflow store', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('refetches node types when the dev reload stream signals', async () => {
    const store = useWorkflowStore()
    const refreshedTypes = { ...FAKE_TYPES, 'dev.hot_node': { type: 'dev.hot_node' } }
    vi.spyOn(api, 'get')
      .mockResolvedValueOnce({ registry_version: 1, node_types: FAKE_TYPES, dev_reload_enabled: true })
      .mockResolvedValueOnce({ registry_version: 1, node_types: refreshedTypes, dev_reload_enabled: true })

    class FakeEventSource {
      constructor(url) {
        this.url = url
        this.listeners = {}
        this.closed = false
      }
      addEventListener(name, handler) { this.listeners[name] = handler }
      close() { this.closed = true }
    }

    await store.loadNodeTypes()
    const source = store.watchNodeTypeReloads({ EventSourceImpl: FakeEventSource })
    expect(source.url).toBe('/api/workflow/dev-reload/events')
    source.listeners['registry-reload']()
    await vi.waitFor(() => expect(store.nodeTypes['dev.hot_node']).toBeTruthy())
    expect(api.get).toHaveBeenCalledTimes(2)
    store.closeNodeTypeReloads()
    expect(source.closed).toBe(true)
  })

  it('does not open a reload stream in normal mode', async () => {
    const store = useWorkflowStore()
    const EventSourceImpl = vi.fn()
    vi.spyOn(api, 'get').mockResolvedValue({
      registry_version: 1,
      node_types: FAKE_TYPES,
      dev_reload_enabled: false,
    })
    await store.loadNodeTypes()
    expect(store.watchNodeTypeReloads({ EventSourceImpl })).toBeNull()
    expect(EventSourceImpl).not.toHaveBeenCalled()
  })

  it('adds a node with registry defaults and snapped position', () => {
    const store = seededStore()
    const node = store.addNode('tts.generate', { x: 33, y: 47 })
    expect(node.id).toMatch(/^n_\d+$/)
    expect(node.type_version).toBe(1)
    expect(node.name).toBe('Text to Speech')
    expect(node.position).toEqual({ x: 40, y: 40 })
    expect(node.configuration).toEqual({ engine: 'kokoro', provider_options: {} })
    expect(node.disabled).toBe(false)
    expect(store.dirty).toBe(true)
  })

  it('deep-copies config defaults per node', () => {
    const store = seededStore()
    const a = store.addNode('tts.generate', { x: 0, y: 0 })
    const b = store.addNode('tts.generate', { x: 0, y: 0 })
    a.configuration.provider_options.key = 'x'
    expect(b.configuration.provider_options).toEqual({})
  })

  it('rejects unknown node types', () => {
    const store = seededStore()
    expect(store.addNode('nope.missing', { x: 0, y: 0 })).toBeNull()
    expect(store.nodes).toHaveLength(0)
  })

  it('generates unique ids even after deletions', () => {
    const store = seededStore()
    const a = store.addNode('script.input', { x: 0, y: 0 })
    const b = store.addNode('script.input', { x: 0, y: 0 })
    store.removeNodes([a.id])
    const c = store.addNode('script.input', { x: 0, y: 0 })
    expect(c.id).not.toBe(b.id)
    const ids = store.nodes.map((n) => n.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('moves and renames nodes', () => {
    const store = seededStore()
    const node = store.addNode('script.input', { x: 0, y: 0 })
    store.moveNode(node.id, { x: 120, y: 80 })
    store.renameNode(node.id, 'My script')
    expect(store.nodeById(node.id).position).toEqual({ x: 120, y: 80 })
    expect(store.nodeById(node.id).name).toBe('My script')
  })

  it('removing a node removes its edges', () => {
    const store = seededStore()
    const a = store.addNode('script.input', { x: 0, y: 0 })
    const b = store.addNode('tts.generate', { x: 200, y: 0 })
    store.edges.push({
      id: 'e_1',
      source_node: a.id, source_port: 'script',
      target_node: b.id, target_port: 'script',
      edge_type: 'data',
    })
    store.removeNodes([a.id])
    expect(store.edges).toHaveLength(0)
    expect(store.nodes.map((n) => n.id)).toEqual([b.id])
  })

  it('removeEdges removes only the named edges', () => {
    const store = seededStore()
    store.edges.push(
      { id: 'e_1', source_node: 'a', source_port: 'x', target_node: 'b', target_port: 'y', edge_type: 'data' },
      { id: 'e_2', source_node: 'a', source_port: 'x', target_node: 'c', target_port: 'y', edge_type: 'data' },
    )
    store.removeEdges(['e_1'])
    expect(store.edges.map((e) => e.id)).toEqual(['e_2'])
  })

  it('round-trips only the persisted document shape', () => {
    const store = seededStore()
    const node = store.addNode('script.input', { x: 10, y: 20 })
    const document = store.toDocument()
    expect(document).toMatchObject({
      schema_version: 1,
      name: 'Untitled workflow',
      variables: {},
      settings: { on_error: 'stop' },
    })
    expect(document.nodes[0].id).toBe(node.id)
    expect(document.nodes[0]).not.toHaveProperty('data')
    expect(document.nodes[0]).not.toHaveProperty('selected')

    store.applyDocument({
      ...document,
      workflow_id: 'wf_ABC123',
      name: 'Reloaded',
      created_at: '2026-08-04T00:00:00Z',
      updated_at: '2026-08-04T00:00:00Z',
    })
    expect(store.workflowId).toBe('wf_ABC123')
    expect(store.workflowName).toBe('Reloaded')
    expect(store.dirty).toBe(false)
  })

  it('creates then updates using optimistic timestamps', async () => {
    const store = seededStore()
    store.addNode('script.input', { x: 0, y: 0 })
    const created = {
      ...store.toDocument(),
      workflow_id: 'wf_ABC123',
      created_at: 'created',
      updated_at: 'v1',
    }
    vi.spyOn(api, 'post').mockResolvedValue({ workflow: created })
    vi.spyOn(api, 'get').mockResolvedValue({ workflows: [], total: 0 })
    await store.saveWorkflow()
    expect(api.post).toHaveBeenCalledWith('/api/workflows', expect.objectContaining({ body: expect.any(Object) }))
    expect(store.workflowId).toBe('wf_ABC123')

    store.renameNode(store.nodes[0].id, 'Renamed')
    const updated = { ...store.toDocument(), updated_at: 'v2' }
    vi.spyOn(api, 'put').mockResolvedValue({ workflow: updated })
    await store.saveWorkflow()
    expect(api.put).toHaveBeenCalledWith('/api/workflows/wf_ABC123', {
      body: expect.objectContaining({ expected_updated_at: 'v1' }),
    })
    expect(store.updatedAt).toBe('v2')
    expect(store.dirty).toBe(false)
  })

  it('opens migrated documents dirty and future documents read-only', async () => {
    const store = seededStore()
    const document = {
      schema_version: 1,
      workflow_id: 'wf_ABC123',
      name: 'Versioned',
      description: '',
      nodes: [], edges: [], variables: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      settings: { on_error: 'stop' }, extensions: {},
      created_at: 'created', updated_at: 'v1',
    }
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      workflow: document,
      migration_trail: [{ node_id: 'n_1', from_version: 1, to_version: 2 }],
      read_only: false,
      warnings: [],
    })
    await store.openWorkflow('wf_ABC123')
    expect(store.dirty).toBe(true)
    expect(store.migrationTrail).toHaveLength(1)

    vi.mocked(api.get).mockResolvedValueOnce({
      workflow: document,
      migration_trail: [],
      read_only: true,
      warnings: [{ code: 'FUTURE_NODE_VERSION', message: 'A newer node version is required.' }],
    })
    await store.openWorkflow('wf_ABC123')
    expect(store.readOnly).toBe(true)
    expect(store.saveBlockedReason).toContain('newer node version')
    expect(store.addNode('script.input', { x: 0, y: 0 })).toBe(false)
    const putSpy = vi.spyOn(api, 'put')
    await expect(store.saveWorkflow()).rejects.toThrow('newer node version')
    expect(putSpy).not.toHaveBeenCalled()
  })

  it('loads the built-in template as a dirty unsaved workflow', () => {
    const store = seededStore()
    store.templates = [{
      template_id: 'full_video',
      workflow: {
        schema_version: 1,
        name: 'Full Video',
        nodes: [], edges: [], variables: {},
        viewport: { x: 0, y: 0, zoom: 1 },
        settings: { on_error: 'stop' }, extensions: {},
      },
    }]
    expect(store.applyTemplate('full_video')).toBe(true)
    expect(store.workflowId).toBeNull()
    expect(store.workflowName).toBe('Full Video')
    expect(store.dirty).toBe(true)
  })

  // ── Default canvas (step 12.2) ─────────────────────────────────────────
  const FULL_VIDEO_TEMPLATE = {
    template_id: 'full_video',
    workflow: {
      schema_version: 1,
      name: 'Full Video',
      nodes: [{
        id: 'n_script', type: 'script.input', type_version: 1, name: 'Script',
        position: { x: 0, y: 0 }, configuration: { text: '' }, disabled: false,
      }],
      edges: [], variables: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      settings: { on_error: 'stop' }, extensions: {},
    },
  }

  function savedFullVideo() {
    return { ...FULL_VIDEO_TEMPLATE.workflow, workflow_id: 'wf_SEED01' }
  }

  it('opens the seeded workflow instead of an empty canvas', async () => {
    const store = seededStore()
    store.templates = [FULL_VIDEO_TEMPLATE]
    store.workflowList = [{ workflow_id: 'wf_SEED01', name: 'Full Video' }]
    vi.spyOn(api, 'get').mockResolvedValue({ workflow: savedFullVideo(), migration_trail: [] })

    expect(await store.openDefaultWorkflow()).toBe(true)
    expect(api.get).toHaveBeenCalledWith('/api/workflows/wf_SEED01')
    expect(store.workflowId).toBe('wf_SEED01')
    expect(store.nodes).toHaveLength(1)
    expect(store.dirty).toBe(false)
  })

  it('falls back to the Full Video template when nothing is saved', async () => {
    const store = seededStore()
    store.templates = [FULL_VIDEO_TEMPLATE]
    store.workflowList = []
    const getSpy = vi.spyOn(api, 'get')

    expect(await store.openDefaultWorkflow()).toBe(true)
    expect(getSpy).not.toHaveBeenCalled()
    expect(store.workflowName).toBe('Full Video')
    expect(store.workflowId).toBeNull()
    // The user asked for nothing, so leaving must not prompt about changes.
    expect(store.dirty).toBe(false)
  })

  it('still fills the canvas when the newest saved workflow will not open', async () => {
    const store = seededStore()
    store.templates = [FULL_VIDEO_TEMPLATE]
    store.workflowList = [{ workflow_id: 'wf_BROKEN', name: 'Broken' }]
    vi.spyOn(api, 'get').mockRejectedValue(new Error('boom'))

    expect(await store.openDefaultWorkflow()).toBe(true)
    expect(store.nodes).toHaveLength(1)
    expect(store.workflowId).toBeNull()
  })

  it('never replaces work that is already on the canvas', async () => {
    const store = seededStore()
    store.templates = [FULL_VIDEO_TEMPLATE]
    store.workflowList = [{ workflow_id: 'wf_SEED01', name: 'Full Video' }]
    store.addNode('tts.generate', { x: 10, y: 10 })
    const getSpy = vi.spyOn(api, 'get')

    expect(await store.openDefaultWorkflow()).toBe(false)
    expect(getSpy).not.toHaveBeenCalled()
    expect(store.nodes).toHaveLength(1)
    expect(store.nodes[0].type).toBe('tts.generate')
  })
})

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import {
  useWorkflowStore,
  DRAFT_STORAGE_KEY,
  DRAFT_DEBOUNCE_MS,
} from '../stores/workflow.js'
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
}

function seededStore() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = FAKE_TYPES
  return store
}

function storedDraft() {
  const raw = localStorage.getItem(DRAFT_STORAGE_KEY)
  return raw ? JSON.parse(raw) : null
}

describe('workflow draft autosave (step 2.4)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('writes a debounced draft after a mutation', () => {
    const store = seededStore()
    store.addNode('script.input', { x: 0, y: 0 })
    expect(store.dirty).toBe(true)
    expect(storedDraft()).toBeNull()

    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS)
    const draft = storedDraft()
    expect(draft.version).toBe(1)
    expect(draft.saved_at).toBeTruthy()
    expect(draft.document.nodes).toHaveLength(1)
    expect(store.draftSavedAt).toBe(draft.saved_at)
  })

  it('coalesces rapid mutations into a single trailing write', () => {
    const store = seededStore()
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const node = store.addNode('script.input', { x: 0, y: 0 })
    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS - 1)
    store.renameNode(node.id, 'Renamed mid-burst')
    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS - 1)
    expect(setItem).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(setItem).toHaveBeenCalledTimes(1)
    expect(storedDraft().document.nodes[0].name).toBe('Renamed mid-burst')
  })

  it('flushDraft writes immediately while dirty and is a no-op when clean', () => {
    const store = seededStore()
    expect(store.flushDraft()).toBe(false)
    expect(storedDraft()).toBeNull()

    store.addNode('script.input', { x: 0, y: 0 })
    expect(store.flushDraft()).toBe(true)
    expect(storedDraft().document.nodes).toHaveLength(1)
  })

  it('explicit save clears dirty state, removes the draft, and disarms the timer', async () => {
    const store = seededStore()
    store.addNode('script.input', { x: 0, y: 0 })
    store.flushDraft()
    expect(storedDraft()).not.toBeNull()

    vi.spyOn(api, 'post').mockResolvedValue({
      workflow: {
        ...store.toDocument(),
        workflow_id: 'wf_ABC123',
        created_at: 'created',
        updated_at: 'v1',
      },
    })
    vi.spyOn(api, 'get').mockResolvedValue({ workflows: [], total: 0 })
    await store.saveWorkflow()

    expect(store.dirty).toBe(false)
    expect(store.draftSavedAt).toBeNull()
    expect(storedDraft()).toBeNull()
    // A pending debounce from before the save must not resurrect the draft.
    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS * 2)
    expect(storedDraft()).toBeNull()
  })

  it('applying a clean document from disk supersedes the stored draft', () => {
    const store = seededStore()
    store.addNode('script.input', { x: 0, y: 0 })
    store.flushDraft()
    expect(storedDraft()).not.toBeNull()

    store.applyDocument({
      schema_version: 1,
      workflow_id: 'wf_ABC123',
      name: 'From disk',
      nodes: [],
      edges: [],
      variables: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      settings: { on_error: 'stop' },
      extensions: {},
      created_at: 'created',
      updated_at: 'v1',
    })
    expect(store.dirty).toBe(false)
    expect(storedDraft()).toBeNull()
    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS * 2)
    expect(storedDraft()).toBeNull()
  })

  it('recovers a draft into a fresh store as a dirty unsaved document', () => {
    const editing = seededStore()
    const node = editing.addNode('script.input', { x: 40, y: 80 })
    editing.renameNode(node.id, 'Survivor')
    editing.workflowName = 'Killed mid-edit'
    editing.flushDraft()

    // Simulate the tab dying and the page reopening with a fresh store.
    setActivePinia(createPinia())
    const reopened = seededStore()
    expect(reopened.nodes).toHaveLength(0)

    const draft = reopened.peekDraft()
    expect(draft.document.name).toBe('Killed mid-edit')
    expect(reopened.recoverDraft()).toBe(true)
    expect(reopened.workflowName).toBe('Killed mid-edit')
    expect(reopened.nodes[0].name).toBe('Survivor')
    expect(reopened.nodes[0].position).toEqual({ x: 40, y: 80 })
    expect(reopened.dirty).toBe(true)
    expect(reopened.draftSavedAt).toBe(draft.saved_at)
  })

  it('recovery keeps workflow identity so save updates the original workflow', () => {
    const editing = seededStore()
    editing.applyDocument({
      schema_version: 1,
      workflow_id: 'wf_XYZ789',
      name: 'Saved workflow',
      nodes: [],
      edges: [],
      variables: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      settings: { on_error: 'stop' },
      extensions: {},
      created_at: 'created',
      updated_at: 'v3',
    })
    editing.addNode('script.input', { x: 0, y: 0 })
    editing.flushDraft()

    setActivePinia(createPinia())
    const reopened = seededStore()
    expect(reopened.recoverDraft()).toBe(true)
    expect(reopened.workflowId).toBe('wf_XYZ789')
    expect(reopened.updatedAt).toBe('v3')
    expect(reopened.dirty).toBe(true)
  })

  it('drops corrupt drafts instead of recovering them', () => {
    localStorage.setItem(DRAFT_STORAGE_KEY, '{not valid json')
    const store = seededStore()
    expect(store.peekDraft()).toBeNull()
    expect(localStorage.getItem(DRAFT_STORAGE_KEY)).toBeNull()

    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify({ version: 1 }))
    expect(store.peekDraft()).toBeNull()
    expect(store.recoverDraft()).toBe(false)
  })

  it('clearDraft removes the draft and resets the saved marker', () => {
    const store = seededStore()
    store.addNode('script.input', { x: 0, y: 0 })
    store.flushDraft()
    expect(store.draftSavedAt).toBeTruthy()

    store.clearDraft()
    expect(store.draftSavedAt).toBeNull()
    expect(storedDraft()).toBeNull()
  })
})

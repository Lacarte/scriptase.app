import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { useWorkflowStore, RECENT_NODE_TYPES_KEY } from '../stores/workflow.js'
import NodeLibrary from '../components/NodeLibrary.vue'

const TYPES = {
  'script.input': {
    type: 'script.input', type_version: 1, display_name: 'Script Input',
    description: 'Enter a script', category: 'input', icon: 'file-text', config_schema: [],
  },
  'tts.generate': {
    type: 'tts.generate', type_version: 1, display_name: 'Text to Speech',
    description: 'Generate narration', category: 'audio', icon: 'mic', config_schema: [],
  },
}

function seededStore() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = TYPES
  store.categories = {
    input: { label: 'Input', color: '#60a5fa' },
    audio: { label: 'Audio', color: '#a78bfa' },
  }
  return store
}

describe('workflow notes and recently used nodes', () => {
  let pinia
  beforeEach(() => {
    localStorage.clear()
    pinia = createPinia()
    setActivePinia(pinia)
  })

  it('persists sticky notes in extensions and round-trips edits through undo/redo', () => {
    const store = seededStore()
    const note = store.addNote({ x: 31, y: 49 }, 'Remember this')

    expect(note.position).toEqual({ x: 40, y: 40 })
    expect(store.toDocument().extensions.notes[0].text).toBe('Remember this')

    store.updateNote(note.id, { text: 'Updated', color: 'blue' })
    store.moveNotes([{ id: note.id, position: { x: 120, y: 80 } }])
    expect(store.noteById(note.id)).toMatchObject({ text: 'Updated', color: 'blue', position: { x: 120, y: 80 } })
    expect(store.undo()).toBe(true)
    expect(store.noteById(note.id).position).toEqual({ x: 40, y: 40 })
    expect(store.redo()).toBe(true)
    expect(store.noteById(note.id).position).toEqual({ x: 120, y: 80 })

    const document = store.toDocument()
    store.applyDocument(document)
    expect(store.noteById(note.id).text).toBe('Updated')
  })

  it('keeps the five most recently used node types, newest first', () => {
    const store = seededStore()
    store.recordNodeUse('script.input')
    store.recordNodeUse('tts.generate')
    store.recordNodeUse('script.input')

    expect(store.recentNodeTypes).toEqual(['script.input', 'tts.generate'])
    expect(JSON.parse(localStorage.getItem(RECENT_NODE_TYPES_KEY))).toEqual([
      'script.input', 'tts.generate',
    ])
  })

  it('renders a Recently used section in the library', () => {
    const store = seededStore()
    store.recordNodeUse('tts.generate')
    const wrapper = mount(NodeLibrary, { global: { plugins: [pinia] } })

    expect(wrapper.text()).toContain('Recently used')
    expect(wrapper.find('.library-recent').text()).toContain('Text to Speech')
  })

  it('clears recently used nodes from the library and local storage', async () => {
    const store = seededStore()
    store.recordNodeUse('tts.generate')
    const wrapper = mount(NodeLibrary, { global: { plugins: [pinia] } })

    await wrapper.get('.library-recent-clear').trigger('click')

    expect(store.recentNodeTypes).toEqual([])
    expect(localStorage.getItem(RECENT_NODE_TYPES_KEY)).toBeNull()
    expect(wrapper.find('.library-recent').exists()).toBe(false)
  })
})

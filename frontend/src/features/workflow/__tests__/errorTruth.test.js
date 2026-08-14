import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

// Step 6.4 — client error-truth: the {error:{code,message}} envelope is
// surfaced on every store API path, Save is blocked with a visible reason
// while any JSON widget holds invalid text, and the number widget's DOM
// always matches state.

vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn() }))
vi.mock('@vue-flow/core', () => ({
  MarkerType: { ArrowClosed: 'arrow' },
  useVueFlow: () => ({
    screenToFlowCoordinate: (point) => point,
    fitView: vi.fn(),
    setViewport: vi.fn(async () => {}),
  }),
  VueFlow: defineComponent({
    name: 'VueFlow',
    setup(_props, { slots }) {
      return () => h('div', { class: 'vue-flow__pane' }, [slots.default?.()])
    },
  }),
}))
vi.mock('@vue-flow/background', () => ({ Background: defineComponent(() => () => h('div')) }))
vi.mock('@vue-flow/controls', () => ({ Controls: defineComponent(() => () => h('div')) }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: defineComponent(() => () => h('div')) }))

import { api } from '@/shared/api/client.js'
import { apiErrorText } from '@/shared/api/errors.js'
import { useWorkflowStore } from '../stores/workflow.js'
import ConfigField from '../components/ConfigField.vue'
import NodeInspector from '../components/NodeInspector.vue'
import WorkflowPage from '../views/WorkflowPage.vue'

const TYPES = {
  'tts.generate': {
    type: 'tts.generate',
    type_version: 1,
    display_name: 'Text to Speech',
    category: 'audio',
    icon: 'mic',
    inputs: [],
    outputs: [],
    config_schema: [
      { name: 'speed', label: 'Speed', type: 'number', default: 1, min: 0.5, max: 2, step: 0.1 },
      { name: 'provider_options', label: 'Provider options', type: 'json', default: {} },
    ],
  },
}

function envelopeError(code, message, status = 422) {
  return Object.assign(new Error(message), { code, status })
}

function seededStore() {
  const store = useWorkflowStore()
  store.registryVersion = 1
  store.nodeTypes = TYPES
  store.categories = { audio: { label: 'Audio', color: '#A78BFA' } }
  return store
}

describe('api client parses the standard error envelope', () => {
  afterEach(() => vi.unstubAllGlobals())

  function stubFetch(response) {
    const impl = vi.fn(async () => response)
    vi.stubGlobal('fetch', impl)
    return impl
  }

  it('surfaces code, message, status, and details from the envelope', async () => {
    stubFetch({
      ok: false,
      status: 409,
      text: async () => JSON.stringify({
        error: { code: 'WORKFLOW_CONFLICT', message: 'Workflow was modified by another writer', details: { expected: 'v1' } },
      }),
    })
    const err = await api.put('/api/workflows/wf_A', { body: {} }).catch((e) => e)
    expect(err).toBeInstanceOf(Error)
    expect(err.message).toBe('Workflow was modified by another writer')
    expect(err.code).toBe('WORKFLOW_CONFLICT')
    expect(err.status).toBe(409)
    expect(err.details).toEqual({ expected: 'v1' })
  })

  it('falls back to the raw body for non-envelope failures', async () => {
    stubFetch({ ok: false, status: 502, text: async () => 'Bad gateway' })
    const err = await api.get('/api/workflows').catch((e) => e)
    expect(err.message).toContain('502')
    expect(err.message).toContain('Bad gateway')
    expect(err.code).toBeUndefined()
    expect(err.status).toBe(502)
  })

  it('returns parsed JSON bodies on success', async () => {
    stubFetch({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ workflows: [] }),
    })
    await expect(api.get('/api/workflows')).resolves.toEqual({ workflows: [] })
  })
})

describe('store API paths surface envelope errors', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })
  afterEach(() => vi.restoreAllMocks())

  it('apiErrorText includes the stable code when present', () => {
    expect(apiErrorText(envelopeError('WORKFLOW_INVALID', 'Bad graph'), 'fallback'))
      .toBe('Bad graph [WORKFLOW_INVALID]')
    expect(apiErrorText(new Error('plain failure'), 'fallback')).toBe('plain failure')
    expect(apiErrorText(undefined, 'fallback')).toBe('fallback')
  })

  it('openWorkflow surfaces the envelope in persistenceError', async () => {
    const store = seededStore()
    vi.spyOn(api, 'get').mockRejectedValue(envelopeError('WORKFLOW_NOT_FOUND', 'No such workflow', 404))
    await expect(store.openWorkflow('wf_missing')).rejects.toThrow('No such workflow')
    expect(store.persistenceError).toBe('No such workflow [WORKFLOW_NOT_FOUND]')
  })

  it('saveWorkflow surfaces the envelope on create and update', async () => {
    const store = seededStore()
    store.addNode('tts.generate', { x: 0, y: 0 })
    vi.spyOn(api, 'post').mockRejectedValue(envelopeError('WORKFLOW_INVALID', 'speed must be ≤ 2'))
    await expect(store.saveWorkflow()).rejects.toThrow('speed must be ≤ 2')
    expect(store.persistenceError).toBe('speed must be ≤ 2 [WORKFLOW_INVALID]')

    store.workflowId = 'wf_A'
    vi.spyOn(api, 'put').mockRejectedValue(envelopeError('WORKFLOW_CONFLICT', 'Modified elsewhere', 409))
    await expect(store.saveWorkflow()).rejects.toThrow('Modified elsewhere')
    expect(store.persistenceError).toBe('Modified elsewhere [WORKFLOW_CONFLICT]')
  })

  it('saveAs surfaces the envelope in persistenceError', async () => {
    const store = seededStore()
    vi.spyOn(api, 'post').mockRejectedValue(envelopeError('REQUEST_TOO_LARGE', 'Body exceeds 2 MiB', 413))
    await expect(store.saveAs('Copy')).rejects.toThrow('Body exceeds 2 MiB')
    expect(store.persistenceError).toBe('Body exceeds 2 MiB [REQUEST_TOO_LARGE]')
  })

  it('importDocument surfaces the envelope in persistenceError', async () => {
    const store = seededStore()
    vi.spyOn(api, 'post').mockRejectedValue(envelopeError('WORKFLOW_INVALID', 'Unknown node type'))
    await expect(store.importDocument({ schema_version: 1 })).rejects.toThrow('Unknown node type')
    expect(store.persistenceError).toBe('Unknown node type [WORKFLOW_INVALID]')
  })

  it('refreshWorkflowList surfaces the envelope instead of throwing raw', async () => {
    const store = seededStore()
    vi.spyOn(api, 'get').mockRejectedValue(envelopeError('INTERNAL_ERROR', 'Listing failed', 500))
    await expect(store.refreshWorkflowList()).rejects.toThrow('Listing failed')
    expect(store.persistenceError).toBe('Listing failed [INTERNAL_ERROR]')
  })

  it('loadTemplates surfaces the envelope instead of throwing raw', async () => {
    const store = seededStore()
    vi.spyOn(api, 'get').mockRejectedValue(envelopeError('INTERNAL_ERROR', 'Templates unavailable', 500))
    await expect(store.loadTemplates()).rejects.toThrow('Templates unavailable')
    expect(store.persistenceError).toBe('Templates unavailable [INTERNAL_ERROR]')
  })

  it('loadNodeTypes surfaces the envelope in registryError', async () => {
    const store = useWorkflowStore()
    vi.spyOn(api, 'get').mockRejectedValue(envelopeError('INTERNAL_ERROR', 'Registry offline', 500))
    await store.loadNodeTypes()
    expect(store.registryError).toBe('Registry offline [INTERNAL_ERROR]')
  })

  it('runWorkflow surfaces the envelope in executionError', async () => {
    const store = seededStore()
    store.addNode('tts.generate', { x: 0, y: 0 })
    vi.spyOn(api, 'post').mockRejectedValue(envelopeError('PROJECT_LOCKED', 'Project already running', 409))
    await expect(store.runWorkflow()).rejects.toThrow('Project already running')
    expect(store.executionError).toBe('Project already running [PROJECT_LOCKED]')
  })

  it('stopExecution surfaces the envelope in executionError', async () => {
    const store = seededStore()
    store.currentExecution = { execution_id: 'ex_1', status: 'running', nodes: {} }
    vi.spyOn(api, 'post').mockRejectedValue(envelopeError('EXECUTION_NOT_FOUND', 'Unknown execution', 404))
    await expect(store.stopExecution()).rejects.toThrow('Unknown execution')
    expect(store.executionError).toBe('Unknown execution [EXECUTION_NOT_FOUND]')
  })

  it('refreshExecution surfaces the envelope in executionError', async () => {
    const store = seededStore()
    vi.spyOn(api, 'get').mockRejectedValue(envelopeError('EXECUTION_NOT_FOUND', 'Unknown execution', 404))
    await expect(store.refreshExecution('ex_missing')).rejects.toThrow('Unknown execution')
    expect(store.executionError).toBe('Unknown execution [EXECUTION_NOT_FOUND]')
  })

  it('refreshExecutionHistory surfaces the envelope in executionHistoryError', async () => {
    const store = seededStore()
    vi.spyOn(api, 'get').mockRejectedValue(envelopeError('VALIDATION_ERROR', 'Bad workflow_id', 400))
    await expect(store.refreshExecutionHistory('wf_A')).rejects.toThrow('Bad workflow_id')
    expect(store.executionHistoryError).toBe('Bad workflow_id [VALIDATION_ERROR]')
  })
})

describe('invalid JSON widgets block Save with a visible reason', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })
  afterEach(() => vi.restoreAllMocks())

  it('reportInvalidField drives saveBlockedReason and prefix clearing', () => {
    const store = seededStore()
    expect(store.saveBlockedReason).toBe('')
    store.reportInvalidField('n_1:opts', 'Fix invalid JSON in "A" → "opts" before saving')
    expect(store.saveBlockedReason).toBe('Fix invalid JSON in "A" → "opts" before saving')
    store.reportInvalidField('workflow:variables', 'Fix the workflow variables JSON before saving')
    expect(store.saveBlockedReason).toContain('(and 1 more invalid field)')
    store.clearInvalidFields('n_1:')
    expect(store.saveBlockedReason).toBe('Fix the workflow variables JSON before saving')
    store.reportInvalidField('workflow:variables', '')
    expect(store.saveBlockedReason).toBe('')
  })

  it('saveWorkflow and saveAs refuse without calling the API while blocked', async () => {
    const store = seededStore()
    store.addNode('tts.generate', { x: 0, y: 0 })
    store.reportInvalidField('n_1:provider_options', 'Fix invalid JSON in "TTS" → "Provider options" before saving')
    const post = vi.spyOn(api, 'post')
    await expect(store.saveWorkflow()).rejects.toThrow('Fix invalid JSON')
    await expect(store.saveAs('Copy')).rejects.toThrow('Fix invalid JSON')
    expect(post).not.toHaveBeenCalled()
    expect(store.persistenceError).toContain('Fix invalid JSON')
  })

  it('applyDocument releases every block (widgets remount)', () => {
    const store = seededStore()
    store.reportInvalidField('n_1:opts', 'reason')
    store.applyDocument({ schema_version: 1, name: 'Fresh', nodes: [], edges: [] })
    expect(store.saveBlockedReason).toBe('')
  })

  it('ConfigField emits invalid on bad JSON, null on fix and on unmount', async () => {
    const field = { name: 'opts', label: 'Opts', type: 'json', default: {} }
    const wrapper = mount(ConfigField, { props: { field, value: { a: 1 } } })
    const area = wrapper.get('textarea')
    await area.setValue('{ bad json')
    await area.trigger('blur')
    expect(wrapper.emitted('invalid').at(-1)).toEqual(['Invalid JSON — fix it before it can be saved'])
    await area.setValue('{"b": 2}')
    await area.trigger('blur')
    expect(wrapper.emitted('invalid').at(-1)).toEqual([null])

    await area.setValue('{ bad again')
    await area.trigger('blur')
    expect(wrapper.emitted('invalid').at(-1)[0]).toContain('Invalid JSON')
    wrapper.unmount()
    expect(wrapper.emitted('invalid').at(-1)).toEqual([null])
  })

  it('NodeInspector registers and releases the block against the store', async () => {
    const store = seededStore()
    const node = store.addNode('tts.generate', { x: 0, y: 0 })
    store.renameNode(node.id, 'Narration')
    store.selectNode(node.id)
    const wrapper = mount(NodeInspector)

    const area = wrapper.get('.cfg-json textarea')
    await area.setValue('{ bad json')
    await area.trigger('blur')
    expect(store.saveBlockedReason)
      .toBe('Fix invalid JSON in "Narration" → "Provider options" before saving')

    await area.setValue('{"ok": true}')
    await area.trigger('blur')
    expect(store.saveBlockedReason).toBe('')
    expect(store.nodeById(node.id).configuration.provider_options).toEqual({ ok: true })
    wrapper.unmount()
  })

  it('deselecting the node discards its invalid text and the block', async () => {
    const store = seededStore()
    const node = store.addNode('tts.generate', { x: 0, y: 0 })
    store.selectNode(node.id)
    const wrapper = mount(NodeInspector)
    const area = wrapper.get('.cfg-json textarea')
    await area.setValue('{ bad json')
    await area.trigger('blur')
    expect(store.saveBlockedReason).not.toBe('')

    store.clearSelection()
    await nextTick()
    expect(store.saveBlockedReason).toBe('')
    wrapper.unmount()
  })

  it('the workflow variables editor blocks Save while invalid', async () => {
    const store = seededStore()
    const node = store.addNode('tts.generate', { x: 0, y: 0 })
    store.selectNode(node.id)
    const wrapper = mount(NodeInspector)
    const editor = wrapper.get('.variables-editor')
    await editor.setValue('[1, 2]')
    await editor.trigger('blur')
    expect(store.saveBlockedReason).toBe('Fix the workflow variables JSON before saving')

    await editor.setValue('{"tone": "calm"}')
    await editor.trigger('blur')
    expect(store.saveBlockedReason).toBe('')
    expect(store.variables).toEqual({ tone: 'calm' })
    wrapper.unmount()
  })

  it('WorkflowPage disables Save and shows the reason while blocked', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path) => path === '/api/workflows'
      ? { workflows: [] }
      : path === '/api/workflow/templates'
        ? { templates: [] }
        : {})
    const store = seededStore()
    const wrapper = mount(WorkflowPage, {
      global: {
        stubs: { NodeLibrary: true, NodeInspector: true, NodeCard: true, ExecutionPanel: true },
      },
    })
    await flushPromises()
    const save = wrapper.findAll('.wf-btn.primary').find((btn) => btn.text() === 'Save')
    expect(save.element.disabled).toBe(false)

    const reason = 'Fix invalid JSON in "Narration" → "Provider options" before saving'
    store.reportInvalidField('n_1:provider_options', reason)
    await nextTick()
    expect(save.element.disabled).toBe(true)
    expect(wrapper.get('.wf-save-blocked').text()).toBe(reason)

    store.reportInvalidField('n_1:provider_options', '')
    await nextTick()
    expect(save.element.disabled).toBe(false)
    expect(wrapper.find('.wf-save-blocked').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('number widget DOM stays in sync with state', () => {
  it('re-displays the clamped value even when state does not change', async () => {
    const field = { name: 'speed', label: 'Speed', type: 'number', default: 1, min: 0.5, max: 2, step: 0.1 }
    const wrapper = mount(ConfigField, { props: { field, value: 2 } })
    const input = wrapper.get('input[type="number"]')
    input.element.value = '5'
    await input.trigger('change')
    // Clamped to the stored value: no update, but the DOM must not keep "5".
    expect(wrapper.emitted('update')).toBeUndefined()
    expect(input.element.value).toBe('2')
  })

  it('restores the stored value when the input is cleared or unparseable', async () => {
    const field = { name: 'speed', label: 'Speed', type: 'number', default: 1, min: 0.5, max: 2, step: 0.1 }
    const wrapper = mount(ConfigField, { props: { field, value: 1.5 } })
    const input = wrapper.get('input[type="number"]')
    input.element.value = ''
    await input.trigger('change')
    expect(wrapper.emitted('update')).toBeUndefined()
    expect(input.element.value).toBe('1.5')
  })

  it('clamps and emits when the value actually changes', async () => {
    const field = { name: 'speed', label: 'Speed', type: 'number', default: 1, min: 0.5, max: 2, step: 0.1 }
    const wrapper = mount(ConfigField, { props: { field, value: 1 } })
    const input = wrapper.get('input[type="number"]')
    input.element.value = '5'
    await input.trigger('change')
    expect(wrapper.emitted('update').at(-1)).toEqual([2])
    expect(input.element.value).toBe('2')
  })
})

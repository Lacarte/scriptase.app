import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WebhookSettings from '../components/WebhookSettings.vue'
import { useWorkflowStore } from '../stores/workflow.js'

describe('WebhookSettings', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('loads the private URL and persists typed payload mappings', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => 'application/json' },
      json: async () => ({ token: 'a'.repeat(43), path: `/api/workflow/hooks/wf_ABC123/${'a'.repeat(43)}` }),
    }))
    const store = useWorkflowStore()
    store.workflowId = 'wf_ABC123'
    store.nodeTypes = {
      'tts.generate': {
        inputs: [
          { id: 'trigger', type: 'control' },
          { id: 'script', type: 'script', required: true },
        ],
      },
    }
    store.nodes = [{
      id: 'tts', type: 'tts.generate', name: 'Narration', disabled: false, configuration: {},
    }]
    const wrapper = mount(WebhookSettings)
    await flushPromises()

    expect(wrapper.find('input.url').element.value).toContain('/api/workflow/hooks/wf_ABC123/')
    const add = wrapper.findAll('button').find((button) => button.text() === 'Add mapping')
    await add.trigger('click')
    const path = wrapper.find('.mapping input:not([type="checkbox"])')
    await path.setValue('story.text')
    await path.trigger('change')
    await wrapper.find('input[type="checkbox"]').setValue(true)

    expect(store.toDocument().settings.webhook).toEqual({
      enabled: true,
      mappings: [{
        payload_path: 'story.text', target_node_id: 'tts', target_port: 'script', required: true,
      }],
    })
    expect(store.dirty).toBe(true)
  })

  it('requires a saved workflow before exposing a token', () => {
    const store = useWorkflowStore()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(WebhookSettings)
    expect(wrapper.text()).toContain('Save this workflow')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

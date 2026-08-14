import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WatchFolderSettings from '../components/WatchFolderSettings.vue'
import { useWorkflowStore } from '../stores/workflow.js'

describe('WatchFolderSettings', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('persists the folder trigger and marks the workflow dirty', async () => {
    const store = useWorkflowStore()
    store.nodeTypes = {
      'script.input': {
        type_version: 1,
        inputs: [{ id: 'trigger', type: 'control' }],
        outputs: [{ id: 'script', type: 'script' }],
        config_schema: [],
      },
    }
    store.nodes = [{
      id: 'script', type: 'script.input', type_version: 1, name: 'Script Input',
      position: { x: 0, y: 0 }, configuration: { text: 'fallback' }, disabled: false,
    }]
    const wrapper = mount(WatchFolderSettings)

    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('input.path').setValue('D:\\Automation\\incoming')
    await wrapper.find('input.path').trigger('change')

    expect(store.dirty).toBe(true)
    expect(store.toDocument().settings.watch_folder).toEqual({
      enabled: true,
      folder: 'D:\\Automation\\incoming',
      pattern: '*.txt',
      target_node_id: '',
      target_port: '',
    })
    expect(wrapper.text()).toContain('processed/')
  })
})

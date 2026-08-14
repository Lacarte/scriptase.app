import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/shared/api/client.js'
import ScheduleSettings from '../components/ScheduleSettings.vue'
import { useWorkflowStore } from '../stores/workflow.js'

function savedWorkflow() {
  return {
    schema_version: 1,
    workflow_id: 'wf_ABC123',
    name: 'Scheduled', description: '', nodes: [], edges: [], variables: {},
    viewport: { x: 0, y: 0, zoom: 1 },
    settings: {
      on_error: 'stop',
      schedules: [{ id: 'sch_daily', cron: '0 9 * * *', enabled: true }],
    },
    extensions: {}, created_at: 'created', updated_at: 'v1',
  }
}

describe('ScheduleSettings', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('shows the server next-fire time and persists enable changes in settings', async () => {
    const store = useWorkflowStore()
    store.applyDocument(savedWorkflow())
    vi.spyOn(api, 'get').mockResolvedValue({
      timezone: 'UTC',
      schedules: [{
        id: 'sch_daily', cron: '0 9 * * *', enabled: true,
        next_fire_at: '2026-08-06T09:00:00Z', timezone: 'UTC',
      }],
    })
    const wrapper = mount(ScheduleSettings)
    await vi.waitFor(() => expect(wrapper.text()).toContain('8/6/2026'))

    await wrapper.find('input[type="checkbox"]').setValue(false)
    expect(store.settings.schedules[0].enabled).toBe(false)
    expect(store.dirty).toBe(true)
    expect(wrapper.text()).toContain('Save to calculate')
    expect(store.toDocument().settings.schedules[0]).toEqual({
      id: 'sch_daily', cron: '0 9 * * *', enabled: false,
    })
  })
})

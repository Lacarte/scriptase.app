import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NotificationCenter from '../components/NotificationCenter.vue'
import { useWorkflowStore } from '../stores/workflow.js'

describe('NotificationCenter', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('shows persisted records, clears unseen state, and edits settings', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true, headers: { get: () => 'application/json' },
        json: async () => ({ unseen: 1, notifications: [{
          notification_id: 'nt_ABC123', execution_id: 'ex_ABC123', outcome: 'failure',
          message: 'Notify test failed', created_at: '2026-08-05T12:00:00Z', seen: false,
        }] }),
      })
      .mockResolvedValueOnce({
        ok: true, headers: { get: () => 'application/json' },
        json: async () => ({ seen: true, updated: 1 }),
      })
    vi.stubGlobal('fetch', fetchMock)
    const store = useWorkflowStore()
    store.workflowId = 'wf_ABC123'
    const wrapper = mount(NotificationCenter)
    await flushPromises()

    expect(wrapper.text()).toContain('Notify test failed')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/workflow/notifications/seen')
    const success = wrapper.findAll('label').find((label) => label.text().includes('Successful runs'))
    await success.find('input').setValue(true)
    expect(store.settings.notifications.on_completion).toBe(true)
    expect(store.dirty).toBe(true)
  })
})

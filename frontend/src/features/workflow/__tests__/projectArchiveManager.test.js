import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import ProjectArchiveManager from '../components/ProjectArchiveManager.vue'
import { useWorkflowStore } from '../stores/workflow.js'

describe('ProjectArchiveManager', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    setActivePinia(createPinia())
  })

  it('lists projects and restores with explicit ID modes', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        headers: { get: () => 'application/json' },
        json: async () => ({ projects: [{
          project_id: 'pm_ABC123', execution_count: 2, last_run_at: '2026-08-05T12:00:00Z',
        }] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ workflow: { workflow_id: 'wf_NEW123' }, project_id: 'pm_NEW123' }),
      })
    vi.stubGlobal('fetch', fetchMock)
    const store = useWorkflowStore()
    store.workflowId = 'wf_ABC123'
    const wrapper = mount(ProjectArchiveManager, { global: { plugins: [] } })
    await flushPromises()

    expect(wrapper.text()).toContain('pm_ABC123')
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true, value: [new File(['archive'], 'backup.sts-project.zip')],
    })
    await input.trigger('change')
    await flushPromises()

    expect(fetchMock.mock.calls[1][0]).toBe('/api/workflow/projects/restore')
    const form = fetchMock.mock.calls[1][1].body
    expect(form.get('project_id_mode')).toBe('new')
    expect(form.get('workflow_id_mode')).toBe('new')
    expect(wrapper.emitted('restored')[0]).toEqual(['wf_NEW123', 'pm_NEW123'])
  })
})

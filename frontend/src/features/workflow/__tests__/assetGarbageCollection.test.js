import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AssetGarbageCollection from '../components/AssetGarbageCollection.vue'

describe('AssetGarbageCollection', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('previews in dry-run mode and deletes only explicitly selected paths', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true, headers: { get: () => 'application/json' },
        json: async () => ({ count: 2, bytes: 15, orphans: [
          { path: 'media/a.bin', size: 5, modified_at: 1 },
          { path: 'media/b.bin', size: 10, modified_at: 2 },
        ] }),
      })
      .mockResolvedValueOnce({
        ok: true, headers: { get: () => 'application/json' },
        json: async () => ({ deleted: ['media/a.bin'], failures: [] }),
      })
      .mockResolvedValueOnce({
        ok: true, headers: { get: () => 'application/json' },
        json: async () => ({ count: 0, bytes: 0, orphans: [] }),
      })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => true))
    const wrapper = mount(AssetGarbageCollection)
    await flushPromises()

    expect(fetchMock.mock.calls[0][0]).toBe('/api/workflow/assets/orphans')
    const boxes = wrapper.findAll('input[type="checkbox"]')
    await boxes[1].setValue(false)
    await wrapper.find('button.delete').trigger('click')
    await flushPromises()

    const request = JSON.parse(fetchMock.mock.calls[1][1].body)
    expect(request).toEqual({ paths: ['media/a.bin'], dry_run: false })
    expect(wrapper.text()).toContain('No orphaned assets found')
  })
})

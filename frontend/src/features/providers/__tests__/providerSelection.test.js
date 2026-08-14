import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import { api } from '@/shared/api/client.js'

// Step 11.5 — selecting a provider is one targeted write to
// PUT /api/providers/<domain>/selection, not a read-modify-write of the whole
// settings document (contracts.md §24.2). Step 12.1 moved these guarantees from
// the useProviders composable onto the catalog store.

const CATALOG = {
  catalog_version: 'abc123',
  dev_reload_enabled: false,
  domains: {
    tts: {
      domain: 'tts',
      label: 'Text to Speech',
      default_provider: 'kokoro',
      selected: 'kokoro',
      count: 2,
      excluded: [],
      providers: [
        { id: 'kokoro', label: 'Kokoro', aliases: [], availability: 'available' },
        {
          id: 'inworld',
          label: 'Inworld',
          aliases: ['inworld-legacy'],
          availability: 'needs_configuration',
        },
      ],
    },
  },
}

async function loadedStore() {
  const store = useProviderCatalogStore()
  await store.loadCatalog()
  return store
}

describe('providerCatalog.selectProvider', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // A fresh copy per call: the store assigns `data.domains` straight into its
    // state, so a shared object would carry one test's mutation to the next.
    vi.spyOn(api, 'get').mockImplementation(async () => structuredClone(CATALOG))
    vi.spyOn(api, 'put').mockResolvedValue({})
    vi.spyOn(api, 'post').mockResolvedValue({})
  })

  afterEach(() => vi.restoreAllMocks())

  it('writes the selection through the targeted endpoint', async () => {
    api.put.mockResolvedValue({
      domain: 'tts',
      selected: 'inworld',
      availability: 'available',
      issues: [],
    })
    const store = await loadedStore()

    const result = await store.selectProvider('tts', 'inworld')

    expect(api.put).toHaveBeenCalledTimes(1)
    expect(api.put).toHaveBeenCalledWith('/api/providers/tts/selection', {
      body: { provider_id: 'inworld' },
    })
    expect(result).toMatchObject({ switched: true, needsConfiguration: false })
    expect(store.selectedId('tts')).toBe('inworld')
  })

  it('never reads or rewrites the whole settings document', async () => {
    api.put.mockResolvedValue({ selected: 'inworld', availability: 'available', issues: [] })
    const store = await loadedStore()

    await store.selectProvider('tts', 'inworld')

    expect(api.get.mock.calls.map(([path]) => path)).not.toContain('/api/settings/v2')
    expect(api.put.mock.calls.map(([path]) => path)).not.toContain('/api/settings/v2')
    // The separate validate round trip is gone: availability answers it (§21.5).
    expect(api.post).not.toHaveBeenCalled()
  })

  it('reports an unconfigured provider from availability, and still switches', async () => {
    api.put.mockResolvedValue({
      selected: 'inworld',
      availability: 'needs_configuration',
      issues: [{ field: 'api_key', severity: 'error', message: 'Required' }],
    })
    const store = await loadedStore()

    const result = await store.selectProvider('tts', 'inworld')

    expect(result.needsConfiguration).toBe(true)
    expect(result.availability).toBe('needs_configuration')
    expect(result.issues).toHaveLength(1)
    // Selection is non-blocking — the store reflects the server's answer.
    expect(store.selectedId('tts')).toBe('inworld')
  })

  it('stores the canonical id the server resolved, not the alias sent', async () => {
    api.put.mockResolvedValue({ selected: 'inworld', availability: 'available', issues: [] })
    const store = await loadedStore()

    await store.selectProvider('tts', 'inworld-legacy')

    expect(store.selectedId('tts')).toBe('inworld')
  })

  it('folds the answered availability back into the cached catalog', async () => {
    api.put.mockResolvedValue({ selected: 'inworld', availability: 'available', issues: [] })
    const store = await loadedStore()

    await store.selectProvider('tts', 'inworld')

    // Without this the dropdown would keep claiming the newly selected provider
    // needs configuration until the next full catalog fetch.
    expect(store.availabilityOf('tts', 'inworld')).toBe('available')
  })

  it('does not write when the provider is already selected', async () => {
    const store = await loadedStore()

    const result = await store.selectProvider('tts', 'kokoro')

    expect(result).toEqual({ switched: false })
    expect(api.put).not.toHaveBeenCalled()
  })

  it('propagates a failed selection instead of faking a switch', async () => {
    const failure = Object.assign(new Error('Provider not found'), {
      status: 404,
      code: 'PROVIDER_NOT_FOUND',
    })
    api.put.mockRejectedValue(failure)
    const store = await loadedStore()

    await expect(store.selectProvider('tts', 'ghost')).rejects.toThrow('Provider not found')
    expect(store.selectedId('tts')).toBe('kokoro')
  })
})

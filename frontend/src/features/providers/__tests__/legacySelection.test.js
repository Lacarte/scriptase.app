import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import { api } from '@/shared/api/client.js'

// Catalog selection is the only authority. The V2 app-config selection keys
// and the legacy pipeline selection mirrors are gone; Scriptase never ports
// settings/pipeline surfaces that used to own them.

const RETIRED_KEYS = [
  'sts-tts-provider',
  'sts-storyboard-provider',
  'sts-asset-provider',
]

function catalog({ selected = 'alpha' } = {}) {
  return {
    catalog_version: 'v1',
    dev_reload_enabled: false,
    domains: {
      demo: {
        domain: 'demo',
        label: 'Demo',
        default_provider: 'alpha',
        selected,
        count: 2,
        excluded: [],
        providers: [
          { id: 'alpha', label: 'Alpha', aliases: [], availability: 'available' },
          { id: 'beta', label: 'Beta', aliases: ['beta-legacy'], availability: 'available' },
        ],
      },
    },
  }
}

describe('legacy selection retirement', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.spyOn(api, 'get')
    vi.spyOn(api, 'put').mockResolvedValue({})
    vi.spyOn(api, 'patch').mockResolvedValue({})
  })

  afterEach(() => vi.restoreAllMocks())

  it('selects from the catalog alone when selected is set', async () => {
    api.get.mockResolvedValue(structuredClone(catalog({ selected: 'beta' })))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.selectedProvider('demo').id).toBe('beta')
  })

  it('falls back to the domain default when the catalog has no selection', async () => {
    api.get.mockResolvedValue(structuredClone(catalog({ selected: null })))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.selectedProvider('demo').id).toBe('alpha')
  })

  it('does not mirror a selection into app-config', async () => {
    api.get.mockResolvedValue(structuredClone(catalog({ selected: 'alpha' })))
    api.put.mockResolvedValue({ selected: 'beta', availability: 'available', issues: [] })
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    await store.selectProvider('demo', 'beta')

    expect(api.patch).not.toHaveBeenCalled()
    expect(store.selectedId('demo')).toBe('beta')
  })

  it('no longer exposes legacySelectionKey or legacyIdFor', async () => {
    api.get.mockResolvedValue(structuredClone(catalog()))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.legacySelectionKey).toBeUndefined()
    expect(store.legacyIdFor).toBeUndefined()
  })

  it('ported provider surfaces no longer name the retired app-config keys', () => {
    const files = [
      'src/features/providers/stores/providerCatalog.js',
      'src/features/providers/composables/useDomainProvider.js',
    ]
    for (const relative of files) {
      const source = readFileSync(resolve(process.cwd(), relative), 'utf8')
      for (const key of RETIRED_KEYS) {
        expect(source, `${relative} still names ${key}`).not.toContain(key)
      }
    }
  })
})

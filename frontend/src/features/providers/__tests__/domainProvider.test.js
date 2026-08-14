import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { useDomainProvider } from '../composables/useDomainProvider.js'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import { api } from '@/shared/api/client.js'

// Step 12.4 / 16.1 — which provider is selected and what it is configured with.
// Both answers come from the catalog; the wire spelling is the canonical id.

const CATALOG = {
  catalog_version: 'v1',
  dev_reload_enabled: false,
  domains: {
    demo: {
      domain: 'demo',
      label: 'Demo',
      default_provider: 'alpha',
      selected: 'alpha',
      count: 2,
      excluded: [],
      providers: [
        {
          id: 'alpha',
          label: 'Alpha',
          aliases: ['alpha-legacy'],
          availability: 'available',
          open_url: 'https://example.test/alpha',
          capabilities: { batch: true, image_to_video: true },
        },
        {
          id: 'beta',
          label: 'Beta',
          aliases: [],
          availability: 'available',
          open_url: null,
          capabilities: { batch: true },
        },
      ],
    },
  },
}

const SCHEMAS = {
  alpha: {
    type: 'object',
    properties: {
      api_key: { type: 'string', label: 'Key', default: '', ui: { type: 'password' } },
      mode: { type: 'string', label: 'Mode', default: 'video', ui: { type: 'dropdown' } },
      tries: { type: 'integer', label: 'Tries', default: 3 },
    },
  },
  beta: {
    type: 'object',
    properties: { model: { type: 'string', label: 'Model', default: 'b1' } },
  },
}

function settingsResponse(url) {
  const providerId = url.split('/')[4]
  return {
    provider_id: providerId,
    domain: 'demo',
    schema: SCHEMAS[providerId],
    // What the server actually returns for a stored secret (§22.6).
    settings: providerId === 'alpha' ? { api_key: '***', mode: 'image' } : {},
  }
}

async function mounted() {
  const domain = useDomainProvider('demo', { withSettings: true })
  await vi.waitUntil(() => domain.providerId.value !== '')
  await vi.waitUntil(() => !domain.settingsLoading.value)
  return domain
}

describe('useDomainProvider', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.endsWith('/settings') ? settingsResponse(url) : structuredClone(CATALOG),
    )
    vi.spyOn(api, 'put').mockResolvedValue({})
  })

  afterEach(() => vi.restoreAllMocks())

  it('reports the selected provider, its label, and its own URL', async () => {
    const domain = await mounted()

    expect(domain.providerId.value).toBe('alpha')
    expect(domain.label.value).toBe('Alpha')
    // The page opens what the manifest declares, not a URL table of its own.
    expect(domain.openUrl.value).toBe('https://example.test/alpha')
  })

  it('answers capability questions declaratively', async () => {
    const domain = await mounted()

    expect(domain.supports('image_to_video')).toBe(true)
    expect(domain.supports('cancel')).toBe(false)
  })

  it('exposes the canonical provider id, never a legacy wire alias', async () => {
    const domain = await mounted()

    expect(domain.providerId.value).toBe('alpha')
    expect(domain.legacyId).toBeUndefined()
  })

  it('overlays stored values on schema defaults and drops secrets', async () => {
    const domain = await mounted()

    expect(domain.settings.value).toEqual({ mode: 'image', tries: 3 })
    // A page has no use for a credential, and what it would get is the sentinel.
    expect(domain.settings.value).not.toHaveProperty('api_key')
  })

  it('re-reads settings when the selection changes', async () => {
    const domain = await mounted()
    const catalog = useProviderCatalogStore()
    api.put.mockResolvedValue({ selected: 'beta', availability: 'available', issues: [] })

    await catalog.selectProvider('demo', 'beta')
    await nextTick()
    await vi.waitUntil(() => domain.providerId.value === 'beta' && !domain.settingsLoading.value)

    // One provider's option keys must never survive into another's request.
    expect(domain.settings.value).toEqual({ model: 'b1' })
    expect(domain.providerId.value).toBe('beta')
  })

  it('leaves the values empty when settings cannot be read', async () => {
    api.get.mockImplementation(async (url) => {
      if (url.endsWith('/settings')) throw new Error('nope')
      return structuredClone(CATALOG)
    })
    const domain = useDomainProvider('demo', { withSettings: true })
    await vi.waitUntil(() => domain.providerId.value !== '')
    await vi.waitUntil(() => !domain.settingsLoading.value)

    expect(domain.settings.value).toEqual({})
  })

  it('costs no settings request when the caller does not need values', async () => {
    useDomainProvider('demo')
    await vi.waitUntil(() => useProviderCatalogStore().loaded)

    expect(api.get.mock.calls.every(([url]) => !url.endsWith('/settings'))).toBe(true)
  })
})

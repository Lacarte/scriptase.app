import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import ProviderSelector from '../components/ProviderSelector.vue'
import { api } from '@/shared/api/client.js'

// Step 12.1 — the catalog served by GET /api/providers is the only source of
// provider identity, grouping, and state on the frontend. A provider added,
// removed, or relabeled in the catalog must reach every surface without a
// frontend code change (contracts.md §25, §26).

function provider(id, overrides = {}) {
  return {
    id,
    label: id.toUpperCase(),
    domain: 'tts',
    aliases: [],
    capabilities: {},
    has_settings: true,
    availability: 'available',
    warnings: [],
    ...overrides,
  }
}

function catalog(version, { providers, selected = null, excluded = [], extraDomains = {} } = {}) {
  return {
    catalog_version: version,
    dev_reload_enabled: false,
    domains: {
      tts: {
        domain: 'tts',
        label: 'Text to Speech',
        default_provider: 'kokoro',
        selected,
        count: providers.length,
        excluded,
        providers,
      },
      ...extraDomains,
    },
  }
}

const BASE = catalog('v1', {
  providers: [provider('kokoro'), provider('inworld', { availability: 'needs_configuration' })],
  selected: 'kokoro',
})

function serve(payload) {
  return vi.spyOn(api, 'get').mockImplementation(async () => structuredClone(payload))
}

describe('provider catalog store', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  // ── Caching ────────────────────────────────────────────────────────────

  it('fetches the catalog once per session', async () => {
    serve(BASE)
    const store = useProviderCatalogStore()

    await store.loadCatalog()
    await store.loadCatalog()

    expect(api.get).toHaveBeenCalledTimes(1)
    expect(api.get).toHaveBeenCalledWith('/api/providers')
    expect(store.loaded).toBe(true)
  })

  it('shares one request between concurrent callers', async () => {
    serve(BASE)
    const store = useProviderCatalogStore()

    // Three selectors mounting together must not race three identical fetches.
    await Promise.all([store.loadCatalog(), store.loadCatalog(), store.loadCatalog()])

    expect(api.get).toHaveBeenCalledTimes(1)
  })

  it('keeps the cached objects when the version is unchanged', async () => {
    serve(BASE)
    const store = useProviderCatalogStore()
    await store.loadCatalog()
    const cached = store.domains

    await store.refresh()

    expect(api.get).toHaveBeenCalledTimes(2)
    // Same content version: no object churn, so downstream computeds hold.
    expect(store.domains).toBe(cached)
  })

  it('replaces the catalog when the version changes', async () => {
    serve(BASE)
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    serve(catalog('v2', { providers: [provider('kokoro')], selected: 'kokoro' }))
    await store.refresh()

    expect(store.catalogVersion).toBe('v2')
    expect(store.providersFor('tts').map(p => p.id)).toEqual(['kokoro'])
  })

  it('refetches the catalog after settings are saved', async () => {
    serve(BASE)
    vi.spyOn(api, 'put').mockResolvedValue({ ok: true, issues: [] })
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    // Filling in a required key flips availability; that is not derivable here.
    serve(catalog('v2', {
      providers: [provider('kokoro'), provider('inworld')],
      selected: 'kokoro',
    }))
    await store.saveProviderSettings('tts', 'inworld', { api_key: 'secret' })

    expect(api.put).toHaveBeenCalledWith('/api/providers/tts/inworld/settings', {
      body: { api_key: 'secret' },
    })
    expect(store.availabilityOf('tts', 'inworld')).toBe('available')
  })

  // ── Domain grouping and filtering ──────────────────────────────────────

  it('groups providers by domain and keeps domains apart', async () => {
    serve(catalog('v1', {
      providers: [provider('kokoro')],
      selected: 'kokoro',
      extraDomains: {
        animator: {
          domain: 'animator',
          label: 'Animator',
          default_provider: 'grok_automa',
          selected: 'grok_automa',
          count: 1,
          excluded: [],
          providers: [provider('grok_automa', { domain: 'animator' })],
        },
      },
    }))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.domainIds).toEqual(['animator', 'tts'])
    expect(store.providersFor('tts').map(p => p.id)).toEqual(['kokoro'])
    expect(store.providersFor('animator').map(p => p.id)).toEqual(['grok_automa'])
    expect(store.domainLabel('animator')).toBe('Animator')
  })

  it('answers empty for a domain the catalog does not carry', async () => {
    serve(BASE)
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.providersFor('scene_blueprint')).toEqual([])
    expect(store.catalogEntriesFor('scene_blueprint')).toEqual([])
    expect(store.selectedProvider('scene_blueprint')).toBeNull()
    // A domain with no registered provider is not an error, it is empty.
    expect(store.domainLabel('scene_blueprint')).toBe('scene_blueprint')
  })

  it('surfaces an excluded provider as unavailable rather than hiding it', async () => {
    serve(catalog('v1', {
      providers: [provider('kokoro')],
      selected: 'kokoro',
      excluded: [{ id: 'broken', reason_code: 'MANIFEST_LOAD_FAILED', message: 'boom' }],
    }))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.providersFor('tts').map(p => p.id)).toEqual(['kokoro'])
    expect(store.catalogEntriesFor('tts').map(p => p.id)).toEqual(['kokoro', 'broken'])
    expect(store.availabilityOf('tts', 'broken')).toBe('unavailable')
    expect(store.excludedFor('tts')[0]).toMatchObject({
      reason_code: 'MANIFEST_LOAD_FAILED',
      warnings: ['boom'],
    })
  })

  it('reads capabilities from the catalog, not from the provider id', async () => {
    serve(catalog('v1', {
      providers: [provider('kokoro', { capabilities: { streaming: true, batch: false } })],
      selected: 'kokoro',
    }))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.capabilitiesOf('tts', 'kokoro')).toEqual({ streaming: true, batch: false })
    expect(store.supports('tts', 'kokoro', 'streaming')).toBe(true)
    expect(store.supports('tts', 'kokoro', 'batch')).toBe(false)
    expect(store.supports('tts', 'kokoro', 'never_declared')).toBe(false)
  })

  it('never offers an undeclared capability (step 6.1)', async () => {
    // Provider row still carries a fantasy key that slipped past a stale cache;
    // the domain vocabulary is the closed set the UI may offer.
    serve({
      catalog_version: 'v1',
      domains: {
        image: {
          domain: 'image',
          label: 'Image',
          default_provider: 'wavespeed_direct',
          selected: 'wavespeed_direct',
          capability_vocabulary: ['text_to_image', 'image_edit', 'batch', 'test_connection'],
          providers: [
            provider('wavespeed_direct', {
              domain: 'image',
              capabilities: {
                text_to_image: true,
                image_edit: true,
                batch: true,
                teleport: true, // undeclared — must never be offered
              },
            }),
          ],
        },
      },
    })
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.vocabularyOf('image')).toEqual([
      'text_to_image', 'image_edit', 'batch', 'test_connection',
    ])
    expect(store.grantedCapabilitiesOf('image', 'wavespeed_direct')).toEqual([
      'batch', 'image_edit', 'text_to_image',
    ])
    expect(store.supports('image', 'wavespeed_direct', 'text_to_image')).toBe(true)
    expect(store.supports('image', 'wavespeed_direct', 'teleport')).toBe(false)
    expect(store.supports('image', 'wavespeed_direct', 'text_to_video')).toBe(false)
  })

  // ── Selection resolution and fallback ──────────────────────────────────

  it('resolves a deprecated identity through its alias', async () => {
    serve(catalog('v1', {
      providers: [provider('gemini_ws', { aliases: ['gemini'] })],
      selected: 'gemini',
    }))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.resolveProvider('tts', 'gemini').id).toBe('gemini_ws')
    expect(store.selectedProvider('tts').id).toBe('gemini_ws')
  })

  it('falls back to the domain default when nothing is selected', async () => {
    serve(catalog('v1', { providers: [provider('inworld'), provider('kokoro')], selected: null }))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.selectedId('tts')).toBeNull()
    expect(store.selectedProvider('tts').id).toBe('kokoro')
  })

  it('falls back to an available provider when the selection was uninstalled', async () => {
    serve(catalog('v1', {
      providers: [
        provider('degraded_one', { availability: 'degraded' }),
        provider('inworld'),
      ],
      selected: 'removed_provider',
    }))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    // Neither the stored selection nor the domain default survives, so the
    // dropdown lands on something usable instead of rendering empty.
    expect(store.selectedProvider('tts').id).toBe('inworld')
  })

  it('falls back to the first provider when none is available', async () => {
    serve(catalog('v1', {
      providers: [provider('degraded_one', { availability: 'degraded' })],
      selected: 'removed_provider',
    }))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.selectedProvider('tts').id).toBe('degraded_one')
  })

  it('resolves nothing for a domain with no providers at all', async () => {
    serve(catalog('v1', { providers: [], selected: null }))
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.selectedProvider('tts')).toBeNull()
    expect(store.availabilityOf('tts', 'kokoro')).toBeNull()
  })

  // ── Health is the other axis ───────────────────────────────────────────

  it('keeps health apart from availability and never throws on a probe', async () => {
    serve(BASE)
    const store = useProviderCatalogStore()
    await store.loadCatalog()
    expect(store.healthFor('tts', 'kokoro')).toBeNull()

    api.get.mockRejectedValueOnce(
      Object.assign(new Error('Connection refused'), { code: 'PROVIDER_UNREACHABLE' }),
    )
    const result = await store.checkHealth('tts', 'kokoro')

    expect(result).toEqual({
      status: 'fail',
      message: 'Connection refused [PROVIDER_UNREACHABLE]',
    })
    expect(store.healthFor('tts', 'kokoro').status).toBe('fail')
    // A failing probe does not make the provider unusable (§21.5).
    expect(store.availabilityOf('tts', 'kokoro')).toBe('available')
  })

  it('caches the health a test probe returns', async () => {
    serve(BASE)
    vi.spyOn(api, 'post').mockResolvedValue({ health: { status: 'ok', latency_ms: 12 } })
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    const result = await store.testProvider('tts', 'inworld', { api_key: 'candidate' })

    expect(api.post).toHaveBeenCalledWith('/api/providers/tts/inworld/test', {
      body: { api_key: 'candidate' },
    })
    expect(result.status).toBe('ok')
    expect(store.healthFor('tts', 'inworld').latency_ms).toBe(12)
  })

  // ── Errors ─────────────────────────────────────────────────────────────

  it('reports a failed catalog fetch through the standard envelope', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(
      Object.assign(new Error('Provider endpoints are local-only'), {
        status: 403,
        code: 'FORBIDDEN',
      }),
    )
    const store = useProviderCatalogStore()

    await store.loadCatalog()

    expect(store.error).toBe('Provider endpoints are local-only [FORBIDDEN]')
    expect(store.loading).toBe(false)
    expect(store.loaded).toBe(false)
  })

  it('clears a previous error once the catalog loads', async () => {
    vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('offline'))
    const store = useProviderCatalogStore()
    await store.loadCatalog()
    expect(store.error).toBe('offline')

    serve(BASE)
    await store.loadCatalog()

    expect(store.error).toBe('')
    expect(store.providersFor('tts')).toHaveLength(2)
  })

  // ── Developer hot reload ───────────────────────────────────────────────

  class FakeEventSource {
    constructor(url) {
      this.url = url
      this.listeners = {}
      this.closed = false
    }
    addEventListener(name, handler) { this.listeners[name] = handler }
    close() { this.closed = true }
  }

  it('refetches the catalog when the dev reload stream signals', async () => {
    serve({ ...BASE, dev_reload_enabled: true })
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    const source = store.watchCatalogReloads({ EventSourceImpl: FakeEventSource })
    expect(source.url).toBe('/api/workflow/dev-reload/events')

    serve({
      ...catalog('v2', { providers: [provider('kokoro'), provider('fixture')], selected: 'kokoro' }),
      dev_reload_enabled: true,
    })
    source.listeners['registry-reload']()

    await vi.waitFor(() => expect(store.providersFor('tts')).toHaveLength(2))
    store.closeCatalogReloads()
    expect(source.closed).toBe(true)
  })

  it('does not open a reload stream when hot reload is off', async () => {
    serve(BASE)
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    expect(store.devReloadEnabled).toBe(false)
    expect(store.watchCatalogReloads({ EventSourceImpl: FakeEventSource })).toBeNull()
  })

  it('subscribes at most once', async () => {
    serve({ ...BASE, dev_reload_enabled: true })
    const store = useProviderCatalogStore()
    await store.loadCatalog()

    const first = store.watchCatalogReloads({ EventSourceImpl: FakeEventSource })
    expect(store.watchCatalogReloads({ EventSourceImpl: FakeEventSource })).toBeNull()
    store.closeCatalogReloads()
    expect(first.closed).toBe(true)
  })
})

// ── The component renders the catalog and nothing else ───────────────────

describe('ProviderSelector reads the catalog', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  async function mountSelector() {
    const wrapper = mount(ProviderSelector, { props: { domain: 'tts', label: 'TTS Provider' } })
    await flushPromises()
    return wrapper
  }

  function optionText(wrapper) {
    return wrapper.findAll('option').map(o => o.text())
  }

  it('renders a catalog change — added, removed, and relabeled — with no code change', async () => {
    serve(BASE)
    const wrapper = await mountSelector()
    // Step 12.3: an entry that is not ready says so in the list itself, rather
    // than reading like a working one until the run fails on it.
    expect(optionText(wrapper)).toEqual(['KOKORO', 'INWORLD — Needs configuration'])

    serve(catalog('v2', {
      providers: [
        provider('kokoro', { label: 'Kokoro (local)' }),
        provider('fixture', { label: 'Fixture Voice' }),
      ],
      selected: 'kokoro',
    }))
    await useProviderCatalogStore().refresh()
    await flushPromises()

    // Relabeled, one removed, one added — the component was never touched.
    expect(optionText(wrapper)).toEqual(['Kokoro (local)', 'Fixture Voice'])
  })

  it('renders an excluded provider as an unselectable option', async () => {
    serve(catalog('v1', {
      providers: [provider('kokoro')],
      selected: 'kokoro',
      excluded: [{ id: 'broken', reason_code: 'MANIFEST_LOAD_FAILED', message: 'boom' }],
    }))
    const wrapper = await mountSelector()

    const options = wrapper.findAll('option')
    expect(options).toHaveLength(2)
    expect(options[1].text()).toBe('broken — Unavailable')
    expect(options[1].attributes('disabled')).toBeDefined()
    expect(options[0].attributes('disabled')).toBeUndefined()
  })

  it('never probes health to decide whether a provider is usable', async () => {
    serve(BASE)
    vi.spyOn(api, 'post')
    await mountSelector()

    // The old selector ran a validate round trip per render (§21.5).
    expect(api.post).not.toHaveBeenCalled()
    expect(api.get.mock.calls.map(([path]) => path)).toEqual(['/api/providers'])
  })

  it('shows the selected provider resolved through the catalog fallback', async () => {
    serve(catalog('v1', { providers: [provider('inworld'), provider('kokoro')], selected: null }))
    const wrapper = await mountSelector()

    expect(wrapper.get('select').element.value).toBe('kokoro')
  })

  it('emits configure instead of select when the new provider is unconfigured', async () => {
    serve(BASE)
    vi.spyOn(api, 'put').mockResolvedValue({
      selected: 'inworld',
      availability: 'needs_configuration',
      issues: [{ field: 'api_key', severity: 'error', message: 'Required' }],
    })
    const wrapper = await mountSelector()

    await wrapper.get('select').setValue('inworld')
    await flushPromises()

    expect(wrapper.emitted('configure')).toEqual([[{
      domain: 'tts',
      providerId: 'inworld',
      instanceId: 'inworld',
    }]])
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('surfaces a catalog error in the standard envelope form', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(
      Object.assign(new Error('Provider endpoints are local-only'), { code: 'FORBIDDEN' }),
    )
    const wrapper = await mountSelector()

    expect(wrapper.get('.selector-error').text()).toBe(
      'Provider endpoints are local-only [FORBIDDEN]',
    )
  })
})

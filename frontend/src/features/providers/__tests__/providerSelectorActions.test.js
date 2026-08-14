import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import ProviderSelector from '../components/ProviderSelector.vue'
import { api } from '@/shared/api/client.js'

// Step 12.2 — capability badges, the health action, and every message come from
// the catalog. The last test is the guard for the whole step: a provider id must
// never appear in component control flow (contracts.md §26).

const CATALOG = {
  catalog_version: 'v1',
  dev_reload_enabled: false,
  domains: {
    demo: {
      domain: 'demo',
      label: 'Demo',
      default_provider: 'alpha',
      selected: 'alpha',
      count: 1,
      excluded: [],
      // Step 6.1: closed vocabulary — undeclared keys are never offered as badges.
      capability_vocabulary: ['batch', 'streaming', 'progress', 'test_connection'],
      providers: [
        {
          id: 'alpha',
          label: 'Alpha',
          domain: 'demo',
          aliases: [],
          capabilities: {
            batch: true,
            streaming: false,
            progress: true,
            teleport: true, // outside vocabulary — never a badge
          },
          has_settings: true,
          availability: 'available',
          warnings: [],
        },
      ],
    },
  },
}

async function mountSelector() {
  const wrapper = mount(ProviderSelector, { props: { domain: 'demo', label: 'Demo' } })
  await flushPromises()
  return wrapper
}

describe('provider selector actions', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('renders only the capabilities the manifest declares true', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(structuredClone(CATALOG))
    const wrapper = await mountSelector()

    // Granted + in vocabulary; never streaming:false and never undeclared teleport.
    expect(wrapper.findAll('.badge').map((el) => el.text())).toEqual(['batch', 'progress'])
  })

  it('probes health only when asked, and names the provider in the result', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.endsWith('/health')
        ? { health: { status: 'fail', message: 'no credentials' } }
        : structuredClone(CATALOG),
    )
    const wrapper = await mountSelector()

    // Rendering costs no I/O: availability already answered "can this be used?"
    expect(get.mock.calls.every(([url]) => !url.endsWith('/health'))).toBe(true)

    await wrapper.find('.health-btn').trigger('click')
    await flushPromises()

    expect(get).toHaveBeenCalledWith('/api/providers/demo/alpha/health')
    expect(wrapper.find('.selector-status').text()).toBe('Alpha: no credentials')
  })

  it('reports a failed probe as a health state rather than throwing', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.endsWith('/health')) throw Object.assign(new Error('boom'), { code: 'X' })
      return structuredClone(CATALOG)
    })
    const wrapper = await mountSelector()

    await wrapper.find('.health-btn').trigger('click')
    await flushPromises()

    expect(wrapper.find('.selector-status').text()).toContain('Alpha: boom [X]')
  })
})

describe('no provider id in component control flow', () => {
  // The whole point of the metadata-driven UI: adding a provider is a backend
  // change. A literal id in a component is how that promise silently breaks.
  const src = resolve(process.cwd(), 'src')
  const componentsDir = join(src, 'features', 'providers', 'components')
  const SHIPPED_PROVIDER_IDS = [
    'kokoro', 'inworld', 'gemini_ws', 'wavespeed_webhook', 'wavespeed_direct',
    'grok_automa', 'kie_ai',
  ]

  it('has no provider id anywhere in the provider components', () => {
    for (const file of readdirSync(componentsDir)) {
      const source = readFileSync(join(componentsDir, file), 'utf8')
      for (const id of SHIPPED_PROVIDER_IDS) {
        expect(source.toLowerCase(), `${file} mentions ${id}`).not.toContain(id)
      }
    }
  })

  it('has no provider id in the catalog store or its shared schema helpers', () => {
    const files = [
      join(src, 'features', 'providers', 'stores', 'providerCatalog.js'),
      join(src, 'features', 'providers', 'availability.js'),
      join(src, 'shared', 'schema', 'providerSettings.js'),
      join(src, 'shared', 'schema', 'visibility.js'),
      join(src, 'shared', 'composables', 'useOptionSources.js'),
    ]
    for (const path of files) {
      const source = readFileSync(path, 'utf8').toLowerCase()
      for (const id of SHIPPED_PROVIDER_IDS) {
        expect(source, `${path} mentions ${id}`).not.toContain(id)
      }
    }
  })
})

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { api } from '@/shared/api/client.js'
import {
  clearOptionSourceCache,
  invalidateOptionSources,
  useOptionSource,
} from '../useOptionSources.js'

// Step 12.2 — the browser cache keys on the full request URL, not the bare
// source (contracts.md §23.4). A source-keyed cache serves one provider's
// options for another provider's field the moment options depend on settings.

function serve(context = {}, options = []) {
  return vi.spyOn(api, 'get').mockImplementation(async (url) => ({
    source: 'fixture_voices',
    context,
    options,
    generated_at: '2026-08-09T00:00:00Z',
  }))
}

describe('option source client', () => {
  beforeEach(() => clearOptionSourceCache())
  afterEach(() => vi.restoreAllMocks())

  it('builds a stable, sorted query string', async () => {
    serve()
    useOptionSource('fixture_voices', { provider: 'alpha', domain: 'demo' })
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith(
      '/api/workflow/options/fixture_voices?domain=demo&provider=alpha',
    )
  })

  it('drops empty context values instead of sending them', async () => {
    serve()
    useOptionSource('fixture_voices', { provider: '', domain: undefined })
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/api/workflow/options/fixture_voices')
  })

  it('fetches once per (source, context) and shares the result', async () => {
    serve()
    const first = useOptionSource('fixture_voices', { provider: 'alpha' })
    const second = useOptionSource('fixture_voices', { provider: 'alpha' })
    await flushPromises()

    expect(api.get).toHaveBeenCalledTimes(1)
    expect(second).toBe(first)
  })

  it('caches two providers separately', async () => {
    serve()
    useOptionSource('fixture_voices', { provider: 'alpha' })
    useOptionSource('fixture_voices', { provider: 'beta' })
    await flushPromises()

    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('invalidates by domain using the server-normalized context', async () => {
    // The caller omitted `domain`; the server filled it in. Invalidating the
    // domain after a settings write still has to reach this entry.
    serve({ domain: 'demo', provider: 'alpha' })
    useOptionSource('fixture_voices', {})
    await flushPromises()

    invalidateOptionSources({ domain: 'demo' })
    useOptionSource('fixture_voices', {})
    await flushPromises()

    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('leaves other domains cached when one domain is invalidated', async () => {
    serve({ domain: 'demo' })
    useOptionSource('fixture_voices', {})
    await flushPromises()

    invalidateOptionSources({ domain: 'tts' })
    useOptionSource('fixture_voices', {})
    await flushPromises()

    expect(api.get).toHaveBeenCalledTimes(1)
  })

  it('invalidates one source by name', async () => {
    serve()
    useOptionSource('fixture_voices', {})
    useOptionSource('story_tones', {})
    await flushPromises()

    invalidateOptionSources({ source: 'story_tones' })
    useOptionSource('fixture_voices', {})
    useOptionSource('story_tones', {})
    await flushPromises()

    expect(api.get).toHaveBeenCalledTimes(3)
  })

  it('reports a failure through the standard error envelope', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(
      Object.assign(new Error('Option source is unavailable'), {
        code: 'PROVIDER_UNAVAILABLE',
      }),
    )
    const state = useOptionSource('fixture_voices', {})
    await flushPromises()

    expect(state.value.loading).toBe(false)
    expect(state.value.options).toEqual([])
    expect(state.value.error).toBe('Option source is unavailable [PROVIDER_UNAVAILABLE]')
  })
})

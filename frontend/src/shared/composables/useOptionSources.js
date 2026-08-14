import { ref } from 'vue'
import { api } from '@/shared/api/client.js'
import { apiErrorText } from '@/shared/api/errors.js'

/**
 * The one client for allowlisted async option sources (contracts.md §23).
 *
 * Shared by workflow node fields and provider settings fields, so both
 * interpret one option contract: the same allowlisted `source`, the same
 * validated `context`, the same `{value, label}` response.
 *
 * Cache key is the **full request URL**, not the bare source (§23.4). Once
 * options depend on the selected provider, a source-keyed cache serves one
 * provider's voices for another provider's field.
 */

const BASE = '/api/workflow/options'

// url -> { source, context, state }
const cache = new Map()

/** Stable query string: sorted keys, empty values dropped. */
function buildUrl(source, context) {
  const params = Object.entries(context || {})
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .sort(([a], [b]) => a.localeCompare(b))
  const query = new URLSearchParams(params).toString()
  return `${BASE}/${encodeURIComponent(source)}${query ? `?${query}` : ''}`
}

/**
 * Reactive `{loading, options, error}` for one source under one context.
 *
 * One fetch per (source, context) per session; every field instance asking for
 * the same pair shares the result.
 */
export function useOptionSource(source, context = {}) {
  const url = buildUrl(source, context)
  const entry = cache.get(url)
  if (entry) return entry.state

  const state = ref({ loading: true, options: [], error: '' })
  const record = { source, context: { ...context }, state }
  cache.set(url, record)
  api
    .get(url)
    .then((data) => {
      // Adopt the server's *normalized* context (§23.2). A caller that omitted
      // `domain` still ends up in a domain-scoped entry, so invalidating one
      // domain after a settings write actually reaches it.
      if (data.context) record.context = data.context
      state.value = { loading: false, options: data.options || [], error: '' }
    })
    .catch((err) => {
      state.value = {
        loading: false,
        options: [],
        error: apiErrorText(err, 'Failed to load options'),
      }
    })
  return state
}

/**
 * Drop cached results so the next reader refetches.
 *
 * With no argument, drops everything. `{ source }` drops one source;
 * `{ domain }` drops every entry resolved for that domain — which is what a
 * selection change or a provider settings save has to do, because the same URL
 * now answers differently (§23.4).
 */
export function invalidateOptionSources({ source, domain } = {}) {
  for (const [url, entry] of cache) {
    if (source && entry.source !== source) continue
    if (domain && entry.context?.domain !== domain) continue
    cache.delete(url)
  }
}

// Test hook: drop cached results so mocks take effect per test.
export function clearOptionSourceCache() {
  cache.clear()
}

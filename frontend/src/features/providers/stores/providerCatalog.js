import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/shared/api/client.js'
import { apiErrorText } from '@/shared/api/errors.js'
import { invalidateOptionSources } from '@/shared/composables/useOptionSources.js'
import { AVAILABLE, UNAVAILABLE } from '../availability.js'

/**
 * The one frontend view of the provider catalog (step 12.1 / 3.2).
 *
 * `GET /api/providers` is authoritative: every provider type, configured
 * instance, label, capability, availability state, and per-domain selection
 * in the app is read from here. Nothing about a provider is hardcoded in a
 * component or in static frontend data, so adding, removing, or relabeling a
 * provider is a backend-only change.
 *
 * Step 3.2 keys health, settings, schemas, and selection on **instance** id.
 * Provider types remain discoverable for labels and capabilities; two
 * instances of one type hold independent availability and settings.
 *
 * Two axes are kept apart, per contracts.md §21.5. **Availability** ships with
 * the catalog, costs nothing, and answers "can this be used?". **Health** costs
 * I/O, is requested explicitly, and is cached separately — it never gates
 * selection. The composable this store replaces conflated them by running a
 * validation round trip per selector render.
 */

const CATALOG_URL = '/api/providers'
// Provider packages are watched by the same dev reloader as node definitions,
// so provider edits arrive on the workflow reload stream (dev_reload.py).
const DEV_RELOAD_URL = '/api/workflow/dev-reload/events'

function healthKey(domain, instanceId) {
  return `${domain}/${instanceId}`
}

/**
 * Type-scoped URL that also accepts instance ids (backend `_resolve_instance`).
 * Default bindings use `id == type`; second bindings use their own instance id
 * in the same path segment.
 */
function instanceApiBase(domain, instanceId) {
  return `${CATALOG_URL}/${domain}/${encodeURIComponent(instanceId)}`
}

/**
 * Project an `excluded[]` entry onto the provider shape.
 *
 * A provider that failed discovery still has to render — silently dropping it
 * is how a broken folder becomes an unexplained missing dropdown entry. It is
 * the only source of the `unavailable` state (§21.4).
 */
function excludedAsProvider(exclusion, domain) {
  return {
    id: exclusion.id,
    label: exclusion.id,
    domain,
    aliases: [],
    capabilities: {},
    has_settings: false,
    availability: UNAVAILABLE,
    warnings: exclusion.message ? [exclusion.message] : [],
    reason_code: exclusion.reason_code,
  }
}

export const useProviderCatalogStore = defineStore('providerCatalog', () => {
  // ── Catalog (backend-served, cached by content version) ────────────────
  const catalogVersion = ref(null)
  const domains = ref({})
  const loading = ref(false)
  const error = ref('')
  const devReloadEnabled = ref(false)
  // `domain/instance_id` -> the last HealthResult seen for that instance.
  const health = ref({})
  // `domain/instance_id` -> that instance's type settings schema, or null when
  // it ships none. Cached because the node inspector asks per selected node.
  const schemas = ref({})

  let inFlight = null
  let devReloadSource = null

  const loaded = computed(() => catalogVersion.value !== null)
  const domainIds = computed(() => Object.keys(domains.value).sort())

  /**
   * Fetch the catalog, at most once per session unless forced.
   *
   * Concurrent callers share one request: three selectors mounting together
   * must not race three identical fetches. An unchanged `catalog_version` keeps
   * the existing objects rather than replacing them, so a forced refresh that
   * finds nothing new cannot churn every downstream computed.
   */
  async function loadCatalog({ force = false } = {}) {
    if (!force && catalogVersion.value !== null) return
    if (inFlight) return inFlight

    loading.value = true
    error.value = ''
    inFlight = api
      .get(CATALOG_URL)
      .then((data) => {
        devReloadEnabled.value = data.dev_reload_enabled === true
        const version = data.catalog_version ?? null
        if (version !== null && version === catalogVersion.value) return
        catalogVersion.value = version
        domains.value = data.domains || {}
        // A changed catalog version is the only thing that can change a
        // provider's settings schema — a reloaded package, a new version of
        // one. Dropping the cache here rather than on every settings save
        // avoids a refetch that a value write could never have invalidated.
        schemas.value = {}
      })
      .catch((err) => {
        error.value = apiErrorText(err, 'Failed to load providers')
      })
      .finally(() => {
        loading.value = false
        inFlight = null
      })
    return inFlight
  }

  function refresh() {
    return loadCatalog({ force: true })
  }

  // ── Domain grouping and lookup ─────────────────────────────────────────

  function domainEntry(domain) {
    return domains.value[domain] || null
  }

  function domainLabel(domain) {
    return domainEntry(domain)?.label || domain
  }

  function providersFor(domain) {
    return domainEntry(domain)?.providers || []
  }

  function instancesFor(domain) {
    return domainEntry(domain)?.instances || []
  }

  function excludedFor(domain) {
    return (domainEntry(domain)?.excluded || []).map((e) => excludedAsProvider(e, domain))
  }

  /**
   * Selectable identities for a domain: configured instances when present,
   * otherwise discovered types (as default instances). Excluded packages
   * trail so a broken folder still renders.
   */
  function catalogEntriesFor(domain) {
    const instances = instancesFor(domain)
    if (instances.length) {
      return [
        ...instances.map((inst) => instanceAsEntry(domain, inst)),
        ...excludedFor(domain),
      ]
    }
    return [...providersFor(domain), ...excludedFor(domain)]
  }

  /** Project a catalog `instances[]` row onto the selector entry shape. */
  function instanceAsEntry(domain, inst) {
    const type = resolveProvider(domain, inst.provider_type)
    return {
      id: inst.instance_id,
      instance_id: inst.instance_id,
      provider_type: inst.provider_type,
      label: inst.label || type?.label || inst.instance_id,
      domain,
      aliases: type?.aliases || [],
      capabilities: type?.capabilities || {},
      has_settings: type?.has_settings ?? true,
      availability: inst.availability || type?.availability || 'needs_configuration',
      warnings: type?.warnings || [],
      open_url: type?.open_url || null,
      docs_url: type?.docs_url || null,
      selected: inst.selected === true,
    }
  }

  /**
   * Resolve a type id through canonical id then alias.
   *
   * Deprecated provider identities are carried as aliases rather than a flag
   * (§20.1), so this is also how a legacy value stored before a rename still
   * points at the provider that replaced it.
   */
  function resolveProvider(domain, providerId) {
    if (!providerId) return null
    const list = providersFor(domain)
    return (
      list.find((p) => p.id === providerId) ||
      list.find((p) => (p.aliases || []).includes(providerId)) ||
      null
    )
  }

  /** Resolve an instance id (or default type id) to a selector entry. */
  function resolveInstance(domain, instanceId) {
    if (!instanceId) return null
    const inst = instancesFor(domain).find((row) => row.instance_id === instanceId)
    if (inst) return instanceAsEntry(domain, inst)
    // Default-instance convention: instance_id == type id, not yet in the map.
    const type = resolveProvider(domain, instanceId)
    if (!type) return null
    return {
      id: type.id,
      instance_id: type.id,
      provider_type: type.id,
      label: type.label,
      domain,
      aliases: type.aliases || [],
      capabilities: type.capabilities || {},
      has_settings: type.has_settings,
      availability: type.availability,
      warnings: type.warnings || [],
      open_url: type.open_url || null,
      docs_url: type.docs_url || null,
      selected: selectedId(domain) === type.id,
    }
  }

  /** Selected instance id for the domain. */
  function selectedId(domain) {
    const entry = domainEntry(domain)
    if (!entry) return null
    return entry.selected_instance_id ?? entry.selected ?? null
  }

  /**
   * The instance a domain will actually use, following the frozen precedence
   * chain (§24.1) for the rules a browser can evaluate: the stored selection,
   * then the domain default. Falling back to a usable binding beats rendering
   * an empty dropdown over a populated domain.
   */
  function selectedProvider(domain) {
    const entry = domainEntry(domain)
    if (!entry) return null
    const selected = selectedId(domain)
    return (
      resolveInstance(domain, selected) ||
      resolveInstance(domain, entry.default_provider) ||
      catalogEntriesFor(domain).find((p) => p.availability === AVAILABLE) ||
      catalogEntriesFor(domain)[0] ||
      null
    )
  }

  function selectedInstance(domain) {
    return selectedProvider(domain)
  }

  function availabilityOf(domain, instanceOrTypeId) {
    const inst = resolveInstance(domain, instanceOrTypeId)
    if (inst) return inst.availability
    const provider = resolveProvider(domain, instanceOrTypeId)
    if (provider) return provider.availability
    const excluded = excludedFor(domain).find((e) => e.id === instanceOrTypeId)
    return excluded ? UNAVAILABLE : null
  }

  function capabilitiesOf(domain, instanceOrTypeId) {
    const inst = resolveInstance(domain, instanceOrTypeId)
    if (inst) return inst.capabilities || {}
    return resolveProvider(domain, instanceOrTypeId)?.capabilities || {}
  }

  function supports(domain, instanceOrTypeId, capability) {
    return capabilitiesOf(domain, instanceOrTypeId)[capability] === true
  }

  // ── Health (explicit action only, cached apart from the catalog) ────────

  function healthFor(domain, instanceId) {
    return health.value[healthKey(domain, instanceId)] || null
  }

  function recordHealth(domain, instanceId, result) {
    health.value = { ...health.value, [healthKey(domain, instanceId)]: result }
    return result
  }

  /** Probe stored settings. Never throws: a failed probe *is* a health state. */
  async function checkHealth(domain, instanceId) {
    try {
      const data = await api.get(`${instanceApiBase(domain, instanceId)}/health`)
      return recordHealth(domain, instanceId, data.health)
    } catch (err) {
      return recordHealth(domain, instanceId, {
        status: 'fail',
        message: apiErrorText(err, 'Health check failed'),
      })
    }
  }

  /** Probe a candidate settings patch without saving it. */
  async function testProvider(domain, instanceId, settings = {}) {
    const data = await api.post(`${instanceApiBase(domain, instanceId)}/test`, {
      body: settings,
    })
    return recordHealth(domain, instanceId, data.health)
  }

  // ── Selection and settings writes ──────────────────────────────────────

  /**
   * One targeted write, not a read-modify-write of the whole settings document
   * (§24.2). Selection is non-blocking: a `needs_configuration` or failing
   * instance may be chosen, and the issues travel back so the caller can prompt.
   */
  async function selectProvider(domain, instanceId) {
    if (selectedId(domain) === instanceId) return { switched: false }

    const result = await api.put(`${CATALOG_URL}/${domain}/selection`, {
      body: { instance_id: instanceId },
    })

    // The server answers with the canonical instance id — an alias is never stored.
    applySelection(domain, result)
    // Any dropdown resolved against this domain now has a different answer: a
    // context-free caller follows the selection (§23.4). Keeping the old list
    // is how one instance's voices end up offered for another instance's node.
    invalidateOptionSources({ domain })
    return {
      switched: true,
      availability: result.availability,
      needsConfiguration: result.availability !== AVAILABLE,
      issues: result.issues || [],
    }
  }

  function applySelection(domain, result) {
    const entry = domainEntry(domain)
    if (!entry) return
    const selectedInstanceId = result.selected_instance_id || result.selected
    const instances = (entry.instances || []).map((row) => ({
      ...row,
      selected: row.instance_id === selectedInstanceId,
      availability:
        row.instance_id === selectedInstanceId && result.availability
          ? result.availability
          : row.availability,
    }))
    const typeId = result.provider_type || selectedInstanceId
    const providers = (entry.providers || []).map((p) =>
      p.id === typeId && result.availability
        ? { ...p, availability: result.availability }
        : p,
    )
    domains.value = {
      ...domains.value,
      [domain]: {
        ...entry,
        selected: selectedInstanceId,
        selected_instance_id: selectedInstanceId,
        instances,
        providers,
      },
    }
  }

  function getProviderSettings(domain, instanceId) {
    return api.get(`${instanceApiBase(domain, instanceId)}/settings`)
  }

  // ── Settings schemas, cached per instance ──────────────────────────────
  //
  // The node inspector renders a per-run options form for whichever instance
  // the *node* selects, which is not necessarily the domain's selection, so it
  // cannot reuse `useDomainProvider`'s single-instance load. Concurrent asks
  // share one request: a workflow with three provider-backed nodes must not
  // fetch the same schema three times.

  const schemaRequests = new Map()

  function schemaFor(domain, instanceId) {
    return schemas.value[healthKey(domain, instanceId)] ?? null
  }

  async function loadProviderSchema(domain, instanceId) {
    if (!domain || !instanceId) return null
    const key = healthKey(domain, instanceId)
    if (key in schemas.value) return schemas.value[key]
    if (schemaRequests.has(key)) return schemaRequests.get(key)

    const request = getProviderSettings(domain, instanceId)
      .then((data) => data.schema || null)
      // A provider that is not installed, or ships no schema, has no form —
      // which is a state the inspector renders, not an error it reports. The
      // node stays inspectable either way (§23.3).
      .catch(() => null)
      .then((schema) => {
        schemas.value = { ...schemas.value, [key]: schema }
        schemaRequests.delete(key)
        return schema
      })
    schemaRequests.set(key, request)
    return request
  }

  /**
   * Save and re-read the catalog: filling in a required key flips availability
   * from `needs_configuration` to `available`, and that is not derivable here.
   */
  async function saveProviderSettings(domain, instanceId, settings) {
    const result = await api.put(`${instanceApiBase(domain, instanceId)}/settings`, {
      body: settings,
    })
    // Changing an API key changes what the provider can offer (§23.4).
    invalidateOptionSources({ domain })
    await refresh()
    return result
  }

  function validateProviderSettings(domain, instanceId, settings = {}) {
    return api.post(`${instanceApiBase(domain, instanceId)}/validate`, {
      body: settings,
    })
  }

  // ── Unsaved drafts (one per instance, never containing a secret) ────────

  /**
   * Editing instance A, switching to B to compare, and coming back must not
   * silently discard A's edits — so a draft is keyed by instance and outlives
   * the modal. Secrets are stripped by the caller before they get here (§22.6).
   */
  const drafts = ref({})

  function draftFor(domain, instanceId) {
    return drafts.value[healthKey(domain, instanceId)] || null
  }

  function setDraft(domain, instanceId, values) {
    drafts.value = { ...drafts.value, [healthKey(domain, instanceId)]: { ...values } }
  }

  function clearDraft(domain, instanceId) {
    const next = { ...drafts.value }
    delete next[healthKey(domain, instanceId)]
    drafts.value = next
  }

  // ── Developer hot reload ───────────────────────────────────────────────

  /**
   * Refetch when the dev reloader republishes the catalog. The stream is shared
   * with the workflow node registry because one watcher covers both.
   */
  function watchCatalogReloads({ EventSourceImpl = globalThis.EventSource } = {}) {
    if (!devReloadEnabled.value || devReloadSource || !EventSourceImpl) return null
    devReloadSource = new EventSourceImpl(DEV_RELOAD_URL)
    devReloadSource.addEventListener('registry-reload', () => refresh())
    return devReloadSource
  }

  function closeCatalogReloads() {
    devReloadSource?.close()
    devReloadSource = null
  }

  return {
    catalogVersion,
    domains,
    loading,
    error,
    devReloadEnabled,
    health,
    loaded,
    domainIds,
    loadCatalog,
    refresh,
    domainEntry,
    domainLabel,
    providersFor,
    instancesFor,
    excludedFor,
    catalogEntriesFor,
    resolveProvider,
    resolveInstance,
    selectedId,
    selectedProvider,
    selectedInstance,
    availabilityOf,
    capabilitiesOf,
    supports,
    healthFor,
    checkHealth,
    testProvider,
    selectProvider,
    getProviderSettings,
    schemas,
    schemaFor,
    loadProviderSchema,
    saveProviderSettings,
    validateProviderSettings,
    drafts,
    draftFor,
    setDraft,
    clearDraft,
    watchCatalogReloads,
    closeCatalogReloads,
  }
})

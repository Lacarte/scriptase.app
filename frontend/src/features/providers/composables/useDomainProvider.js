import { computed, ref, watch } from 'vue'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import { effectiveSettings } from '@/shared/schema/providerSettings.js'

/**
 * One legacy page's view of one provider domain (step 12.4 / 16.1 / 3.2).
 *
 * The pages that predate the provider platform each answered which provider is
 * selected and what it is configured with. They answered them from
 * `useSettings`, a hardcoded list, and `localStorage` — stores that could
 * disagree with the catalog. This answers both from `GET /api/providers`
 * (contracts.md §24), so a page keeps its own layout and request shape while
 * owning none of the provider knowledge. Step 3.2 keys selection and settings
 * on **instance** id; `providerId` remains the public name for the selected
 * binding so existing call sites keep working.
 *
 * `withSettings` is opt-in because it costs a request per instance switch, and
 * only pages that put a configured value on the wire need it.
 */
export function useDomainProvider(domain, { withSettings = false } = {}) {
  const catalog = useProviderCatalogStore()

  const provider = computed(() => catalog.selectedProvider(domain))
  const providerId = computed(() => provider.value?.id || '')
  const instanceId = computed(
    () => provider.value?.instance_id || provider.value?.id || '',
  )
  const providerType = computed(
    () => provider.value?.provider_type || provider.value?.id || '',
  )
  const label = computed(() => provider.value?.label || providerId.value)
  /** The provider's own page, from its manifest — never a literal in a view. */
  const openUrl = computed(() => provider.value?.open_url || null)

  /** Declarative branching, the replacement for `if (provider === '…')`. */
  function supports(capability) {
    return catalog.supports(domain, instanceId.value || providerId.value, capability)
  }

  // ── Configured values of the selected instance ─────────────────────────
  const schema = ref({})
  const settings = ref({})
  const settingsLoading = ref(false)

  async function loadSettings() {
    const id = instanceId.value
    if (!id) {
      schema.value = {}
      settings.value = {}
      return
    }
    settingsLoading.value = true
    try {
      const data = await catalog.getProviderSettings(domain, id)
      // Guard against an out-of-order response for an instance that is no longer
      // selected: switching twice quickly must not leave the first one's values
      // on screen.
      if (instanceId.value !== id) return
      schema.value = data.schema || {}
      settings.value = effectiveSettings(data.schema, data.settings)
    } catch {
      schema.value = {}
      settings.value = {}
    } finally {
      settingsLoading.value = false
    }
  }

  catalog.loadCatalog()
  if (withSettings) watch(instanceId, loadSettings, { immediate: true })

  return {
    catalog,
    provider,
    providerId,
    instanceId,
    providerType,
    label,
    openUrl,
    supports,
    schema,
    settings,
    settingsLoading,
    loadSettings,
  }
}

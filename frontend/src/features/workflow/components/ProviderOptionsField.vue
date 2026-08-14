<script setup>
import { computed, watch } from 'vue'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'
import ProviderSettingsForm from '@/features/providers/components/ProviderSettingsForm.vue'
import { withoutSecretProperties } from '@/shared/schema/providerSettings.js'

/**
 * The `provider_options` node widget (contracts.md §26, step 12.5).
 *
 * Step 12.3 gave the five provider-backed nodes a `provider_id` +
 * `provider_options` pair and moved every provider-specific field out of the
 * node registry into the providers' own settings schemas. Nothing rendered the
 * result: `ConfigField` had no branch for either widget, so the inspector drew
 * "Unsupported field type: provider" and those five nodes could not be
 * configured at all. This is the missing half.
 *
 * It renders the *same* `ProviderSettingsForm` the Settings page and the five
 * legacy pages use, over the schema of whichever provider the node selected —
 * so a new provider's per-run options appear on the node with no edit here.
 * `field.provider_domain` is the only thing this component knows; no provider
 * id appears in it.
 */
const props = defineProps({
  field: { type: Object, required: true },
  value: { type: Object, default: () => ({}) },
  // The provider the *node* selected, which is not necessarily the domain's
  // global selection — a saved workflow must keep running the provider it was
  // saved with (§24.1 rule 2).
  providerId: { type: String, default: '' },
})
const emit = defineEmits(['update'])

const catalog = useProviderCatalogStore()

const domain = computed(() => props.field.provider_domain || '')

watch(
  [domain, () => props.providerId],
  ([nextDomain, nextProvider]) => catalog.loadProviderSchema(nextDomain, nextProvider),
  { immediate: true },
)

const schema = computed(() => catalog.schemaFor(domain.value, props.providerId))

/**
 * A credential is never offered here. Per-run options are persisted into the
 * workflow document, its archives, and its exported templates, and
 * `_validate_provider_options` refuses one at save time — not drawing the field
 * is how that is communicated before the operator types (§22.6).
 */
const visibleSchema = computed(() =>
  schema.value ? withoutSecretProperties(schema.value) : null,
)

const hasFields = computed(
  () => Object.keys(visibleSchema.value?.properties || {}).length > 0,
)
</script>

<template>
  <div class="cfg-field provider-options">
    <span class="cfg-label">{{ field.label || field.name }}</span>

    <p v-if="!providerId" class="cfg-note">
      Choose a provider first.
    </p>
    <p v-else-if="!hasFields" class="cfg-note">
      This provider has no per-run options.
    </p>
    <ProviderSettingsForm
      v-else
      :model-value="value || {}"
      :schema="visibleSchema"
      :domain="domain"
      :provider-id="providerId"
      @update:model-value="(next) => emit('update', next)"
    />

    <span v-if="field.description" class="cfg-desc">{{ field.description }}</span>
  </div>
</template>

<style scoped>
.cfg-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px 14px;
}

.cfg-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}

.provider-options :deep(.provider-settings-form) {
  gap: 12px;
  padding: 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-dark);
}

.provider-options :deep(.field-label) {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}

.provider-options :deep(.field-input) {
  padding: 7px 10px;
  font-size: 12px;
}

.provider-options :deep(.field-description),
.provider-options :deep(.field-note) {
  font-size: 10.5px;
}

.cfg-note {
  font-size: 11px;
  color: var(--text-muted);
  font-style: italic;
  margin: 0;
}

.cfg-desc {
  font-size: 10.5px;
  color: var(--text-muted);
  line-height: 1.4;
}
</style>

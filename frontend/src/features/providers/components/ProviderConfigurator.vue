<script setup>
import { ref } from 'vue'
import ProviderSelector from './ProviderSelector.vue'
import ProviderSettingsModal from './ProviderSettingsModal.vue'
import ProviderSettingsForm from './ProviderSettingsForm.vue'

/**
 * Selector + settings modal, wired together (step 12.4).
 *
 * The Settings page assembled these three components by hand. Every legacy page
 * that adopts the shared provider UI needs the same assembly, and copying it
 * five times is how five surfaces end up with four behaviors — so the assembly
 * itself is the component. A page renders `<ProviderConfigurator domain="…" />`
 * and gets the catalog dropdown, the availability and health affordances, and
 * the metadata-driven settings form with nothing page-specific in between.
 */

defineOptions({ name: 'ProviderConfigurator' })

const props = defineProps({
  domain: { type: String, required: true },
  label: { type: String, default: 'Provider' },
  description: { type: String, default: '' },
  variant: { type: String, default: 'inline' },
})

const emit = defineEmits(['select', 'saved'])

const modalOpen = ref(false)
const modalProviderId = ref('')

function onConfigure({ providerId }) {
  modalProviderId.value = providerId
  modalOpen.value = true
}

function onSelect(payload) {
  emit('select', payload)
}

function onSaved(payload) {
  modalOpen.value = false
  emit('saved', payload)
}
</script>

<template>
  <div class="provider-configurator">
    <ProviderSelector
      :domain="props.domain"
      :label="props.label"
      :description="props.description"
      :variant="props.variant"
      @select="onSelect"
      @configure="onConfigure"
    />

    <ProviderSettingsModal
      v-if="modalOpen"
      :visible="modalOpen"
      :domain="props.domain"
      :provider-id="modalProviderId"
      @close="modalOpen = false"
      @saved="onSaved"
    >
      <template #form="{ formData, schema, errors, domain, providerId }">
        <ProviderSettingsForm
          :model-value="formData"
          :schema="schema"
          :errors="errors"
          :domain="domain"
          :provider-id="providerId"
          @update:model-value="(val) => Object.assign(formData, val)"
        />
      </template>
    </ProviderSettingsModal>
  </div>
</template>

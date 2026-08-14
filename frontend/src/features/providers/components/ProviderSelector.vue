<script setup>
import { computed, ref, watch } from 'vue'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import { availabilityInfo, healthInfo, isSelectable, toneColor } from '../availability.js'

const props = defineProps({
  domain: { type: String, required: true },
  label: { type: String, default: 'Provider' },
  description: { type: String, default: '' },
  // `panel` is the Settings-page row. `inline` is the compact control group the
  // legacy pages already lay out beside their own selects (step 12.4): same
  // component, same behavior, their spacing. A second selector component is how
  // the two surfaces would start to drift.
  variant: { type: String, default: 'panel' },
})

const emit = defineEmits(['select', 'configure'])

// Everything rendered here comes from the catalog: the list, the labels, the
// state, the capabilities, and the selection. No provider id appears in this
// component.
const catalog = useProviderCatalogStore()

const probing = ref(false)

const providerList = computed(() => catalog.catalogEntriesFor(props.domain))
const selected = computed(() => catalog.selectedProvider(props.domain))
const selectedId = computed(() => selected.value?.id || '')
const selectedName = computed(() => selected.value?.label || selectedId.value)
const availability = computed(
  () => catalog.resolveProvider(props.domain, selectedId.value)?.availability,
)
// Availability is the resting state. A health probe costs I/O and runs only on
// an explicit user action, so it shows here once one has happened and never
// gates the selection (contracts.md §21.5).
const probed = computed(() => catalog.healthFor(props.domain, selectedId.value))
const status = computed(() =>
  probed.value ? healthInfo(probed.value.status) : availabilityInfo(availability.value),
)
const needsAttention = computed(() => status.value.tone !== 'ok')

/**
 * Capabilities the selected provider grants and the domain vocabulary allows
 * (step 6.1). An undeclared key is never offered as a badge.
 */
const capabilities = computed(() =>
  catalog.grantedCapabilitiesOf(props.domain, selectedId.value),
)

// Feedback names the provider it is about: three selectors share this page and
// "Health check failed" alone says nothing about which one failed.
const statusText = computed(() =>
  `${selectedName.value}: ${probed.value?.message || status.value.label}`,
)

async function onSelect(event) {
  const instanceId = event.target.value
  const result = await catalog.selectProvider(props.domain, instanceId)
  if (!result.switched) return
  if (result.needsConfiguration) {
    emit('configure', { domain: props.domain, providerId: instanceId, instanceId })
  } else {
    emit('select', { domain: props.domain, providerId: instanceId, instanceId })
  }
}

async function checkHealth() {
  probing.value = true
  try {
    await catalog.checkHealth(props.domain, selectedId.value)
  } finally {
    probing.value = false
  }
}

function openSettings() {
  emit('configure', {
    domain: props.domain,
    providerId: selectedId.value,
    instanceId: selectedId.value,
  })
}

watch(() => props.domain, () => catalog.loadCatalog(), { immediate: true })
</script>

<template>
  <div class="provider-selector" :class="`variant-${variant}`">
    <div class="selector-row">
      <div class="selector-info">
        <label class="selector-label">{{ label }}</label>
        <p v-if="description" class="selector-desc">{{ description }}</p>
      </div>
      <div class="selector-controls">
        <select
          class="selector-select"
          :value="selectedId"
          :disabled="catalog.loading"
          @change="onSelect"
        >
          <option
            v-for="p in providerList"
            :key="p.id"
            :value="p.id"
            :disabled="!isSelectable(p)"
          >
            {{ p.label }}{{ isSelectable(p) ? '' : ` — ${availabilityInfo(p.availability).label}` }}
          </option>
        </select>
        <button
          class="gear-btn"
          :class="{ 'has-warning': needsAttention }"
          :disabled="!selectedId || catalog.loading"
          title="Configure provider"
          @click="openSettings"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l-1.42-1.42"/>
          </svg>
        </button>
        <button
          class="health-btn"
          :disabled="!selectedId || probing"
          :title="`Check ${selectedName}`"
          @click="checkHealth"
        >
          <span class="health-dot" :style="{ background: toneColor(status.tone) }" />
          <span class="health-text">{{ probing ? 'Checking…' : status.label }}</span>
        </button>
      </div>
    </div>
    <p v-if="capabilities.length" class="selector-capabilities">
      <span v-for="name in capabilities" :key="name" class="badge">{{ name }}</span>
    </p>
    <p v-if="probed" class="selector-status" :style="{ color: toneColor(status.tone) }">
      {{ statusText }}
    </p>
    <p v-if="catalog.error" class="selector-error">{{ catalog.error }}</p>
  </div>
</template>

<style scoped>
.provider-selector {
  width: 100%;
}

.selector-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

/* Inline: the label sits above a compact control group, matching the
   `control-group` / `webhook-section` rhythm the legacy pages already use. */
.variant-inline .selector-row {
  display: block;
}

.variant-inline .selector-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--text-muted, #9ca3af);
  margin-bottom: 8px;
}

.variant-inline .selector-controls {
  gap: 6px;
}

.variant-inline .selector-select {
  padding: 8px 30px 8px 12px;
  font-size: 12px;
  min-width: 150px;
}

.variant-inline .gear-btn,
.variant-inline .health-btn {
  height: 33px;
}

.variant-inline .gear-btn {
  width: 33px;
}

.variant-inline .health-text {
  font-size: 11px;
}

.selector-info {
  flex: 1;
}

.selector-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text, #e5e5e5);
  display: block;
}

.selector-desc {
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
  margin: 4px 0 0;
}

.selector-error {
  font-size: 12px;
  color: #ef4444;
  margin: 6px 0 0;
}

.selector-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.selector-select {
  padding: 10px 32px 10px 12px;
  border: 1px solid var(--border, #3f3f46);
  border-radius: 6px;
  background: var(--bg-surface, #1f1f23);
  color: var(--text, #e5e5e5);
  font-size: 14px;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%239ca3af' d='M6 8L2 4h8z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  min-width: 140px;
}

.selector-select:focus {
  outline: none;
  border-color: var(--accent, #4ECDC4);
}

.gear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border, #3f3f46);
  border-radius: 6px;
  background: var(--bg-surface, #1f1f23);
  color: var(--text-secondary, #9ca3af);
  cursor: pointer;
  transition: all 0.15s;
}

.gear-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover, #3a3a3f);
  color: var(--text, #e5e5e5);
}

.gear-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.gear-btn.has-warning {
  border-color: var(--accent-warning, #f59e0b);
}

.health-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--border, #3f3f46);
  border-radius: 6px;
  background: var(--bg-surface, #1f1f23);
  color: var(--text-secondary, #9ca3af);
  font-size: 12px;
  cursor: pointer;
}

.health-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover, #3a3a3f);
  color: var(--text, #e5e5e5);
}

.health-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.health-text {
  white-space: nowrap;
}

.selector-capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0 0;
}

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--bg-elevated, #2a2a2f);
  border: 1px solid var(--border, #3f3f46);
  color: var(--text-secondary, #9ca3af);
}

.selector-status {
  font-size: 12px;
  margin: 6px 0 0;
}
</style>
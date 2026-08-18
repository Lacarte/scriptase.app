<script setup>
import { computed, ref, watch } from 'vue'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import { AVAILABLE, availabilityInfo, healthInfo, isSelectable, toneColor } from '../availability.js'

const props = defineProps({
  domain: { type: String, required: true },
  label: { type: String, default: 'Provider' },
  description: { type: String, default: '' },
  // `panel` is the Settings-page row. `inline` is the compact control group the
  // legacy pages already lay out beside their own selects (step 12.4): same
  // component, same behavior, their spacing. A second selector component is how
  // the two surfaces would start to drift.
  variant: { type: String, default: 'panel' },
  // ── Controlled mode (step 12.3) ──────────────────────────────────────────
  // A non-null `modelValue` hands ownership of the selection to the parent: the
  // node's own `provider_id` field, which is *not* the domain-wide selection. A
  // saved workflow must keep running the instance it was saved with, so the
  // node editor may never write the domain default (§24.1 rule 2). `null` keeps
  // the catalog-bound mode the Settings surfaces use.
  modelValue: { type: String, default: null },
  // An entry list the parent already resolved — the node editor's allowlisted
  // `<domain>_providers` source, which is authoritative about *which* instances
  // are legal values. Availability is still read off the catalog, so both modes
  // render the same states. `null` means read the list from the catalog too.
  options: { type: Array, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  // The gear needs somewhere to go. Surfaces that mount no settings editor turn
  // it off rather than render a button that does nothing.
  configurable: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'select', 'configure'])

// Everything rendered here comes from the catalog: the list, the labels, the
// state, the capabilities, and the selection. No provider id appears in this
// component.
const catalog = useProviderCatalogStore()

const probing = ref(false)

const controlled = computed(() => props.modelValue !== null)
const busy = computed(() => catalog.loading || props.loading)
const errorText = computed(() => props.error || catalog.error)

const providerList = computed(() => {
  if (!props.options) return catalog.catalogEntriesFor(props.domain)
  return props.options.map((opt) => {
    const id = String(opt.value ?? '')
    return { id, label: opt.label ?? id, availability: catalog.availabilityOf(props.domain, id) }
  })
})

const selectedId = computed(() =>
  controlled.value ? props.modelValue : catalog.selectedProvider(props.domain)?.id || '',
)
const selected = computed(
  () =>
    providerList.value.find((p) => p.id === selectedId.value) ||
    catalog.resolveInstance(props.domain, selectedId.value) ||
    null,
)
const selectedName = computed(() => selected.value?.label || selectedId.value)
// `availabilityOf` resolves an instance id, then a type id, then an excluded
// package — so a second named binding reports its own state rather than the
// state of the type it was cloned from.
const availability = computed(() => catalog.availabilityOf(props.domain, selectedId.value))
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

/**
 * The dropdown label: the entry name, plus its resting availability whenever
 * that is anything other than "ready". An instance nobody has given credentials
 * to used to read exactly like a working one and only announced itself when the
 * run failed.
 */
function entryLabel(entry) {
  const state = entry.availability
  if (!state || state === AVAILABLE) return entry.label
  return `${entry.label} — ${availabilityInfo(state).label}`
}

async function onSelect(event) {
  const instanceId = event.target.value
  if (controlled.value) {
    emit('update:modelValue', instanceId)
    emit('select', { domain: props.domain, providerId: instanceId, instanceId })
    return
  }
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
          :disabled="busy"
          @change="onSelect"
        >
          <option v-if="busy && !providerList.length" :value="selectedId">Loading…</option>
          <option
            v-for="p in providerList"
            :key="p.id"
            :value="p.id"
            :disabled="!isSelectable(p)"
          >
            {{ entryLabel(p) }}
          </option>
        </select>
        <button
          v-if="configurable"
          class="gear-btn"
          :class="{ 'has-warning': needsAttention }"
          :disabled="!selectedId || busy"
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
    <p v-if="errorText" class="selector-error">{{ errorText }}</p>
  </div>
</template>

<style scoped>
/**
 * The provider selector — a machined control group.
 *
 * Two states carry colour and nothing else does: the focused control takes the
 * accent ring, and the gear takes the status ramp when the selection needs
 * attention. Capability names are metadata (§20.4) and are deliberately styled
 * as neutral "kind" tags, never as the accent.
 *
 * The health dot and the status line take their colour from an inline binding
 * (`toneColor()` in ../availability.js), so the rules below own their geometry
 * and rhythm only; retiring that palette into the status tokens is a change to
 * that module, not to this stylesheet.
 */

.provider-selector {
  width: 100%;
  font-family: var(--body);
  font-size: 13px;
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
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
  margin-bottom: 8px;
}

.variant-inline .selector-controls {
  gap: 6px;
}

.variant-inline .selector-select {
  padding: 8px 30px 8px 11px;
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
  font-size: 10px;
}

.selector-info {
  flex: 1;
  min-width: 0;
}

.selector-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  color: var(--text);
}

.selector-desc {
  font-size: 12px;
  line-height: 1.5;
  color: var(--muted);
  margin: 4px 0 0;
}

.selector-error {
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--fail);
  margin: 8px 0 0;
}

.selector-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.selector-select {
  min-width: 140px;
  padding: 9px 32px 9px 11px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel);
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%237c8698' stroke-width='2'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.selector-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.selector-select:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.gear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel-grad);
  color: var(--muted);
  cursor: pointer;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.16s, border-color 0.16s, color 0.14s,
    box-shadow 0.16s, transform 0.12s var(--ease-spring);
}

.gear-btn:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  color: var(--text);
  transform: translateY(-1px);
}

.gear-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

/* "Needs attention" is a status, so it reads on the status ramp — the accent
   is reserved for the primary action and the active selection. */
.gear-btn.has-warning,
.gear-btn.has-warning:hover:not(:disabled) {
  border-color: var(--warn-line);
  background: var(--warn-dim);
  color: var(--warn);
}

/* The health control doubles as the connection-status badge. */
.health-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  height: 36px;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel-grad);
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  cursor: pointer;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.16s, border-color 0.16s, color 0.14s,
    box-shadow 0.16s, transform 0.12s var(--ease-spring);
}

.health-btn:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  color: var(--text);
  transform: translateY(-1px);
}

.health-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

.health-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
  background: var(--faint);
}

.health-text {
  white-space: nowrap;
}

.selector-capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0 0;
}

/* Capability is metadata. The global `.badge` is the base layer; this narrows
   it to the prototype's neutral kind tag rather than replacing it. */
.selector-capabilities .badge {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 4px;
  color: var(--text-2);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line-soft);
}

.selector-status {
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.5;
  margin: 8px 0 0;
}
</style>
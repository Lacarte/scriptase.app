<script setup>
import { computed } from 'vue'
import { useOptionSource } from '@/shared/composables/useOptionSources.js'
import { isFieldVisible } from '@/shared/schema/visibility.js'
import {
  REDACTION_SENTINEL,
  isSecretField,
  optionSourceOf,
  requiredKeys,
  staticOptions,
  widgetFor,
} from '@/shared/schema/providerSettings.js'

/**
 * The one provider settings renderer (step 12.2).
 *
 * Every field, its widget, its label, its help text, its options, its
 * visibility, and whether it is a secret come from the provider's own public
 * settings schema (contracts.md §22). No provider id appears anywhere in this
 * component, so a new provider configures without a Vue edit — that is the
 * whole point of §26.
 */
const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  // Absent until the provider's schema arrives, and legitimately absent for a
  // provider that ships no `settings_schema.py`.
  schema: { type: Object, default: () => ({}) },
  errors: { type: Array, default: () => [] },
  // Context for `ui.options_source`, so a provider's dropdown can resolve
  // against this instance rather than the global selection (§23.1 / 3.2).
  domain: { type: String, default: '' },
  providerId: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

const required = computed(() => requiredKeys(props.schema))

const optionContext = computed(() =>
  props.domain && props.providerId
    ? {
        domain: props.domain,
        provider: props.providerId,
        instance: props.providerId,
      }
    : {},
)

const fields = computed(() =>
  Object.entries(props.schema?.properties || {}).map(([key, prop]) => {
    const { widget, known } = widgetFor(prop)
    return {
      key,
      prop: prop || {},
      widget,
      unknownWidget: !known,
      secret: isSecretField(key, prop),
      required: required.value.has(key),
      source: optionSourceOf(prop, optionContext.value),
    }
  }),
)

// A hidden field keeps its stored value and is exempt from `required` — the
// server enforces both; the renderer only stops drawing it (§22.3).
const visibleFields = computed(() =>
  fields.value.filter((field) => isFieldVisible(field.prop, props.modelValue)),
)

/**
 * Options for one field. `useOptionSource` is a lookup into a module-level
 * cache keyed by request URL, so calling it per render is a Map hit and the ref
 * it returns is what makes the resolved list arrive reactively.
 */
function asyncState(field) {
  return field.source ? useOptionSource(field.source.source, field.source.context).value : null
}

function optionsFor(field) {
  const async = asyncState(field)
  const listed = async ? async.options : staticOptions(field.prop)
  const current = valueOf(field)
  // Keep a stored value visible even when the provider no longer offers it,
  // instead of silently showing option 0 and saving something else.
  if (current !== '' && current != null && !listed.some((o) => o.value === current)) {
    return [{ value: current, label: `${current} (unavailable)` }, ...listed]
  }
  return listed
}

function optionsLoading(field) {
  return Boolean(asyncState(field)?.loading)
}

function optionsError(field) {
  return asyncState(field)?.error || ''
}

function valueOf(field) {
  const stored = props.modelValue?.[field.key]
  return stored === undefined ? field.prop.default : stored
}

function update(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

/**
 * True while a secret still holds the redacted value the server served.
 *
 * The sentinel *is* the state — there is no separate "am I editing this?" flag.
 * A field holding `"***"` means "unchanged" to the server (§22.6), so the two
 * can never disagree, and a parent that resets the form restores the masked
 * display for free.
 */
function isStoredSecret(field) {
  return field.secret && valueOf(field) === REDACTION_SENTINEL
}

function startReplacing(field) {
  update(field.key, '')
}

function keepStoredSecret(field) {
  update(field.key, REDACTION_SENTINEL)
}

function issuesFor(key) {
  return props.errors.filter((issue) => issue.field === key)
}

function hasError(key) {
  return issuesFor(key).some((issue) => issue.severity === 'error')
}

function numberFrom(raw, field) {
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : (valueOf(field) ?? 0)
}

// Issues about keys the schema no longer declares. The value is preserved
// server-side (§22.5), so the warning is the only thing telling the operator it
// is there — dropping it on the floor would hide a real configuration.
const orphanIssues = computed(() => {
  const known = new Set(Object.keys(props.schema?.properties || {}))
  return props.errors.filter((issue) => issue.field !== 'root' && !known.has(issue.field))
})
</script>

<template>
  <div class="provider-settings-form">
    <p v-if="!visibleFields.length" class="form-empty">
      This provider has no settings to configure.
    </p>

    <div
      v-for="field in visibleFields"
      :key="field.key"
      class="form-field"
      :class="{ 'has-error': hasError(field.key) }"
    >
      <label :for="`field-${field.key}`" class="field-label">
        {{ field.prop.label || field.key }}
        <span v-if="field.required" class="required-badge" title="Required">*</span>
      </label>

      <p v-if="field.prop.description" class="field-description">
        {{ field.prop.description }}
      </p>

      <!-- secret: write-only, replaced explicitly -->
      <div v-if="field.secret" class="secret-field">
        <input
          v-if="!isStoredSecret(field)"
          :id="`field-${field.key}`"
          type="password"
          :value="valueOf(field) ?? ''"
          class="field-input"
          placeholder="Enter a new value…"
          autocomplete="off"
          @input="update(field.key, $event.target.value)"
        />
        <span v-else class="secret-stored">Saved — hidden</span>
        <button
          v-if="isStoredSecret(field)"
          type="button"
          class="link-btn"
          @click="startReplacing(field)"
        >
          Replace
        </button>
        <button v-else type="button" class="link-btn" @click="keepStoredSecret(field)">
          Keep current
        </button>
      </div>

      <!-- dropdown, static or from an allowlisted option source -->
      <template v-else-if="field.widget === 'dropdown'">
        <select
          :id="`field-${field.key}`"
          :value="valueOf(field)"
          :disabled="optionsLoading(field)"
          class="field-input"
          @change="update(field.key, $event.target.value)"
        >
          <option v-for="opt in optionsFor(field)" :key="opt.value" :value="opt.value">
            {{ opt.label || opt.value }}
          </option>
        </select>
        <p v-if="optionsLoading(field)" class="field-note">Loading options…</p>
        <p v-else-if="optionsError(field)" class="issue-message error">
          {{ optionsError(field) }}
        </p>
      </template>

      <div v-else-if="field.widget === 'slider'" class="slider-field">
        <input
          :id="`field-${field.key}`"
          type="range"
          :min="field.prop.minimum ?? 0"
          :max="field.prop.maximum ?? 100"
          :step="field.prop.multipleOf ?? 1"
          :value="valueOf(field)"
          class="slider-input"
          @input="update(field.key, numberFrom($event.target.value, field))"
        />
        <span class="slider-value">{{ valueOf(field) }}</span>
      </div>

      <label v-else-if="field.widget === 'toggle'" class="toggle-field">
        <input
          :id="`field-${field.key}`"
          type="checkbox"
          :checked="valueOf(field) === true"
          class="toggle-input"
          @change="update(field.key, $event.target.checked)"
        />
        <span class="toggle-slider"></span>
      </label>

      <textarea
        v-else-if="field.widget === 'textarea'"
        :id="`field-${field.key}`"
        :value="valueOf(field) ?? ''"
        rows="4"
        class="field-input field-textarea"
        @input="update(field.key, $event.target.value)"
      ></textarea>

      <input
        v-else-if="field.widget === 'number'"
        :id="`field-${field.key}`"
        type="number"
        :min="field.prop.minimum"
        :max="field.prop.maximum"
        :step="field.prop.multipleOf"
        :value="valueOf(field)"
        class="field-input"
        @input="update(field.key, numberFrom($event.target.value, field))"
      />

      <input
        v-else
        :id="`field-${field.key}`"
        type="text"
        :value="valueOf(field) ?? ''"
        class="field-input"
        @input="update(field.key, $event.target.value)"
      />

      <p v-if="field.unknownWidget" class="field-note">
        This installation does not recognize the widget this field asks for; it is
        shown as text.
      </p>

      <div v-if="issuesFor(field.key).length" class="field-issues">
        <p
          v-for="(issue, idx) in issuesFor(field.key)"
          :key="idx"
          class="issue-message"
          :class="issue.severity"
        >
          {{ issue.message }}
        </p>
      </div>
    </div>

    <div v-if="issuesFor('root').length || orphanIssues.length" class="field-issues">
      <p
        v-for="(issue, idx) in [...issuesFor('root'), ...orphanIssues]"
        :key="idx"
        class="issue-message"
        :class="issue.severity"
      >
        {{ issue.message }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.provider-settings-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-empty {
  font-size: 13px;
  color: var(--text-secondary, #9ca3af);
  margin: 0;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field.has-error .field-input {
  border-color: var(--accent-error, #ef4444);
}

.field-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text, #e5e5e5);
}

.required-badge {
  color: var(--accent-error, #ef4444);
  margin-left: 4px;
}

.field-description {
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
  margin: 0;
}

.field-note {
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
  margin: 2px 0 0;
}

.field-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border, #3f3f46);
  border-radius: 6px;
  background: var(--bg-surface, #1f1f23);
  color: var(--text, #e5e5e5);
  font-size: 14px;
  transition: border-color 0.15s;
}

.field-input:focus {
  outline: none;
  border-color: var(--accent, #4ECDC4);
}

.field-textarea {
  resize: vertical;
  font-family: inherit;
}

select.field-input {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%239ca3af' d='M6 8L2 4h8z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 32px;
}

.secret-field {
  display: flex;
  align-items: center;
  gap: 10px;
}

.secret-stored {
  flex: 1;
  padding: 10px 12px;
  border: 1px dashed var(--border, #3f3f46);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-secondary, #9ca3af);
}

.link-btn {
  background: none;
  border: none;
  color: var(--accent, #4ECDC4);
  font-size: 13px;
  cursor: pointer;
  padding: 0;
  white-space: nowrap;
}

.slider-field {
  display: flex;
  align-items: center;
  gap: 12px;
}

.slider-input {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--border, #3f3f46);
  appearance: none;
  cursor: pointer;
}

.slider-input::-webkit-slider-thumb {
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--accent, #4ECDC4);
  cursor: pointer;
}

.slider-value {
  min-width: 48px;
  text-align: right;
  font-size: 14px;
  font-family: monospace;
  color: var(--text, #e5e5e5);
}

.toggle-field {
  position: relative;
  display: inline-block;
  width: 48px;
  height: 24px;
  cursor: pointer;
}

.toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  inset: 0;
  background: var(--border, #3f3f46);
  border-radius: 24px;
  transition: background 0.2s;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  width: 18px;
  height: 18px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}

.toggle-input:checked + .toggle-slider {
  background: var(--accent, #4ECDC4);
}

.toggle-input:checked + .toggle-slider::before {
  transform: translateX(24px);
}

.field-issues {
  margin-top: 4px;
}

.issue-message {
  font-size: 12px;
  margin: 2px 0;
}

.issue-message.error {
  color: var(--accent-error, #ef4444);
}

.issue-message.warning {
  color: var(--accent-warning, #f59e0b);
}

.issue-message.info {
  color: var(--text-secondary, #9ca3af);
}
</style>

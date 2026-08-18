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
/**
 * The one provider settings renderer — the prototype's `.pv-field` rhythm.
 *
 * Every label is the mono/uppercase eyebrow, every control is a panel-on-line
 * box that takes the accent ring on focus, and a validation failure recolours
 * the border on the status ramp. The accent appears on the focus ring, the
 * slider thumb and the checked toggle only: the states the operator is acting
 * on right now.
 *
 * A stored secret is rendered as a recessed well holding a *word*, never a
 * value — the masking itself lives in the script (§22.6) and nothing here may
 * change what that readout contains.
 */

.provider-settings-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.form-empty {
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--muted);
  margin: 0;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: var(--muted);
}

.required-badge {
  color: var(--fail);
  font-size: 11px;
  line-height: 1;
}

.field-description {
  font-size: 12px;
  line-height: 1.5;
  color: var(--muted);
  margin: 0;
}

.field-note {
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.5;
  color: var(--muted);
  margin: 0;
}

.field-input {
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel);
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.field-input::placeholder {
  color: var(--faint);
}

.field-input:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

/* A blocking issue outranks focus, so the field keeps saying it is wrong
   while it is being corrected. */
.form-field.has-error .field-input {
  border-color: var(--fail-line-2);
}

.form-field.has-error .field-input:focus {
  box-shadow: 0 0 0 3px var(--fail-dim);
}

.field-textarea {
  resize: vertical;
  line-height: 1.55;
  font-family: var(--body);
}

select.field-input {
  cursor: pointer;
  appearance: none;
  padding-right: 32px;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%237c8698' stroke-width='2'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
}

.secret-field {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* A secret is entered as mono: it is a key, not prose. */
.secret-field .field-input {
  flex: 1;
  font-family: var(--mono);
  font-size: 12px;
}

/* Recessed well. It carries the word "Saved — hidden" and nothing else. */
.secret-stored {
  flex: 1;
  padding: 9px 11px;
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  background: var(--bg-2);
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.3px;
  color: var(--muted);
}

.link-btn {
  flex: none;
  background: none;
  border: none;
  padding: 0;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.14s;
}

.link-btn:hover {
  color: var(--accent-2);
}

.slider-field {
  display: flex;
  align-items: center;
  gap: 12px;
}

.slider-input {
  flex: 1;
  height: 4px;
  border-radius: 3px;
  background: var(--raise);
  box-shadow: inset 0 0 0 1px var(--line);
  appearance: none;
  cursor: pointer;
}

.slider-input::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-ring), var(--accent-cast);
  cursor: pointer;
}

.slider-input::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: none;
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-ring), var(--accent-cast);
  cursor: pointer;
}

.slider-value {
  min-width: 44px;
  text-align: right;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text);
}

.toggle-field {
  position: relative;
  display: inline-block;
  flex: none;
  width: 44px;
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
  border-radius: 24px;
  background: var(--raise);
  box-shadow: inset 0 0 0 1px var(--line);
  transition: background 0.2s, box-shadow 0.2s;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  width: 18px;
  height: 18px;
  left: 3px;
  bottom: 3px;
  border-radius: 50%;
  background: var(--text);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.45);
  transition: transform 0.2s var(--ease-spring);
}

.toggle-input:checked + .toggle-slider {
  background: var(--accent-grad);
  box-shadow: inset 0 0 0 1px var(--accent-line-2), var(--accent-cast);
}

.toggle-input:checked + .toggle-slider::before {
  transform: translateX(20px);
}

.field-issues {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 2px;
}

.issue-message {
  font-size: 12px;
  line-height: 1.5;
  margin: 0;
}

.issue-message.error {
  color: var(--fail);
}

.issue-message.warning {
  color: var(--warn);
}

.issue-message.info {
  color: var(--muted);
}
</style>

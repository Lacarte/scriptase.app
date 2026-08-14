/**
 * The browser's reading of the provider settings contract (contracts.md §22).
 *
 * Mirrors `studio/shared/providers_common/settings_schema.py` for the decisions
 * a renderer has to make locally — which widget, which fields are secret, which
 * option source to call. The server stays authoritative for validation; this
 * only decides what to draw.
 */

/**
 * §22.6 — what a redacted secret arrives as, and the exact value the client
 * sends back to mean "leave the stored secret alone".
 */
export const REDACTION_SENTINEL = '***'

/** §22.2, frozen. `select` is an accepted spelling of `dropdown`. */
export const WIDGET_TYPES = new Set([
  'text',
  'number',
  'password',
  'dropdown',
  'select',
  'slider',
  'toggle',
  'textarea',
])

/** §22.6 — the same pattern the backend classifies secrets with. */
export const SENSITIVE_KEYS_RE = /(api_key|token|secret|password|auth|bearer|credential)/i

export function isSecretField(key, prop) {
  return prop?.ui?.type === 'password' || SENSITIVE_KEYS_RE.test(key)
}

/**
 * Which widget to draw for one property.
 *
 * `known: false` means the schema named a widget this build does not have; §22.2
 * makes that a text input plus a warning, never an error, so a provider written
 * against a newer platform still configures.
 */
export function widgetFor(prop) {
  const declared = prop?.ui?.type
  if (declared) {
    if (!WIDGET_TYPES.has(declared)) return { widget: 'text', known: false }
    return { widget: declared === 'select' ? 'dropdown' : declared, known: true }
  }
  // Declaring options is itself a widget choice: a field with a fixed option
  // list is a dropdown even when the schema never spelled `ui.type`.
  if (prop?.ui?.options || prop?.ui?.options_source) {
    return { widget: 'dropdown', known: true }
  }
  // The rest of the absent-`ui.type` fallback is driven by the JSON type.
  // `boolean` gets a toggle rather than §22.2's literal text input: a text
  // input can only ever produce a string, which `validate_against_schema`
  // rejects for a boolean property, so the field could never hold a legal value.
  if (prop?.type === 'boolean') return { widget: 'toggle', known: true }
  if (prop?.type === 'number' || prop?.type === 'integer') {
    return { widget: 'number', known: true }
  }
  return { widget: 'text', known: true }
}

/**
 * Normalize `ui.options` into `[{value, label}]`.
 * Accepts bare strings and `{value, label}` objects, as the shipped schemas use both.
 */
export function staticOptions(prop) {
  const options = prop?.ui?.options
  if (!Array.isArray(options)) return []
  return options.map((option) =>
    typeof option === 'object' && option !== null
      ? { value: option.value, label: option.label ?? String(option.value) }
      : { value: option, label: option === '' ? '—' : String(option) },
  )
}

/**
 * Normalize `ui.options_source` into `{source, context}`, or null.
 *
 * §22.4: `ui.options` and `ui.options_source` are mutually exclusive and
 * `options_source` wins, so a caller only has to ask for this first.
 */
export function optionSourceOf(prop, baseContext = {}) {
  const declared = prop?.ui?.options_source
  if (!declared) return null
  if (typeof declared === 'string') return { source: declared, context: { ...baseContext } }
  if (!declared.source) return null
  return { source: declared.source, context: { ...baseContext, ...(declared.context || {}) } }
}

/** Fields listed in the schema's `required` array (§22.1). */
export function requiredKeys(schema) {
  return new Set(Array.isArray(schema?.required) ? schema.required : [])
}

/**
 * Strip secrets from a settings object.
 *
 * Used to keep an unsaved draft: a draft outlives the modal, and a typed
 * credential must not (§22.6).
 */
export function withoutSecrets(values, schema) {
  const props = schema?.properties || {}
  const kept = {}
  for (const [key, value] of Object.entries(values || {})) {
    if (!isSecretField(key, props[key])) kept[key] = value
  }
  return kept
}

/**
 * Drop the secret *properties* from a schema, so a renderer cannot offer them.
 *
 * The node inspector's per-run `provider_options` form uses this: a credential
 * typed there would be persisted into the workflow document, its archives, and
 * its exported templates, which `_validate_provider_options` already refuses at
 * save time. Not drawing the field is how the operator learns that before
 * typing rather than after (§22.6).
 */
export function withoutSecretProperties(schema) {
  const props = schema?.properties || {}
  const kept = {}
  for (const [key, prop] of Object.entries(props)) {
    if (!isSecretField(key, prop)) kept[key] = prop
  }
  return {
    ...schema,
    properties: kept,
    required: (Array.isArray(schema?.required) ? schema.required : []).filter(
      (key) => key in kept,
    ),
  }
}

/**
 * The values a *caller* should act on: schema defaults overlaid with what is
 * stored, secrets removed.
 *
 * A legacy page needs the configured value of a non-secret field — the webhook
 * URL to post to, the prompt prefix to prepend — and an unsaved provider must
 * still behave like its declared defaults, exactly as the un-migrated page's
 * own `|| 'default'` expressions did. Secrets are dropped rather than passed
 * through: a page has no use for one, and what it would receive is the
 * redaction sentinel anyway (§22.6).
 */
export function effectiveSettings(schema, stored) {
  const props = schema?.properties || {}
  const values = {}
  for (const [key, prop] of Object.entries(props)) {
    if (isSecretField(key, prop)) continue
    if (prop?.default !== undefined) values[key] = prop.default
  }
  return { ...values, ...withoutSecrets(stored, schema) }
}

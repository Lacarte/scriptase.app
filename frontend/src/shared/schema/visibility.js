/**
 * The one conditional-visibility rule, shared by workflow node fields and
 * provider settings fields (contracts.md §22.3).
 *
 * Both spellings mean the same thing — AND across keys, OR within a list — and
 * §22.3 froze `ui.show_if` *because* it is the node registry's
 * `display_options.show` under another name. Keeping one implementation is what
 * makes "workflow and legacy forms interpret the same settings contract" true
 * rather than aspirational.
 */

/** AND across keys, OR within each list of allowed values. */
export function matchesAll(conditions, values) {
  for (const [field, allowed] of Object.entries(conditions || {})) {
    const candidates = Array.isArray(allowed) ? allowed : [allowed]
    if (!candidates.includes(values?.[field])) return false
  }
  return true
}

/** True when any key matches — the negative half of `display_options`. */
export function matchesAny(conditions, values) {
  for (const [field, allowed] of Object.entries(conditions || {})) {
    const candidates = Array.isArray(allowed) ? allowed : [allowed]
    if (candidates.includes(values?.[field])) return true
  }
  return false
}

/** n8n-style node field rule: `{show: {field: [values]}, hide: {...}}`. */
export function isDisplayed(displayOptions, values) {
  if (!displayOptions) return true
  return (
    matchesAll(displayOptions.show, values) && !matchesAny(displayOptions.hide, values)
  )
}

/**
 * Provider settings rule: `ui.show_if: {field: [values]}`.
 *
 * A hidden field keeps its stored value, is exempt from `required`, and is not
 * sent in the invocation config — the renderer only has to stop drawing it; the
 * server owns the other two (§22.3).
 */
export function isFieldVisible(prop, values) {
  const showIf = prop?.ui?.show_if
  if (!showIf || typeof showIf !== 'object' || !Object.keys(showIf).length) return true
  return matchesAll(showIf, values)
}

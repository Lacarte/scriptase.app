/**
 * The frozen availability vocabulary (contracts.md §21.5) and its one
 * presentation mapping.
 *
 * Availability is cheap and synchronous — the catalog carries it on every
 * provider, so no surface may derive "is this usable?" from a validation or
 * health round trip. Health is the orthogonal axis: it costs I/O, runs only on
 * an explicit user action, and never blocks selection.
 *
 * Every consumer reads these tables rather than branching on provider ids, so a
 * catalog-only change renders correctly without a component edit.
 */

export const AVAILABLE = 'available'
export const NEEDS_CONFIGURATION = 'needs_configuration'
export const DEGRADED = 'degraded'
/** Discovered but excluded — present only as an `excluded[]` entry (§21.4). */
export const UNAVAILABLE = 'unavailable'

const AVAILABILITY = {
  [AVAILABLE]: { label: 'Ready', tone: 'ok', selectable: true },
  [NEEDS_CONFIGURATION]: { label: 'Needs configuration', tone: 'warn', selectable: true },
  [DEGRADED]: { label: 'Degraded', tone: 'warn', selectable: true },
  [UNAVAILABLE]: { label: 'Unavailable', tone: 'fail', selectable: false },
}

// An unrecognized state is rendered, not swallowed: the same fall-back-and-warn
// rule the widget vocabulary uses (§22.2).
const UNKNOWN_AVAILABILITY = { label: 'Unknown', tone: 'unknown', selectable: true }

/** Frozen health states (§21.5); a provider with no hook reports `unknown`. */
const HEALTH = {
  ok: { label: 'Healthy', tone: 'ok' },
  warn: { label: 'Warning', tone: 'warn' },
  fail: { label: 'Failing', tone: 'fail' },
  unknown: { label: 'Not checked', tone: 'unknown' },
}

const TONE_COLORS = {
  ok: '#22c55e',
  warn: '#f59e0b',
  fail: '#ef4444',
  unknown: '#6b7280',
}

export function availabilityInfo(availability) {
  return AVAILABILITY[availability] || UNKNOWN_AVAILABILITY
}

export function healthInfo(status) {
  return HEALTH[status] || HEALTH.unknown
}

export function toneColor(tone) {
  return TONE_COLORS[tone] || TONE_COLORS.unknown
}

/** True when a provider may be chosen — only an excluded one may not (§24.2). */
export function isSelectable(provider) {
  return availabilityInfo(provider?.availability).selectable
}

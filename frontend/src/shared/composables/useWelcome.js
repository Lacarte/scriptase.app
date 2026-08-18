/**
 * First-run welcome state (step 0.3).
 *
 * The overlay is shown once per browser and never on a deep link — a URL
 * someone handed you names a destination, and a splash screen in front of it
 * is an obstacle rather than an introduction.
 */

export const WELCOME_SEEN_KEY = 'scriptase.welcome.seen'

export function hasSeenWelcome() {
  try {
    return window.localStorage.getItem(WELCOME_SEEN_KEY) === '1'
  } catch {
    // Private mode or a blocked store: never trap the user behind a splash
    // we cannot record as dismissed.
    return true
  }
}

export function markWelcomeSeen() {
  try {
    window.localStorage.setItem(WELCOME_SEEN_KEY, '1')
  } catch {
    // Nothing to do — the overlay is dismissed in memory either way.
  }
}

/**
 * Anything but a bare visit to the root counts as a deep link: a named route,
 * or the root carrying query state (`?job_id=`, `?create=1`, …).
 *
 * @param {{ path?: string, query?: object }} route
 * @returns {boolean}
 */
export function isDeepLink(route) {
  if (!route) return false
  const path = String(route.path || '/')
  if (path !== '/') return true
  return Object.keys(route.query || {}).length > 0
}

/**
 * @param {{ path?: string, query?: object }} route  the entry route
 * @returns {boolean}
 */
export function shouldShowWelcome(route) {
  return !isDeepLink(route) && !hasSeenWelcome()
}

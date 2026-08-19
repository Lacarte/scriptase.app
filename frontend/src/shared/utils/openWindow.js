/**
 * Open an app route in its own browser window (step 14.4).
 *
 * Production and the Workflow canvas each hold a live SSE stream and a running
 * Job. Routing away from them to trim a timeline tears that down, so the
 * Timeline Editor and the Export Library open beside the app instead of on top
 * of it.
 *
 * Two properties the callers depend on:
 *
 * - The URL carries the whole instruction (`?project=…`), never in-memory
 *   state, so the popup survives a reload and stays pasteable.
 * - The window name is derived from the target, so clicking twice focuses the
 *   window already showing that project rather than stacking duplicates — and
 *   a *different* project gets its own window rather than navigating away from
 *   unsaved edits.
 */

/** Editor needs timeline width; the library is a card grid. */
export const APP_WINDOW_TARGETS = {
  editor: { path: '/editor', width: 1600, height: 950 },
  library: { path: '/library', width: 1280, height: 900 },
}

/**
 * Build a same-origin relative URL. Empty and nullish query values are
 * dropped so `?project=` never reaches a page that reads it as an id.
 */
export function buildRouteUrl(path, query = {}) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query || {})) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const search = params.toString()
  return search ? `${path}?${search}` : path
}

/** Window names are matched literally by the browser — keep them predictable. */
export function windowNameFor(target, key = '') {
  const suffix = String(key || '').replace(/[^A-Za-z0-9_-]/g, '') || 'default'
  return `scriptase-${target}-${suffix}`
}

function centeredFeatures(width, height, screen) {
  const availWidth = Number(screen?.availWidth) || Number(screen?.width) || 0
  const availHeight = Number(screen?.availHeight) || Number(screen?.height) || 0
  const w = availWidth > 0 ? Math.min(width, availWidth) : width
  const h = availHeight > 0 ? Math.min(height, availHeight) : height
  const left = availWidth > 0 ? Math.max(0, Math.round((availWidth - w) / 2)) : 0
  const top = availHeight > 0 ? Math.max(0, Math.round((availHeight - h) / 2)) : 0
  return [
    'popup=yes',
    `width=${w}`,
    `height=${h}`,
    `left=${left}`,
    `top=${top}`,
    'resizable=yes',
    'scrollbars=yes',
  ].join(',')
}

/**
 * @param {'editor'|'library'} target
 * @param {object}   [options]
 * @param {object}   [options.query]  route query, e.g. `{ project: 'pm_ABC123' }`
 * @param {string}   [options.key]    window identity; defaults to `query.project`
 * @param {Window}   [options.win]    injected for tests
 * @returns {Window|null} the opened window, or null when a blocker refused it
 */
export function openAppWindow(target, { query = {}, key, win } = {}) {
  const spec = APP_WINDOW_TARGETS[target]
  if (!spec) throw new Error(`Unknown app window target "${target}"`)

  const host = win || (typeof window !== 'undefined' ? window : null)
  if (!host || typeof host.open !== 'function') return null

  const url = buildRouteUrl(spec.path, query)
  const name = windowNameFor(target, key ?? query.project)
  const handle = host.open(url, name, centeredFeatures(spec.width, spec.height, host.screen))
  // A blocked popup returns null; a reused window returns the existing handle,
  // which may be cross-origin-guarded in odd cases, hence the try.
  try {
    handle?.focus?.()
  } catch {
    // Focus is a courtesy — the window is already open either way.
  }

  // A blocker refusing the popup used to end here, and every caller ignored the
  // null — so clicking Library did nothing at all and read as a broken button.
  // The separate window is a preference, not the instruction: the instruction
  // is "show me this project in the Library". Falling back to this tab honours
  // it. The URL already carries the whole instruction, so the destination is
  // identical either way; only the window is lost.
  if (!handle) {
    try {
      host.location?.assign?.(url)
    } catch {
      // Nothing further to try — the caller gets null and can decide.
    }
    return null
  }
  return handle
}

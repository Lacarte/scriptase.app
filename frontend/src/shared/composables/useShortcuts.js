/**
 * One global keydown dispatcher (step 0.3).
 *
 * The shell installs a single listener; views register their own handlers and
 * the most recently mounted view is asked first, so a shortcut always means
 * what it means on the surface you are looking at.
 *
 * Two rules the prototype establishes and this keeps:
 *
 * - Escape reaches handlers even from inside a text field, so a stray focus
 *   can never trap you inside an overlay.
 * - Every other key is ignored while you are typing, so `/` and `?` stay
 *   ordinary characters in a search box.
 *
 * A handler returns `true` to claim the event; the dispatcher then calls
 * preventDefault for it, so no handler has to remember to.
 */
import { onBeforeUnmount, readonly, ref } from 'vue'

/** The sheet `?` opens. Also the single source for the rendered list. */
export const SHORTCUTS = Object.freeze([
  { keys: ['/'], label: 'Focus search' },
  { keys: ['↑', '↓'], label: 'Move through the list' },
  { keys: ['Enter'], label: 'Expand the focused row' },
  { keys: ['Space'], label: 'Select / deselect the focused row' },
  { keys: ['E'], label: 'Open the Timeline Editor' },
  { keys: ['R'], label: 'Run the focused step' },
  { keys: ['Esc'], label: 'Close dialog · clear selection' },
  { keys: ['?'], label: 'Toggle this help' },
])

/** Marks the one input `/` focuses on a view. */
export const SEARCH_ATTR = 'data-shortcut-search'

const sheetOpen = ref(false)
/** Registered in mount order; the dispatcher walks it backwards. */
const handlers = []
let detach = null

export const shortcutsSheetOpen = readonly(sheetOpen)

export function openShortcutsSheet() {
  sheetOpen.value = true
}

export function closeShortcutsSheet() {
  sheetOpen.value = false
}

export function toggleShortcutsSheet() {
  sheetOpen.value = !sheetOpen.value
}

/**
 * @param {EventTarget | null} target
 * @returns {boolean} true when the key belongs to whatever is being typed into
 */
export function isTypingTarget(target) {
  if (!target || typeof target !== 'object') return false
  if (target.isContentEditable) return true
  return /^(INPUT|TEXTAREA|SELECT)$/.test(String(target.tagName || ''))
}

function focusSearchField() {
  const field = document.querySelector(`[${SEARCH_ATTR}]`)
  if (!field || typeof field.focus !== 'function') return false
  field.focus()
  if (typeof field.select === 'function') field.select()
  return true
}

function runHandlers(event) {
  for (let i = handlers.length - 1; i >= 0; i -= 1) {
    if (handlers[i](event) === true) return true
  }
  return false
}

/**
 * Exported so tests can drive it without installing a real listener.
 *
 * @param {KeyboardEvent} event
 * @returns {boolean} whether the event was claimed
 */
export function dispatchShortcut(event) {
  if (event.defaultPrevented) return false

  if (event.key === 'Escape') {
    if (sheetOpen.value) {
      closeShortcutsSheet()
      event.preventDefault()
      return true
    }
    if (runHandlers(event)) {
      event.preventDefault()
      return true
    }
    return false
  }

  if (isTypingTarget(event.target)) return false
  // `?` is Shift+/, so shiftKey is deliberately not a disqualifier here.
  if (event.ctrlKey || event.metaKey || event.altKey) return false

  if (event.key === '?') {
    toggleShortcutsSheet()
    event.preventDefault()
    return true
  }

  if (event.key === '/') {
    if (!focusSearchField()) return false
    event.preventDefault()
    return true
  }

  // The sheet is modal: it swallows the view's shortcuts while it is open.
  if (sheetOpen.value) return false

  if (runHandlers(event)) {
    event.preventDefault()
    return true
  }
  return false
}

/**
 * Install the one document listener. The shell calls this on mount.
 *
 * @returns {() => void} teardown
 */
export function installShortcuts() {
  if (detach) return detach
  const listener = (event) => dispatchShortcut(event)
  document.addEventListener('keydown', listener)
  detach = () => {
    document.removeEventListener('keydown', listener)
    detach = null
  }
  return detach
}

/**
 * Register a view's handler for as long as the calling component is mounted.
 *
 * @param {(event: KeyboardEvent) => boolean | void} handler
 * @returns {() => void} unregister, for the rare caller that needs it early
 */
export function onShortcut(handler) {
  handlers.push(handler)
  const off = () => {
    const idx = handlers.indexOf(handler)
    if (idx !== -1) handlers.splice(idx, 1)
  }
  onBeforeUnmount(off)
  return off
}

/** Test seam — drops every registration and closes the sheet. */
export function resetShortcuts() {
  handlers.length = 0
  sheetOpen.value = false
  if (detach) detach()
}

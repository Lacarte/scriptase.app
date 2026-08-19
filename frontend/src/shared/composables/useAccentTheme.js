/**
 * The prototype's accent shuffle (`randomTheme` / `resetTheme`).
 *
 * The port left `.theme-btn` out as "a feature, and a settings-shaped one".
 * It is a feature, but it is not settings-shaped: it writes six custom
 * properties onto the root element and nothing else, owns no server state, and
 * has no configuration surface. Everything it touches is already a token
 * declared in `styles/theme.css`, so the whole mechanism is an override layer
 * over that file which `reset()` removes.
 *
 * The chosen hue persists in `localStorage`, which the prototype does not do —
 * a page reload there discards the shuffle. Here a reload is routine, and a
 * theme that silently reverted would read as a bug.
 */
import { ref } from 'vue'

const STORAGE_KEY = 'scriptase.accent.hue'

/** The values `theme.css` declares; `reset()` restores exactly these. */
const THEME_DEFAULTS = {
  '--accent': '#6a8cff',
  '--accent-2': '#a58bff',
  '--accent-grad': 'linear-gradient(135deg, #6a8cff, #9b7bff)',
  '--accent-dim': 'rgba(106,140,255,.15)',
  '--run': '#58a6ff',
  '--run-dim': 'rgba(88,166,255,.15)',
  '--glow': '0 0 0 1px rgba(106,140,255,.35), 0 6px 24px -6px rgba(106,140,255,.55)',
}

/** Null when the default palette is in force. */
const hue = ref(null)

/** hsl → hex, s/l in percent. Ported verbatim; the rounding is load-bearing. */
function hslHex(h, s, l) {
  s /= 100
  l /= 100
  const k = n => (n + h / 30) % 12
  const a = s * Math.min(l, 1 - l)
  const f = n => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))
  const to = x => Math.round(255 * x).toString(16).padStart(2, '0')
  return `#${to(f(0))}${to(f(8))}${to(f(4))}`
}

function channels(hex) {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** Paint one hue across every accent-derived token. */
function paint(h) {
  const partner = (h + 38) % 360 // duotone partner, ~40° along the wheel
  const accent = hslHex(h, 78, 70)
  const accent2 = hslHex(partner, 72, 74)
  const run = hslHex(h, 82, 68)

  const [ar, ag, ab] = channels(accent)
  const [br, bg, bb] = channels(accent2)
  const [rr, rg, rb] = channels(run)

  const style = document.documentElement.style
  style.setProperty('--accent', accent)
  style.setProperty('--accent-2', accent2)
  style.setProperty('--accent-grad', `linear-gradient(135deg, ${accent}, ${accent2})`)
  style.setProperty('--accent-dim', `rgba(${ar},${ag},${ab},.15)`)
  style.setProperty('--run', run)
  style.setProperty('--run-dim', `rgba(${rr},${rg},${rb},.15)`)
  style.setProperty(
    '--glow',
    `0 0 0 1px rgba(${ar},${ag},${ab},.35), 0 6px 24px -6px rgba(${ar},${ag},${ab},.55)`,
  )

  // The ambient wash is painted on <body> by theme.css, so re-tinting it means
  // writing the same three gradients back with the new hues.
  document.body.style.background =
    `radial-gradient(1300px 680px at 82% -12%, rgba(${ar},${ag},${ab},.10), transparent 58%),`
    + `radial-gradient(1000px 560px at -6% 112%, rgba(${br},${bg},${bb},.06), transparent 54%),`
    + `radial-gradient(700px 400px at 50% 120%, rgba(53,192,138,.03), transparent 60%), var(--bg)`
}

export function useAccentTheme() {
  /** Re-apply a stored hue. Call once as the shell mounts. */
  function restore() {
    let stored = null
    try {
      stored = localStorage.getItem(STORAGE_KEY)
    } catch {
      // Private-mode and disabled-storage browsers simply get the default.
      return
    }
    if (stored === null) return
    const h = Number(stored)
    if (!Number.isFinite(h) || h < 0 || h > 359) return
    hue.value = h
    paint(h)
  }

  /** @returns {number} the hue chosen, so the caller can report it. */
  function shuffle() {
    const h = Math.floor(Math.random() * 360)
    hue.value = h
    paint(h)
    try {
      localStorage.setItem(STORAGE_KEY, String(h))
    } catch { /* the shuffle still applies for this session */ }
    return h
  }

  function reset() {
    const style = document.documentElement.style
    for (const [token, value] of Object.entries(THEME_DEFAULTS)) {
      style.setProperty(token, value)
    }
    document.body.style.background = '' // fall back to the stylesheet default
    hue.value = null
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch { /* nothing to forget */ }
  }

  return { hue, restore, shuffle, reset }
}

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { APP_NAME } from './shared/constants.js'
import { APP_WINDOW_TARGETS, openAppWindow } from './shared/utils/openWindow.js'
import NavIcon from './shared/components/NavIcon.vue'
import ShortcutsSheet from './shared/components/ShortcutsSheet.vue'
import ToastContainer from './shared/components/ToastContainer.vue'
import WelcomeOverlay from './shared/components/WelcomeOverlay.vue'
import {
  installShortcuts,
  onShortcut,
  toggleShortcutsSheet,
} from './shared/composables/useShortcuts.js'
import { useAccentTheme } from './shared/composables/useAccentTheme.js'
import { useOnAir } from './shared/composables/useOnAir.js'
import { useToast } from './shared/composables/useToast.js'

const route = useRoute()
const fullHeight = computed(() => Boolean(route.meta?.fullHeight))
/** The Timeline Editor is its own window — no studio nav, on-air, or welcome. */
const bare = computed(() => Boolean(route.meta?.bare))

/**
 * The prototype's six destinations, ordered create, run, monitor, output,
 * configure (step 1.1). This is the app's information architecture — nothing
 * else belongs in the first rank.
 */
const navItems = [
  { to: '/script', icon: 'script', label: 'Script', sub: '(S1)' },
  { to: '/production', icon: 'production', label: 'Production' },
  { to: '/schema', icon: 'schema', label: 'Schema' },
  { to: '/library', icon: 'library', label: 'Library' },
  { to: '/channels', icon: 'channels', label: 'Channels' },
  { to: '/providers', icon: 'providers', label: 'Providers' },
]

/**
 * The Editor leaves the app running (step 14.4). It keeps a real `href` so
 * middle-click, "copy link", and a pasted URL all still work — the click
 * handler only upgrades a plain click to a sized window. The Library lost its
 * window link here when it became a destination; Production still opens it in
 * a window rather than tearing down its SSE stream.
 */
const windowLinks = [{ target: 'editor', label: 'Editor' }]

/** Below 860px the destinations collapse behind one toggle (prototype shell). */
const navOpen = ref(false)

/**
 * The prototype's on-air pill. It reads the Job list rather than holding run
 * state of its own — see `useOnAir` for why this polls instead of streaming.
 */
const { live: onAirLive, label: onAirLabel, title: onAirTitle, subscribe: subscribeOnAir } = useOnAir()

/** The prototype's accent shuffle: click to reroll, right-click to reset. */
const { shuffle: shuffleAccent, reset: resetAccent, restore: restoreAccent } = useAccentTheme()
const toast = useToast()

/**
 * The prototype hardcodes "DV" here. The app is local-first and has no user
 * model to draw from, so the avatar reads a name this browser has been given
 * and falls back to the prototype's initials when it has not — chrome that can
 * be made true rather than a fabricated account.
 */
const profileInitials = computed(() => {
  let name = null
  try {
    name = localStorage.getItem('scriptase.profile.name')
  } catch { /* storage disabled; the default stands */ }
  if (!name || !name.trim()) return 'DV'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map(part => part[0]).join('').toUpperCase()
})

function onShuffleAccent() {
  const hue = shuffleAccent()
  toast.success(`Accent shuffled · hue ${hue}°`)
}

function onResetAccent() {
  resetAccent()
  toast.info('Theme reset to default')
}

function pathFor(target) {
  return APP_WINDOW_TARGETS[target].path
}

function openInWindow(target) {
  navOpen.value = false
  openAppWindow(target)
}

function goto(navigate) {
  navOpen.value = false
  navigate()
}

watch(() => route.fullPath, () => {
  navOpen.value = false
})

onShortcut((event) => {
  if (event.key !== 'Escape' || !navOpen.value) return false
  navOpen.value = false
  return true
})

let teardownShortcuts = null
let releaseOnAir = null
onMounted(() => {
  teardownShortcuts = installShortcuts()
  restoreAccent()
  releaseOnAir = subscribeOnAir()
})
onBeforeUnmount(() => {
  teardownShortcuts?.()
  teardownShortcuts = null
  releaseOnAir?.()
  releaseOnAir = null
})
</script>

<template>
  <div class="app-root" :class="{ 'app-root--full': fullHeight, 'app-root--bare': bare }">
    <header v-if="!bare" class="topbar">
      <router-link class="brand" to="/" :aria-label="APP_NAME">
        <span class="logo" aria-hidden="true"></span>
        <span class="name">Script<b>ase</b></span>
        <span class="tag" aria-hidden="true">Studio</span>
      </router-link>

      <button
        type="button"
        class="nav-toggle"
        aria-label="Toggle navigation"
        aria-controls="app-nav"
        :aria-expanded="String(navOpen)"
        @click="navOpen = !navOpen"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <nav id="app-nav" class="topnav" :class="{ open: navOpen }">
        <div class="nav-tabs" role="tablist" aria-label="Main sections">
          <router-link
            v-for="item in navItems"
            :key="item.to"
            v-slot="{ href, navigate, isActive }"
            :to="item.to"
            custom
          >
            <a
              :href="href"
              role="tab"
              :class="{ active: isActive }"
              :aria-selected="String(isActive)"
              :aria-current="isActive ? 'page' : undefined"
              @click.exact.prevent="goto(navigate)"
            >
              <NavIcon :name="item.icon" />
              <span>{{ item.label }}<span v-if="item.sub" class="nav-sub">{{ item.sub }}</span></span>
            </a>
          </router-link>
        </div>
        <div class="nav-windows">
          <a
            v-for="link in windowLinks"
            :key="link.target"
            class="window-link"
            :href="pathFor(link.target)"
            :title="`Open ${link.label} in its own window`"
            @click.exact.prevent="openInWindow(link.target)"
          >{{ link.label }} ↗</a>
        </div>
      </nav>

      <div class="spacer"></div>

      <div
        class="onair"
        :class="{ live: onAirLive }"
        role="status"
        aria-live="polite"
        :title="onAirTitle"
      >
        <span class="dot" aria-hidden="true"></span>
        <span>{{ onAirLabel }}</span>
      </div>

      <button
        type="button"
        class="theme-btn"
        title="Shuffle accent theme · right-click to reset"
        aria-label="Shuffle accent theme"
        @click="onShuffleAccent()"
        @contextmenu.prevent="onResetAccent()"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="13.5" cy="6.5" r="2.5" />
          <circle cx="17.5" cy="12.5" r="2.5" />
          <circle cx="8.5" cy="7.5" r="2.5" />
          <circle cx="6.5" cy="14.5" r="2.5" />
          <path d="M12 22a10 10 0 1 1 0-20 6 6 0 0 0 0 12 3 3 0 0 0 0 6z" />
        </svg>
      </button>

      <button
        type="button"
        class="help-btn"
        aria-label="Keyboard shortcuts"
        title="Keyboard shortcuts (?)"
        @click="toggleShortcutsSheet()"
      >?</button>

      <div class="avatar-me" aria-hidden="true">{{ profileInitials }}</div>
    </header>
    <main id="app-main" class="app-main" :class="{ 'app-main--full': fullHeight }">
      <router-view />
    </main>
    <ToastContainer />
    <ShortcutsSheet v-if="!bare" />
    <WelcomeOverlay v-if="!bare" />
  </div>
</template>

<style>
/* The reset, body background and type ramp live in styles/theme.css.
   This block would otherwise win on order and repaint the ambient wash. */
a {
  color: inherit;
}

#app {
  height: 100%;
}
</style>

<style scoped>
.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-root--full {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.app-root--bare .app-main {
  min-height: 100%;
}

/* The prototype's topbar: a lit bar over the ambient wash, with a hairline
   of light along the top and a hard shadow beneath so it sits above the page.

   The three controls after the spacer — `.onair`, `.theme-btn`, `.avatar-me` —
   were left out by the first pass and are now ported. Each is answered by real
   state rather than the prototype's literals: the pill counts the Job list
   (`useOnAir`), the shuffle writes the accent tokens `theme.css` declares
   (`useAccentTheme`), and the avatar shows this browser's profile initials,
   falling back to the prototype's when none is set. */
.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 56px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 55%), var(--bg-2);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.5), 0 8px 24px -18px rgba(0, 0, 0, 0.9);
  position: sticky;
  top: 0;
  z-index: 30;
  flex: 0 0 auto;
}

.app-root--full .topbar {
  position: relative;
}

/* ---- Brand: a lit tile, the wordmark, and a mono qualifier ---- */
.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  flex: none;
  text-decoration: none;
}

.brand .logo {
  position: relative;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--accent-grad);
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.14) inset,
    0 1px 0 rgba(255, 255, 255, 0.25) inset,
    var(--accent-cast-glow);
}

/* The mark: a rotated square knocked out of the tile. */
.brand .logo::after {
  content: '';
  width: 9px;
  height: 9px;
  border-radius: 2px;
  background: var(--bg);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.9);
  transform: rotate(45deg);
}

.brand .name {
  font-family: var(--display);
  font-weight: 600;
  font-size: 15.5px;
  letter-spacing: -0.4px;
  color: var(--text);
}

/* Only the second half carries the duotone — the wordmark is the one place
   the accent reads as identity rather than as state. */
.brand .name b {
  font-weight: 600;
  background: var(--accent-grad);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.brand .tag {
  margin-left: 2px;
  padding: 2px 7px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--panel);
  font-family: var(--mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

/* ---- Destinations ---- */
.topnav {
  display: flex;
  gap: 2px;
  align-items: center;
  margin-left: 14px;
  min-width: 0;
}

.nav-tabs,
.nav-windows {
  display: flex;
  gap: 2px;
  align-items: center;
}

.nav-windows {
  margin-left: 14px;
}

.topnav a {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--text-2);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  padding: 7px 11px;
  border-radius: 8px;
  white-space: nowrap;
  transition: background 0.18s var(--ease-spring), color 0.15s, box-shadow 0.18s;
}

.topnav a:hover {
  background: var(--panel);
  color: var(--text);
}

.topnav a:hover :deep(.nav-icon) {
  opacity: 1;
}

/* Active is the second and last place the accent appears in the shell. */
.topnav a.active {
  color: var(--text);
  background: var(--accent-fill);
  box-shadow: inset 0 0 0 1px var(--accent-line), var(--accent-cast-sm);
}

.topnav a.active :deep(.nav-icon) {
  opacity: 1;
  color: var(--accent);
}

/* The prototype qualifies Script with a mono suffix — "Script(S1)". */
.topnav a .nav-sub {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.3px;
  color: var(--muted);
}

.topnav a.active .nav-sub {
  color: var(--accent);
}

/* Pushes everything after it to the right edge. */
.spacer {
  flex: 1;
}

/* Icon-only controls keep the prototype's distinct shapes: the navigation
   toggle is a compact panel, while help is a circular utility control. */
.nav-toggle {
  display: none;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 34px;
  height: 34px;
  padding: 0;
  margin-left: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text-2);
  cursor: pointer;
  transition: background 0.16s, color 0.14s, border-color 0.16s;
}

.nav-toggle:hover {
  background: var(--panel-2);
  color: var(--text);
}

.help-btn {
  display: grid;
  place-items: center;
  flex: none;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--panel);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.16s, color 0.14s, border-color 0.16s;
}

.help-btn:hover {
  background: var(--panel-2);
  border-color: var(--line-2);
  color: var(--text);
}

/* Reads as "leaves this page" — it opens its own window, never navigates. */
.window-link {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 12px;
}

.window-link:hover {
  color: var(--accent);
  background: transparent;
}

.app-main {
  flex: 1 1 auto;
  min-height: calc(100vh - 56px);
}

/* No `height: 100%` here, deliberately.

   `.app-main` is a flex child of `.app-root--full`, which is itself exactly
   the viewport and holds a 56px topbar as its first child. A percentage height
   on a flex item resolves against the *container*, not the space left over, so
   `height: 100%` claimed a full viewport beside the topbar and made the column
   100vh + 56px inside a 100vh box. The overflow escaped the panes that were
   supposed to scroll internally, and every Channels scroll moved the whole
   frame instead of the rail or the detail.

   `flex: 1 1 auto` from `.app-main` already grants the leftover space, which is
   the correct height by construction. `min-height: 0` is what lets this shrink
   below its content so the children can own the scrolling. */
.app-main--full {
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.app-main--full > :deep(*) {
  flex: 1 1 auto;
  min-height: 0;
}

/* ================================================================
   Below 860px the destinations collapse behind one toggle.
   Six nowrap links cannot share a 375px bar without forcing a
   horizontal scrollbar on every view underneath.
   ================================================================ */
@media (max-width: 860px) {
  .topbar {
    gap: 10px;
    padding: 0 12px;
  }

  .brand .tag {
    display: none;
  }

  .nav-toggle {
    display: inline-flex;
    order: 3;
  }

  .help-btn {
    order: 4;
  }

  /* The nav becomes a dropdown panel under the bar. */
  .topnav {
    display: none;
    position: absolute;
    top: 56px;
    left: 0;
    right: 0;
    z-index: 40;
    margin: 0;
    flex-direction: column;
    align-items: stretch;
    gap: 3px;
    padding: 8px;
    background: var(--bg-2);
    border-bottom: 1px solid var(--line);
    box-shadow: 0 12px 30px -12px rgba(0, 0, 0, 0.6);
  }

  .topnav.open {
    display: flex;
  }

  .nav-tabs,
  .nav-windows {
    flex-direction: column;
    align-items: stretch;
    gap: 3px;
  }

  .nav-windows {
    margin: 6px 0 0;
    padding-top: 8px;
    border-top: 1px solid var(--line-soft);
  }

  .topnav a {
    padding: 11px 12px;
    font-size: 14px;
  }
}

/* --- topbar tail, ported from the prototype ---------------------------- */

.topbar .spacer {
  flex: 1;
}

/* Live on-air indicator */
.onair {
  display: flex;
  align-items: center;
  gap: 9px;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.4px;
  padding: 6px 13px 6px 11px;
  border-radius: 20px;
  border: 1px solid var(--line);
  background: var(--panel-grad);
  box-shadow: var(--hairline-top);
  color: var(--text-2);
  flex: none;
  white-space: nowrap;
}

.onair .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--faint);
}

.onair.live {
  border-color: rgba(88, 166, 255, 0.45);
  color: var(--run);
  background: var(--run-dim);
  box-shadow: var(--hairline-top), 0 0 20px -6px rgba(88, 166, 255, 0.5);
}

.onair.live .dot {
  background: var(--run);
  box-shadow: 0 0 0 0 rgba(88, 166, 255, 0.7), 0 0 8px var(--run);
  animation: onair-pulse 1.6s infinite;
}

@keyframes onair-pulse {
  0% { box-shadow: 0 0 0 0 rgba(88, 166, 255, 0.6); }
  70% { box-shadow: 0 0 0 7px rgba(88, 166, 255, 0); }
  100% { box-shadow: 0 0 0 0 rgba(88, 166, 255, 0); }
}

/* The pulse is decorative; a reduced-motion request keeps the colour and
   drops the animation rather than hiding the indicator. */
@media (prefers-reduced-motion: reduce) {
  .onair.live .dot {
    animation: none;
  }
}

.theme-btn {
  width: 30px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--accent);
  cursor: pointer;
  flex: none;
  transition: transform 0.35s var(--ease-spring), border-color 0.2s, background 0.2s;
}

.theme-btn:hover {
  background: var(--panel-2);
  border-color: rgba(106, 140, 255, 0.4);
}

.theme-btn:active {
  transform: rotate(180deg) scale(0.92);
}

.theme-btn svg {
  color: var(--accent);
}

.avatar-me {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: linear-gradient(145deg, #2b323b, #1a1e24);
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  box-shadow: inset 0 0 0 1px var(--line);
  flex: none;
}

/* The prototype drops the pill and the avatar before the nav collapses —
   the shuffle and the shortcuts key are the two that stay reachable. */
@media (max-width: 860px) {
  .onair,
  .avatar-me {
    display: none;
  }
}
</style>

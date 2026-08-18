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

const route = useRoute()
const fullHeight = computed(() => Boolean(route.meta?.fullHeight))

/**
 * The prototype's six destinations, ordered create, run, monitor, output,
 * configure (step 1.1). This is the app's information architecture — nothing
 * else belongs in the first rank.
 */
const navItems = [
  { to: '/script', icon: 'script', label: 'Script' },
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

/** Below 820px the destinations collapse behind one toggle (step 0.3). */
const navOpen = ref(false)

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
onMounted(() => {
  teardownShortcuts = installShortcuts()
})
onBeforeUnmount(() => {
  teardownShortcuts?.()
  teardownShortcuts = null
})
</script>

<template>
  <div class="app-root" :class="{ 'app-root--full': fullHeight }">
    <header class="topbar">
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
              <span>{{ item.label }}</span>
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

      <button
        type="button"
        class="help-btn"
        aria-label="Keyboard shortcuts"
        title="Keyboard shortcuts (?)"
        @click="toggleShortcutsSheet()"
      >?</button>
    </header>
    <main id="app-main" class="app-main" :class="{ 'app-main--full': fullHeight }">
      <router-view />
    </main>
    <ToastContainer />
    <ShortcutsSheet />
    <WelcomeOverlay />
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

/* The prototype's topbar: a lit bar over the ambient wash, with a hairline
   of light along the top and a hard shadow beneath so it sits above the page.

   Three of the prototype's topbar controls are deliberately absent, and stay
   absent — they are not styling gaps:
     - `.avatar-me` renders a hardcoded "DV". The app is local-first and has
       no user model, so there is no one to show.
     - `.theme-btn` shuffles the accent duotone at random. That is a feature,
       and a settings-shaped one; it is not part of porting a stylesheet.
     - `.onair` reports whether anything is running. That is Production's
       projection, not the shell's, and wiring it here would mean the shell
       polling for run state. It lands with Production (step 6.2). */
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

/* The prototype qualifies one destination with a mono suffix — "Script (S1)".
   S1 is its own internal view id, so no destination here carries one; the slot
   is part of the family and stays. */
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

/* Icon-only controls: a hit area, no chrome until you touch them. */
.nav-toggle,
.help-btn {
  display: none;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--r-s);
  background: transparent;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.16s, color 0.14s, border-color 0.16s;
}

.nav-toggle:hover,
.help-btn:hover {
  background: var(--panel);
  border-color: var(--line);
  color: var(--text);
}

.help-btn {
  display: inline-flex;
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

.app-main--full {
  min-height: 0;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.app-main--full > :deep(*) {
  flex: 1 1 auto;
  min-height: 0;
}

/* ================================================================
   Below 820px the destinations collapse behind one toggle (step 0.3).
   Six nowrap links cannot share a 375px bar without forcing a
   horizontal scrollbar on every view underneath.
   ================================================================ */
@media (max-width: 820px) {
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
    margin-left: auto;
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
</style>

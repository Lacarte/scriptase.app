<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { APP_NAME } from './shared/constants.js'
import { APP_WINDOW_TARGETS, openAppWindow } from './shared/utils/openWindow.js'
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

const navItems = [
  { to: '/production', label: 'Production' },
  { to: '/workflow', label: 'Workflow' },
  { to: '/channels', label: 'Channels' },
  { to: '/settings/providers', label: 'Settings' },
]

/**
 * Editor and Exports leave the app running (step 14.4). They keep a real
 * `href` so middle-click, "copy link", and a pasted URL all still work — the
 * click handler only upgrades a plain click to a sized window.
 */
const windowLinks = [
  { target: 'editor', label: 'Editor' },
  { target: 'exports', label: 'Exports' },
]

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
    <header class="app-nav">
      <router-link class="brand" to="/">{{ APP_NAME }}</router-link>

      <button
        type="button"
        class="nav-toggle"
        aria-label="Toggle navigation"
        aria-controls="app-nav"
        :aria-expanded="String(navOpen)"
        @click="navOpen = !navOpen"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M3 6h18M3 12h18M3 18h18" />
        </svg>
      </button>

      <nav id="app-nav" class="app-nav-links" :class="{ 'app-nav-links--open': navOpen }">
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
              class="nav-tab"
              :class="{ 'router-link-active': isActive }"
              :aria-selected="String(isActive)"
              :aria-current="isActive ? 'page' : undefined"
              @click.exact.prevent="goto(navigate)"
            >{{ item.label }}</a>
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
   of light along the top and a hard shadow beneath so it sits above the page. */
.app-nav {
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

.app-root--full .app-nav {
  position: relative;
}

.brand {
  font-family: var(--display);
  font-weight: 600;
  font-size: 15.5px;
  letter-spacing: -0.4px;
  text-decoration: none;
  /* The wordmark is the one place the duotone reads as identity. */
  background: var(--accent-grad);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.app-nav-links {
  display: flex;
  gap: 16px;
  align-items: center;
  flex: 1 1 auto;
  min-width: 0;
}

.nav-tabs,
.nav-windows {
  display: flex;
  gap: 2px;
  align-items: center;
}

nav a {
  color: var(--text-2);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  padding: 7px 11px;
  border-radius: var(--r-s);
  white-space: nowrap;
  transition: background 0.18s var(--ease-spring), color 0.15s, box-shadow 0.18s;
}

nav a:hover {
  background: var(--panel);
  color: var(--text);
}

/* Active is the second and last place the accent appears in the shell. */
nav a.router-link-active {
  color: var(--text);
  background: linear-gradient(180deg, rgba(106, 140, 255, 0.12), rgba(106, 140, 255, 0.05));
  box-shadow: inset 0 0 0 1px var(--accent-line), 0 4px 14px -8px rgba(106, 140, 255, 0.6);
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
  font-size: 13px;
  font-weight: 600;
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
  margin-left: auto;
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
  .app-nav {
    gap: 10px;
    padding: 0 14px;
  }

  .nav-toggle {
    display: inline-flex;
    order: 3;
    margin-left: auto;
  }

  .help-btn {
    order: 4;
    margin-left: 0;
  }

  .app-nav-links {
    display: none;
    position: absolute;
    top: 56px;
    left: 0;
    right: 0;
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    padding: 10px 14px 14px;
    background: var(--bg-2);
    border-bottom: 1px solid var(--line);
    box-shadow: 0 14px 30px -18px rgba(0, 0, 0, 0.95);
  }

  .app-nav-links--open {
    display: flex;
  }

  .nav-tabs,
  .nav-windows {
    flex-direction: column;
    align-items: stretch;
    gap: 2px;
  }

  .nav-windows {
    margin-top: 6px;
    padding-top: 8px;
    border-top: 1px solid var(--line-soft);
  }

  nav a {
    padding: 10px 12px;
  }
}
</style>

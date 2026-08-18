<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { APP_NAME } from './shared/constants.js'
import { APP_WINDOW_TARGETS, openAppWindow } from './shared/utils/openWindow.js'
import ToastContainer from './shared/components/ToastContainer.vue'

const route = useRoute()
const fullHeight = computed(() => Boolean(route.meta?.fullHeight))

/**
 * Editor and Exports leave the app running (step 14.4). They keep a real
 * `href` so middle-click, "copy link", and a pasted URL all still work — the
 * click handler only upgrades a plain click to a sized window.
 */
const windowLinks = [
  { target: 'editor', label: 'Editor' },
  { target: 'exports', label: 'Exports' },
]

function pathFor(target) {
  return APP_WINDOW_TARGETS[target].path
}

function openInWindow(target) {
  openAppWindow(target)
}
</script>

<template>
  <div class="app-root" :class="{ 'app-root--full': fullHeight }">
    <header class="app-nav">
      <router-link class="brand" to="/">{{ APP_NAME }}</router-link>
      <nav>
        <router-link to="/production">Production</router-link>
        <router-link to="/workflow">Workflow</router-link>
        <router-link to="/channels">Channels</router-link>
        <router-link to="/settings/providers">Settings</router-link>
        <a
          v-for="link in windowLinks"
          :key="link.target"
          class="window-link"
          :href="pathFor(link.target)"
          :title="`Open ${link.label} in its own window`"
          @click.exact.prevent="openInWindow(link.target)"
        >{{ link.label }} ↗</a>
      </nav>
    </header>
    <main class="app-main" :class="{ 'app-main--full': fullHeight }">
      <router-view />
    </main>
    <ToastContainer />
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

.app-nav {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--border, #2d2e30);
  background: var(--bg-dark, #1a1a1c);
  position: sticky;
  top: 0;
  z-index: 10;
  flex: 0 0 auto;
}

.app-root--full .app-nav {
  position: relative;
}

.brand {
  font-weight: 700;
  letter-spacing: -0.02em;
  text-decoration: none;
  color: var(--text, #e8eaed);
  font-family: var(--font-display, system-ui, sans-serif);
}

nav {
  display: flex;
  gap: 1rem;
}

nav a {
  color: var(--text-secondary, #9aa0a6);
  text-decoration: none;
  font-size: 0.95rem;
}

nav a.router-link-active {
  color: var(--accent, #8ab4f8);
}

/* Reads as "leaves this page" — it opens its own window, never navigates. */
.window-link {
  color: var(--text-dim, #6b7280);
}

.window-link:hover {
  color: var(--accent, #8ab4f8);
}

.app-main {
  flex: 1 1 auto;
  min-height: calc(100vh - 52px);
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
</style>

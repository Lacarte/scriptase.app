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

nav {
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
</style>

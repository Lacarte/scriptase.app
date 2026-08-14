<script setup>
import { APP_NAME } from './shared/constants.js'
</script>

<template>
  <div class="app-root">
    <header class="app-nav">
      <router-link class="brand" to="/">{{ APP_NAME }}</router-link>
      <nav>
        <router-link to="/channels">Channels</router-link>
      </nav>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style>
:root {
  color-scheme: dark;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: #121214;
  color: #e8eaed;
}

a {
  color: inherit;
}
</style>

<style scoped>
.app-root {
  min-height: 100vh;
  font-family: "Segoe UI", system-ui, sans-serif;
}

.app-nav {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid #2d2e30;
  background: #1a1a1c;
  position: sticky;
  top: 0;
  z-index: 10;
}

.brand {
  font-weight: 700;
  letter-spacing: -0.02em;
  text-decoration: none;
  color: #e8eaed;
}

nav {
  display: flex;
  gap: 1rem;
}

nav a {
  color: #9aa0a6;
  text-decoration: none;
  font-size: 0.95rem;
}

nav a.router-link-active {
  color: #8ab4f8;
}

.app-main {
  min-height: calc(100vh - 52px);
}
</style>

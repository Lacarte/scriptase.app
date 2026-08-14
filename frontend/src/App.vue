<script setup>
// Scaffold shell. The two views land in Phase 2:
//   features/production — the step/window Production view
//   features/workflow   — the ported Vue Flow builder
// Both render from the same backend records; neither hardcodes a step list.
import { APP_NAME } from './shared/constants.js'
</script>

<template>
  <main class="app-shell">
    <h1>{{ APP_NAME }}</h1>
    <p>Scaffold. Production and Workflow views land in Phase 2.</p>
  </main>
</template>

<style scoped>
.app-shell {
  font-family: system-ui, sans-serif;
  padding: 2rem;
}
</style>

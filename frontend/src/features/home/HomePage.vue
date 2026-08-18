<script setup>
/**
 * The landing destination.
 *
 * This deliberately lives in an SFC rather than inline in `router.js`. A
 * component declared with a string `template` needs Vue's runtime compiler,
 * which the standard `vue.runtime.esm-bundler` build does not ship — so it
 * threw on render ("runtime compilation is not supported in this build"), and
 * the failure cascaded: the router's injections were lost and every route
 * mounted afterwards, including the Library, crashed reaching for `route.query`.
 */
import { APP_NAME } from '@/shared/constants.js'
</script>

<template>
  <section class="home">
    <h1 class="page-title">{{ APP_NAME }}</h1>
    <p class="page-subtitle">
      Channel-aware, provider-driven, local-first AI video production.
      Production and Schema are projections of one node-based execution.
    </p>
    <p class="home-actions">
      <router-link class="btn primary" to="/production">Open Production →</router-link>
      <router-link class="btn" to="/script">Open Script →</router-link>
      <router-link class="btn" to="/channels">Open Channels →</router-link>
    </p>
  </section>
</template>

<style scoped>
.home {
  max-width: 720px;
  margin: 0 auto;
  padding: 2rem 1.25rem;
  font-family: var(--body);
  color: var(--text);
}
.page-title { font-size: 28px; }
.page-subtitle { font-size: 13.5px; }
.home-actions {
  margin-top: 1.5rem;
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
}
</style>

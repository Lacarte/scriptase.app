<script setup>
/**
 * Schema is a read-only projection of the running job — it never executes
 * anything, which is the one rule the whole project hangs off. Step 1.1 lands
 * the destination; step 1.2 renders the graph from the backend node registry
 * and the stage projection, never from a hardcoded array in here.
 */
import { RouterLink } from 'vue-router'

defineOptions({ name: 'SchemaPage' })
</script>

<template>
  <section class="schema-page">
    <header class="page-header">
      <h1 class="page-title">Schema</h1>
      <p class="page-subtitle">
        The workflow graph as the engine sees it, read-only. Nodes are the execution
        model; this view watches them, it never runs them.
      </p>
    </header>

    <div class="panel placeholder">
      <span class="section-label">Not built yet</span>
      <p>
        The canvas arrives in step 1.2, projected from the node registry, with live
        job animation and the node inspector following in 1.3 and 1.4.
      </p>
      <p class="links">
        <RouterLink class="btn primary" to="/production">Watch a Job in Production →</RouterLink>
      </p>
    </div>
  </section>
</template>

<style scoped>
.schema-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 20px 40px;
}

.page-header {
  margin-bottom: 18px;
}

.placeholder {
  padding: 20px;
}

.placeholder p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-2);
}

.links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px !important;
}
</style>

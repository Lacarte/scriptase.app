<script setup>
/**
 * The Script destination exists from step 1.1 so the nav's first rank is real
 * rather than a dead tab. The studio itself — Channel-driven generation,
 * the beat outline and the hand-off into Production — is Phase 3.
 */
import { RouterLink } from 'vue-router'

defineOptions({ name: 'ScriptPage' })
</script>

<template>
  <section class="script-page">
    <header class="page-header">
      <h1 class="page-title">Script</h1>
      <p class="page-subtitle">
        Where a Channel becomes a draft: brief, generation, beat outline and revision,
        before anything is queued for production.
      </p>
    </header>

    <div class="panel placeholder">
      <span class="section-label">Not built yet</span>
      <p>
        The Script studio arrives in Phase 3. Until then a script is written by the
        Script node inside a Job, so start one from Production.
      </p>
      <p class="links">
        <RouterLink class="btn primary" to="/production">Go to Production →</RouterLink>
        <RouterLink class="btn" to="/channels">Edit Channels →</RouterLink>
      </p>
    </div>
  </section>
</template>

<style scoped>
.script-page {
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

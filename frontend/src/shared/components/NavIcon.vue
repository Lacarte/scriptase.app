<script setup>
/**
 * The prototype's six nav glyphs, traced from its topbar (step 1.1).
 *
 * They are decorative — the label beside each one is the accessible name — so
 * every SVG is `aria-hidden`. Rects and paths mix per glyph, which is why this
 * is a template switch rather than a table of path data.
 */
defineProps({
  name: {
    type: String,
    required: true,
    validator: (value) =>
      ['script', 'production', 'schema', 'library', 'channels', 'providers'].includes(value),
  },
})
</script>

<template>
  <svg
    class="nav-icon"
    width="15"
    height="15"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    aria-hidden="true"
  >
    <template v-if="name === 'script'">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </template>
    <template v-else-if="name === 'production'">
      <rect x="3" y="4" width="18" height="4" rx="1" />
      <rect x="3" y="10" width="18" height="4" rx="1" />
      <rect x="3" y="16" width="18" height="4" rx="1" />
    </template>
    <template v-else-if="name === 'schema'">
      <rect x="3" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="8" width="7" height="5" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
      <path d="M10 5.5h2a2 2 0 0 1 2 2v3M10 18.5h2a2 2 0 0 0 2-2v-3" />
    </template>
    <template v-else-if="name === 'library'">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </template>
    <template v-else-if="name === 'channels'">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </template>
    <template v-else-if="name === 'providers'">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
    </template>
  </svg>
</template>

<style scoped>
.nav-icon {
  flex: none;
  opacity: 0.75;
  transition: opacity 0.15s, color 0.15s;
}
</style>

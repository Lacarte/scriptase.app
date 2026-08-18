<script setup>
/**
 * The Channels index. In the prototype this route and the editor are one
 * screen — a rail beside a detail pane — so both render the same shell and
 * differ only in what fills `.ch-detail` (step 6.4). With nothing selected
 * that is the prototype's `ch-empty` placeholder.
 */
import ChannelRail from './ChannelRail.vue'
</script>

<template>
  <section class="chview" aria-label="Channels">
    <ChannelRail />

    <main class="ch-detail">
      <div class="ch-empty">
        <div class="ic">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
            <rect x="3" y="3" width="7" height="7" rx="1.5" />
            <rect x="14" y="3" width="7" height="7" rx="1.5" />
            <rect x="3" y="14" width="7" height="7" rx="1.5" />
            <rect x="14" y="14" width="7" height="7" rx="1.5" />
          </svg>
        </div>
        <h3>No channel selected</h3>
        <p>Pick a channel to edit its identity and production defaults.</p>
      </div>
    </main>
  </section>
</template>

<style scoped>
/* The prototype's `.body.chview`: a channel rail and a scrolling detail. */
.chview {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: var(--bg);
}

.ch-detail { min-width: 0; overflow-y: auto; }

.ch-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--muted);
  padding: 40px;
}

.ch-empty .ic {
  width: 60px;
  height: 60px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  background: var(--panel);
  box-shadow: inset 0 0 0 1px var(--line);
  color: var(--faint);
  margin-bottom: 18px;
}

.ch-empty h3 { margin: 0 0 7px; font-family: var(--display); font-size: 16px; color: var(--text); }
.ch-empty p { margin: 0; font-size: 13px; max-width: 300px; line-height: 1.6; }

/* The prototype hides the rail below 820px. Here it is the only way to reach
   a channel from this route, so it stacks above the detail instead. */
@media (max-width: 820px) {
  .chview { display: block; overflow-y: auto; }
  .ch-rail { border-right: 0; border-bottom: 1px solid var(--line); }
}
</style>

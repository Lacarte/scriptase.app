<script setup>
/**
 * The `?` cheat sheet (step 0.3, restyled step 8.3).
 *
 * Rendered from SHORTCUTS so the documented bindings and the dispatched ones
 * cannot drift apart. Escape is handled centrally by the dispatcher.
 *
 * The chrome is the prototype's `modal keys-modal` → `modal-head` →
 * `modal-body` with a `keys-grid` of `krow` entries → `modal-foot`.
 */
import { nextTick, ref, watch } from 'vue'

import {
  SHORTCUTS,
  closeShortcutsSheet,
  shortcutsSheetOpen,
} from '../composables/useShortcuts.js'

const closeButton = ref(null)

watch(shortcutsSheetOpen, (open) => {
  if (open) void nextTick(() => closeButton.value?.focus())
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="shortcutsSheetOpen"
      class="overlay"
      @click.self="closeShortcutsSheet()"
    >
      <div
        class="modal keys-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
      >
        <div class="modal-head">
          <div class="ic" style="background:var(--run-dim);color:var(--run)">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8"/>
            </svg>
          </div>
          <h3 id="shortcuts-title">Keyboard shortcuts</h3>
        </div>
        <div class="modal-body" style="padding-left:20px">
          <div class="keys-grid">
            <div v-for="shortcut in SHORTCUTS" :key="shortcut.label" class="krow">
              <kbd v-for="key in shortcut.keys" :key="key">{{ key }}</kbd>
              <span>{{ shortcut.label }}</span>
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button ref="closeButton" type="button" class="btn ghost" @click="closeShortcutsSheet()">
            Close
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

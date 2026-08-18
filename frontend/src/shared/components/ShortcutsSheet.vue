<script setup>
/**
 * The `?` cheat sheet (step 0.3).
 *
 * Rendered from SHORTCUTS so the documented bindings and the dispatched ones
 * cannot drift apart. Escape is handled centrally by the dispatcher.
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
      class="sheet-backdrop"
      @click.self="closeShortcutsSheet()"
    >
      <div
        class="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
      >
        <h2 id="shortcuts-title" class="sheet-title">Keyboard shortcuts</h2>
        <dl class="sheet-list">
          <div v-for="shortcut in SHORTCUTS" :key="shortcut.label" class="sheet-row">
            <dt class="sheet-keys">
              <kbd v-for="key in shortcut.keys" :key="key">{{ key }}</kbd>
            </dt>
            <dd class="sheet-label">{{ shortcut.label }}</dd>
          </div>
        </dl>
        <div class="sheet-foot">
          <button ref="closeButton" type="button" class="sheet-close" @click="closeShortcutsSheet()">
            Close
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9997;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(4, 6, 10, 0.72);
}

.sheet {
  width: min(440px, 100%);
  max-height: 100%;
  overflow: auto;
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r-l);
  box-shadow: var(--shadow);
  padding: 20px;
  font-family: var(--body);
  color: var(--text);
}

.sheet-title {
  margin: 0 0 16px;
  font-family: var(--display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.3px;
}

.sheet-list {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sheet-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 0;
  border-bottom: 1px solid var(--line-soft);
}

.sheet-row:last-child {
  border-bottom: none;
}

.sheet-keys {
  flex: none;
  display: flex;
  gap: 4px;
  min-width: 92px;
  margin: 0;
}

kbd {
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  padding: 5px 7px;
  min-width: 22px;
  text-align: center;
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 5px;
  box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.4);
}

.sheet-label {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-2);
}

.sheet-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 18px;
}

.sheet-close {
  border: 1px solid var(--line);
  background: var(--panel-grad);
  color: var(--text);
  border-radius: var(--r-s);
  padding: 8px 16px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: var(--hairline-top);
}

.sheet-close:hover {
  background: var(--panel-grad2);
  border-color: var(--line-2);
}
</style>

<script setup>
import { useToast } from '../composables/useToast'

const { toasts, dismiss } = useToast()

function runAction(toast) {
  toast.action?.onAction?.()
  dismiss(toast.id)
}
</script>

<template>
  <Teleport to="body">
    <!-- One always-mounted live region (step 0.3): a region created at the
         moment of the announcement is not reliably read out. -->
    <div class="toast-region" role="status" aria-live="polite" aria-atomic="false">
      <TransitionGroup name="toast" tag="div" class="toast-container">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="toast"
          :class="toast.type"
          @click="dismiss(toast.id)"
        >
          <span class="toast-message">{{ toast.message }}</span>
          <button
            v-if="toast.action"
            type="button"
            class="toast-action"
            @click.stop="runAction(toast)"
          >
            {{ toast.action.label }}
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
/* The region spans the corner but must never eat clicks meant for the page
   beneath it, so only the toasts themselves are hit-testable. */
.toast-region {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 9999;
  pointer-events: none;
}

.toast-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 15px;
  border-radius: var(--r);
  font-family: var(--body);
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  cursor: pointer;
  max-width: 380px;
}

/* The status dot — the toast markup carries no element for it, so it is
   drawn here rather than by changing a template the tests assert on. */
.toast::before {
  content: '';
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--queue);
}

.toast-message {
  flex: 1 1 auto;
  min-width: 0;
}

/* Undo (step 0.3) — the accent, because it is the one thing to act on. */
.toast-action {
  flex: none;
  margin-left: 4px;
  border: 1px solid var(--line);
  background: var(--raise);
  color: var(--accent);
  border-radius: 6px;
  padding: 4px 11px;
  font-family: var(--body);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.toast-action:hover {
  background: var(--accent-wash);
  border-color: var(--accent-line);
}

.toast.success::before { background: var(--ok); }
.toast.error::before   { background: var(--fail); }
.toast.warning::before { background: var(--warn); }
.toast.info::before    { background: var(--run); }

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from { transform: translateX(100%); opacity: 0; }
.toast-leave-to   { transform: translateX(100%); opacity: 0; }
</style>

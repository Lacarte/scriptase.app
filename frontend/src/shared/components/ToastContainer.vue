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
      <TransitionGroup name="toast" tag="div" class="toasts">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="toast"
          :class="toast.type"
          @click="dismiss(toast.id)"
        >
          <span class="dot" aria-hidden="true"></span>
          <span class="tmsg">{{ toast.message }}</span>
          <button
            v-if="toast.action"
            type="button"
            class="toast-undo"
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
   beneath it, so only the toasts themselves are hit-testable. The prototype
   stacks them bottom-right, out of the way of every page header. */
.toast-region {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 200;
  pointer-events: none;
}

.toasts {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 240px;
  max-width: 380px;
  padding: 11px 15px;
  border-radius: var(--r);
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--line);
  /* Toasts float higher than any panel — they sit over everything. */
  box-shadow: var(--shadow), 0 20px 40px -18px rgba(0, 0, 0, 0.8);
  cursor: pointer;
}

.toast .dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--queue);
}

.tmsg {
  flex: 1 1 auto;
  min-width: 0;
}

/* Undo (step 0.3) — the accent, because it is the one thing to act on. */
.toast-undo {
  flex: none;
  margin-left: 6px;
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

.toast-undo:hover {
  background: var(--accent-dim);
  border-color: var(--accent-line);
}

/* The prototype's names on the left, `useToast`'s on the right — the
   composable's vocabulary is the API, so both spellings resolve. */
.toast.ok .dot,
.toast.success .dot { background: var(--ok); }
.toast.err .dot,
.toast.error .dot   { background: var(--fail); }
.toast.warn .dot,
.toast.warning .dot { background: var(--warn); }
.toast.info .dot    { background: var(--run); }

.toast-enter-active,
.toast-leave-active {
  transition: all 0.22s ease;
}

.toast-enter-from { transform: translateX(20px); opacity: 0; }
.toast-leave-to   { transform: translateX(20px); opacity: 0; }
</style>

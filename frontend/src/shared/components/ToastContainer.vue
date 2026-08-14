<script setup>
import { useToast } from '../composables/useToast'

const { toasts, dismiss } = useToast()
</script>

<template>
  <Teleport to="body">
    <TransitionGroup name="toast" tag="div" class="toast-container">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="toast"
        :class="toast.type"
        @click="dismiss(toast.id)"
      >
        {{ toast.message }}
      </div>
    </TransitionGroup>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  padding: 10px 20px;
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-md);
  cursor: pointer;
  max-width: 380px;
}

.toast.success { border-left: 3px solid var(--accent-success); }
.toast.error   { border-left: 3px solid var(--accent-error); }
.toast.warning { border-left: 3px solid var(--accent-warning); }
.toast.info    { border-left: 3px solid var(--accent-info); }

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from { transform: translateX(100%); opacity: 0; }
.toast-leave-to   { transform: translateX(100%); opacity: 0; }
</style>

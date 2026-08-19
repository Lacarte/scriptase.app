<script setup>
/**
 * Right-click realign menu for the Schema canvas (step 1.2).
 *
 * Every item here moves the camera or the cards. None of them touches the
 * workflow, so there is deliberately no destructive entry and no Undo toast to
 * pair with one — realigning a projection cannot lose anything.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  /** Node the menu was opened on, or null for the empty canvas. */
  node: { type: Object, default: null },
})

const emit = defineEmits(['select', 'close'])

const MENU_W = 200
const MENU_H = 280

const root = ref(null)

const style = computed(() => {
  const vw = typeof window === 'undefined' ? MENU_W : window.innerWidth
  const vh = typeof window === 'undefined' ? MENU_H : window.innerHeight
  return {
    left: `${Math.max(8, Math.min(props.x, vw - MENU_W - 8))}px`,
    top: `${Math.max(8, Math.min(props.y, vh - MENU_H - 8))}px`,
  }
})

function choose(action) {
  emit('select', { action, nodeId: props.node?.id || null })
  emit('close')
}

function onWindowDown(event) {
  if (root.value && root.value.contains(event.target)) return
  emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') emit('close')
}

watch(() => props.open, (open) => {
  if (typeof window === 'undefined') return
  if (open) {
    window.addEventListener('mousedown', onWindowDown, true)
    window.addEventListener('keydown', onKeydown)
  } else {
    window.removeEventListener('mousedown', onWindowDown, true)
    window.removeEventListener('keydown', onKeydown)
  }
})

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return
  window.removeEventListener('mousedown', onWindowDown, true)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div
    v-if="open"
    ref="root"
    class="ctx-menu open"
    role="menu"
    aria-label="Realign the schema canvas"
    :style="style"
  >
    <template v-if="node">
      <div class="ctx-head">{{ node.name }}</div>
      <button class="ctx-item" role="menuitem" type="button" @click="choose('center-node')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" />
        </svg>
        <span>Center on node</span>
      </button>
      <button class="ctx-item" role="menuitem" type="button" @click="choose('reset-node')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
        <span>Reset this node</span>
      </button>
      <div class="ctx-sep" />
    </template>

    <div class="ctx-head">Realign</div>
    <button class="ctx-item" role="menuitem" type="button" @click="choose('auto-align')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M21 10H3M21 6H3M21 14H3M21 18H3" />
      </svg>
      <span>Auto-align layout</span>
    </button>
    <button class="ctx-item" role="menuitem" type="button" @click="choose('snap-grid')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
      </svg>
      <span>Snap all to grid</span>
    </button>
    <button class="ctx-item" role="menuitem" type="button" @click="choose('reset-layout')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" />
      </svg>
      <span>Reset positions</span>
    </button>
    <div class="ctx-sep" />
    <button class="ctx-item" role="menuitem" type="button" @click="choose('fit')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3" />
      </svg>
      <span>Fit &amp; centre view</span>
    </button>
  </div>
</template>

<style scoped>
.ctx-menu {
  position: fixed;
  z-index: 100;
  min-width: 176px;
  padding: 5px;
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: var(--panel-grad2);
  box-shadow: var(--shadow), 0 30px 60px -24px rgba(0, 0, 0, 0.85);
  animation: ctx-pop 0.12s ease;
}

@keyframes ctx-pop {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}

.ctx-head {
  padding: 6px 10px 3px;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.7px;
  text-transform: uppercase;
  color: var(--muted);
}

.ctx-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-2);
  font-family: var(--body);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.ctx-item:hover {
  background: var(--raise);
  color: var(--text);
}

.ctx-item svg {
  flex: none;
  width: 14px;
  height: 14px;
  opacity: 0.8;
}

.ctx-sep {
  height: 1px;
  margin: 5px 4px;
  background: var(--line-soft);
}
</style>

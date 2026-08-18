<script setup>
/**
 * First-run welcome (step 0.3).
 *
 * The prototype treats this as part of the floor rather than decoration: a lit
 * ambient field, the wordmark, one sentence about what the app is, and a single
 * way in. It appears once per browser and never in front of a deep link.
 */
import { nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { markWelcomeSeen, shouldShowWelcome } from '../composables/useWelcome.js'
import { onShortcut } from '../composables/useShortcuts.js'

const route = useRoute()

const visible = ref(false)
const leaving = ref(false)
const enterButton = ref(null)

function dismiss() {
  if (!visible.value || leaving.value) return
  leaving.value = true
  markWelcomeSeen()
  // Let the exit animation play, then unmount. Reduced motion collapses the
  // animation to ~0ms, so this timeout is the only thing still holding it.
  setTimeout(() => {
    visible.value = false
    leaving.value = false
  }, 460)
}

onShortcut((event) => {
  if (!visible.value || event.key !== 'Escape') return false
  dismiss()
  return true
})

onMounted(() => {
  if (!shouldShowWelcome(route)) return
  visible.value = true
  void nextTick(() => enterButton.value?.focus())
})

defineExpose({ dismiss })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="welcome"
      :class="{ leaving }"
      role="dialog"
      aria-modal="true"
      aria-labelledby="welcome-title"
    >
      <div class="welcome-bg" aria-hidden="true">
        <div class="welcome-sweep"></div>
        <div class="welcome-grid"></div>
        <div class="welcome-orb welcome-orb--blue"></div>
        <div class="welcome-orb welcome-orb--violet"></div>
      </div>

      <div class="welcome-content">
        <h1 id="welcome-title" class="welcome-title">Scriptase</h1>
        <p class="welcome-kicker">Studio</p>
        <div class="welcome-rule" aria-hidden="true"></div>
        <p class="welcome-copy">
          Channel-aware, provider-driven AI video production — local-first.
          Pick a channel, choose where the script comes from, and one node
          engine runs the whole pipeline. Production, Schema and the Library
          are windows onto that same run.
        </p>
        <p class="welcome-tagline">Script. Narrate. Segment. Visualise. Export.</p>
        <button
          ref="enterButton"
          type="button"
          class="welcome-enter"
          @click="dismiss"
        >
          Enter Studio
        </button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.welcome {
  position: fixed;
  inset: 0;
  z-index: 9998;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: var(--bg);
}

.welcome.leaving {
  animation: welcome-out 0.46s ease forwards;
}

@keyframes welcome-out {
  to {
    opacity: 0;
    transform: scale(1.03);
  }
}

.welcome-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

/* The ambient field: a slow duotone sweep behind a hairline grid. */
.welcome-sweep {
  position: absolute;
  inset: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(
    135deg,
    var(--bg) 0%,
    var(--panel) 14%,
    rgba(106, 140, 255, 0.2) 34%,
    var(--bg) 46%,
    rgba(165, 139, 255, 0.18) 64%,
    var(--bg) 78%,
    rgba(106, 140, 255, 0.14) 90%,
    var(--bg) 100%
  );
  background-size: 200% 200%;
  animation: welcome-sweep 12s ease infinite;
}

@keyframes welcome-sweep {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

.welcome-grid {
  position: absolute;
  inset: 0;
  opacity: 0.22;
  background-image:
    linear-gradient(var(--line) 1px, transparent 1px),
    linear-gradient(90deg, var(--line) 1px, transparent 1px);
  background-size: 60px 60px;
}

.welcome-orb {
  position: absolute;
  border-radius: 50%;
}

.welcome-orb--blue {
  top: 18%;
  left: 12%;
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(106, 140, 255, 0.18), transparent 70%);
  animation: welcome-float 8s ease-in-out infinite;
}

.welcome-orb--violet {
  right: 12%;
  bottom: 18%;
  width: 250px;
  height: 250px;
  background: radial-gradient(circle, rgba(165, 139, 255, 0.16), transparent 70%);
  animation: welcome-float 10s ease-in-out infinite reverse;
}

@keyframes welcome-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-18px); }
}

.welcome-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  max-width: 620px;
  padding: 24px;
  text-align: center;
  animation: welcome-rise 0.9s var(--ease-spring) both;
}

@keyframes welcome-rise {
  from { opacity: 0; transform: translateY(22px); }
  to { opacity: 1; transform: none; }
}

.welcome-title {
  margin: 0;
  font-family: var(--display);
  font-size: 52px;
  font-weight: 600;
  letter-spacing: -1.6px;
  line-height: 1;
  background: var(--accent-grad);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.welcome-kicker {
  margin: 0;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 4px;
  color: var(--muted);
}

.welcome-rule {
  width: 64px;
  height: 1px;
  margin: 6px 0;
  background: linear-gradient(90deg, transparent, var(--line-2), transparent);
}

.welcome-copy {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-2);
}

.welcome-tagline {
  margin: 0;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.6px;
  color: var(--faint);
}

.welcome-enter {
  margin-top: 12px;
  border: none;
  border-radius: var(--r-s);
  padding: 13px 30px;
  font-family: var(--body);
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  cursor: pointer;
  background: var(--accent-grad);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
  transition: filter 0.14s, transform 0.1s var(--ease-spring);
}

.welcome-enter:hover {
  filter: brightness(1.07) saturate(1.05);
}

.welcome-enter:active {
  transform: translateY(1px);
}

@media (max-width: 820px) {
  .welcome-title { font-size: 38px; letter-spacing: -1px; }
  .welcome-orb { display: none; }
}
</style>

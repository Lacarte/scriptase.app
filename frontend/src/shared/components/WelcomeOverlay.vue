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
  }, 500)
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
      class="welcome-root"
      :class="{ dismissing: leaving }"
      role="dialog"
      aria-modal="true"
      aria-labelledby="welcome-title"
    >
      <div class="welcome-bg" aria-hidden="true">
        <div class="welcome-gradient"></div>
        <div class="welcome-grid"></div>
        <div class="welcome-orb welcome-orb--blue"></div>
        <div class="welcome-orb welcome-orb--purple"></div>
        <svg class="welcome-icon welcome-icon--film" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
          <rect x="2" y="4" width="20" height="16" rx="2" />
          <path d="M7 4v16M17 4v16M2 9h5M2 15h5M17 9h5M17 15h5" />
        </svg>
        <svg class="welcome-icon welcome-icon--wave" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
          <path d="M3 12h2M7 7v10M11 4v16M15 8v8M19 11h2" />
        </svg>
      </div>

      <div class="welcome-content">
        <div class="welcome-logo" aria-hidden="true"><span class="wl-mark"></span></div>
        <div class="welcome-titles">
          <h1 id="welcome-title" class="welcome-h1">Scriptase</h1>
          <p class="welcome-studio">Studio</p>
        </div>
        <div class="welcome-divider" aria-hidden="true"></div>
        <p class="welcome-desc">
          Channel-aware, provider-driven AI video production — <b>local-first</b>.
          Pick a channel, choose where the script comes from, and one node
          engine runs the whole pipeline. Production, Schema and the Library
          are windows onto that same run.
        </p>
        <p class="welcome-tagline">Script. Narrate. Segment. Visualise. Export.</p>
        <button
          ref="enterButton"
          type="button"
          class="welcome-enter-btn"
          @click="dismiss"
        >
          Enter Studio
        </button>
        <p class="welcome-note">Shown once per browser. Esc dismisses it.</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* The prototype hides a permanently-present overlay with `body.welcomed`.
   This one is mounted by `v-if` and torn down when it leaves, so there is
   nothing left to hide and no `.welcomed` class to carry. */
.welcome-root {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: var(--bg);
}

.welcome-root.dismissing {
  animation: welcomeOut 0.5s ease forwards;
}

@keyframes welcomeOut {
  to {
    opacity: 0;
    transform: scale(1.04);
    visibility: hidden;
  }
}

.welcome-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

/* The ambient field: a slow duotone sweep behind a hairline grid. */
.welcome-gradient {
  position: absolute;
  inset: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(
    135deg,
    var(--bg) 0%,
    var(--panel) 12%,
    #14243a 22%,
    rgba(106, 140, 255, 0.22) 35%,
    var(--bg) 45%,
    #241a40 55%,
    rgba(167, 139, 255, 0.2) 65%,
    var(--bg) 75%,
    rgba(106, 140, 255, 0.16) 88%,
    var(--bg) 100%
  );
  background-size: 200% 200%;
  animation: welcomeGradient 12s ease infinite;
}

@keyframes welcomeGradient {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

.welcome-grid {
  position: absolute;
  inset: 0;
  opacity: 0.25;
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
  top: 20%;
  left: 15%;
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(106, 140, 255, 0.18), transparent 70%);
  animation: welcomeFloat 8s ease-in-out infinite;
}

.welcome-orb--purple {
  right: 15%;
  bottom: 20%;
  width: 250px;
  height: 250px;
  background: radial-gradient(circle, rgba(167, 139, 255, 0.16), transparent 70%);
  animation: welcomeFloat 10s ease-in-out infinite reverse;
}

@keyframes welcomeFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-18px); }
}

/* Two production glyphs drifting in the field, barely there. */
.welcome-icon {
  position: absolute;
  opacity: 0.15;
  color: var(--accent);
}

.welcome-icon--film {
  top: 16%;
  right: 22%;
  width: 96px;
  height: 96px;
  animation: welcomeFloat 11s ease-in-out infinite;
}

.welcome-icon--wave {
  bottom: 18%;
  left: 20%;
  width: 74px;
  height: 74px;
  animation: welcomeSpin 40s linear infinite;
}

@keyframes welcomeSpin {
  to { transform: rotate(360deg); }
}

.welcome-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 26px;
  max-width: 620px;
  padding: 24px;
  text-align: center;
  animation: welcomeFadeUp 1s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes welcomeFadeUp {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: none; }
}

/* The topbar's logo tile at hero scale — the same mark, the same light. */
.welcome-logo {
  position: relative;
  display: grid;
  place-items: center;
  width: 84px;
  height: 84px;
  border-radius: 20px;
  background: linear-gradient(145deg, #5b8cff, #7a5bff);
  box-shadow: 0 0 48px rgba(106, 140, 255, 0.5), inset 0 0 0 1px rgba(255, 255, 255, 0.12);
}

.wl-mark {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  background: var(--bg);
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.9);
  transform: rotate(45deg);
}

.welcome-titles {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.welcome-h1 {
  margin: 0;
  font-family: var(--display);
  font-size: clamp(40px, 7vw, 60px);
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1;
  background: linear-gradient(135deg, #fff 0%, #5b8cff 35%, #a78bff 70%, #fff 100%);
  background-size: 200% 200%;
  animation: welcomeTextGrad 6s ease infinite;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

@keyframes welcomeTextGrad {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

.welcome-studio {
  margin: 0;
  font-family: var(--mono);
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.35em;
  color: var(--accent);
}

.welcome-divider {
  width: 60px;
  height: 2px;
  border-radius: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
}

.welcome-desc {
  margin: 0;
  font-size: 14.5px;
  line-height: 1.65;
  color: var(--text-2);
}

.welcome-desc b {
  color: var(--text);
  font-weight: 600;
}

.welcome-tagline {
  margin: 0;
  font-family: var(--mono);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
}

.welcome-enter-btn {
  margin-top: 4px;
  border: none;
  border-radius: 10px;
  padding: 13px 30px;
  font-family: var(--body);
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  cursor: pointer;
  background: linear-gradient(180deg, #6a97ff, var(--accent));
  box-shadow: 0 10px 28px -8px rgba(106, 140, 255, 0.8), inset 0 1px 0 rgba(255, 255, 255, 0.25);
  transition: filter 0.14s, transform 0.05s;
}

.welcome-enter-btn:hover {
  filter: brightness(1.07);
}

.welcome-enter-btn:active {
  transform: translateY(1px);
}

.welcome-note {
  margin: 2px 0 0;
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--faint);
}

@media (max-width: 820px) {
  .welcome-content { gap: 18px; }
  .welcome-orb { display: none; }
}
</style>

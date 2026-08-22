<script setup>
/**
 * Rich voice picker: each option shows the voice name, its gender, a language
 * code chip, and a country flag. Voices are identified by their Voice ID
 * (`value` is the id); the label/flag are presentation only.
 *
 * A native <select> can't render flags, so this is a small custom listbox.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

// Bundle the four flags at build time (CSP blocks remote SVGs).
import usFlag from '@/assets/flags/us.svg'
import gbFlag from '@/assets/flags/gb.svg'
import mxFlag from '@/assets/flags/mx.svg'
import esFlag from '@/assets/flags/es.svg'

const FLAGS = { us: usFlag, gb: gbFlag, mx: mxFlag, es: esFlag }

const props = defineProps({
  modelValue: { type: String, default: '' },
  voices: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const root = ref(null)

const selected = computed(
  () => props.voices.find((v) => v.id === props.modelValue) || null,
)

function flagSrc(code) {
  return FLAGS[code] || ''
}
function genderIcon(gender) {
  const g = String(gender || '').toLowerCase()
  if (g === 'male') return '♂'
  if (g === 'female') return '♀'
  return '•'
}

function toggle() {
  if (props.disabled) return
  open.value = !open.value
}
function choose(voice) {
  emit('update:modelValue', voice.id)
  open.value = false
}
function onDocClick(event) {
  if (root.value && !root.value.contains(event.target)) open.value = false
}
// If the field is disabled while its list is open (e.g. a generation starts),
// close it so a stale overlay never sits on top of the busy panel.
watch(
  () => props.disabled,
  (isDisabled) => {
    if (isDisabled) open.value = false
  },
)
onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="root" class="voice-select" :class="{ open, disabled }">
    <button
      type="button"
      class="vs-trigger"
      :disabled="disabled"
      aria-haspopup="listbox"
      :aria-expanded="String(open)"
      @click.stop="toggle"
    >
      <template v-if="selected">
        <img v-if="flagSrc(selected.flag)" class="vs-flag" :src="flagSrc(selected.flag)" :alt="selected.lang_code" />
        <span v-else class="vs-flag vs-flag-none" aria-hidden="true">{{ selected.lang_code }}</span>
        <span class="vs-name">{{ selected.label || selected.id }}</span>
        <span class="vs-gender" :title="selected.gender">{{ genderIcon(selected.gender) }}</span>
      </template>
      <span v-else class="vs-placeholder">Select a voice</span>
      <svg class="vs-caret" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
    </button>

    <ul v-if="open" class="vs-list" role="listbox">
      <li
        v-for="voice in voices"
        :key="voice.id"
      >
        <button
          type="button"
          class="vs-opt"
          role="option"
          :aria-selected="String(voice.id === modelValue)"
          :class="{ on: voice.id === modelValue }"
          @click="choose(voice)"
        >
          <img v-if="flagSrc(voice.flag)" class="vs-flag" :src="flagSrc(voice.flag)" :alt="voice.lang_code" />
          <span v-else class="vs-flag vs-flag-none" aria-hidden="true">{{ voice.lang_code }}</span>
          <span class="vs-name">{{ voice.label || voice.id }}</span>
          <span class="vs-lang">{{ voice.lang_code }}</span>
          <span class="vs-gender" :title="voice.gender">{{ genderIcon(voice.gender) }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.voice-select { position: relative; min-width: 0; }
.vs-trigger {
  display: flex; align-items: center; gap: 9px; width: 100%;
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 6px;
  color: var(--text); font: inherit; font-size: 13px; padding: 8px 11px; cursor: pointer;
  transition: border-color .14s;
}
.vs-trigger:hover:not(:disabled) { border-color: var(--line-2); }
.vs-trigger:focus-visible { outline: none; border-color: var(--accent-line-2); }
.voice-select.disabled .vs-trigger { opacity: .6; cursor: not-allowed; }
.vs-placeholder { color: var(--muted); flex: 1; text-align: left; }
.vs-name { flex: 1; min-width: 0; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
.vs-caret { flex: none; color: var(--muted); transition: transform .14s; }
.voice-select.open .vs-caret { transform: rotate(180deg); }

.vs-flag {
  flex: none; width: 20px; height: 15px; border-radius: 2px; object-fit: cover;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .12);
}
.vs-flag-none {
  display: grid; place-items: center; width: 22px; height: 15px; border-radius: 2px;
  background: var(--raise); color: var(--muted); font-family: var(--mono);
  font-size: 8px; font-weight: 600; letter-spacing: .2px; box-shadow: none;
}
.vs-gender { flex: none; color: var(--muted); font-size: 14px; width: 16px; text-align: center; }
.vs-lang {
  flex: none; font-family: var(--mono); font-size: 9.5px; letter-spacing: .4px;
  color: var(--muted); padding: 2px 5px; border-radius: 4px; background: var(--raise);
}

.vs-list {
  /* The list opens wider than the (often cramped) trigger so the full voice
     name, language chip and gender are all readable at once. It anchors to the
     left edge and grows rightward, clamped to the viewport. */
  position: absolute; z-index: 50; top: calc(100% + 5px); left: 0;
  min-width: max(100%, 280px); width: max-content; max-width: min(360px, 92vw);
  margin: 0; padding: 6px; list-style: none;
  max-height: 340px; overflow-y: auto;
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, .45);
}
.vs-list li { margin: 0; }
.vs-opt {
  display: flex; align-items: center; gap: 11px; width: 100%;
  padding: 9px 11px; border: 0; border-radius: 7px;
  background: transparent; color: var(--text-2); font: inherit; font-size: 13.5px;
  text-align: left; cursor: pointer; transition: background .12s, color .12s;
}
.vs-opt:hover { background: var(--raise); color: var(--text); }
.vs-opt.on { background: var(--accent-wash); color: var(--text); }
/* In the list, the name gets the room to show in full — no truncation. */
.vs-opt .vs-name { flex: 1; font-weight: 600; white-space: nowrap; overflow: visible; text-overflow: clip; }
</style>

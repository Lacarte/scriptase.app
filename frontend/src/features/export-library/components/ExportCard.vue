<script setup>
import { ref, onMounted } from 'vue'
import { fmtDuration } from '@/shared/utils/format.js'

defineOptions({ name: 'ExportCard' })

const props = defineProps({
  item: { type: Object, required: true },
  /* The calendar decides this: anything older than 48h is behind a date cell. */
  archived: { type: Boolean, default: false },
  highlighted: { type: Boolean, default: false },
})

const emit = defineEmits(['open', 'editor', 'export'])

const rootEl = ref(null)
const cardEl = ref(null)
const loaded = ref(false)

/* The library row carries no channel artwork, so the avatar is the channel's
   own initials rather than a colour this frontend invented for it. */
function channelInitials() {
  const name = props.item.channel_name || props.item.channel_id || ''
  const words = name.replace(/[^\p{L}\p{N}]+/gu, ' ').trim().split(' ').filter(Boolean)
  if (!words.length) return '—'
  return words.map(word => word[0]).join('').slice(0, 2).toUpperCase()
}

function title() {
  return props.item.project_id || props.item.video_name || ''
}

function open() {
  emit('open', props.item)
}

defineExpose({ cardRootEl: rootEl })

// The preview only loads once the card is near the viewport; without an
// observer it loads eagerly rather than staying blank forever.
onMounted(() => {
  if (!cardEl.value || typeof IntersectionObserver !== 'function') {
    loaded.value = true
    return
  }
  const observer = new IntersectionObserver((entries, obs) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        loaded.value = true
        obs.unobserve(entry.target)
      }
    }
  }, { rootMargin: '200px' })
  observer.observe(cardEl.value)
})
</script>

<template>
  <article
    ref="rootEl"
    class="lib-card"
    :class="{ 'lib-flash': highlighted }"
    tabindex="-1"
    @click="open"
  >
    <div ref="cardEl" class="lib-thumb">
      <video
        v-if="loaded"
        :src="item.preview_url"
        class="lib-frame"
        muted
        preload="metadata"
        playsinline
        aria-hidden="true"
      />
      <div class="cap">{{ title() }}</div>
      <div v-if="fmtDuration(item.duration)" class="dur">{{ fmtDuration(item.duration) }}</div>
      <!-- The prototype's hover affordance, as the real control: the card opens
           on any click, and this is what a keyboard reaches. -->
      <button type="button" class="play" :aria-label="`Open ${title()}`" @click.stop="open">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3" /></svg>
      </button>
    </div>

    <div class="lib-body">
      <div class="t" :title="title()">{{ title() }}</div>
      <div class="m">
        <span class="cav">{{ channelInitials() }}</span>
        {{ item.channel_name || item.channel_id || 'No channel' }}
        <span class="dot-sep"></span>
        {{ item.video_name }}
        <template v-if="archived">
          <span class="dot-sep"></span>
          <span class="lib-badge-arch">archived</span>
        </template>
      </div>
      <div class="lib-actions">
        <button class="btn xs" @click.stop="emit('editor', item)">Editor</button>
        <button class="btn xs" @click.stop="emit('export', item)">Export</button>
      </div>
    </div>
  </article>
</template>

<style scoped>
/* The prototype's `lib-card`, ported in step 6.7. */
.lib-card {
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: var(--panel);
  overflow: hidden;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.14s, transform 0.12s;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
}

.lib-card:hover {
  border-color: var(--line-2);
  transform: translateY(-2px);
  box-shadow: var(--hairline-top), 0 12px 30px -14px rgba(0, 0, 0, 0.7);
}

/* Arriving from ?project= flashes the card once rather than pulsing forever. */
.lib-card.lib-flash {
  animation: libFlash 1.6s var(--ease-spring);
}

@keyframes libFlash {
  0% {
    box-shadow: var(--glow);
    border-color: var(--accent);
    transform: translateY(-2px) scale(1.015);
  }
  60% {
    box-shadow: var(--glow);
    border-color: var(--accent);
  }
  100% {
    box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
    border-color: var(--line);
    transform: none;
  }
}

.lib-thumb {
  aspect-ratio: 16 / 10;
  position: relative;
  display: grid;
  place-items: center;
  overflow: hidden;
  background: var(--bg);
}

/* The prototype paints a channel gradient here; the library has the real
   frame, so the frame is the backdrop. */
.lib-frame {
  grid-area: 1 / 1;
  width: 100%;
  height: 100%;
  object-fit: cover;
  z-index: 1;
}

.lib-thumb .cap {
  position: absolute;
  bottom: 10px;
  left: 10px;
  right: 10px;
  text-align: center;
  font-weight: 700;
  font-size: 12px;
  color: #fff;
  text-shadow: 0 1px 5px rgba(0, 0, 0, 0.9);
  line-height: 1.2;
  z-index: 2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lib-thumb .dur {
  position: absolute;
  bottom: 8px;
  right: 8px;
  font-family: var(--mono);
  font-size: 9.5px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  padding: 2px 6px;
  border-radius: 4px;
  z-index: 4;
}

.lib-thumb .play {
  position: absolute;
  inset: 0;
  margin: auto;
  width: 40px;
  height: 40px;
  border: none;
  cursor: pointer;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(3px);
  display: grid;
  place-items: center;
  color: #fff;
  opacity: 0;
  transition: opacity 0.15s;
  z-index: 4;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.3);
}

.lib-card:hover .lib-thumb .play,
.lib-thumb .play:focus-visible {
  opacity: 1;
}

.lib-body {
  padding: 11px 13px;
}

.lib-body .t {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text);
}

.lib-body .m {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 6px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}

.lib-body .cav {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  flex: none;
  display: grid;
  place-items: center;
  font-size: 8px;
  color: var(--text);
  font-weight: 700;
  background: var(--raise);
  box-shadow: inset 0 0 0 1px var(--line);
  background-size: cover;
  background-position: center;
}

.lib-actions {
  display: flex;
  gap: 6px;
  margin-top: 11px;
}

.lib-actions .btn {
  flex: 1;
}

.lib-badge-arch {
  font-family: var(--mono);
  font-size: 8.5px;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  color: var(--muted);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line-soft);
  padding: 1px 6px;
  border-radius: 4px;
  flex: none;
}

@media (prefers-reduced-motion: reduce) {
  .lib-card.lib-flash {
    animation: none;
  }
}
</style>

import { ref, computed } from 'vue'

const entries = ref([])
const MAX_ENTRIES = 80
let nextId = 0

// Types that auto-expand the snackbar (require user attention)
const URGENT_TYPES = new Set(['error', 'warning'])

// Reactive flag — snackbar watches this to auto-expand
const urgentPing = ref(0)

/**
 * Global activity feed — collects toast messages, pipeline events,
 * and any app-wide notifications into a single timeline.
 *
 * Types: 'info' | 'success' | 'warning' | 'error' | 'pipeline'
 */
export function useActivityFeed() {
  function push(message, type = 'info', meta = {}) {
    const id = nextId++
    entries.value = [
      { id, message, type, time: new Date(), ...meta },
      ...entries.value,
    ].slice(0, MAX_ENTRIES)

    if (URGENT_TYPES.has(type)) {
      urgentPing.value++
    }

    return id
  }

  function clear() {
    entries.value = []
  }

  const latest = computed(() => entries.value[0] || null)
  const count = computed(() => entries.value.length)

  return { entries, latest, count, push, clear, urgentPing }
}

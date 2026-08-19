/**
 * The prototype's on-air pill, backed by real Job state.
 *
 * The Phase 6 port left `.onair` out on the grounds that run state is
 * Production's projection and the shell should not poll for it. The first half
 * is right and the second is not: the pill is the one place in the app that
 * answers "is anything running right now?" from any screen, which is the whole
 * point of putting it in the shell. What it must not do is hold a second
 * source of truth, so it holds none — it counts the Job list the Production
 * API already serves and derives every label from that.
 *
 * Polling rather than SSE is deliberate. The job SSE streams are per-execution
 * (`useProductionStages`), so a shell-wide subscription would mean opening one
 * stream per running Job just to count them. A single list read on an interval
 * is cheaper and cannot leak a connection. The interval stops when the document
 * is hidden, so a backgrounded tab costs nothing.
 *
 * This is a module-level singleton: every caller shares one timer.
 */
import { computed, ref } from 'vue'

import { listJobs } from '@/features/production/api.js'

const POLL_MS = 6000

const running = ref(0)
const queued = ref(0)
/** Null until the first read lands, so the pill can stay neutral rather than lie. */
const reachable = ref(null)

let timer = null
let subscribers = 0
let inFlight = false

/** `ON AIR` only when something is actually executing (prototype `renderOnAir`). */
const live = computed(() => running.value > 0)

const label = computed(() => {
  if (running.value > 0) {
    return `ON AIR · ${running.value} RUNNING`
  }
  // The prototype says PAUSED when work is waiting behind a stopped drain.
  // Here the equivalent is a queue that exists while nothing is executing.
  if (queued.value > 0) return 'PAUSED'
  return 'IDLE'
})

const title = computed(() => {
  if (reachable.value === false) return 'Job state unavailable — the backend did not answer'
  if (running.value > 0) return `${running.value} running, ${queued.value} queued`
  if (queued.value > 0) return `${queued.value} queued, nothing running`
  return 'Nothing running'
})

async function refresh() {
  // A slow answer must not stack requests behind it.
  if (inFlight) return
  inFlight = true
  try {
    // Both counts come from one read; asking per status would double the cost
    // of the most frequent request the app makes.
    const payload = await listJobs({ limit: 200 })
    const jobs = Array.isArray(payload) ? payload : (payload?.jobs ?? [])
    running.value = jobs.filter(job => job.status === 'running').length
    queued.value = jobs.filter(job => job.status === 'queued').length
    reachable.value = true
  } catch {
    // A failed poll reports nothing rather than a stale ON AIR. The counts are
    // cleared so the pill cannot claim a run that may have ended.
    running.value = 0
    queued.value = 0
    reachable.value = false
  } finally {
    inFlight = false
  }
}

function tick() {
  if (typeof document !== 'undefined' && document.hidden) return
  refresh()
}

function start() {
  if (timer !== null) return
  refresh()
  timer = setInterval(tick, POLL_MS)
  // A tab returning to the foreground should not wait out the interval.
  document.addEventListener('visibilitychange', onVisibility)
}

function stop() {
  if (timer === null) return
  clearInterval(timer)
  timer = null
  document.removeEventListener('visibilitychange', onVisibility)
}

function onVisibility() {
  if (!document.hidden) refresh()
}

/**
 * @returns {{ live: import('vue').ComputedRef<boolean>,
 *             label: import('vue').ComputedRef<string>,
 *             title: import('vue').ComputedRef<string>,
 *             running: import('vue').Ref<number>,
 *             queued: import('vue').Ref<number>,
 *             subscribe: () => () => void,
 *             refresh: () => Promise<void> }}
 */
export function useOnAir() {
  /** Ref-counted so the last component to unmount is the one that stops the timer. */
  function subscribe() {
    subscribers += 1
    start()
    let released = false
    return () => {
      if (released) return
      released = true
      subscribers -= 1
      if (subscribers <= 0) {
        subscribers = 0
        stop()
      }
    }
  }

  return { live, label, title, running, queued, subscribe, refresh }
}

/** Test seam: drop all state and timers between cases. */
export function __resetOnAir() {
  stop()
  subscribers = 0
  inFlight = false
  running.value = 0
  queued.value = 0
  reachable.value = null
}

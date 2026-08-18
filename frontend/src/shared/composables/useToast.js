import { ref } from 'vue'
import { useActivityFeed } from './useActivityFeed.js'

const toasts = ref([])
let nextId = 0

export function useToast() {
  const activity = useActivityFeed()

  /**
   * @param {string} message
   * @param {string} [type]
   * @param {number} [duration]  0 keeps the toast until it is dismissed
   * @param {{ label: string, onAction: () => void }} [action]
   *   An inline button — how a destructive action offers Undo instead of
   *   stopping the user with a confirm dialog (step 0.3).
   * @returns {number} toast id
   */
  function show(message, type = 'info', duration = 3000, action = null) {
    const id = nextId++
    toasts.value.push({ id, message, type, action })
    activity.push(message, type)
    if (duration > 0) {
      setTimeout(() => dismiss(id), duration)
    }
    return id
  }

  function dismiss(id) {
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) toasts.value.splice(idx, 1)
  }

  return {
    toasts,
    show,
    success: (msg, dur) => show(msg, 'success', dur),
    error:   (msg, dur) => show(msg, 'error', dur),
    warning: (msg, dur) => show(msg, 'warning', dur),
    info:    (msg, dur) => show(msg, 'info', dur),
    dismiss,
  }
}

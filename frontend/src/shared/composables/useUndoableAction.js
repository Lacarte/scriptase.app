/**
 * Destructive actions behind a five-second Undo instead of a confirm dialog
 * (step 0.3).
 *
 * A confirm dialog asks before you can see the result; Undo shows you the
 * result and lets you take it back. The commit is *deferred*, not reversed —
 * during the window nothing has reached the backend, so Undo is exact rather
 * than a best-effort restore.
 *
 * Callers hide the row optimistically, then call `run`. Two obligations:
 * `undo` puts the row back, and it is also what runs if the deferred commit
 * fails, so a failed delete never leaves a hole in the list.
 */
import { useToast } from './useToast.js'

export const UNDO_WINDOW_MS = 5000

export function useUndoableAction() {
  const toast = useToast()

  /**
   * @param {object} options
   * @param {string} options.message      what just (apparently) happened
   * @param {() => unknown} options.commit  the real, deferred effect
   * @param {() => void} options.undo       restore the optimistic change
   * @param {(error: unknown) => void} [options.onError]
   * @param {number} [options.delay]
   * @returns {() => void} cancel, for a caller that must abandon the window
   */
  function run({ message, commit, undo, onError, delay = UNDO_WINDOW_MS }) {
    let cancelled = false

    const timer = setTimeout(() => {
      if (cancelled) return
      Promise.resolve()
        .then(commit)
        .catch((error) => {
          undo?.()
          onError?.(error)
        })
    }, delay)

    const cancel = () => {
      cancelled = true
      clearTimeout(timer)
    }

    toast.show(message, 'info', delay, {
      label: 'Undo',
      onAction() {
        cancel()
        undo?.()
      },
    })

    return cancel
  }

  return { run }
}

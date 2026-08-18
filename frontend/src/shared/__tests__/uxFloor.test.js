/**
 * Step 0.3 — the UX floor.
 *
 * These are the affordances the prototype treats as baseline rather than
 * extras, so they are asserted rather than assumed: one keyboard dispatcher,
 * a first-run welcome that stays out of the way of deep links, Undo instead of
 * a confirm dialog, and toasts that a screen reader actually announces.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'

import ShortcutsSheet from '../components/ShortcutsSheet.vue'
import ToastContainer from '../components/ToastContainer.vue'
import WelcomeOverlay from '../components/WelcomeOverlay.vue'
import {
  SEARCH_ATTR,
  closeShortcutsSheet,
  dispatchShortcut,
  onShortcut,
  resetShortcuts,
  shortcutsSheetOpen,
} from '../composables/useShortcuts.js'
import { useToast } from '../composables/useToast.js'
import {
  UNDO_WINDOW_MS,
  useUndoableAction,
} from '../composables/useUndoableAction.js'
import {
  WELCOME_SEEN_KEY,
  hasSeenWelcome,
  isDeepLink,
  markWelcomeSeen,
  shouldShowWelcome,
} from '../composables/useWelcome.js'

/** Drive the dispatcher directly — no real listener, no real event loop. */
function press(key, overrides = {}) {
  const event = {
    key,
    target: document.body,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: key === '?',
    defaultPrevented: false,
    prevented: false,
    preventDefault() {
      this.prevented = true
    },
    ...overrides,
  }
  const handled = dispatchShortcut(event)
  return { handled, prevented: event.prevented }
}

/** A component that exists only to own a registered shortcut handler. */
function handlerHost(handler) {
  return defineComponent({
    setup() {
      onShortcut(handler)
      return () => h('div')
    },
  })
}

function routerWith(path = '/') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/production', component: { template: '<div />' } },
    ],
  })
  router.push(path)
  return router
}

beforeEach(() => {
  resetShortcuts()
  document.body.innerHTML = ''
  window.localStorage.clear()
})

afterEach(() => {
  resetShortcuts()
  vi.useRealTimers()
})

describe('keyboard dispatcher', () => {
  it('toggles the shortcuts sheet on ?', () => {
    expect(shortcutsSheetOpen.value).toBe(false)
    expect(press('?').prevented).toBe(true)
    expect(shortcutsSheetOpen.value).toBe(true)
    press('?')
    expect(shortcutsSheetOpen.value).toBe(false)
  })

  it('focuses and selects the view search field on /', () => {
    const input = document.createElement('input')
    input.setAttribute(SEARCH_ATTR, '')
    input.value = 'draft'
    document.body.appendChild(input)
    const select = vi.spyOn(input, 'select')

    expect(press('/').prevented).toBe(true)
    expect(document.activeElement).toBe(input)
    expect(select).toHaveBeenCalled()
  })

  it('leaves / alone when the view has no search field', () => {
    expect(press('/')).toEqual({ handled: false, prevented: false })
  })

  it('never hijacks a key while the user is typing', () => {
    const wrapper = mount(handlerHost(() => true))
    const field = document.createElement('input')

    expect(press('r', { target: field }).handled).toBe(false)
    expect(press('?', { target: field }).handled).toBe(false)
    expect(shortcutsSheetOpen.value).toBe(false)

    wrapper.unmount()
  })

  it('still delivers Escape from inside a field, so focus cannot trap you', () => {
    const escapes = []
    const wrapper = mount(handlerHost((event) => {
      escapes.push(event.key)
      return true
    }))
    const field = document.createElement('input')

    expect(press('Escape', { target: field }).handled).toBe(true)
    expect(escapes).toEqual(['Escape'])

    wrapper.unmount()
  })

  it('asks the most recently mounted view first and falls through on false', () => {
    const seen = []
    const first = mount(handlerHost(() => {
      seen.push('first')
      return true
    }))
    const second = mount(handlerHost(() => {
      seen.push('second')
      return false
    }))

    press('r')

    expect(seen).toEqual(['second', 'first'])

    second.unmount()
    first.unmount()
  })

  it('drops a handler when its view unmounts', () => {
    const handler = vi.fn(() => true)
    const wrapper = mount(handlerHost(handler))
    press('r')
    expect(handler).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    press('r')
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('ignores chorded keys so browser and OS shortcuts still work', () => {
    const handler = vi.fn(() => true)
    const wrapper = mount(handlerHost(handler))

    expect(press('r', { ctrlKey: true }).handled).toBe(false)
    expect(press('r', { metaKey: true }).handled).toBe(false)
    expect(handler).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('swallows view shortcuts while the sheet is open, and Escape closes it', () => {
    const handler = vi.fn(() => true)
    const wrapper = mount(handlerHost(handler))

    press('?')
    expect(press('r').handled).toBe(false)
    expect(handler).not.toHaveBeenCalled()

    expect(press('Escape').handled).toBe(true)
    expect(shortcutsSheetOpen.value).toBe(false)

    wrapper.unmount()
  })
})

describe('shortcuts sheet', () => {
  afterEach(() => closeShortcutsSheet())

  it('renders every documented binding as a dialog', async () => {
    const wrapper = mount(ShortcutsSheet, { attachTo: document.body })
    press('?')
    await flushPromises()

    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog.textContent).toContain('Focus search')
    expect(dialog.textContent).toContain('Run the focused step')
    expect(dialog.querySelectorAll('kbd').length).toBeGreaterThan(7)

    wrapper.unmount()
  })
})

describe('first-run welcome', () => {
  it('shows only on a bare visit to the root', () => {
    expect(shouldShowWelcome({ path: '/', query: {} })).toBe(true)
  })

  it('is skipped by a deep link', () => {
    expect(isDeepLink({ path: '/production', query: {} })).toBe(true)
    expect(isDeepLink({ path: '/', query: { job_id: 'job_1' } })).toBe(true)
    expect(shouldShowWelcome({ path: '/production', query: {} })).toBe(false)
    expect(shouldShowWelcome({ path: '/', query: { create: '1' } })).toBe(false)
  })

  it('is shown once per browser', () => {
    expect(hasSeenWelcome()).toBe(false)
    markWelcomeSeen()
    expect(window.localStorage.getItem(WELCOME_SEEN_KEY)).toBe('1')
    expect(shouldShowWelcome({ path: '/', query: {} })).toBe(false)
  })

  it('mounts on the root, records the dismissal, and closes on Enter Studio', async () => {
    const router = routerWith('/')
    await router.isReady()
    const wrapper = mount(WelcomeOverlay, {
      global: { plugins: [router] },
      attachTo: document.body,
    })
    await flushPromises()

    const overlay = document.querySelector('[role="dialog"][aria-modal="true"]')
    expect(overlay).not.toBeNull()
    expect(overlay.textContent).toContain('Enter Studio')

    vi.useFakeTimers()
    overlay.querySelector('.welcome-enter').click()
    expect(hasSeenWelcome()).toBe(true)
    vi.advanceTimersByTime(600)
    await flushPromises()

    expect(document.querySelector('.welcome')).toBeNull()
    wrapper.unmount()
  })

  it('does not mount in front of a deep link', async () => {
    const router = routerWith('/production')
    await router.isReady()
    const wrapper = mount(WelcomeOverlay, {
      global: { plugins: [router] },
      attachTo: document.body,
    })
    await flushPromises()

    expect(document.querySelector('.welcome')).toBeNull()
    wrapper.unmount()
  })
})

describe('undo instead of a confirm dialog', () => {
  function harness() {
    let api = null
    const wrapper = mount(defineComponent({
      setup() {
        api = useUndoableAction()
        return () => h('div')
      },
    }))
    return { api, wrapper }
  }

  it('defers the commit for five seconds, then runs it', async () => {
    vi.useFakeTimers()
    const { api, wrapper } = harness()
    const commit = vi.fn()

    api.run({ message: 'Deleted channel “Ghosts”', commit, undo: vi.fn() })
    expect(commit).not.toHaveBeenCalled()

    vi.advanceTimersByTime(UNDO_WINDOW_MS - 1)
    expect(commit).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    await Promise.resolve()
    expect(commit).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  it('never reaches the backend when Undo is pressed', async () => {
    vi.useFakeTimers()
    const { api, wrapper } = harness()
    const commit = vi.fn()
    const undo = vi.fn()
    const { toasts } = useToast()

    api.run({ message: 'Deleted channel “Ghosts”', commit, undo })

    const toast = toasts.value.at(-1)
    expect(toast.action.label).toBe('Undo')
    toast.action.onAction()

    vi.advanceTimersByTime(UNDO_WINDOW_MS * 2)
    await Promise.resolve()
    expect(commit).not.toHaveBeenCalled()
    expect(undo).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  it('puts the row back when the deferred commit fails', async () => {
    vi.useFakeTimers()
    const { api, wrapper } = harness()
    const undo = vi.fn()
    const onError = vi.fn()

    api.run({
      message: 'Deleted channel “Ghosts”',
      commit: () => Promise.reject(new Error('409 stale version')),
      undo,
      onError,
    })

    vi.advanceTimersByTime(UNDO_WINDOW_MS)
    await flushPromises()

    expect(undo).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0].message).toBe('409 stale version')

    wrapper.unmount()
  })
})

describe('toasts', () => {
  it('announce through one always-mounted live region', () => {
    const wrapper = mount(ToastContainer, { attachTo: document.body })
    const region = document.querySelector('.toast-region')

    expect(region.getAttribute('role')).toBe('status')
    expect(region.getAttribute('aria-live')).toBe('polite')

    wrapper.unmount()
  })

  it('render an action button that runs the action and dismisses', async () => {
    const wrapper = mount(ToastContainer, { attachTo: document.body })
    const { show, toasts, dismiss } = useToast()
    toasts.value.slice().forEach((t) => dismiss(t.id))

    const onAction = vi.fn()
    show('Deleted channel “Ghosts”', 'info', 0, { label: 'Undo', onAction })
    await flushPromises()

    const button = document.querySelector('.toast-action')
    expect(button.textContent.trim()).toBe('Undo')

    button.click()
    await flushPromises()

    expect(onAction).toHaveBeenCalledTimes(1)
    expect(document.querySelector('.toast-action')).toBeNull()

    wrapper.unmount()
  })
})

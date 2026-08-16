import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

import EditorPage from '../views/EditorPage.vue'

// Step 14.2 — a mount smoke test. video-editor.js owns the page by element id,
// so the two things that can silently break the port are the shell markup not
// landing in the DOM and the window.* dialog bridge not being wired.

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/editor', component: EditorPage },
      { path: '/production', component: { template: '<div />' } },
    ],
  })
}

async function mountAt(fullPath) {
  const router = makeRouter()
  router.push(fullPath)
  await router.isReady()
  // attachTo is not optional here: the inline scripts wire the shell up with
  // document.getElementById, which sees nothing off-document.
  const wrapper = mount(EditorPage, {
    attachTo: document.body,
    global: { plugins: [router] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  window.initEditor = vi.fn()
  window.resetEditor = vi.fn()
})

afterEach(() => {
  delete window.initEditor
  delete window.resetEditor
})

describe('EditorPage', () => {
  it('injects the shell markup video-editor.js queries by id', async () => {
    const wrapper = await mountAt('/editor')
    const shell = wrapper.get('#editor-shell')

    // A representative slice of refreshElements()'s lookups.
    for (const id of [
      'project-name', 'timeline-tracks', 'video-track', 'preview-canvas',
      'current-time', 'total-time', 'time-scrubber', 'play-btn', 'time-ruler',
      'audio-tracks-container', 'scene-properties', 'timeline-minimap',
    ]) {
      expect(shell.element.querySelector(`#${id}`), id).not.toBeNull()
    }

    wrapper.unmount()
  })

  it('publishes the dialog bridge while mounted and removes it after', async () => {
    const wrapper = await mountAt('/editor')

    expect(typeof window._vueShowNoData).toBe('function')
    expect(typeof window._vueShowExportProgressModal).toBe('function')

    // Dialogs stay unmounted until the imperative side asks for them.
    expect(wrapper.find('#export-progress-modal').exists()).toBe(false)
    window._vueShowExportProgressModal()
    await flushPromises()
    expect(wrapper.find('#export-progress-modal').exists()).toBe(true)

    wrapper.unmount()
    expect(window._vueShowNoData).toBeUndefined()
    expect(window.resetEditor).toHaveBeenCalled()
  })

  it('defaults to the project picker, and defers to ?project=', async () => {
    const bare = await mountAt('/editor')
    expect(sessionStorage.getItem('sts-editor-entry-source')).toBe('menu')
    bare.unmount()

    sessionStorage.clear()
    localStorage.clear()
    const named = await mountAt('/editor?project=pm_ABC123')
    expect(sessionStorage.getItem('sts-editor-entry-source')).not.toBe('menu')
    expect(localStorage.getItem('sts-editor-last-saved-project-id')).toBe('pm_ABC123')
    named.unmount()
  })
})

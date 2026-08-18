import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia } from 'pinia'

import App from './App.vue'
import { API_BASE, APP_NAME } from './shared/constants.js'
import { markWelcomeSeen } from './shared/composables/useWelcome.js'
import {
  resetShortcuts,
  shortcutsSheetOpen,
} from './shared/composables/useShortcuts.js'

async function mountShell(path = '/') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: `<div>${APP_NAME}</div>` } },
      { path: '/production', component: { template: '<div>production</div>' } },
      { path: '/workflow', component: { template: '<div>workflow</div>' } },
      { path: '/channels', component: { template: '<div>channels</div>' } },
      { path: '/settings/providers', component: { template: '<div>settings</div>' } },
      { path: '/editor', component: { template: '<div>editor</div>' } },
      { path: '/exports', component: { template: '<div>exports</div>' } },
    ],
  })
  router.push(path)
  await router.isReady()

  const wrapper = mount(App, {
    global: { plugins: [router, createPinia()] },
  })
  return { router, wrapper }
}

describe('scaffold', () => {
  beforeEach(() => {
    // The welcome overlay is a step 0.3 affordance of its own; the shell tests
    // are about the shell, so they start from an already-welcomed browser.
    markWelcomeSeen()
    resetShortcuts()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    resetShortcuts()
  })

  it('mounts the app shell with navigation', async () => {
    const { wrapper } = await mountShell()
    expect(wrapper.text()).toContain(APP_NAME)
    expect(wrapper.text()).toContain('Production')
    expect(wrapper.text()).toContain('Workflow')
    expect(wrapper.text()).toContain('Channels')
    expect(wrapper.text()).toContain('Settings')
  })

  it('opens Editor and Exports in their own windows without navigating (step 14.4)', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() })
    const { router, wrapper } = await mountShell()

    const links = wrapper.findAll('nav a.window-link')
    expect(links.map((a) => a.attributes('href'))).toEqual(['/editor', '/exports'])

    await links[0].trigger('click')
    await links[1].trigger('click')

    expect(open.mock.calls.map((call) => call[0])).toEqual(['/editor', '/exports'])
    expect(open.mock.calls[0][2]).toContain('popup=yes')
    // Production stays put; only the popup moved.
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('exposes the destinations as a labelled tablist (step 0.3)', async () => {
    const { wrapper } = await mountShell('/channels')

    const tablist = wrapper.find('[role="tablist"]')
    expect(tablist.attributes('aria-label')).toBe('Main sections')

    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs.map((tab) => tab.text())).toEqual([
      'Production',
      'Workflow',
      'Channels',
      'Settings',
    ])

    const current = tabs.filter((tab) => tab.attributes('aria-current') === 'page')
    expect(current).toHaveLength(1)
    expect(current[0].text()).toBe('Channels')
    expect(current[0].attributes('aria-selected')).toBe('true')
    expect(tabs[0].attributes('aria-selected')).toBe('false')
  })

  it('labels its icon-only controls and reports the nav collapse state', async () => {
    const { wrapper } = await mountShell()

    const toggle = wrapper.find('.nav-toggle')
    expect(toggle.attributes('aria-label')).toBe('Toggle navigation')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.attributes('aria-controls')).toBe('app-nav')

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('#app-nav').classes()).toContain('app-nav-links--open')

    // Choosing a destination puts the collapsed nav away again.
    await wrapper.findAll('[role="tab"]')[0].trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
  })

  it('opens the shortcuts sheet from the help button', async () => {
    const { wrapper } = await mountShell()

    const help = wrapper.find('.help-btn')
    expect(help.attributes('aria-label')).toBe('Keyboard shortcuts')

    await help.trigger('click')
    expect(shortcutsSheetOpen.value).toBe(true)

    await help.trigger('click')
    expect(shortcutsSheetOpen.value).toBe(false)
  })

  it('talks to the backend through a relative API base', () => {
    // An absolute origin here would break the loopback-only guarantee and the
    // Flask-served production build at the same time.
    expect(API_BASE.startsWith('/')).toBe(true)
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia } from 'pinia'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import App from './App.vue'
import { API_BASE, APP_NAME } from './shared/constants.js'
import { markWelcomeSeen } from './shared/composables/useWelcome.js'
import {
  resetShortcuts,
  shortcutsSheetOpen,
} from './shared/composables/useShortcuts.js'

/** The prototype's order: create, run, monitor, output, configure. */
const DESTINATIONS = ['Script', 'Production', 'Schema', 'Library', 'Channels', 'Providers']

async function mountShell(path = '/') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: `<div>${APP_NAME}</div>` } },
      { path: '/script', component: { template: '<div>script</div>' } },
      { path: '/production', component: { template: '<div>production</div>' } },
      { path: '/schema', component: { template: '<div>schema</div>' } },
      { path: '/library', component: { template: '<div>library</div>' } },
      { path: '/channels', component: { template: '<div>channels</div>' } },
      { path: '/providers', component: { template: '<div>providers</div>' } },
      { path: '/editor', component: { template: '<div>editor</div>' } },
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
    for (const label of DESTINATIONS) {
      expect(wrapper.text()).toContain(label)
    }
  })

  it('opens the Editor in its own window without navigating (step 14.4)', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() })
    const { router, wrapper } = await mountShell()

    const links = wrapper.findAll('nav a.window-link')
    expect(links.map((a) => a.attributes('href'))).toEqual(['/editor'])

    await links[0].trigger('click')

    expect(open.mock.calls.map((call) => call[0])).toEqual(['/editor'])
    expect(open.mock.calls[0][2]).toContain('popup=yes')
    // Production stays put; only the popup moved.
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('renders the six destinations in the prototype order (step 1.1)', async () => {
    const { wrapper } = await mountShell('/channels')

    const tablist = wrapper.find('[role="tablist"]')
    expect(tablist.attributes('aria-label')).toBe('Main sections')

    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs.map((tab) => tab.text())).toEqual(DESTINATIONS)
    expect(tabs.map((tab) => tab.attributes('href'))).toEqual([
      '/script',
      '/production',
      '/schema',
      '/library',
      '/channels',
      '/providers',
    ])
  })

  it('gives every destination its own glyph (step 1.1)', async () => {
    const { wrapper } = await mountShell()

    const tabs = wrapper.findAll('[role="tab"]')
    for (const tab of tabs) {
      const icon = tab.find('svg.nav-icon')
      expect(icon.exists()).toBe(true)
      // Decorative: the label beside it is the accessible name.
      expect(icon.attributes('aria-hidden')).toBe('true')
    }

    // Six distinct glyphs, not one repeated six times.
    const shapes = tabs.map((tab) => tab.find('svg.nav-icon').html())
    expect(new Set(shapes).size).toBe(DESTINATIONS.length)
  })

  it('has no editable-canvas navigation entry (step 1.5)', async () => {
    const { wrapper } = await mountShell()

    expect(wrapper.find('nav a[href="/workflow"]').exists()).toBe(false)
    expect(wrapper.find('.secondary-link').exists()).toBe(false)
  })

  it('marks the active destination (step 0.3)', async () => {
    const { wrapper } = await mountShell('/channels')

    const tabs = wrapper.findAll('[role="tab"]')
    const current = tabs.filter((tab) => tab.attributes('aria-current') === 'page')
    expect(current).toHaveLength(1)
    expect(current[0].text()).toBe('Channels')
    expect(current[0].attributes('aria-selected')).toBe('true')
    expect(tabs[0].attributes('aria-selected')).toBe('false')

    // The prototype's active treatment hangs off `.active` (step 6.1).
    expect(wrapper.findAll('.topnav a.active')).toHaveLength(1)
    expect(current[0].classes()).toContain('active')
  })

  it('wears the prototype topbar and brand (step 6.1)', async () => {
    const { wrapper } = await mountShell()

    expect(wrapper.find('header.topbar').exists()).toBe(true)
    expect(wrapper.find('nav.topnav').exists()).toBe(true)

    // The wordmark is the lit tile plus Script/ase, not a bare text link.
    const brand = wrapper.find('.brand')
    expect(brand.find('.logo').exists()).toBe(true)
    expect(brand.find('.name').text()).toBe(APP_NAME)
    expect(brand.find('.tag').text()).toBe('Studio')
  })

  it('keeps the prototype nav breakpoint and non-shrinking button icons (step 6.1)', () => {
    const shellSource = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')
    const sharedSource = readFileSync(resolve(process.cwd(), 'src/styles/shared.css'), 'utf8')

    expect(shellSource).toMatch(/@media \(max-width: 860px\)/)
    expect(sharedSource).toMatch(/\.btn svg\s*\{[^}]*flex:\s*none/s)
  })

  it('labels its icon-only controls and reports the nav collapse state', async () => {
    const { wrapper } = await mountShell()

    const toggle = wrapper.find('.nav-toggle')
    expect(toggle.attributes('aria-label')).toBe('Toggle navigation')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.attributes('aria-controls')).toBe('app-nav')

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('#app-nav').classes()).toContain('open')

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

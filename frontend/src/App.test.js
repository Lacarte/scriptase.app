import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia } from 'pinia'

import App from './App.vue'
import { API_BASE, APP_NAME } from './shared/constants.js'

async function mountShell() {
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
  router.push('/')
  await router.isReady()

  const wrapper = mount(App, {
    global: { plugins: [router, createPinia()] },
  })
  return { router, wrapper }
}

describe('scaffold', () => {
  afterEach(() => {
    vi.restoreAllMocks()
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

  it('talks to the backend through a relative API base', () => {
    // An absolute origin here would break the loopback-only guarantee and the
    // Flask-served production build at the same time.
    expect(API_BASE.startsWith('/')).toBe(true)
  })
})

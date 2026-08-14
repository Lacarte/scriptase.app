import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

import App from './App.vue'
import { API_BASE, APP_NAME } from './shared/constants.js'

describe('scaffold', () => {
  it('mounts the app shell with navigation', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: `<div>${APP_NAME}</div>` } },
        { path: '/channels', component: { template: '<div>channels</div>' } },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(App, {
      global: { plugins: [router] },
    })
    expect(wrapper.text()).toContain(APP_NAME)
    expect(wrapper.text()).toContain('Channels')
  })

  it('talks to the backend through a relative API base', () => {
    // An absolute origin here would break the loopback-only guarantee and the
    // Flask-served production build at the same time.
    expect(API_BASE.startsWith('/')).toBe(true)
  })
})

import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import App from './App.vue'
import { API_BASE, APP_NAME } from './shared/constants.js'

describe('scaffold', () => {
  it('mounts the app shell', () => {
    const wrapper = mount(App)
    expect(wrapper.text()).toContain(APP_NAME)
  })

  it('talks to the backend through a relative API base', () => {
    // An absolute origin here would break the loopback-only guarantee and the
    // Flask-served production build at the same time.
    expect(API_BASE.startsWith('/')).toBe(true)
  })
})

/**
 * Step 1.1 — the six-destination nav and routes.
 *
 * Done when: all six destinations route correctly, the nav matches the
 * prototype's order and labels, and every previous route redirects rather than
 * returning a 404. The nav half is asserted in App.test.js; this file owns the
 * routing table, resolved through the real router so a typo in a redirect
 * target fails here rather than in a browser.
 */
import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import { createAppRouter, routes } from './router.js'

/** Ordered create, run, monitor, output, configure. */
const DESTINATIONS = [
  ['/script', 'script'],
  ['/production', 'production'],
  ['/schema', 'schema'],
  ['/library', 'library'],
  ['/channels', 'channels'],
  ['/providers', 'providers'],
]

function makeRouter() {
  return createAppRouter(createMemoryHistory())
}

describe('routes (step 1.1)', () => {
  it.each(DESTINATIONS)('resolves %s to a component', async (path, name) => {
    const router = makeRouter()
    await router.push(path)
    const current = router.currentRoute.value
    expect(current.path).toBe(path)
    expect(current.name).toBe(name)
    expect(current.matched).toHaveLength(1)
    expect(current.matched[0].components?.default).toBeTruthy()
  })

  it('keeps the destinations reachable by name', () => {
    const router = makeRouter()
    for (const [path, name] of DESTINATIONS) {
      expect(router.resolve({ name }).path).toBe(path)
    }
  })

  it('redirects every previous path instead of 404ing', async () => {
    const previous = [
      ['/exports', '/library'],
      ['/settings/providers', '/providers'],
    ]
    for (const [from, to] of previous) {
      const router = makeRouter()
      await router.push(from)
      expect(router.currentRoute.value.path).toBe(to)
      expect(router.currentRoute.value.matched).not.toHaveLength(0)
    }
  })

  it('carries the deep link through the redirect', async () => {
    // `/exports?project=…&export=…` is what step 14.4's window link and every
    // pasted URL look like. A bare string redirect would drop both.
    const router = makeRouter()
    await router.push('/exports?project=pm_ABC123&export=ex_1')
    expect(router.currentRoute.value.path).toBe('/library')
    expect(router.currentRoute.value.query).toEqual({
      project: 'pm_ABC123',
      export: 'ex_1',
    })
  })

  it('still routes the paths that survive unchanged', async () => {
    const router = makeRouter()
    for (const path of ['/', '/channels/ch_ABC123', '/editor']) {
      await router.push(path)
      expect(router.currentRoute.value.matched).not.toHaveLength(0)
    }
  })

  it('retires the editable canvas route (step 1.5)', () => {
    const router = makeRouter()

    expect(routes.some((route) => route.path === '/workflow')).toBe(false)
    expect(router.resolve('/workflow').matched).toHaveLength(0)
    expect(() => router.resolve({ name: 'workflow' })).toThrow()
  })

  it('has no route left pointing at a renamed path', () => {
    // A redirect target is a name here, so this catches a stale literal.
    const paths = routes.map((route) => route.path)
    expect(paths).toContain('/library')
    expect(paths).toContain('/providers')
    expect(paths.filter((path) => path === '/exports')).toHaveLength(1)
  })
})

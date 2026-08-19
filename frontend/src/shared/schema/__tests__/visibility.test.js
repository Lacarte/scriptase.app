import { describe, it, expect } from 'vitest'
import { isDisplayed, isFieldVisible } from '../visibility.js'

// Step 12.2 — `display_options.show` (workflow nodes) and `ui.show_if`
// (provider settings) are the same rule under two names (contracts.md §22.3).
// One implementation is what makes both forms interpret one contract.

describe('shared visibility rule', () => {
  it('ANDs across keys and ORs within a list', () => {
    const show = { mode: ['advanced'], level: [1, 2] }
    expect(isDisplayed({ show }, { mode: 'advanced', level: 2 })).toBe(true)
    expect(isDisplayed({ show }, { mode: 'advanced', level: 3 })).toBe(false)
    expect(isDisplayed({ show }, { mode: 'basic', level: 1 })).toBe(false)
  })

  it('hides on any matching hide key', () => {
    expect(isDisplayed({ hide: { mode: ['auto'] } }, { mode: 'auto' })).toBe(false)
    expect(isDisplayed({ hide: { mode: ['auto'] } }, { mode: 'manual' })).toBe(true)
  })

  it('accepts a bare value as a one-element list', () => {
    expect(isFieldVisible({ ui: { show_if: { mode: 'advanced' } } }, { mode: 'advanced' }))
      .toBe(true)
  })

  it('shows a field with no condition', () => {
    expect(isDisplayed(undefined, {})).toBe(true)
    expect(isFieldVisible({}, {})).toBe(true)
    expect(isFieldVisible({ ui: { show_if: {} } }, {})).toBe(true)
  })

  it('treats an absent value as not matching', () => {
    expect(isFieldVisible({ ui: { show_if: { mode: ['advanced'] } } }, {})).toBe(false)
    expect(isFieldVisible({ ui: { show_if: { mode: [undefined] } } }, {})).toBe(true)
  })
})

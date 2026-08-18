import { describe, expect, it, vi } from 'vitest'

import {
  APP_WINDOW_TARGETS,
  buildRouteUrl,
  openAppWindow,
  windowNameFor,
} from '../openWindow.js'

function fakeWindow() {
  const focus = vi.fn()
  const open = vi.fn(() => ({ focus }))
  return { open, focus, screen: { availWidth: 2560, availHeight: 1440 } }
}

function featureMap(features) {
  return Object.fromEntries(
    features.split(',').map((part) => {
      const [key, value] = part.split('=')
      return [key, value ?? '']
    }),
  )
}

describe('buildRouteUrl', () => {
  it('drops empty query values so a page never reads "" as an id', () => {
    expect(buildRouteUrl('/library', { project: '' })).toBe('/library')
    expect(buildRouteUrl('/library', { project: null, export: undefined })).toBe('/library')
    expect(buildRouteUrl('/editor', { project: 'pm_ABC123' })).toBe('/editor?project=pm_ABC123')
  })

  it('encodes query values', () => {
    expect(buildRouteUrl('/library', { export: 'a b&c' })).toBe('/library?export=a+b%26c')
  })
})

describe('windowNameFor', () => {
  it('gives each project its own window so a second open never clobbers edits', () => {
    expect(windowNameFor('editor', 'pm_ABC123')).toBe('scriptase-editor-pm_ABC123')
    expect(windowNameFor('editor', 'pm_ABC123')).not.toBe(windowNameFor('editor', 'pm_ZZZ999'))
  })

  it('falls back to a stable name when no project is known', () => {
    expect(windowNameFor('library', '')).toBe('scriptase-library-default')
    expect(windowNameFor('library', undefined)).toBe('scriptase-library-default')
  })
})

describe('openAppWindow', () => {
  it('opens the editor as a sized, centered popup carrying the project in the URL', () => {
    const win = fakeWindow()
    const handle = openAppWindow('editor', { query: { project: 'pm_ABC123' }, win })

    expect(win.open).toHaveBeenCalledTimes(1)
    const [url, name, features] = win.open.mock.calls[0]
    expect(url).toBe('/editor?project=pm_ABC123')
    expect(name).toBe('scriptase-editor-pm_ABC123')

    const parsed = featureMap(features)
    expect(parsed.popup).toBe('yes')
    expect(Number(parsed.width)).toBe(APP_WINDOW_TARGETS.editor.width)
    expect(Number(parsed.height)).toBe(APP_WINDOW_TARGETS.editor.height)
    // Centered on a 2560x1440 screen.
    expect(Number(parsed.left)).toBe((2560 - 1600) / 2)
    expect(Number(parsed.top)).toBe((1440 - 950) / 2)
    expect(parsed.resizable).toBe('yes')

    expect(win.focus).toHaveBeenCalled()
    expect(handle).not.toBeNull()
  })

  it('opens the export library without a project when none is bound', () => {
    const win = fakeWindow()
    openAppWindow('library', { query: { project: '' }, win })

    const [url, name] = win.open.mock.calls[0]
    expect(url).toBe('/library')
    expect(name).toBe('scriptase-library-default')
  })

  it('clamps to the available screen so a small display still gets a usable window', () => {
    const win = fakeWindow()
    win.screen = { availWidth: 1024, availHeight: 768 }
    openAppWindow('editor', { win })

    const parsed = featureMap(win.open.mock.calls[0][2])
    expect(Number(parsed.width)).toBe(1024)
    expect(Number(parsed.height)).toBe(768)
    expect(Number(parsed.left)).toBe(0)
    expect(Number(parsed.top)).toBe(0)
  })

  it('returns null when a popup blocker refuses the window', () => {
    const win = { open: vi.fn(() => null), screen: { availWidth: 1920, availHeight: 1080 } }
    expect(openAppWindow('library', { win })).toBeNull()
  })

  it('rejects an unknown target rather than opening an arbitrary URL', () => {
    expect(() => openAppWindow('anything', { win: fakeWindow() })).toThrow(/Unknown app window target/)
  })
})

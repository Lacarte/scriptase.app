import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  timeAgo,
  formatDuration,
  formatElapsed,
  formatBytes,
  fmtTime,
  fmtDuration,
} from '../format.js'

// Step 14.1 — ported from V2 ahead of the editor and export-library ports, so
// nothing imports it yet. These cases are the contract those two features rely
// on; without them the port is unexercised until Phase 14 finishes.

afterEach(() => {
  vi.useRealTimers()
})

describe('timeAgo', () => {
  it('returns empty for a missing timestamp', () => {
    expect(timeAgo(null)).toBe('')
    expect(timeAgo(undefined)).toBe('')
    expect(timeAgo(0)).toBe('')
  })

  it('steps through the units', () => {
    vi.useFakeTimers()
    const now = new Date('2026-08-15T12:00:00Z')
    vi.setSystemTime(now)
    const ago = (seconds) => timeAgo(now.getTime() - seconds * 1000)

    expect(ago(30)).toBe('just now')
    expect(ago(120)).toBe('2m ago')
    expect(ago(7200)).toBe('2h ago')
    expect(ago(172800)).toBe('2d ago')
    expect(ago(1209600)).toBe('2w ago')
  })

  it('clamps a future timestamp instead of going negative', () => {
    vi.useFakeTimers()
    const now = new Date('2026-08-15T12:00:00Z')
    vi.setSystemTime(now)
    expect(timeAgo(now.getTime() + 60_000)).toBe('just now')
  })
})

describe('formatDuration', () => {
  it('drops empty leading units', () => {
    expect(formatDuration(45)).toBe('45s')
    expect(formatDuration(125)).toBe('2m 5s')
    expect(formatDuration(3725)).toBe('1h 2m 5s')
  })

  it('treats missing and non-positive input as zero', () => {
    expect(formatDuration(null)).toBe('0s')
    expect(formatDuration(0)).toBe('0s')
    expect(formatDuration(-5)).toBe('0s')
  })
})

describe('formatElapsed', () => {
  it('keeps sub-second precision below ten seconds', () => {
    expect(formatElapsed(0.25)).toBe('0.25s')
    expect(formatElapsed(4.5)).toBe('4.5s')
  })

  it('trims trailing zeros from the fractional part', () => {
    expect(formatElapsed(2.0)).toBe('2s')
    expect(formatElapsed(0.5)).toBe('0.5s')
  })

  it('rounds to whole units at ten seconds and above', () => {
    expect(formatElapsed(42.4)).toBe('42s')
    expect(formatElapsed(3725)).toBe('1h 2m 5s')
  })

  it('returns empty for unusable input', () => {
    expect(formatElapsed(null)).toBe('')
    expect(formatElapsed(0)).toBe('')
    expect(formatElapsed(NaN)).toBe('')
    expect(formatElapsed(Infinity)).toBe('')
  })
})

describe('formatBytes', () => {
  it('scales to the largest fitting unit', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(1024 ** 3)).toBe('1.0 GB')
  })

  it('shows no decimals for whole bytes', () => {
    expect(formatBytes(999)).toBe('999 B')
  })

  it('treats missing and zero as zero', () => {
    expect(formatBytes(null)).toBe('0 B')
    expect(formatBytes(0)).toBe('0 B')
  })
})

describe('fmtTime', () => {
  it('pads seconds to a clock reading', () => {
    expect(fmtTime(5)).toBe('0:05')
    expect(fmtTime(65)).toBe('1:05')
    expect(fmtTime(600)).toBe('10:00')
  })

  it('falls back to 0:00 for unusable input', () => {
    expect(fmtTime(0)).toBe('0:00')
    expect(fmtTime(null)).toBe('0:00')
    expect(fmtTime(NaN)).toBe('0:00')
  })
})

describe('fmtDuration', () => {
  it('always emits a minute field', () => {
    expect(fmtDuration(5)).toBe('0:05')
    expect(fmtDuration(65)).toBe('1:05')
  })

  it('returns empty rather than a zero clock when there is nothing to show', () => {
    expect(fmtDuration(0)).toBe('')
    expect(fmtDuration(null)).toBe('')
  })
})

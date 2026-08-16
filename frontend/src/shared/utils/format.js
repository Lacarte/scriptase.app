/**
 * Shared formatting utilities.
 * Replaces duplicated timeAgo, formatDuration, formatBytes, fmtTime across features.
 */

export function timeAgo(timestamp) {
  if (!timestamp) return ''
  const now = Date.now()
  const date = new Date(timestamp)
  const diff = Math.max(0, now - date.getTime()) / 1000

  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`
  if (diff < 2592000) return `${Math.floor(diff / 604800)}w ago`
  return date.toLocaleDateString()
}

export function formatDuration(seconds) {
  if (seconds == null || seconds <= 0) return '0s'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.round(seconds % 60)
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export function formatElapsed(seconds) {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value <= 0) return ''
  if (value < 10) {
    const precision = value < 1 ? 2 : 1
    return `${value.toFixed(precision).replace(/\.0+$/, '').replace(/(\.\d*[1-9])0$/, '$1')}s`
  }
  const rounded = Math.round(value)
  const h = Math.floor(rounded / 3600)
  const m = Math.floor((rounded % 3600) / 60)
  const s = rounded % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${rounded}s`
}

export function formatBytes(bytes) {
  if (bytes == null || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const val = bytes / Math.pow(1024, i)
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function fmtTime(s) {
  if (!s || isNaN(s)) return '0:00'
  return Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0')
}

export function fmtDuration(sec) {
  const s = Number(sec || 0)
  if (!s || s <= 0) return ''
  const m = Math.floor(s / 60)
  const ss = Math.floor(s % 60)
  return m > 0 ? `${m}:${String(ss).padStart(2, '0')}` : `0:${String(ss).padStart(2, '0')}`
}

/**
 * How a Channel is drawn wherever it is referenced — the rail row, the editor
 * hero, a job row, a script card (step 6.4).
 *
 * The prototype stores `code` and `color` on the channel. `ChannelProfile`
 * carries neither, and inventing them would mean a schema change and a second
 * source of truth for something that is purely presentation. Both are derived
 * instead: the label from the name, the colour from the id. Deriving from the
 * id — not the list position — is what keeps a channel the same colour in
 * every view and after every re-sort.
 */

/** The prototype's eight channel accents, in its order. */
export const CHANNEL_COLORS = [
  '#5b8cff',
  '#b06be6',
  '#3fb68b',
  '#e0a44a',
  '#f0616d',
  '#4ea1ff',
  '#e084c4',
  '#5bd1c9',
]

/**
 * The prototype's `deriveCode`: two initials from two words, the first two
 * letters from one.
 */
export function channelInitials(name) {
  const words = String(name || '').trim().split(/\s+/).filter(Boolean)
  if (!words.length) return 'CH'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

/**
 * Stable palette entry for a channel id.
 *
 * FNV-1a rather than the usual `hash * 31 + c`: channel ids share a `ch_`
 * prefix and differ in six characters from one alphabet, and a polynomial
 * hash reduced mod a power-of-two palette maps most of them onto the same
 * colour. This one mixes the low bits.
 */
export function channelAccent(id) {
  const text = String(id || '')
  let hash = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return CHANNEL_COLORS[(hash >>> 0) % CHANNEL_COLORS.length]
}

/**
 * Inline background for an avatar: the channel thumbnail when it has one,
 * otherwise its derived accent. Thumbnails are managed refs served from
 * `/output/`, never a browser-supplied path.
 */
export function channelAvatarStyle(channel) {
  const thumbnail = channel?.thumbnail_asset_id || channel?.branding?.thumbnail_asset_id
  if (thumbnail) return { background: `center/cover url("/output/${thumbnail}")` }
  return { background: channelAccent(channel?.id) }
}

/** The avatar's text: empty when a thumbnail covers it. */
export function channelAvatarLabel(channel) {
  const thumbnail = channel?.thumbnail_asset_id || channel?.branding?.thumbnail_asset_id
  return thumbnail ? '' : channelInitials(channel?.name)
}

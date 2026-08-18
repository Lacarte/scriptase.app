/**
 * Preserve provider prose while making a Channel's ordered outline explicit.
 * This is used only for generated drafts; Paste and editor saves bypass it.
 */
export function applyTemplateOutline(text, sections) {
  const outline = Array.isArray(sections) ? sections.filter(Boolean) : []
  const source = String(text || '').trim()
  if (!source || !outline.length) return source

  let parts = source.split(/\n\s*\n/).map(part => part.trim()).filter(Boolean)
  if (parts.length < outline.length) {
    parts = source.split(/(?<=[.!?])\s+/).map(part => part.trim()).filter(Boolean)
  }

  const buckets = outline.map(() => [])
  parts.forEach((part, index) => {
    const target = Math.min(
      outline.length - 1,
      Math.floor(index * outline.length / Math.max(parts.length, 1)),
    )
    buckets[target].push(part)
  })

  return outline
    .map((section, index) => `${section}\n${buckets[index].join(' ')}`.trim())
    .join('\n\n')
}

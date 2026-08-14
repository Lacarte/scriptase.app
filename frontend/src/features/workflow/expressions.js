const WHOLE_EXPRESSION = /^\s*\{\{\s*(nodes\.[A-Za-z][A-Za-z0-9_-]{0,63}\.outputs\.[A-Za-z][A-Za-z0-9_-]{0,63}|workflow\.project_id|variables\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\}\}\s*$/

export function isExpressionValue(value) {
  return typeof value === 'string' && value.includes('{{')
}

export function expressionSyntaxError(value) {
  if (!isExpressionValue(value)) return ''
  return WHOLE_EXPRESSION.test(value)
    ? ''
    : 'Expression must be a whole-value node output, project ID, or workflow variable reference'
}

export function expressionOptions(node, nodes, edges, nodeTypes, variables = {}) {
  if (!node) return []
  const byId = Object.fromEntries(nodes.map((item) => [item.id, item]))
  const incoming = new Map(nodes.map((item) => [item.id, []]))
  for (const edge of edges) incoming.get(edge.target_node)?.push(edge.source_node)
  const ancestors = new Set()
  const pending = [...(incoming.get(node.id) || [])]
  while (pending.length) {
    const id = pending.pop()
    if (ancestors.has(id)) continue
    ancestors.add(id)
    pending.push(...(incoming.get(id) || []))
  }
  const options = []
  for (const source of nodes.filter((item) => ancestors.has(item.id))) {
    for (const port of nodeTypes[source.type]?.outputs || []) {
      if (port.type === 'control') continue
      options.push({
        value: `{{ nodes.${source.id}.outputs.${port.id} }}`,
        label: `${source.name || source.id} · ${port.id} (${port.type})`,
      })
    }
  }
  return options
}

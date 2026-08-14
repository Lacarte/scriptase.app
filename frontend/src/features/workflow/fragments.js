export const WORKFLOW_FRAGMENT_KIND = 'scriptase.workflow-fragment'
export const WORKFLOW_FRAGMENT_VERSION = 1

export function makeWorkflowFragment(nodes, edges, nodeIds) {
  const selected = new Set(nodeIds || [])
  const fragmentNodes = nodes.filter((node) => selected.has(node.id))
  if (!fragmentNodes.length) return null
  return {
    kind: WORKFLOW_FRAGMENT_KIND,
    version: WORKFLOW_FRAGMENT_VERSION,
    nodes: JSON.parse(JSON.stringify(fragmentNodes)),
    edges: JSON.parse(JSON.stringify(edges.filter(
      (edge) => selected.has(edge.source_node) && selected.has(edge.target_node),
    ))),
  }
}

export function parseWorkflowFragment(value) {
  let fragment = value
  if (typeof value === 'string') {
    try {
      fragment = JSON.parse(value)
    } catch {
      return null
    }
  }
  if (
    !fragment || fragment.kind !== WORKFLOW_FRAGMENT_KIND
    || fragment.version !== WORKFLOW_FRAGMENT_VERSION
    || !Array.isArray(fragment.nodes) || !Array.isArray(fragment.edges)
  ) return null
  return JSON.parse(JSON.stringify(fragment))
}

function resolvedPortType(node, definition, kind, portId) {
  const port = (definition?.[kind] || []).find((item) => item.id === portId)
  if (!port) return null
  return port.type === 'dynamic'
    ? node?.configuration?.port_type || 'generic_json'
    : port.type
}

export function compatibleInsertions({ nodeTypes, node, handleId, handleType }) {
  const existingDef = nodeTypes[node?.type]
  const existingKind = handleType === 'target' ? 'inputs' : 'outputs'
  const neededType = resolvedPortType(node, existingDef, existingKind, handleId)
  if (!neededType) return []
  const candidateKind = handleType === 'target' ? 'outputs' : 'inputs'
  const choices = []
  for (const definition of Object.values(nodeTypes)) {
    for (const port of definition[candidateKind] || []) {
      // Dynamic testing ports can resolve themselves to the dragged type.
      const portType = port.type === 'dynamic' ? neededType : port.type
      if (portType !== neededType) continue
      choices.push({
        type: definition.type,
        displayName: definition.display_name,
        category: definition.category,
        portId: port.id,
        portType: neededType,
      })
    }
  }
  return choices.sort((left, right) =>
    left.displayName.localeCompare(right.displayName) || left.portId.localeCompare(right.portId),
  )
}

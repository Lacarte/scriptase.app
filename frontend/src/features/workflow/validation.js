/**
 * Client-side connection validation (contracts.md §3, frozen rules):
 * exact type match only, single-value inputs, no duplicates, DAG only.
 * Pure functions over plain data so Vitest can cover every rule.
 */

function resolvePortType(node, portDef) {
  if (portDef.type !== 'dynamic') return portDef.type
  return node?.configuration?.port_type || 'generic_json'
}

function findPort(def, kind, portId) {
  return (def?.[kind] || []).find((p) => p.id === portId) || null
}

function wouldCreateCycle(edges, sourceNodeId, targetNodeId) {
  if (sourceNodeId === targetNodeId) return true
  // Walk downstream from target; if we reach source, the new edge closes a loop.
  const adjacency = new Map()
  for (const e of edges) {
    if (!adjacency.has(e.source_node)) adjacency.set(e.source_node, [])
    adjacency.get(e.source_node).push(e.target_node)
  }
  const queue = [targetNodeId]
  const seen = new Set()
  while (queue.length) {
    const current = queue.pop()
    if (current === sourceNodeId) return true
    if (seen.has(current)) continue
    seen.add(current)
    for (const next of adjacency.get(current) || []) queue.push(next)
  }
  return false
}

/**
 * `connection.edgeId` identifies an EXISTING edge being re-validated
 * (Vue Flow re-runs isValidConnection over every edge whenever the edge
 * array is set). That edge must be excluded from the duplicate/occupied/
 * cycle checks or it invalidates itself and vanishes from the canvas.
 *
 * @returns {{ok: true, edgeType: 'data'|'control'} | {ok: false, reason: string}}
 */
export function validateConnection({ nodes, edges, nodeTypes, portTypes = [] }, connection) {
  const { sourceNode: sourceId, sourcePort, targetNode: targetId, targetPort, edgeId } = connection
  if (edgeId) {
    edges = edges.filter((e) => e.id !== edgeId)
  }

  const sourceNode = nodes.find((n) => n.id === sourceId)
  const targetNode = nodes.find((n) => n.id === targetId)
  if (!sourceNode || !targetNode) {
    return { ok: false, reason: 'Both ends of a connection must be nodes on the canvas.' }
  }

  const sourceDef = nodeTypes[sourceNode.type]
  const targetDef = nodeTypes[targetNode.type]
  const outPort = findPort(sourceDef, 'outputs', sourcePort)
  const inPort = findPort(targetDef, 'inputs', targetPort)
  if (!outPort) {
    return { ok: false, reason: `"${sourceNode.name}" has no output named ${sourcePort}.` }
  }
  if (!inPort) {
    return { ok: false, reason: `"${targetNode.name}" has no input named ${targetPort}.` }
  }

  const outType = resolvePortType(sourceNode, outPort)
  const inType = resolvePortType(targetNode, inPort)
  const knownTypes = new Set(portTypes.length ? portTypes : [
    'control', 'text', 'script', 'project_id', 'project_settings',
    'audio_file', 'tts_metadata', 'alignment', 'segments', 'scenes',
    'image_prompts', 'storyboard_images', 'animation_assets', 'captions',
    'music_track', 'editor_project', 'export_profile', 'video_file', 'generic_json',
  ])
  if (!knownTypes.has(outType) || !knownTypes.has(inType)) {
    return { ok: false, reason: 'A dynamic port has an unsupported data type.' }
  }
  if (outType !== inType) {
    return {
      ok: false,
      reason: `Type mismatch: ${outType} output can't feed the ${inType} input on "${targetNode.name}".`,
    }
  }

  const duplicate = edges.some(
    (e) => e.source_node === sourceId && e.source_port === sourcePort
      && e.target_node === targetId && e.target_port === targetPort,
  )
  if (duplicate) {
    return { ok: false, reason: 'These ports are already connected.' }
  }

  if (!inPort.multiple) {
    const occupied = edges.some(
      (e) => e.target_node === targetId && e.target_port === targetPort,
    )
    if (occupied) {
      return {
        ok: false,
        reason: `The ${targetPort} input on "${targetNode.name}" already has a connection.`,
      }
    }
  }

  if (wouldCreateCycle(edges, sourceId, targetId)) {
    return { ok: false, reason: 'That connection would create a loop — workflows must stay a DAG.' }
  }

  return { ok: true, edgeType: outType === 'control' ? 'control' : 'data' }
}

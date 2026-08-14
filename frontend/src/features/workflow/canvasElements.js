export const LARGE_CANVAS_NODE_THRESHOLD = 100

function samePosition(left, right) {
  return left?.x === right?.x && left?.y === right?.y
}

/**
 * Keep Vue Flow element objects stable when unrelated canvas state changes.
 * Vue Flow can then skip patching the other 149 cards when selection or one
 * persisted position changes.
 */
export function createCanvasNodeProjector() {
  let cache = new Map()

  return function projectCanvasNodes(nodes, notes, selection) {
    const next = new Map()
    const elements = []

    for (const node of nodes) {
      const selected = selection.has(node.id)
      const previous = cache.get(node.id)
      const unchanged = previous
        && previous.type === 'sts'
        && samePosition(previous.position, node.position)
        && previous.selected === selected
        && previous.data.nodeType === node.type
        && previous.data.label === node.name
        && previous.data.disabled === node.disabled
      const element = unchanged ? previous : {
        id: node.id,
        type: 'sts',
        position: { ...node.position },
        selected,
        data: { nodeType: node.type, label: node.name, disabled: node.disabled },
      }
      next.set(node.id, element)
      elements.push(element)
    }

    for (const note of notes) {
      const selected = selection.has(note.id)
      const previous = cache.get(note.id)
      const unchanged = previous
        && previous.type === 'note'
        && samePosition(previous.position, note.position)
        && previous.selected === selected
      const element = unchanged ? previous : {
        id: note.id,
        type: 'note',
        dragHandle: '.sticky-note-drag-handle',
        position: { ...note.position },
        selected,
        selectable: true,
        connectable: false,
        data: {},
      }
      next.set(note.id, element)
      elements.push(element)
    }

    cache = next
    return elements
  }
}

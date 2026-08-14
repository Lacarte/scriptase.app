import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const LARGE_WORKFLOW_NODE_COUNT = 150

export function generateLargeWorkflow(nodeCount = LARGE_WORKFLOW_NODE_COUNT) {
  const columns = 15
  return {
    schema_version: 1,
    name: `${nodeCount}-node canvas performance fixture`,
    description: 'Deterministic generated fixture for large-canvas interaction regressions.',
    nodes: Array.from({ length: nodeCount }, (_, index) => ({
      id: `fixture_node_${String(index + 1).padStart(3, '0')}`,
      type: 'stub.input',
      type_version: 1,
      name: `Sample ${String(index + 1).padStart(3, '0')}`,
      position: {
        x: (index % columns) * 240,
        y: Math.floor(index / columns) * 120,
      },
      configuration: { port_type: 'text', payload: `fixture-${index + 1}` },
      disabled: false,
      on_error: { policy: 'stop' },
    })),
    edges: [],
    variables: {},
    viewport: { x: 0, y: 0, zoom: 1 },
    settings: { on_error: 'stop', auto_attach_stubs: false },
    extensions: {},
  }
}

const scriptPath = fileURLToPath(import.meta.url)
if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  const output = resolve(dirname(scriptPath), '../src/features/workflow/fixtures/large-workflow.json')
  await mkdir(dirname(output), { recursive: true })
  await writeFile(output, `${JSON.stringify(generateLargeWorkflow(), null, 2)}\n`, 'utf8')
  console.log(`Generated ${LARGE_WORKFLOW_NODE_COUNT} nodes at ${output}`)
}

import { performance } from 'node:perf_hooks'
import { createCanvasNodeProjector } from '../src/features/workflow/canvasElements.js'
import { generateLargeWorkflow } from './generate-large-workflow.mjs'

const FRAME_BUDGET_MS = 1000 / 60
const document = generateLargeWorkflow()
const project = createCanvasNodeProjector()
let nodes = document.nodes
const samples = []

function measure(action) {
  const started = performance.now()
  action()
  samples.push(performance.now() - started)
}

measure(() => project(nodes, [], new Set()))
for (let frame = 0; frame < 600; frame += 1) {
  const selected = new Set([nodes[frame % nodes.length].id])
  measure(() => project(nodes, [], selected))
}
for (let frame = 0; frame < 120; frame += 1) {
  nodes = nodes.map((node, index) => index === 0
    ? { ...node, position: { x: frame, y: frame } }
    : node)
  measure(() => project(nodes, [], new Set([nodes[0].id])))
}

const sorted = [...samples].sort((left, right) => left - right)
const percentile = (ratio) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * ratio))]
const report = {
  node_count: nodes.length,
  measured_updates: samples.length,
  frame_budget_ms: Number(FRAME_BUDGET_MS.toFixed(2)),
  median_ms: Number(percentile(0.5).toFixed(3)),
  p95_ms: Number(percentile(0.95).toFixed(3)),
  max_ms: Number(sorted.at(-1).toFixed(3)),
  updates_over_budget: samples.filter((sample) => sample > FRAME_BUDGET_MS).length,
}

console.log(JSON.stringify(report, null, 2))
if (report.updates_over_budget > 0) process.exitCode = 1

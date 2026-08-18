/**
 * What a running Job looks like on the graph (step 1.3) — pure functions, no Vue.
 *
 * Everything here is derived. The engine owns node status; this module only
 * decides how a status is drawn, which edges are carrying work, and what one
 * card's panel should show. It invents no status, no stage and no node.
 *
 * On percent: the engine records per-node status, not per-node progress, so
 * there is no honest number for "how far through is this one node". The live
 * percent is therefore the *run's* — how much of the graph has settled — which
 * is exactly what the plan asks the pill to show, and what an active card is
 * reflecting when it shows it. One number, defined once, shown in both places.
 */

/**
 * Engine status → the five states the plan names.
 *
 * The engine's vocabulary is wider than the picture's, so several statuses
 * share a look:
 *   - `stale` is dim like `idle`: it has a result, but one that must be redone.
 *   - `invalid` is red like `failed`: the node cannot run as configured.
 *   - `cancelled` is struck through like `skipped`: this node never ran, and
 *     saying so is more honest than painting a stop as a failure.
 * A status this map has never heard of falls back to `pending` rather than
 * disappearing, the same way an unknown node type still renders.
 */
export const VISUAL_BY_STATUS = Object.freeze({
  idle: 'pending',
  stale: 'pending',
  queued: 'active',
  waiting: 'active',
  running: 'active',
  awaiting_approval: 'blocked',
  succeeded: 'done',
  failed: 'failed',
  invalid: 'failed',
  skipped: 'skipped',
  cancelled: 'skipped',
})

const DEFAULT_STATUS = 'idle'

/** States that mean the node will not be worked on again in this run. */
const SETTLED_VISUALS = new Set(['done', 'failed', 'skipped'])

export function visualForStatus(status) {
  return VISUAL_BY_STATUS[String(status || DEFAULT_STATUS)] || 'pending'
}

/**
 * The visual, spelled the way the prototype's stylesheet spells it (step 6.6).
 *
 * Two differences, both deliberate. `skipped` is the engine's word and `s-skip`
 * is the prototype's class, so this map translates rather than renaming the
 * engine's vocabulary to suit a stylesheet. And `blocked` has no prototype
 * counterpart at all — the prototype has no approval gate — so it keeps its own
 * token instead of being flattened onto a state that means something else.
 */
const STATE_CLASS = Object.freeze({
  idle: 's-idle',
  pending: 's-pending',
  active: 's-active',
  done: 's-done',
  failed: 's-failed',
  skipped: 's-skip',
  blocked: 's-blocked',
})

/**
 * `s-*` for one card.
 *
 * `bound` separates the prototype's two quiet states, which the engine does not
 * distinguish because it has no reason to: `s-idle` is "no run is being
 * watched", `s-pending` is "this run has not reached here yet". Same status,
 * two different things to say.
 */
export function stateClass(visual, bound = true) {
  const key = visual === 'pending' && !bound ? 'idle' : visual
  return STATE_CLASS[key] || STATE_CLASS.pending
}

/**
 * What the corner pill on a card reads (step 6.6).
 *
 * The percent is the run's, for the same reason the topbar's is: the engine
 * records per-node status, not per-node progress. The other three states are
 * the prototype's glyphs, and every other state reads empty — the pill is
 * `display: none` until it has something to say.
 */
export function stateBadge(visual, percent = null) {
  if (visual === 'active') return Number.isFinite(percent) ? `${percent}%` : ''
  if (visual === 'done') return '✓'
  if (visual === 'failed') return '✕'
  if (visual === 'skipped') return 'skip'
  return ''
}

/**
 * node_id → what the card should look like right now.
 *
 * Keyed off the graph rather than the record map so a node the run has not
 * reached still gets a state, and a record for a node this graph does not
 * contain is ignored instead of drawn.
 *
 * @param {object[]} nodes    buildSchemaGraph nodes
 * @param {Record<string, {status?: string}>} records  node execution records
 * @returns {Record<string, {status: string, visual: string}>}
 */
export function buildNodeStates(nodes, records = {}) {
  const states = {}
  for (const node of nodes || []) {
    if (!node?.id) continue
    const record = records?.[node.id]
    const status = String(record?.status || DEFAULT_STATUS)
    states[node.id] = {
      status,
      visual: visualForStatus(status),
      // Carried so a red card can say *why* without the canvas reaching for
      // the execution record itself (step 1.4).
      error: record?.error || null,
    }
  }
  return states
}

/**
 * Every node this run failed on, in graph order (step 1.4).
 *
 * `visual` rather than a status list, so `invalid` — a node that cannot run as
 * configured — is counted as the error it is, exactly as the card paints it.
 *
 * @param {object[]} nodes    buildSchemaGraph nodes
 * @param {Record<string, object>} records  node execution records
 * @returns {Array<{nodeId: string, name: string, type: string, stageKey: string,
 *   stageLabel: string, status: string, code: string, message: string}>}
 */
export function nodeFailures(nodes, records = {}) {
  const failures = []
  for (const node of nodes || []) {
    if (!node?.id) continue
    const record = records?.[node.id]
    if (!record || visualForStatus(record.status) !== 'failed') continue
    failures.push({
      nodeId: node.id,
      name: node.name,
      type: node.type,
      stageKey: node.stageKey || '',
      // A node no stage claims is infrastructure; its category is the honest
      // answer to "where did this happen", and inventing a stage would be a lie.
      stageLabel: node.stageLabel || node.subtitle || '',
      status: String(record.status),
      code: record.error?.code || '',
      message: record.error?.message || '',
    })
  }
  return failures
}

/**
 * edge id → `e-*`, by the prototype's rule (step 6.6).
 *
 * An edge is coloured by what happened at *both* ends, which is what makes a
 * running graph readable at a glance:
 *
 *   - `e-done`   work has crossed it — the source finished and the target has
 *                started or finished too
 *   - `e-active` work is crossing it right now: the source finished and the
 *                target is running. This is the only edge that animates, and
 *                it is deliberately narrower than "any edge into an active
 *                node" — an edge whose source has not produced anything yet is
 *                carrying nothing, so animating it would be a lie
 *   - `e-fail`   either end failed, so nothing more will cross it
 *
 * @returns {Record<string, string>} edge id → class string, `''` when plain
 */
export function edgeStateClasses(edges, nodeStates) {
  const classes = {}
  for (const edge of edges || []) {
    if (!edge?.id) continue
    const from = nodeStates?.[edge.source]?.visual
    const to = nodeStates?.[edge.target]?.visual
    const names = []
    if (from === 'done' && (to === 'active' || to === 'done')) names.push('e-done')
    if (from === 'done' && to === 'active') names.push('e-active')
    if (from === 'failed' || to === 'failed') names.push('e-fail')
    classes[edge.id] = names.join(' ')
  }
  return classes
}

/**
 * How much of the graph has settled.
 *
 * `total` counts the nodes on screen, so a run scoped to part of the graph
 * still reports against the whole picture the user is looking at.
 *
 * @returns {{settled: number, total: number, percent: number, active: number}}
 */
export function runProgress(nodes, nodeStates) {
  const list = nodes || []
  const total = list.length
  let settled = 0
  let active = 0
  for (const node of list) {
    const visual = nodeStates?.[node.id]?.visual
    if (SETTLED_VISUALS.has(visual)) settled += 1
    else if (visual === 'active') active += 1
  }
  return {
    settled,
    total,
    active,
    percent: total ? Math.round((settled / total) * 100) : 0,
  }
}

/**
 * The stage the run is in, named by the projection rather than by this file.
 *
 * The first active node wins; with nothing active, the last stage to have
 * settled is what the run is standing on.
 */
export function currentStageLabel(nodes, nodeStates) {
  let lastSettled = null
  for (const node of nodes || []) {
    const visual = nodeStates?.[node.id]?.visual
    if (visual === 'active' && node.stageLabel) return node.stageLabel
    if (SETTLED_VISUALS.has(visual) && node.stageLabel) lastSettled = node.stageLabel
  }
  return lastSettled
}

/**
 * The panel one card opens (step 1.3): status, resolved provider, input,
 * output and error, for the run currently bound.
 *
 * `cost` is where the engine records which provider instance actually ran and
 * why (contracts §1.4 / step 13.2). It is an instance **reference**; a
 * credential never reaches a Job document, an execution record or this panel.
 *
 * @param {object} node    buildSchemaGraph node
 * @param {object} record  node execution record, or null before the run reaches it
 */
export function inspectorModel(node, record) {
  if (!node) return null
  const status = String(record?.status || DEFAULT_STATUS)
  const cost = record?.cost || null
  return {
    id: node.id,
    name: node.name,
    type: node.type,
    stageLabel: node.stageLabel,
    subtitle: node.subtitle,
    icon: node.icon,
    accent: node.accent,
    // What the node actions need (step 1.4), carried from the registry through
    // the graph model rather than looked up again here.
    inputs: Array.isArray(node.inputs) ? node.inputs : [],
    providerDomain: node.providerDomain || '',
    status,
    visual: visualForStatus(status),
    attempts: Number.isFinite(record?.attempts) ? record.attempts : null,
    durationMs: Number.isFinite(record?.duration_ms) ? record.duration_ms : null,
    fromSampleData: Boolean(record?.from_sample_data),
    provider: cost?.provider_instance_id
      ? {
        instanceId: cost.provider_instance_id,
        providerId: cost.provider_id || '',
        reason: cost.selection_reason || '',
      }
      : null,
    input: record?.resolved_inputs_summary || null,
    output: record?.outputs_summary || null,
    artifacts: Array.isArray(record?.artifact_refs) ? record.artifact_refs : [],
    error: record?.error || null,
    /** True before the run has produced anything for this node at all. */
    empty: !record,
  }
}

/**
 * A redacted summary, split into the three tokens the prototype colours
 * (step 6.6): `k` keys, `s` strings, `n` numbers, literals and punctuation.
 *
 * The prototype colours its JSON by assigning a rewritten string to
 * `innerHTML`. Tokens are returned as data here and rendered as elements by
 * the caller, because a summary is engine output and engine output must never
 * reach `v-html` — the same rule step 6.5 applied to the simulate console.
 *
 * @returns {Array<{text: string, cls: string}>}
 */
export function jsonTokens(value) {
  let text
  try {
    text = JSON.stringify(value, null, 2)
  } catch {
    text = String(value)
  }
  if (typeof text !== 'string') return []

  const tokens = []
  // One pass over strings, numbers and literals. A string followed by a colon
  // is a key; every other string is a value.
  const pattern = /"(?:[^"\\]|\\.)*"(\s*:)?|\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b|\b(?:true|false|null)\b/g
  let last = 0
  for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
    if (match.index > last) tokens.push({ text: text.slice(last, match.index), cls: '' })
    const raw = match[0]
    if (raw.startsWith('"')) tokens.push({ text: raw, cls: match[1] ? 'k' : 's' })
    else tokens.push({ text: raw, cls: 'n' })
    last = match.index + raw.length
  }
  if (last < text.length) tokens.push({ text: text.slice(last), cls: '' })
  return tokens
}

/** Compact one-line duration for the panel. */
export function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds - minutes * 60)}s`
}

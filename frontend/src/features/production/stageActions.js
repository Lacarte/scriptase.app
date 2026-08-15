/**
 * Step detail panel actions → existing engine run modes (step 2.4).
 *
 * Mirrors scriptase.jobs.stage_actions. Each executable action maps onto a
 * ported run mode the canvas already uses — no second execution path.
 *
 *   Run            → node_with_deps
 *   Test           → node_isolated
 *   Regenerate     → retry_failed
 *   Run From Here  → from_node
 *
 * View Input / View Output / Provider / History / Approve are inspect or
 * checkpoint actions, not run modes. Provider UI appears only when the stage
 * is provider_capable and the action is executable (§6, §19).
 */

/** @typedef {'run'|'test'|'regenerate'|'run_from_here'|'view_input'|'view_output'|'provider'|'history'|'approve'} StageActionId */

export const STAGE_ACTIONS = Object.freeze([
  'run',
  'test',
  'regenerate',
  'run_from_here',
  'view_input',
  'view_output',
  'provider',
  'history',
  'approve',
])

export const EXECUTABLE_STAGE_ACTIONS = Object.freeze([
  'run',
  'test',
  'regenerate',
  'run_from_here',
])

/** §18 action → ported run_mode. */
export const ACTION_RUN_MODES = Object.freeze({
  run: 'node_with_deps',
  test: 'node_isolated',
  regenerate: 'retry_failed',
  run_from_here: 'from_node',
})

export const ACTION_LABELS = Object.freeze({
  run: 'Run',
  test: 'Test',
  regenerate: 'Regenerate',
  run_from_here: 'Run From Here',
  view_input: 'View Input',
  view_output: 'View Output',
  provider: 'Provider',
  history: 'History',
  approve: 'Approve',
})

export const ACTION_HINTS = Object.freeze({
  run: 'Execute this stage with upstream dependencies resolved first.',
  test: 'Open the Test Node panel: isolate this stage’s primary node with the input picker. Never advances the Job.',
  regenerate: 'Re-run only this stage’s primary node.',
  run_from_here: 'Run this stage and eligible downstream stages.',
  view_input: 'Inspect resolved inputs recorded for the primary node.',
  view_output: 'Inspect outputs and artifact refs for the primary node.',
  provider: 'Active provider instance for this provider-capable stage.',
  history: 'Attempt history, side-by-side artifact version comparison (provider instance, seed, prompt revision), and the repairs the correction loop ran for this Job.',
  approve: 'Mark the stage accepted at a human checkpoint (durable at 2.6).',
})

/**
 * @param {string} action
 * @returns {boolean}
 */
export function isExecutableAction(action) {
  return EXECUTABLE_STAGE_ACTIONS.includes(action)
}

/**
 * @param {string} action
 * @returns {string}
 */
export function runModeForAction(action) {
  const mode = ACTION_RUN_MODES[action]
  if (!mode) {
    throw new Error(
      action in ACTION_LABELS
        ? `Action "${action}" does not start a run`
        : `Unknown stage action: ${action}`,
    )
  }
  return mode
}

/**
 * Prefer the first primary (non-side-branch) member; else the first id.
 * Node types that own a stage via PRIMARY_STAGE_BY_TYPE win over collapsed
 * side branches (captions/music → Composer).
 *
 * @param {{ node_ids?: string[], key?: string }} stage
 * @param {{ nodes?: Array<{ id: string, type?: string }> }} [workflow]
 * @param {Record<string, string>} [primaryStageByType]
 * @returns {string}
 */
export function stagePrimaryTarget(
  stage,
  workflow = {},
  primaryStageByType = null,
) {
  const nodeIds = Array.isArray(stage?.node_ids) ? stage.node_ids : []
  if (!nodeIds.length) {
    throw new Error('Stage has no member nodes to target')
  }
  const nodesById = Object.create(null)
  for (const node of workflow?.nodes || []) {
    if (node && typeof node.id === 'string') nodesById[node.id] = node
  }

  // Default primary map mirrors backend PRIMARY_STAGE_BY_TYPE for the common
  // media types. Callers may inject the live map when available.
  const primaryMap = primaryStageByType || DEFAULT_PRIMARY_STAGE_BY_TYPE
  const stageKey = stage?.key

  for (const nodeId of nodeIds) {
    if (typeof nodeId !== 'string' || !nodeId) continue
    const typeKey = String(nodesById[nodeId]?.type || '')
    const primaryStage = primaryMap[typeKey]
    if (primaryStage != null && (stageKey == null || primaryStage === stageKey)) {
      return nodeId
    }
  }
  for (const nodeId of nodeIds) {
    if (typeof nodeId === 'string' && nodeId) return nodeId
  }
  throw new Error('Stage has no valid target node id')
}

/**
 * Build the same POST /api/workflow/run body the canvas store sends.
 *
 * @param {StageActionId|string} action
 * @param {object} stage
 * @param {object} [options]
 * @param {string} [options.workflowId]
 * @param {object} [options.workflow]  draft document when no saved id
 * @param {boolean} [options.force]
 * @param {Record<string, string>} [options.primaryStageByType]
 * @returns {{ run_mode: string, target_node_ids: string[], force: boolean, workflow_id?: string, workflow?: object }}
 */
export function buildStageRunRequest(action, stage, options = {}) {
  const runMode = runModeForAction(action)
  const target = stagePrimaryTarget(
    stage,
    options.workflow || {},
    options.primaryStageByType || null,
  )
  const body = {
    run_mode: runMode,
    target_node_ids: [target],
    force: Boolean(options.force),
  }
  if (options.workflowId) {
    body.workflow_id = options.workflowId
  } else if (options.workflow) {
    body.workflow = options.workflow
  }
  return body
}

/**
 * @param {string} action
 * @param {{ provider_capable?: boolean }} stage
 * @returns {boolean}
 */
export function actionRequiresProvider(action, stage) {
  if (!isExecutableAction(action)) return false
  return Boolean(stage?.provider_capable)
}

/**
 * Whether Approve is currently meaningful for this stage.
 * Durable checkpoints land in step 2.6; until then only awaiting_approval.
 *
 * @param {{ status?: string }} stage
 * @returns {boolean}
 */
export function canApproveStage(stage) {
  return String(stage?.status || '') === 'awaiting_approval'
}

/** Keep in lockstep with scriptase.jobs.stage_projection.PRIMARY_STAGE_BY_TYPE */
export const DEFAULT_PRIMARY_STAGE_BY_TYPE = Object.freeze({
  'script.input': 'script',
  'story.generate': 'script',
  'tts.generate': 'voice',
  'timing.align': 'timing',
  'segment.run': 'segments',
  'scenes.blueprint': 'scenes',
  'storyboard.generate': 'images',
  'animator.generate': 'videos',
  'review.run': 'review',
  'review.validate': 'review',
  'review.semantic': 'review',
  'assemble.project': 'composer',
  'timeline.project': 'composer',
  'export.video': 'export',
})

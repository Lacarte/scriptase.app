/**
 * Script-stage source modes (product §6 / step 2.5).
 *
 * Mirrors scriptase.jobs.source_modes. Provider UI is shown only for modes
 * that need a script provider; Paste and Manual require none.
 */

/** @typedef {'automatic'|'topic'|'idea'|'paste'|'manual'} SourceMode */
/** @typedef {'manual'|'assisted'|'automatic'} ExecutionMode */

export const SOURCE_MODES = Object.freeze([
  'automatic',
  'topic',
  'idea',
  'paste',
  'manual',
])

export const PROVIDER_REQUIRED_SOURCE_MODES = Object.freeze([
  'automatic',
  'topic',
  'idea',
])

export const DIRECT_TEXT_SOURCE_MODES = Object.freeze(['paste', 'manual'])

export const SOURCE_MODE_CATALOG = Object.freeze([
  {
    mode: 'automatic',
    label: 'Automatic',
    description:
      'Scriptase selects or derives a topic using Channel rules/history, then writes the script.',
    provider_required: true,
    input_fields: ['topic', 'idea'],
    primary_field: null,
  },
  {
    mode: 'topic',
    label: 'Topic → Script',
    description: 'User supplies a topic; the script provider writes the narration.',
    provider_required: true,
    input_fields: ['topic'],
    primary_field: 'topic',
  },
  {
    mode: 'idea',
    label: 'Idea → Script',
    description: 'User supplies a rough idea or premise; the provider expands it.',
    provider_required: true,
    input_fields: ['idea'],
    primary_field: 'idea',
  },
  {
    mode: 'paste',
    label: 'Paste Script',
    description: 'User supplies final text; the stage stores it without AI generation.',
    provider_required: false,
    input_fields: ['pasted_script'],
    primary_field: 'pasted_script',
  },
  {
    mode: 'manual',
    label: 'Manual / Edit',
    description: 'User writes or edits the narration text directly.',
    provider_required: false,
    input_fields: ['pasted_script'],
    primary_field: 'pasted_script',
  },
])

export const EXECUTION_MODE_CATALOG = Object.freeze([
  {
    mode: 'manual',
    label: 'Manual',
    description:
      'Operator runs or approves important stages. Default checkpoints pause after each primary stage (export excluded).',
  },
  {
    mode: 'assisted',
    label: 'Assisted',
    description:
      'Pipeline runs automatically and pauses only at configured human checkpoints (durable awaiting_approval).',
  },
  {
    mode: 'automatic',
    label: 'Automatic',
    description:
      'Unattended start-to-export under Channel policy: bounded retries, fallback, safe degradation; pause only on critical/unrecoverable issues.',
  },
])

/**
 * @param {string} [mode]
 * @returns {boolean}
 */
export function sourceModeRequiresProvider(mode) {
  const text = String(mode || '').trim() || 'topic'
  return PROVIDER_REQUIRED_SOURCE_MODES.includes(text)
}

/**
 * @param {string} [mode]
 * @returns {string}
 */
export function sourceModeLabel(mode) {
  const text = String(mode || '').trim() || 'topic'
  const entry = SOURCE_MODE_CATALOG.find((item) => item.mode === text)
  return entry?.label || text
}

/**
 * @param {{ mode?: string, topic?: string, idea?: string, pasted_script?: string }} source
 * @returns {string[]} validation error messages (empty = ok)
 */
export function validateJobSource(source) {
  if (!source || typeof source !== 'object') return ['Source is required']
  const mode = String(source.mode || '').trim() || 'topic'
  if (!SOURCE_MODES.includes(mode)) {
    return [`Unknown source mode: ${mode}`]
  }
  const topic = String(source.topic || '').trim()
  const idea = String(source.idea || '').trim()
  const pasted = String(source.pasted_script || '').trim()
  if (DIRECT_TEXT_SOURCE_MODES.includes(mode)) {
    if (!pasted) {
      return ['Script text is required for Paste Script and Manual/Edit modes']
    }
    if (pasted.length > 10000) {
      return ['Script text must be at most 10,000 characters']
    }
  } else if (mode === 'topic' && !topic) {
    return ['Topic is required for Topic → Script mode']
  } else if (mode === 'idea' && !idea) {
    return ['Idea is required for Idea → Script mode']
  }
  return []
}

/**
 * Default create draft used before GET /api/jobs/defaults returns.
 * @returns {{ execution_mode: ExecutionMode, source: object }}
 */
export function defaultJobDraft() {
  return {
    execution_mode: 'manual',
    source: {
      mode: 'paste',
      topic: '',
      idea: '',
      pasted_script: '',
      references: [],
      remove_silence: null,
      speed: null,
    },
  }
}

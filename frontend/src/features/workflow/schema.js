/**
 * Schema helpers shared by the inspector and node cards (step 2.2).
 * Mirrors the backend rules in studio/workflows/validation.py for the
 * checks that matter while editing; the server stays authoritative.
 */

import { validateStubPayload } from './stubPayloads.js'
import { expressionSyntaxError, isExpressionValue } from './expressions.js'
import { isDisplayed } from '@/shared/schema/visibility.js'

/**
 * n8n-style display_options: {show: {field: [values]}, hide: {...}}.
 * Delegates to the shared rule that provider settings `ui.show_if` also uses,
 * so a node field and a provider field can never disagree about visibility.
 */
export function shouldDisplayField(field, configuration) {
  return isDisplayed(field.display_options, configuration || {})
}

function configIssue(name, message) {
  return { kind: 'config', name, message }
}

function isJsonCompatible(value, seen = new Set()) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (typeof value !== 'object' || seen.has(value)) return false
  seen.add(value)
  const children = Array.isArray(value) ? value : Object.values(value)
  return children.every((child) => isJsonCompatible(child, seen))
}

function fieldValue(configuration, field) {
  return Object.hasOwn(configuration, field.name) ? configuration[field.name] : field.default
}

function validateField(field, value) {
  const label = field.label || field.name
  if (value === null || value === undefined) return null
  if (isExpressionValue(value)) return expressionSyntaxError(value) || null
  if (field.type === 'string' || field.type === 'textarea') {
    if (typeof value !== 'string') return `${label} must be a string`
    if (value.length < (field.min_length ?? 0) || value.length > (field.max_length ?? 100000)) {
      return `${label} has an invalid length`
    }
    if (field.pattern) {
      try {
        const match = value.match(new RegExp(field.pattern))
        if (!match || match[0] !== value) return `${label} has an invalid format`
      } catch {
        return `${label} has an invalid validation pattern`
      }
    }
  } else if (field.type === 'number') {
    if (typeof value !== 'number' || !Number.isFinite(value)) return `${label} must be a finite number`
    if (value < (field.min ?? -Infinity) || value > (field.max ?? Infinity)) {
      return `${label} is outside the allowed range`
    }
    if (field.integer && !Number.isInteger(value)) return `${label} must be an integer`
  } else if (field.type === 'boolean') {
    if (typeof value !== 'boolean') return `${label} must be a boolean`
  } else if (field.type === 'options') {
    if (field.options?.length && !field.options.includes(value)) {
      return `${label} is not an allowed option`
    }
  } else if (field.type === 'json') {
    if (!isJsonCompatible(value)) return `${label} must contain valid finite JSON data`
  } else if (field.type === 'media_asset') {
    if (typeof value !== 'object' || Array.isArray(value)) {
      return `${label} must be a managed media reference`
    }
  }
  return null
}

/**
 * Issues for one node: empty required config fields (only when visible)
 * and required data inputs with no incoming edge.
 * @returns {Array<{kind: 'config'|'input', name: string, message: string}>}
 */
export function nodeIssues(node, def, edges) {
  if (!def) {
    return [{ kind: 'config', name: node.type, message: `Unknown node type: ${node.type}` }]
  }
  const issues = []
  if (node.type_version !== def.type_version) {
    issues.push(configIssue('type_version', `Unsupported version for ${node.type}`))
  }

  let configuration = node.configuration
  if (!configuration || typeof configuration !== 'object' || Array.isArray(configuration)) {
    issues.push(configIssue('configuration', 'Configuration must be an object'))
    configuration = {}
  }

  const fields = new Map((def.config_schema || []).map((field) => [field.name, field]))
  for (const name of Object.keys(configuration)) {
    if (!fields.has(name)) issues.push(configIssue(name, `Unknown configuration field: ${name}`))
  }

  for (const field of def.config_schema || []) {
    const value = fieldValue(configuration, field)
    if (field.required && shouldDisplayField(field, configuration)
      && (value === null || value === undefined || value === '')) {
      issues.push(configIssue(field.name, `${field.label || field.name} is required`))
      continue
    }
    const message = validateField(field, value)
    if (message) issues.push(configIssue(field.name, message))
  }

  // Sample Input payloads are typed sample data (step 2.5) — validate them
  // against the selected port type, not just "is JSON".
  if (node.type === 'stub.input' || (
    node.type === 'stub.output' && configuration.pinned === true
  )) {
    const portType = configuration.port_type ?? 'generic_json'
    const payload = Object.hasOwn(configuration, 'payload') ? configuration.payload : {}
    for (const message of validateStubPayload(portType, payload)) {
      issues.push(configIssue('payload', message))
    }
  }

  for (const port of def.inputs || []) {
    if (!port.required || port.type === 'control') continue
    const connected = edges.some(
      (e) => e.target_node === node.id && e.target_port === port.id,
    )
    if (!connected) {
      issues.push({
        kind: 'input',
        name: port.id,
        message: `The ${port.id} input needs a connection`,
      })
    }
  }

  return issues
}

export const APP_NAME = 'Scriptase'

// The frontend renders from GET /api/workflow/node-types and hardcodes nothing
// but SVG icon paths and port colours. Preserve that property: adding a node
// type must mean editing the backend registry, never a Vue component.
export const API_BASE = '/api'

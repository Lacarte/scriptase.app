# workflow

Ported from V2 `frontend/features/workflow/` in step 2.1: the Vue Flow canvas,
dagre auto-layout, registry-driven inspector, and execution panel, with their
Vitest suites.

The inspector is generated from `GET /api/workflow/node-types`. Only SVG icon
paths and port colours are hardcoded — preserve that property.

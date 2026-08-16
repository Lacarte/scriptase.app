# editor

Timeline editor, ported from V2 in step 14.2. The backend was already in place:
`scriptase/modules/compose/` serves every endpoint this feature calls.

This is a **legacy-bridge feature, not idiomatic Vue**. `video-editor.js` is a
12k-line imperative module that owns the DOM by element id. Vue's only jobs are
to mount the shell markup it expects, host the dialogs, and hand it a project.
There is no component tree to refactor toward — treat the split below as the
seam and leave the imperative side alone.

| Surface | Role |
|---|---|
| `../../../public/js/editor/video-editor.js` | The editor. Timeline, tracks, history, save, export |
| `../../../public/js/editor/preview.js` | `CanvasPreview` — canvas playback and effects |
| `../../../public/js/editor/export-api.js` | Export profiles, payload assembly, job polling |
| `../../../public/js/editor/utils.js` | Shared constants, toasts, backend log relay |
| `views/EditorPage.vue` | Mounts the shell, owns dialog visibility, calls `useEditor` |
| `composables/useEditor.js` | Boot bridge: storage, `?project=`, load/destroy |
| `editor-shell-html.js` | The DOM `video-editor.js` queries by id |
| `editor-inline-scripts.js` | Project picker, TTS picker, panel resize, ratio menu |
| `components/*.vue` | Eight dialogs, driven through the `window._vue*` bridge |
| `styles/editor.css` | 139 KB of editor styling |

## Why the four modules live in `public/`

They are classic ES modules that use `fetch`, DOM ids, and `window.*` only.
Bundling them would rewrite their `window` exports out of existence, so they
are loaded by a `<script type="module">` tag `useEditor` appends, resolved
against `import.meta.env.BASE_URL` — `/js/editor/…` under Vite, and
`/static/js/editor/…` once `npm run build` copies `public/` into
`static/dist/`.

## Booting a project

V2 fronted the boot handoff with a Pinia `stagingStore` that only wrapped
storage reads and writes. It is gone; the keys are the contract.

| Key | Store | Meaning |
|---|---|---|
| `sts-staged-timeline` | session | Staged project payload, preferred source |
| `sts-editor-boot-project` | local | Same payload, survives a reload |
| `sts-editor-scenes` | local | Older alias of the above |
| `sts-editor-entry-source` | session | One-shot. `menu` shows the project picker |
| `sts-editor-last-saved-project-id` | local | Project id to fetch on boot |

`/editor?project=<id>` — what Workflow's "Open in Timeline Editor" pushes —
wins over all of it: `useEditor.stageProjectId` drops the staged keys first,
because stale scenes from an earlier session would otherwise take the boot
race and quietly open the wrong project. Bare `/editor` sets the entry source
to `menu` and lands on the picker.

## Two adaptations, both deliberate

The route is **lazy**. `editor.css` is global and defines generic names
(`.modal-content`, `.modal-header`, `.modal-body`, `.modal-footer`,
`.btn-secondary`, `.toggle-slider`) that collide with
`features/providers/components/`. Loading it only on `/editor` keeps that
bleed out of every other view. Step 14.4 moves the editor into its own window,
which removes the problem rather than containing it.

`.editor-page` is `height: 100%`, not V2's `100vh`: this app renders below a
top nav bar, so a viewport-height page would overflow by exactly that bar. The
route carries `meta.fullHeight` so `App.vue` bounds it.

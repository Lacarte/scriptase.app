# export-library

Browse, download, and prune finished exports. Ported from V2 in step 14.3 and
mounted at `/exports`. The backend was already in place —
`scriptase/modules/compose/export_routes.py` serves every endpoint below.

Unlike the timeline editor next door, this is ordinary Vue 3: no `window.*`
bridge, no imperative DOM owner, no global stylesheet. Refactor it normally.

| Surface | Role |
|---|---|
| `views/ExportLibraryPage.vue` | Header, sync panel, stats bar, grid, delete dialog |
| `composables/useExportLibrary.js` | Fetch, filter/sort projection, downloads, sync, trash |
| `components/ExportCard.vue` | One export: inline player, chips, timing and detail panels |
| `components/LibrarySearch.vue` | Search box with suggestions, plus the four filter selects |
| `components/LibraryAnalytics.vue` | Collapsed dashboard — overview, styles, pipeline, prompts |
| `components/DeleteExportDialog.vue` | Confirms the move to `output/TRASH` |

## Backend contract

| Endpoint | Used by |
|---|---|
| `GET /api/export/library` | `fetchLibrary` — one row per video under `output/exports` |
| `GET /api/export/library/preview/<relpath>` | `item.preview_url`, the inline `<video>` |
| `GET /api/export/library/download/<relpath>` | `item.video_download_url` / `zip_download_url` |
| `GET /api/export/library/prompts/<project_id>` | The Analytics "Prompts" tab |
| `POST /api/export/library/trash` | `trashVideo`, keyed by `video_relpath` |
| `GET /api/export/library/sync` | `syncToFolder`, an SSE stream |

Rows carry a managed relative path (`video_relpath`) and server-built URLs only
— never an absolute filesystem path. `trashVideo` sends that same relative path
back, so the browser never names a file the backend did not hand it.

`zip_download_url` has two shapes the card distinguishes through `zip_source`:
a real sibling `.zip` (`file`), or `/api/editor/export-zip/<project_id>`, which
builds one on demand (`generated`).

## Folder sync

`syncToFolder` opens the SSE stream and folds `copying` / `copied` / `skip` /
`error` / `done` events into a single `syncProgress` object. The button label
and the backend both say *folder*: it copies into `<sts-sync-folder>/exports`
and skips any destination file already matching in name and size. V2 called the
function `syncToPhone`, which no longer described anything it does.

## Three adaptations

`ExportCard` falls back to eager loading when `IntersectionObserver` is absent
instead of leaving the player permanently blank, and `focusRequestedExport`
guards `scrollIntoView` the way it already guarded `focus`. Those are the jsdom
cases, but they are also the correct degradations.

`LibrarySearch` closes its suggestion dropdown from a script-side timer.
V2 wrote `@blur="setTimeout(() => searchFocused = false, 200)"`; a compiled
render function resolves `setTimeout` against the component instance, not the
window, so that handler threw instead of running and the dropdown never closed
on blur.

The composable's `stats` computed is gone. The page never read it — it computes
`extendedStats` from the same rows — and keeping two divergent copies of the
same arithmetic was the only thing it bought.

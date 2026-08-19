# export-library

Browse, download, and prune finished exports. Ported from V2 in step 14.3 and
mounted at `/exports`. The backend was already in place —
`scriptase/modules/compose/export_routes.py` serves every endpoint below.

Unlike the timeline editor next door, this is ordinary Vue 3: no `window.*`
bridge, no imperative DOM owner, no global stylesheet. Refactor it normally.

| Surface | Role |
|---|---|
| `views/ExportLibraryPage.vue` | Head, sync panel, stat run, gallery, detail modal, delete dialog |
| `composables/useExportLibrary.js` | Fetch, filter/sort projection, downloads, sync, trash |
| `components/ExportCard.vue` | One export as a gallery card: preview frame, channel line, two actions |
| `components/ExportDetailModal.vue` | One export in full: preview, output, pipeline timing, destination |
| `components/LibrarySearch.vue` | The toolbar — search with suggestions, five filter selects, the count |
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

## Prototype fidelity (step 6.7)

The `lib-*` family is ported: the `lib-view` / `lib-inner` shell, `lib-head`
with its `sub` and `spacer`, the naked `lib-stats` run of `lib-stat` figures,
`lib-toolbar`, the `lib-grid` track, `lib-card` with its `lib-thumb`
(`cap` / `dur` / hover `play`), `lib-body` (`t` / `m` / `cav`), `lib-actions`,
`lib-badge-arch`, the `lib-flash` arrival animation and `lib-empty`.

The `exp-*` family is ported as the detail modal a card opens: `exp-head` with
its `ei` / `et` / `exp-close`, the `exp-body` split of `exp-preview` — the
`exp-thumb` with its `cap`, `dur` and `play` — and `exp-cfg`, whose `exp-sec`
groups are runs of `exp-kv`, then `exp-path`, `exp-size-note` and `exp-foot`.

**The card gave up its inline detail.** The prototype's library card carries a
thumbnail, one channel line and two buttons; clicking it opens the modal. So
the metadata chips, the Details drawer and the timing drawer moved into the
modal wholesale, and Delete and Project ZIP moved into its foot. Nothing was
dropped — it is one click further in, which is where the prototype puts it.

The prototype's `lib-thumb .play` is decorative — a `div` inside a `div` with
an `onclick`. Here it is a real `<button>`, because the card holds two more
buttons and `role="button"` around those would be invalid. The card still
opens on any click; the overlay is what a keyboard reaches.

Four things are done differently, because the prototype renders a fixture and
this page renders `/api/export/library`:

- **The avatar and the thumbnail.** The prototype paints `lib-thumb` with a
  channel gradient and stamps a logo on it. The export row carries no channel
  artwork, so the thumb is the export's own first frame and `cav` is the
  channel's initials. A colour derived from a channel id would be invention.
- **`lib-thumb .wm` and `exp-watermark`** are excluded for the same reason:
  there is no watermark on the row to draw.
- **The stat run** counts what the backend returned. It keeps the prototype's
  four figures — videos, channels, total runtime, archived — and adds the four
  the app already computed. None of them carry a colour any more; the prototype
  leaves them in `--text`, and a palette of hardcoded hexes was the drift.
- **`exp-thumb`'s aspect** follows the export's own ratio. The prototype fixes
  9:16 because it renders one channel; the library holds every ratio the
  pipeline has produced.

And three parts of `exp-*` are excluded rather than faked:

- **`exp-opts` / `exp-opt`** are the prototype's format and quality selects.
  The video in the library is already rendered and there is no transcode
  endpoint behind them, so shipping the controls would be two dropdowns that
  change nothing.
- **`exp-progress`** is its simulated encode. Download here is a single
  `fetch`, with no progress the backend reports.
- **`exp-foot`'s "Open folder"** needs a local-filesystem action the app does
  not expose, and would have to name an absolute path to be useful.

**Pipeline timing has no prototype counterpart** — the prototype records no
run. Its bars read in `--run`, the one tone the system gives to work, rather
than the seven hardcoded hues they used to carry.

The 48-hour line is still `shared/components/ArchiveCalendar.vue`, the same
component Production draws its rows with. It gained one prop, `itemsClass`, so
a view can name its own item track — `lib-grid` here — and lost the `layout`
prop that used to do the same job less directly.

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

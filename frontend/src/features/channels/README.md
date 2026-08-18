# channels

The Channel Profile rail and editor (step 1.3, restyled onto the prototype in
step 6.4).

```
api.js             CRUD plus managed image and music uploads
ChannelRail.vue    the ch-rail: list, filter, create, deferred delete
ChannelsPage.vue   /channels — the chview shell with an empty detail
ChannelEditor.vue  /channels/:id — hero, section stack, inherit strip, footer
```

Logo and thumbnail uploads go through the managed-branding endpoint — never a
browser-supplied filesystem path. Channels select provider **instance ids**;
they never carry credentials or duplicated account configuration.
`visual_direction.pattern` is edited as a structured role → shot-direction map,
not a free-text box.

## The prototype's `ch-*` family (step 6.4)

Both routes render the prototype's one screen: a `chview` grid with the rail on
the left and a `ch-detail` pane on the right. `/channels` fills that pane with
`ch-empty`; `/channels/:id` fills it with the editor. That is why `ChannelRail`
is a component — the list, its filter and its Undo delete exist once.

56 of the prototype's 61 `ch-*` classes are styled here with its declarations;
the five that are not are listed under Exclusions.

| Region | Classes |
|---|---|
| Shell | `chview`, `ch-rail`, `ch-detail`, `ch-empty` |
| Rail | `ch-rail-head`, `ch-rail-title`, `ch-rail-sub`, `ch-list`, `ch-litem` (`lav`, `lmeta`, `lname`, `lrow`) |
| Hero | `ch-hero`, `ch-hero-av`, `ch-hero-main`, `ch-name-input`, `ch-hero-sub`, `ch-hero-stats`, `ch-stat` |
| Sections | `ch-body`, `ch-section`, `ch-grid`, `ch-field`, `ch-field-label`, `ch-input`, `ch-select` |
| Script template | `ch-tpl-sections`, `ch-tpl-sec`, `ch-tpl-num`, `ch-tpl-mv`, `ch-tpl-x`, `ch-tpl-actions` |
| Image prompt | `ch-imgprev`, `ch-imgprev-h`, `ch-imgprev-code` |
| Music | `ch-path-row`, `ch-tracklist`, `ch-track`, `ch-track-play` |
| Narration | `ch-narr-row`, `ch-narr-item`, `ch-narr-txt` |
| Brand assets | `ch-asset-drop`, `ch-asset-img` (`wm-check`), `ch-asset-ph`, `ch-asset-meta`, `ch-asset-x` |
| Watermark | `ch-wm-pos-wrap`, `ch-wm-editor`, `ch-wm-frame`, `ch-wm-preview`, `ch-wm-grid`, `ch-wm-cell`, `ch-wm-note` |
| Inherit strip | `ch-preview`, `ch-preview-chips`, `ch-pchip` |
| Footer | `ch-foot`, `ch-dirty` |

Three of the family are not this view's and ship where they belong.
`ch-avatar` and `ch-meta` are in `styles/shared.css`: a Channel is drawn in
four places, and the prototype's own stylesheet reaches them from the job row
and the batch dropdown too. `s1-toggle` moved there for the same reason — the
prototype puts Script Studio's switch in this editor's narration row, so it is
cross-cutting rather than either view's.

Where the prototype writes a literal rgba, the port uses the token that already
names it (`--accent-line`, `--accent-line-2`, `--accent-dim`, `--accent-wash`,
`--accent-fill-2`, `--line-2`, `--fail-line-2`). Only the checkerboard behind a
transparent logo stays literal — it is a texture, not a colour in the ramp.

## The avatar is derived, not stored

`ChannelProfile` carries neither the prototype's `code` nor its `color`, and
step 6.3 left the question here. Both are **derived** rather than added to the
schema: initials from the name, and a palette entry from a hash of the id
(`shared/utils/channelIdentity.js`). Hashing the id and not the list position
is what keeps one channel the same colour in the rail, the hero, a job row and
a script card, and across every re-sort. A thumbnail, when set, covers it.

Adding a real `color` field was the alternative. It would mean a schema
migration for something with no effect on any output, and a second source of
truth for a plate colour.

## The 3x3 watermark picker

The cells write `WATERMARK_POSITIONS` values (`top-left` … `bottom-right`, with
`center` in the middle) straight into `branding.position`. The prototype spells
its cells `tl`…`br`; translating would put a second vocabulary between the
control and the field it validates against.

Beside the grid is the prototype's live frame, which takes its aspect ratio from
`export_defaults.aspect_ratio` — so the preview shows where the mark lands on
this channel's exports, not on a square. With no logo uploaded yet it shows a
placeholder mark rather than nothing, because the position is still editable.

## What this step fixed rather than styled

**`music_library` was write-only.** `create_channel` and `update_channel` both
omitted it when constructing the document, so the folder label and track list
reset to empty on every save. Porting the prototype's music panel onto a field
that discards its input would have hidden the bug behind a nicer surface;
`tests/test_channel_store.py::test_music_library_survives_create_and_update`
now covers the round trip.

**Save erased `cadence` and `fallback_policies`.** Neither has a control in
this editor and `draftPayload` never emitted them, so pressing Save on an
unrelated field destroyed a schedule or a stage fallback chain. Both are now
held outside `form` — plain, never rendered — and written back verbatim.

## Deliberate exclusions

Accounted for so they do not read as drift:

- **`ch-swatches` / `ch-sw`** — the accent-colour picker. There is no `color`
  field to persist it to; see *The avatar is derived* above.
- **`ch-plat-row` / `ch-plat`** — the YouTube/TikTok/Instagram toggles.
  `ChannelProfile` has no `platforms` field and nothing downstream consumes
  one, so this is a feature, not a style. `lplats` in the rail row and `plats`
  in the hero go with them; the rail shows niche and revision instead.
- **The hero's Videos / Published counters.** Neither number is on a Channel —
  they would need a Jobs and a Library query. The three `ch-stat` counters
  carry what this document owns: sections, tracks and revision.
- **The prototype's "Add location" button and its `D:\Scriptase\music\channel`
  placeholder.** It browses to a folder on disk and scans it. Uploads go
  through the managed music endpoint here, and `music_library.folder` is a
  collection label — an absolute path is rejected by the model.
- **The footer's Duplicate and "New job with this".** Duplication has no
  endpoint and Production's create panel reads only `?create=1`; both are
  features. The footer keeps the prototype's dirty note, spacer and layout.
- **The 820px breakpoint** hides the rail in the prototype. It is the only way
  to reach a channel from these routes, so it stacks above the detail instead.

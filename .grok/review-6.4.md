## Summary

Step 6.4 correctly fixes the two claimed persistence defects (`music_library` omitted from store constructors; `cadence` / `fallback_policies` wiped on save) and ports the rail+editor shell, watermark picker, and derived avatars without contract or secret leakage problems. Path traversal via `/output/${thumbnail}` is blocked by `_managed_ref` (requires `branding/`, rejects `..` and `:`) before anything is stored; list summaries use the same validated field. Cadence null-vs-empty omission is safe for real API documents because `ChannelProfile.to_document()` always emits a truthy cadence object, which is carried and written back; omitting only when absent falls through to `ChannelDraft`'s `default_factory` (disabled). `music_library.tracks` is re-copied after `Object.assign`. Provider defaults, budget, and review_policy still round-trip in `draftPayload`. Script/Production avatar wiring is non-breaking.

The real regressions come from embedding `ChannelRail` beside the editor without keeping the list in sync with editor mutations, plus an unguarded `load()` race that the new in-place rail navigation makes easy to hit. Tests cover watermark spelling and cadence carry, but not rail↔editor sync, so they miss these.

## Issues

### Issue 1 -- Severity: bug
- File: frontend/src/features/channels/ChannelRail.vue:103
- File: frontend/src/features/channels/ChannelEditor.vue:512-523
- Description: After a successful editor save, `meta.version` / the document bump, but the sibling rail keeps the summary object loaded at mount (`ch.version` unchanged). Rail delete then calls `deleteChannel(ch.id, ch.version)` with the stale expected version → `ChannelConflict`. `useUndoableAction` restores the row on failure, so the user sees a failed delete after the undo window with no recovery short of refresh/reseed. `defineExpose({ refresh })` exists but `ChannelEditor` never holds a ref or calls it after `onSave` / `applyDocument`.
- Suggestion: After save (and on name/thumbnail changes), refresh the rail or patch the matching list row's `version` / `name` / `thumbnail_asset_id`. Alternatively have the rail delete use a fresh `getChannel` version, or drop expected_version for rail deletes only if that matches store policy.
- Status: fixed

### Issue 2 -- Severity: bug
- File: frontend/src/features/channels/ChannelRail.vue:68-73
- Description: `onCreate` creates the channel and `router.push`es to `/channels/:id` but never `refresh()`es the list. Creating from `/channels` remounts a new rail (OK). Creating while already on `ChannelEditor` reuses the same rail instance (param-only navigation) so the new channel never appears until a manual reseed/reload. The selected editor pane shows the new channel; the rail does not.
- Suggestion: `await refresh()` before or after the push (and/or prepend the created summary into `channels`). Same expose/`refresh` wiring as Issue 1.
- Status: fixed

### Issue 3 -- Severity: bug
- File: frontend/src/features/channels/ChannelEditor.vue:492-510
- File: frontend/src/features/channels/ChannelEditor.vue:717-719
- Description: `load()` has no request generation / abort guard (unlike `refreshPromptPreview`). Step 6.4 makes rapid rail clicks the normal way to switch channels on a reused `ChannelEditor`. Out-of-order `getChannel` responses can `applyDocument` an older channel after a newer one: URL shows B while form/`meta.id` are A, and Save writes A under a B URL. Dirty state from A can also be silently overwritten when B's response arrives second, or vice versa.
- Suggestion: Mirror the `promptPreviewRequest` pattern (increment on each `load`, ignore stale responses), or abort the prior fetch; optionally confirm-discard when `dirty` before switching.
- Status: fixed

### Issue 4 -- Severity: suggestion
- File: frontend/src/features/channels/channels.test.js:376-446
- Description: New tests assert watermark cell→`center` and cadence/fallback carry on save, and the backend music_library round-trip. They never mount editor+rail together to assert list version after save, create visibility, or in-flight load ordering—so Issues 1–3 would stay green.
- Suggestion: Add a focused rail↔editor interaction test (shared host or stubbed rail ref) covering create→row present, save→version used by delete, and optionally overlapping loads.
- Status: fixed

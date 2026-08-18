# script

Script Studio: the library rail, the document editor, the create flow, the
narration panel and the virality gauge (Phase 3, restyled onto the prototype in
step 6.3).

```
api.js             /api/scripts + /api/story/generate + /api/tts/voices client
generation.js      applyTemplateOutline — provider prose onto the Channel outline
ScriptPage.vue     the whole view: rail, create sheet, document, narration panel
ViralityPanel.vue  the s1-vir-* gauge, bars and reason chips
```

## The prototype's `s1-*` family (step 6.3)

The view carries the prototype's own class names and declarations, so a drift
check reads mechanically. 57 of the prototype's 58 `s1-*` classes are styled
here; the one that is not is listed under Exclusions below.

| Region | Classes |
|---|---|
| Shell | `s1view`, `s1-rail`, `s1-detail` |
| Rail | `s1-rail-head`, `s1-rail-title`, `s1-search`, `s1-filters`, `s1-fchip`, `s1-list-wrap`, `s1-card`, `s1-rail-foot` |
| Document | `s1-doc-head`, `s1-doc-eyebrow`, `s1-title-input`, `s1-doc-sub`, `s1-doc-body`, `s1-script-col`, `s1-col-label`, `s1-script-area`, `s1-doc-foot`, `s1-dirty-note`, `s1-empty` |
| Create flow | `s1-tpl-card`, `s1-tpl-head`, `s1-tpl-edit`, `s1-tpl-brief`, `s1-tpl-chips`, `s1-tpl-chip` |
| Narration | `s1-tts`, `s1-panel`, `s1-panel-head`, `s1-panel-body`, `s1-tts-status`, `s1-kv`, `s1-player`, `s1-play`, `s1-wave-track`, `s1-tts-actions`, `s1-proc`, `s1-proc-head`, `s1-proc-src`, `s1-proc-reset`, `s1-inh`, `s1-toggle` |
| Virality | `s1-vir`, `s1-vir-head`, `s1-vir-gauge`, `s1-vir-recheck`, `s1-vir-body`, `s1-vir-dim`, `s1-vir-bar`, `s1-vir-issues`, `s1-vir-chip`, `s1-vir-empty`, `s1-vir-scan` |

Two of them live outside this folder because they are not this view's:
`s1-list` and `s1-row` are the **job-create** script picker, so they ship with
`production/components/JobCreatePanel.vue`. Its rows stay multi-select — one Job
per script is the point there — so `.sel` follows the checkbox rather than a
single cursor. `.dot-sep`, `.tts-tag`, `.tts-ready` and `.tts-only` are
cross-cutting and live in `styles/shared.css`, since both the library card and
that picker carry them. `.s1-toggle` joined them in step 6.4 — the prototype
gives the same switch to the Channel editor's narration rows, so it keeps this
view's name without being this view's rule.

Where the prototype writes a literal rgba, the port uses the token that already
names it (`--accent-line-2`, `--accent-ring`, `--accent-wash`, `--line-2`,
`--ok-line`, `--run-line`, `--warn-line`). Only `.s1-play`'s gradient and cast
stay literal — no token names that green pair.

## Filtering by narration state

The three `s1-fchip` chips (All / TTS Ready / Script Only) were missing
entirely, so this step built the control, not just its styling.

Filtering happens in the browser over the list the backend returned, because
`narration.state` is already on every summary — no second source of truth and no
new endpoint. **The search box is the opposite**: `q` is answered by
`GET /api/scripts`, so the chip counts describe the set the search returned. The
prototype counts its whole in-memory library; counting the whole library here
would take a second unfiltered request whose numbers would then disagree with
the list on screen.

`generating` counts as Script Only, matching the prototype: a take in flight is
not yet a take.

## The virality action

The prototype puts **Check Virality** in the `s1-col-label` above the editor and
leaves the not-yet-run panel as copy only. Both are ported: the panel's empty
state has no button, and `s1-vir-recheck` in the panel head is the control once a
score exists. It reads *Check current text* when the body has moved on from the
scored text — the app knows the difference and the prototype had no such state.

The panel's subtitle stays "Advisory only — it never blocks saving." The
prototype says "this channel sets no virality threshold", which would be a claim
about a `ChannelProfile` field that does not exist.

## Narration processing

Remove silence is the prototype's `s1-toggle`, speed is its select, and both
show the **effective** value with an `s1-inh` badge when it is the Channel's.
Touching either writes an explicit override; `s1-proc-reset` returns both to
`null`, which is how the API spells "inherit". Nothing is sent until Generate.

The player replaces the browser's default controls with `s1-play` and the
prototype's 48-bar track. The bars are a progress track, not a waveform — there
is no per-sample envelope to draw — and they follow the real `<audio>` element's
`timeupdate`, which stays in the DOM with its controls hidden.

`.prov` names the Channel's `tts_provider_instance_id` (falling back to
`provider_defaults.tts`, then "Channel default"). It is an **instance
reference**, never a provider name written into this view.

## Deliberate exclusions

Accounted for so they do not read as drift:

- **`s1-autogen`** and its `.txt` / `.t` / `.d` children — the prototype's
  "Auto-generate on save" switch. `Narration` has no such field and forbids
  extras, so the switch would have nowhere to persist. It is unstyled rather
  than faked.
- **`s1-card:focus-visible`** — the prototype groups it with `button:focus-visible`
  and gives it the standard ring. The card *is* a button here, so
  `shared.css`'s `:focus-visible` already carries those two declarations.
- **`s1-doc-foot`'s Use in Batch and Duplicate** — Production's create panel
  reads only `?create=1` from the route, and duplication has no endpoint; both
  are features, not styling. The footer keeps the prototype's spacer and layout
  with Save alone.
- ~~**The channel avatar's colour.**~~ Answered in step 6.4: `cavatar` became
  the shared `.ch-avatar`, tinted from a hash of the channel id so the same
  channel reads the same here, in a job row and in the Channels rail.
- **The 820px breakpoint** hides the rail in the prototype, whose library also
  lives in a modal. There is no modal here, so the rail stacks above the
  document instead of disappearing.
- **`s1-doc-body.single`** is a modifier the prototype spells as an inline
  `grid-template-columns:1fr` on the create flow. It also caps the measure,
  which the prototype does not, so a one-column form stays readable on a wide
  display. `.s1-doc-body` itself keeps the prototype's declarations.

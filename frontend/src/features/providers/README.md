# providers

Ported from V2 `frontend/features/providers/` in step 2.1: the provider catalog
store and schema-driven settings forms.

Step 3.2 makes all of it **instance**-aware: the catalog store, selector, and
settings forms key on instance id; option-source context carries `instance` so
two bindings of one type resolve their own model and voice lists.

Secrets are write-only: the API never echoes one back, so these forms must never
try to display a stored credential.

Plan step 5.2 replaces the settings-card index with the prototype's provider
rail/detail surface. `ProviderSimulationConsole` calls the platform-owned
`/simulate` fixture for the selected instance; that endpoint never invokes the
provider or a configured transport and returns only dummy request/response data.

## Step 6.5 — the prototype's `pv-*` family

`ProvidersSettingsPage.vue` is the prototype's whole screen: `pvview` grid,
`pv-rail` (head, sub, list, foot), `pv-litem` with its `pv-ic` plate, `cap`,
`pn`/`kind` and `pv-status-dot`, then `pv-detail` — `pv-hero` with `pv-badge`,
`pv-link`, `pv-meta`, `pv-cfg` fields, `pv-static`, `pv-test-out` and the
sticky `pv-foot`. `ProviderSimulationConsole.vue` owns `pv-sim` and everything
under it. The `st-*` dot states and the `pv-badge` states are shared between
the two views by class name, exactly as in the prototype.

Four things are deliberately **not** ported, because the app has no fact for
them rather than because they were missed:

- **`.pv-enable` and the enable toggle.** A provider is discovered or excluded
  (contracts §21.4). There is no enable flag for a switch to write, and adding
  one would invent a third availability axis.
- **`.pv-secret` / `.pv-secret .pv-input`.** The prototype renders a masked key
  inline with a Reveal button. Stored secrets are never returned to the browser
  here, so this pane has nothing to render and no Reveal to offer; settings are
  edited in `ProviderSettingsModal` instead.
- **`.pv-sim-step.active`.** It paces a fabricated multi-second animation over
  steps the prototype already has. One real round trip either returned or it
  did not; the ported console shows `run` while the request is in flight and
  `done` steps once it is not.
- **The prototype's per-provider colour, icon, tagline and activity counters.**
  Those are hardcoded provider data. The tagline is the manifest `description`,
  the counters are the catalog's own answers about the binding, the glyph is
  the capability's initial, and the plate colour is derived from the domain's
  position in the sorted domain list. A new provider still renders with no Vue
  edit (§26).

`connect` / `disconnect` are likewise absent: `Test connection` runs the
existing health probe and `pv-test-out` reports it. Availability and health
stay the two separate axes the store keeps them as (§21.5) — nothing in the
rail triggers I/O to decide which dot to draw.

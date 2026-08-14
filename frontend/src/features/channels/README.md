# channels

The Channel Profile editor (step 1.3).

| Surface | Role |
|---|---|
| `ChannelsPage.vue` | List + create + delete; auto-seeds starters from niche presets |
| `ChannelEditor.vue` | Full ChannelProfile form with structured pattern editor |
| `api.js` | CRUD against `/api/channels`; logo via `/api/workflow/branding` |

Logo upload goes through the managed-branding endpoint — never a
browser-supplied filesystem path. Channels select provider **instance ids**;
they never carry credentials or duplicated account configuration.

`visual_direction.pattern` is edited as a structured role → shot-direction map,
not a free-text box.


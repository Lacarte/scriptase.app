<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useUndoableAction } from '@/shared/composables/useUndoableAction.js'

import { createChannel, deleteChannel, listChannels, seedChannels } from './api.js'

const router = useRouter()
const undoable = useUndoableAction()

const channels = ref([])
/**
 * Ids hidden by an open Undo window (step 0.3). The row leaves the list at
 * once, but nothing has reached the backend until the window closes.
 */
const pendingDelete = ref([])
const starterMappings = ref({})
const seedInfo = ref(null)
const loading = ref(true)
const error = ref('')
const filter = ref('')
const busy = ref(false)

const starterIds = computed(() => new Set(Object.values(starterMappings.value || {})))

const visible = computed(() =>
  channels.value.filter((ch) => !pendingDelete.value.includes(ch.id)),
)

const filtered = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) return visible.value
  return visible.value.filter((ch) => {
    const hay = `${ch.name} ${ch.niche || ''} ${ch.style || ''} ${ch.id}`.toLowerCase()
    return hay.includes(q)
  })
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const data = await listChannels({ limit: 500 })
    channels.value = data.channels || []
    starterMappings.value = data.starter_mappings || {}
    seedInfo.value = data.seed || null
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  busy.value = true
  error.value = ''
  try {
    const { channel } = await createChannel({ name: 'New Channel' })
    await router.push({ name: 'channel-edit', params: { id: channel.id } })
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    busy.value = false
  }
}

async function onSeed() {
  busy.value = true
  error.value = ''
  try {
    seedInfo.value = await seedChannels(false)
    await refresh()
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    busy.value = false
  }
}

function onDelete(ch) {
  error.value = ''
  pendingDelete.value = [...pendingDelete.value, ch.id]
  const restore = () => {
    pendingDelete.value = pendingDelete.value.filter((id) => id !== ch.id)
  }
  undoable.run({
    message: `Deleted channel “${ch.name}”`,
    async commit() {
      await deleteChannel(ch.id, ch.version)
      // Refresh first: dropping the pending id before the list reloads would
      // flash the deleted row back for a frame.
      await refresh()
      restore()
    },
    undo: restore,
    onError(err) {
      error.value = err?.message || String(err)
    },
  })
}

function open(ch) {
  router.push({ name: 'channel-edit', params: { id: ch.id } })
}

onMounted(refresh)
</script>

<template>
  <section class="channels-page">
    <header class="page-header">
      <div>
        <h1>Channels</h1>
        <p class="lede">
          Reusable brand profiles. Starter Channels are migrated from niche presets;
          each is fully editable. Provider credentials never live here — only instance
          references (step 3.x).
        </p>
      </div>
      <div class="actions">
        <button type="button" class="ghost" :disabled="busy || loading" @click="onSeed">
          Reseed starters
        </button>
        <button type="button" class="primary" :disabled="busy" @click="onCreate">
          New Channel
        </button>
      </div>
    </header>

    <div v-if="seedInfo" class="seed-banner">
      Starters: {{ seedInfo.total_presets ?? '—' }} presets ·
      {{ seedInfo.created ?? 0 }} created ·
      {{ seedInfo.skipped ?? 0 }} already present
    </div>

    <div class="toolbar">
      <input
        v-model="filter"
        type="search"
        placeholder="Filter by name, niche, style…"
        class="search"
        aria-label="Filter channels"
        data-shortcut-search
      />
      <span class="count">{{ filtered.length }} / {{ channels.length }}</span>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="muted">Loading channels…</p>

    <ul v-else class="channel-list">
      <li
        v-for="ch in filtered"
        :key="ch.id"
        class="channel-card"
        @click="open(ch)"
      >
        <!-- The whole card is clickable for a mouse, but the accessible name
             and the keyboard path belong to one real control (step 0.3). Its
             click bubbles to the row, so Enter and Space need no handler. -->
        <button type="button" class="card-main">
          <img
            v-if="ch.thumbnail_asset_id"
            class="channel-thumbnail"
            :src="`/output/${ch.thumbnail_asset_id}`"
            alt=""
          />
          <span class="card-copy">
          <strong>{{ ch.name }}</strong>
          <span class="meta">
            <code>{{ ch.id }}</code>
            <span v-if="starterIds.has(ch.id)" class="badge">starter</span>
            <span v-if="ch.niche">· {{ ch.niche }}</span>
            <span v-if="ch.style">· {{ ch.style }}</span>
          </span>
          </span>
        </button>
        <div class="card-side" @click.stop>
          <span class="version">v{{ ch.version }}</span>
          <button
            type="button"
            class="danger ghost"
            :disabled="busy"
            :aria-label="`Delete channel ${ch.name}`"
            @click="onDelete(ch)"
          >
            Delete
          </button>
        </div>
      </li>
      <li v-if="!filtered.length" class="empty muted">No channels match.</li>
    </ul>
  </section>
</template>

<style scoped>
/* Channels index — the prototype's channel rail rendered as a full-width
   page. Every surface is a raised panel lit from above; the accent duotone
   appears on the primary action and focus ring only, and every readout
   (id, version, count) is mono. */

.channels-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 20px 48px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}

h1 {
  margin: 0 0 5px;
  font-family: var(--display);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: var(--text);
}

.lede {
  margin: 0;
  max-width: 42rem;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.5;
}

.actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* The template carries bare .primary / .ghost / .danger rather than .btn,
   so the shared button primitive is restated here on the element itself. */
button {
  border: 1px solid var(--line);
  background: var(--panel-grad);
  color: var(--text);
  border-radius: var(--r-s);
  padding: 9px 14px;
  font-family: var(--body);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  white-space: nowrap;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.16s, border-color 0.16s, color 0.14s,
    box-shadow 0.16s, transform 0.12s var(--ease-spring);
}

button:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  transform: translateY(-1px);
  box-shadow: var(--hairline-top), 0 4px 12px -4px rgba(0, 0, 0, 0.5);
}

button:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--hairline-top), inset 0 2px 4px rgba(0, 0, 0, 0.35);
}

button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

button.primary {
  background: var(--accent-grad);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast);
}

button.primary:hover:not(:disabled) {
  filter: brightness(1.07) saturate(1.05);
  border-color: transparent;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
}

button.ghost {
  background: transparent;
  box-shadow: none;
}

button.ghost:hover:not(:disabled) {
  background: var(--panel);
  box-shadow: var(--hairline-top);
}

/* Ordered after .ghost so the danger wash wins on the `.danger.ghost` row. */
button.danger {
  color: var(--fail);
  border-color: var(--fail-line);
}

button.danger:hover:not(:disabled) {
  background: var(--fail-dim);
  border-color: var(--fail-line-2);
}

/* The seed summary is informational, not accented — the `run` blue. */
.seed-banner {
  background: var(--run-dim);
  border: 1px solid var(--run-line);
  border-radius: var(--r-s);
  padding: 11px 13px;
  font-size: 12.5px;
  line-height: 1.55;
  margin-bottom: 16px;
  color: var(--run);
}

.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}

/* There is no global `.search` — `.search-field` is the container primitive,
   and this is a bare <input>. Styled as a control, not a wrapper. */
.search {
  flex: 1;
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
  padding: 9px 11px;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.search::placeholder {
  color: var(--faint);
}

.search:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.count {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
  flex: none;
}

.channel-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.channel-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  padding: 12px 16px;
  cursor: pointer;
  transition: border-color 0.14s, background 0.14s, box-shadow 0.14s;
}

.channel-card:hover {
  border-color: var(--line-2);
  background: var(--panel-grad2);
}

/* A real button for semantics, with none of the chrome of one: the card it
   sits in is the surface, so it must stay invisible until focused. */
.card-main {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1 1 auto;
  padding: 0;
  border: none;
  border-radius: 0;
  background: none;
  box-shadow: none;
  text-align: left;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.card-main:hover:not(:disabled) {
  background: none;
  border: none;
  transform: none;
  box-shadow: none;
}

.card-copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 0;
}

.channel-thumbnail {
  width: 64px;
  height: 40px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg-2);
  object-fit: cover;
}

.card-main strong {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  color: var(--text);
}

.meta {
  color: var(--muted);
  font-size: 11.5px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

/* A recessed well for the identity readout. */
.meta code {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0;
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  padding: 1px 6px;
  border-radius: 5px;
}

/* Shaped like the global `.badge` it collides with; a starter marker is
   informational, so it takes the `sched` violet, never the accent. */
.badge {
  display: inline-flex;
  align-items: center;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 20px;
  white-space: nowrap;
  color: var(--sched);
  background: var(--sched-dim);
  box-shadow: inset 0 0 0 1px var(--sched-line);
}

.card-side {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.card-side button {
  padding: 6px 10px;
  font-size: 12px;
  border-radius: 6px;
}

.version {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}

.error {
  background: var(--fail-dim);
  border: 1px solid var(--fail-line);
  border-radius: var(--r-s);
  color: var(--fail-text);
  padding: 11px 13px;
  font-size: 12.5px;
  line-height: 1.55;
}

.muted {
  color: var(--muted);
}

.empty {
  padding: 24px;
  text-align: center;
  font-size: 12.5px;
}

/* Step 0.3 — the header's two nowrap buttons and the channel card's action
   column both need their own line once the viewport is phone-width. */
@media (max-width: 820px) {
  .page-header {
    flex-direction: column;
  }

  .actions {
    flex-wrap: wrap;
  }

  .channel-card {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .card-side {
    justify-content: space-between;
  }
}
</style>

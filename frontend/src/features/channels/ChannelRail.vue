<script setup>
/**
 * The prototype's `ch-rail`: the channel list that stands beside the detail
 * pane in both Channels routes (step 6.4). It is a component rather than
 * markup in each page so the list, its search and its deferred delete exist
 * once — the two routes differ only in what fills `.ch-detail`.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useUndoableAction } from '@/shared/composables/useUndoableAction.js'
import {
  channelAvatarLabel,
  channelAvatarStyle,
  PLATFORM_COLORS,
} from '@/shared/utils/channelIdentity.js'
import { listJobs } from '@/features/production/api.js'

import { createChannel, deleteChannel, listChannels, seedChannels } from './api.js'

const route = useRoute()
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
const jobCounts = ref({})

const selectedId = computed(() => route.params.id || '')

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

async function refresh({ silent = false } = {}) {
  if (!silent) loading.value = true
  error.value = ''
  try {
    const [data, jobs] = await Promise.all([
      listChannels({ limit: 500 }),
      listJobs({ limit: 500 }).catch(() => ({ jobs: [] })),
    ])
    channels.value = data.channels || []
    starterMappings.value = data.starter_mappings || {}
    seedInfo.value = data.seed || null
    const counts = {}
    for (const job of jobs.jobs || []) {
      const id = job.channel_id
      if (!id) continue
      counts[id] = (counts[id] || 0) + 1
    }
    jobCounts.value = counts
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    if (!silent) loading.value = false
  }
}

/**
 * Keep a rail row aligned with an editor save without blanking the list.
 * The editor and rail share a screen now (step 6.4); a silent list refresh
 * after every Save would flash, and a stale `version` makes Undo-delete 409.
 */
function upsertSummary(summary) {
  if (!summary?.id) return
  const index = channels.value.findIndex((ch) => ch.id === summary.id)
  if (index >= 0) {
    channels.value[index] = { ...channels.value[index], ...summary }
    return
  }
  channels.value = [summary, ...channels.value]
}

async function onCreate() {
  busy.value = true
  error.value = ''
  try {
    const { channel } = await createChannel({ name: 'New Channel' })
    // Creating while already on the editor reuses this rail instance — the
    // route param changes but onMounted does not re-run, so the new row
    // must be inserted here or it never appears.
    upsertSummary({
      id: channel.id,
      name: channel.name,
      version: channel.version,
      niche: channel.content?.niche || '',
      style: channel.visual_direction?.style || '',
      thumbnail_asset_id: channel.branding?.thumbnail_asset_id || null,
      track_count: channel.music_library?.tracks?.length || 0,
      created_at: channel.created_at,
      updated_at: channel.updated_at,
    })
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
      // Standing on the deleted channel's editor would 404 on the next load.
      if (selectedId.value === ch.id) await router.push({ name: 'channels' })
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

defineExpose({ refresh, upsertSummary })
</script>

<template>
  <aside class="ch-rail">
    <div class="ch-rail-head">
      <div class="ch-rail-title">
        <h2>Channels</h2>
        <button type="button" class="btn primary sm" :disabled="busy" @click="onCreate">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
          New
        </button>
      </div>
      <div class="ch-rail-sub">
        Identity &amp; production defaults inherited by every job.
      </div>
      <label class="search-field rail-search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
        <span class="sr-only">Filter channels</span>
        <input
          v-model="filter"
          type="search"
          placeholder="Filter by name, niche, style…"
          aria-label="Filter channels"
          data-shortcut-search
        />
      </label>
    </div>

    <p v-if="error" class="banner error rail-error" role="alert">{{ error }}</p>

    <div class="ch-list">
      <p v-if="loading" class="rail-state">Loading channels…</p>
      <template v-else>
        <!-- The whole row is clickable for a mouse, but the accessible name
             and the keyboard path belong to one real control (step 0.3). Its
             click bubbles to the row, so Enter and Space need no handler. -->
        <div
          v-for="ch in filtered"
          :key="ch.id"
          class="ch-litem"
          :class="{ sel: selectedId === ch.id }"
          @click="open(ch)"
        >
          <button type="button" class="litem-main">
            <span class="lav ch-avatar" :style="channelAvatarStyle(ch)">
              {{ channelAvatarLabel(ch) }}
            </span>
            <span class="lmeta">
              <span class="lname">{{ ch.name }}</span>
              <span class="lrow">
                <span v-if="ch.platforms?.length" class="lplats">
                  <span
                    v-for="plat in ch.platforms"
                    :key="plat"
                    class="plat-ic"
                    :style="{ background: PLATFORM_COLORS[plat] || 'var(--raise)' }"
                  >{{ plat[0] }}</span>
                </span>
                <span v-else-if="starterIds.has(ch.id)" class="lstarter">starter</span>
                <template v-else>
                  <span class="lid">{{ ch.id }}</span>
                </template>
                <span class="dot-sep" />
                {{ jobCounts[ch.id] || 0 }} videos
              </span>
            </span>
          </button>
          <button
            type="button"
            class="danger litem-x"
            :disabled="busy"
            :aria-label="`Delete channel ${ch.name}`"
            @click.stop="onDelete(ch)"
          >✕</button>
        </div>
        <p v-if="!filtered.length" class="rail-state">No channels match.</p>
      </template>
    </div>

    <div class="ch-rail-foot">
      <span class="counts">
        {{ filtered.length }} / {{ channels.length }}
        <template v-if="seedInfo">
          <span class="dot-sep" />
          {{ seedInfo.total_presets ?? '—' }} presets
        </template>
      </span>
      <button type="button" class="btn xs ghost" :disabled="busy || loading" @click="onSeed">
        Reseed starters
      </button>
    </div>
  </aside>
</template>

<style scoped>
/* The prototype's `.ch-rail` — a column lit from the top, ruled off from the
   detail pane. Its literal rgba values are the named tokens here. */
.ch-rail {
  border-right: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, .02), rgba(255, 255, 255, 0) 180px),
    linear-gradient(180deg, var(--bg-2), var(--bg));
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.ch-rail-head { padding: 18px 20px 15px; border-bottom: 1px solid var(--line-soft); }
.ch-rail-title { display: flex; align-items: center; justify-content: space-between; }
.ch-rail-title h2 { margin: 0; font-family: var(--display); font-size: 15px; font-weight: 600; }
.ch-rail-sub { color: var(--muted); font-size: 12px; margin-top: 8px; line-height: 1.45; }

/* The prototype's rail has no search. 81 starter channels make it necessary,
   so it is the shared field primitive rather than a new `ch-` class. */
.rail-search { margin-top: 12px; }

.rail-error { margin: 10px 10px 0; }
.rail-state { padding: 28px 14px; text-align: center; color: var(--muted); font-size: 12.5px; }

.ch-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.ch-litem {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: var(--r-s);
  padding: 11px 12px;
  cursor: pointer;
  flex: none;
  display: flex;
  align-items: center;
  gap: 11px;
  box-shadow: var(--hairline-top);
  transition: border-color .16s, background .16s, box-shadow .16s,
    transform .16s var(--ease-spring);
}

.ch-litem:hover { border-color: var(--line-2); background: var(--panel-2); transform: translateY(-1px); }

/* The prototype's premium pass gives the selected row a duotone wash and a
   soft lift rather than the flat accent fill of its base rule. */
.ch-litem.sel {
  border-color: var(--accent-line-2);
  background: var(--accent-fill-2);
  box-shadow: var(--hairline-top), var(--accent-cast-md);
}

/* A real button for semantics with none of the chrome of one — the row it
   sits in is the surface. */
.litem-main {
  display: flex;
  align-items: center;
  gap: 11px;
  flex: 1;
  min-width: 0;
  padding: 0;
  border: none;
  background: none;
  box-shadow: none;
  text-align: left;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.ch-litem .lav { width: 34px; height: 34px; border-radius: 9px; font-size: 13px; }
.ch-litem .lmeta { min-width: 0; flex: 1; }
.ch-litem .lname {
  display: block;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -.1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ch-litem .lrow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  min-width: 0;
}
.ch-litem .lid { flex: none; }
.ch-litem .ltrunc { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ch-litem .lplats { display: inline-flex; gap: 3px; }
/* `.plat-ic` is a shared primitive in styles/shared.css — three surfaces draw
   it and only a global rule reaches all of them. */

/* A starter marker is informational, so it takes the `sched` violet and
   never the accent — the accent means "selected" in this rail. */
.lstarter {
  flex: none;
  padding: 1px 6px;
  border-radius: 20px;
  font-size: 9px;
  letter-spacing: .4px;
  text-transform: uppercase;
  color: var(--sched);
  background: var(--sched-dim);
  box-shadow: inset 0 0 0 1px var(--sched-line);
}

/* Shaped like the prototype's `.ch-asset-x`: a quiet square that only turns
   red under the pointer. Delete is deferred with Undo, never a confirm. */
.litem-x {
  flex: none;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: var(--raise);
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
  opacity: 0;
  transition: opacity .12s, background .12s, color .12s;
}

.ch-litem:hover .litem-x,
.litem-x:focus-visible { opacity: 1; }
.litem-x:hover:not(:disabled) { background: var(--fail-dim); color: var(--fail); }

/* No `ch-rail-foot` in the prototype — its channel counts live on the hero it
   cannot show here. Shaped like `s1-rail-foot`, which is the same idea. */
.ch-rail-foot {
  padding: 10px 14px;
  border-top: 1px solid var(--line-soft);
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--muted);
}

.ch-rail-foot .counts { display: flex; align-items: center; gap: 7px; flex: 1; }

.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
</style>

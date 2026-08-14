<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { createChannel, deleteChannel, listChannels, seedChannels } from './api.js'

const router = useRouter()

const channels = ref([])
const starterMappings = ref({})
const seedInfo = ref(null)
const loading = ref(true)
const error = ref('')
const filter = ref('')
const busy = ref(false)

const starterIds = computed(() => new Set(Object.values(starterMappings.value || {})))

const filtered = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) return channels.value
  return channels.value.filter((ch) => {
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

async function onDelete(ch) {
  if (!window.confirm(`Delete channel “${ch.name}”?`)) return
  busy.value = true
  error.value = ''
  try {
    await deleteChannel(ch.id, ch.version)
    await refresh()
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    busy.value = false
  }
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
        <div class="card-main">
          <strong>{{ ch.name }}</strong>
          <span class="meta">
            <code>{{ ch.id }}</code>
            <span v-if="starterIds.has(ch.id)" class="badge">starter</span>
            <span v-if="ch.niche">· {{ ch.niche }}</span>
            <span v-if="ch.style">· {{ ch.style }}</span>
          </span>
        </div>
        <div class="card-side" @click.stop>
          <span class="version">v{{ ch.version }}</span>
          <button type="button" class="danger ghost" :disabled="busy" @click="onDelete(ch)">
            Delete
          </button>
        </div>
      </li>
      <li v-if="!filtered.length" class="empty muted">No channels match.</li>
    </ul>
  </section>
</template>

<style scoped>
.channels-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 1.5rem 1.25rem 3rem;
  font-family: "Segoe UI", system-ui, sans-serif;
  color: #e8eaed;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  margin-bottom: 1rem;
}

h1 {
  margin: 0 0 0.35rem;
  font-size: 1.6rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.lede {
  margin: 0;
  max-width: 42rem;
  color: #9aa0a6;
  font-size: 0.95rem;
  line-height: 1.45;
}

.actions {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}

button {
  border: 1px solid #3c4043;
  background: #2d2e30;
  color: #e8eaed;
  border-radius: 8px;
  padding: 0.45rem 0.85rem;
  font-size: 0.9rem;
  cursor: pointer;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

button.primary {
  background: #8ab4f8;
  border-color: #8ab4f8;
  color: #202124;
  font-weight: 600;
}

button.ghost {
  background: transparent;
}

button.danger {
  color: #f28b82;
  border-color: #5f3a38;
}

.seed-banner {
  background: #1e3a5f;
  border: 1px solid #3c5a80;
  border-radius: 8px;
  padding: 0.55rem 0.85rem;
  font-size: 0.85rem;
  margin-bottom: 1rem;
  color: #c2d7f7;
}

.toolbar {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: 0.75rem;
}

.search {
  flex: 1;
  background: #1f1f1f;
  border: 1px solid #3c4043;
  border-radius: 8px;
  color: #e8eaed;
  padding: 0.5rem 0.75rem;
  font-size: 0.95rem;
}

.count {
  color: #9aa0a6;
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

.channel-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.channel-card {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  background: #1a1a1c;
  border: 1px solid #2d2e30;
  border-radius: 10px;
  padding: 0.75rem 1rem;
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}

.channel-card:hover {
  border-color: #5f6368;
  background: #202124;
}

.card-main {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.card-main strong {
  font-size: 1rem;
}

.meta {
  color: #9aa0a6;
  font-size: 0.82rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
}

.meta code {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.78rem;
  background: #2d2e30;
  padding: 0.05rem 0.35rem;
  border-radius: 4px;
}

.badge {
  background: #3c4043;
  color: #fdd663;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  font-weight: 600;
}

.card-side {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-shrink: 0;
}

.version {
  color: #9aa0a6;
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.error {
  color: #f28b82;
  background: #3c1f1e;
  border: 1px solid #5f3a38;
  border-radius: 8px;
  padding: 0.6rem 0.85rem;
}

.muted {
  color: #9aa0a6;
}

.empty {
  padding: 1.5rem;
  text-align: center;
}
</style>

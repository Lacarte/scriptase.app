<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/shared/api/client.js'
import { useWorkflowStore } from '../stores/workflow.js'

const emit = defineEmits(['close'])
const store = useWorkflowStore()
const serverSchedules = ref([])
const loading = ref(false)
const error = ref('')
const schedules = computed(() => Array.isArray(store.settings.schedules) ? store.settings.schedules : [])

function nextId() {
  const used = new Set(schedules.value.map((item) => item.id))
  let number = 1
  while (used.has(`sch_${number}`)) number += 1
  return `sch_${number}`
}

function addSchedule() {
  store.setSchedules([...schedules.value, { id: nextId(), cron: '0 9 * * *', enabled: true }])
}

function updateSchedule(index, patch) {
  store.setSchedules(schedules.value.map((item, position) => (
    position === index ? { ...item, ...patch } : item
  )))
}

function removeSchedule(index) {
  store.setSchedules(schedules.value.filter((_, position) => position !== index))
}

function nextFire(id) {
  const item = serverSchedules.value.find((schedule) => schedule.id === id)
  if (!item?.next_fire_at) return 'Disabled'
  return new Date(item.next_fire_at).toLocaleString()
}

async function refresh() {
  serverSchedules.value = []
  error.value = ''
  if (!store.workflowId || store.dirty) return
  loading.value = true
  try {
    const data = await api.get(`/api/workflows/${encodeURIComponent(store.workflowId)}/schedules`)
    serverSchedules.value = data.schedules || []
  } catch (err) {
    error.value = err?.message || 'Could not load schedule times'
  } finally {
    loading.value = false
  }
}

watch(() => [store.workflowId, store.updatedAt, store.dirty], refresh)
onMounted(refresh)
</script>

<template>
  <div class="schedule-backdrop" @click.self="emit('close')">
    <section class="schedule-dialog" role="dialog" aria-modal="true" aria-labelledby="schedule-title">
      <header>
        <div>
          <h2 id="schedule-title">Scheduled runs</h2>
          <p>Five-field cron expressions run in UTC. Missed times catch up once, using the latest fire.</p>
        </div>
        <button class="close" aria-label="Close scheduled runs" @click="emit('close')">×</button>
      </header>

      <div v-if="!schedules.length" class="empty">No schedules configured.</div>
      <div v-for="(schedule, index) in schedules" :key="schedule.id" class="schedule-row">
        <label class="enabled">
          <input type="checkbox" :checked="schedule.enabled" @change="updateSchedule(index, { enabled: $event.target.checked })" />
          <span>Enabled</span>
        </label>
        <label class="cron">
          <span>Cron (UTC)</span>
          <input :value="schedule.cron" placeholder="0 9 * * *" @change="updateSchedule(index, { cron: $event.target.value.trim() })" />
        </label>
        <div class="next">
          <span>Next fire</span>
          <strong v-if="loading">Calculating…</strong>
          <strong v-else-if="store.dirty">Save to calculate</strong>
          <strong v-else>{{ nextFire(schedule.id) }}</strong>
        </div>
        <button class="remove" :aria-label="`Remove ${schedule.id}`" @click="removeSchedule(index)">Remove</button>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <footer>
        <button class="add" :disabled="schedules.length >= 16" @click="addSchedule">Add schedule</button>
        <button class="done" @click="emit('close')">Done</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.schedule-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 7, 13, .72); }
.schedule-dialog { width: min(720px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto; border: 1px solid var(--border); border-radius: 13px; padding: 18px; color: var(--text); background: var(--bg-darkest); box-shadow: 0 24px 70px rgba(0,0,0,.55); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
h2 { margin: 0; font-size: 17px; } p { margin: 4px 0 0; color: var(--text-muted); font-size: 11px; }
.close, .remove, .add, .done { border: 1px solid var(--border); border-radius: 7px; padding: 7px 10px; color: var(--text-secondary); background: rgba(20,34,51,.78); cursor: pointer; }
.close { border: 0; padding: 2px 7px; font-size: 22px; background: transparent; }
.schedule-row { display: grid; grid-template-columns: 82px minmax(190px, 1fr) minmax(160px, 1fr) auto; align-items: end; gap: 12px; margin-top: 15px; padding: 12px; border: 1px solid var(--border); border-radius: 9px; }
label, .next { display: grid; gap: 5px; color: var(--text-muted); font-size: 10px; }
.enabled { display: flex; align-items: center; padding-bottom: 8px; }
.cron input { min-width: 0; border: 1px solid var(--border); border-radius: 6px; padding: 8px; color: var(--text); background: var(--bg-dark); font: 12px ui-monospace, monospace; }
.next strong { min-height: 28px; color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.remove { color: #fda4af; }.empty { margin: 18px 0; color: var(--text-muted); font-size: 12px; }
.error { color: #fb7185; } footer { margin-top: 16px; }.done { color: #062318; border-color: var(--accent); background: var(--accent); }
@media (max-width: 650px) { .schedule-row { grid-template-columns: 1fr 1fr; }.cron { grid-column: 1 / -1; } }
</style>

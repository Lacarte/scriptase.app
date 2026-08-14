<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '@/shared/api/client.js'
import { useWorkflowStore } from '../stores/workflow.js'

const emit = defineEmits(['close', 'seen'])
const store = useWorkflowStore()
const defaults = {
  on_completion: false,
  on_failure: false,
  windows_toast: false,
  webhook: { enabled: false, url: '' },
}
const records = ref([])
const loading = ref(false)
const error = ref('')
const notifications = computed(() => ({
  ...defaults,
  ...(store.settings.notifications || {}),
  webhook: { ...defaults.webhook, ...(store.settings.notifications?.webhook || {}) },
}))

function update(patch) {
  store.setNotifications({ ...notifications.value, ...patch })
}

function updateWebhook(patch) {
  update({ webhook: { ...notifications.value.webhook, ...patch } })
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString() : ''
}

async function refresh() {
  records.value = []
  if (!store.workflowId) return
  loading.value = true
  error.value = ''
  try {
    const query = encodeURIComponent(store.workflowId)
    const data = await api.get(`/api/workflow/notifications?workflow_id=${query}&limit=100`)
    records.value = data.notifications || []
    if (data.unseen) {
      await api.post('/api/workflow/notifications/seen', { body: { workflow_id: store.workflowId } })
      records.value = records.value.map((item) => ({ ...item, seen: true }))
    }
    emit('seen', 0)
  } catch (err) {
    error.value = err?.message || 'Could not load notifications'
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="notification-backdrop" @click.self="emit('close')">
    <section class="notification-dialog" role="dialog" aria-modal="true" aria-labelledby="notification-title">
      <header>
        <div>
          <h2 id="notification-title">Run notifications</h2>
          <p>Choose which terminal run outcomes create notifications and where they are delivered.</p>
        </div>
        <button class="close" aria-label="Close run notifications" @click="emit('close')">×</button>
      </header>

      <div class="settings-grid">
        <label><input type="checkbox" :checked="notifications.on_completion" @change="update({ on_completion: $event.target.checked })" /> Successful runs</label>
        <label><input type="checkbox" :checked="notifications.on_failure" @change="update({ on_failure: $event.target.checked })" /> Failed runs</label>
        <label><input type="checkbox" :checked="notifications.windows_toast" @change="update({ windows_toast: $event.target.checked })" /> Windows toast</label>
        <label><input type="checkbox" :checked="notifications.webhook.enabled" @change="updateWebhook({ enabled: $event.target.checked })" /> Outbound webhook</label>
      </div>
      <label class="webhook-url">
        <span>Notification webhook URL</span>
        <input :disabled="!notifications.webhook.enabled" :value="notifications.webhook.url" placeholder="https://example.com/workflow-events" @change="updateWebhook({ url: $event.target.value.trim() })" />
      </label>
      <p class="save-state">{{ store.dirty ? 'Save the workflow to apply notification changes.' : 'Saved notification settings are active.' }}</p>

      <div class="history-head"><strong>Notification history</strong><button :disabled="loading" @click="refresh">Refresh</button></div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-else-if="loading" class="empty">Loading…</p>
      <p v-else-if="!records.length" class="empty">No run notifications yet.</p>
      <ul v-else class="notification-list">
        <li v-for="item in records" :key="item.notification_id" :class="item.outcome">
          <span class="outcome" aria-hidden="true">{{ item.outcome === 'success' ? '✓' : '!' }}</span>
          <div><strong>{{ item.message }}</strong><small>{{ formatTime(item.created_at) }} · {{ item.execution_id }}</small></div>
        </li>
      </ul>
      <footer><button class="done" @click="emit('close')">Done</button></footer>
    </section>
  </div>
</template>

<style scoped>
.notification-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2,7,13,.72); }
.notification-dialog { width: min(720px, calc(100vw - 32px)); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid var(--border); border-radius: 13px; padding: 18px; color: var(--text); background: var(--bg-darkest); box-shadow: 0 24px 70px rgba(0,0,0,.55); }
header, .history-head, footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { margin: 0; font-size: 17px; } p { margin: 4px 0 0; color: var(--text-muted); font-size: 11px; }
button { border: 1px solid var(--border); border-radius: 7px; padding: 7px 10px; color: var(--text-secondary); background: rgba(20,34,51,.78); cursor: pointer; }
.close { border: 0; padding: 2px 7px; font-size: 22px; background: transparent; }.settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 18px 0 12px; }
.settings-grid label { color: var(--text-secondary); font-size: 12px; }.webhook-url { display: grid; gap: 6px; color: var(--text-muted); font-size: 10px; }
.webhook-url input { border: 1px solid var(--border); border-radius: 6px; padding: 9px; color: var(--text); background: var(--bg-dark); font: 12px ui-monospace, monospace; }.webhook-url input:disabled { opacity: .5; }
.save-state { margin-top: 8px; }.history-head { margin-top: 22px; }.notification-list { display: grid; gap: 8px; margin: 12px 0 0; padding: 0; list-style: none; }
.notification-list li { display: flex; gap: 10px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; }.notification-list li.success { border-left: 3px solid var(--accent); }.notification-list li.failure { border-left: 3px solid #fb7185; }
.notification-list .outcome { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; background: rgba(255,255,255,.06); }.notification-list div { display: grid; gap: 3px; font-size: 12px; }.notification-list small { color: var(--text-muted); }
.empty, .error { margin: 14px 0; }.error { color: #fb7185; } footer { justify-content: flex-end; margin-top: 16px; }.done { color: #062318; border-color: var(--accent); background: var(--accent); }
@media (max-width: 540px) { .settings-grid { grid-template-columns: 1fr; } }
</style>

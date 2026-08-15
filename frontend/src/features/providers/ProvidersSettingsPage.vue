<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { apiErrorText } from '@/shared/api/errors.js'
import ProviderConfigurator from './components/ProviderConfigurator.vue'
import ProviderSettingsForm from './components/ProviderSettingsForm.vue'
import ProviderSettingsModal from './components/ProviderSettingsModal.vue'
import { useProviderCatalogStore } from './stores/providerCatalog.js'

defineOptions({ name: 'ProvidersSettingsPage' })

const catalog = useProviderCatalogStore()
const creatingFor = ref('')
const busyKey = ref('')
const error = ref('')
const modal = reactive({ open: false, domain: '', instanceId: '' })
const drafts = reactive({})
const editing = reactive({})

const domains = computed(() =>
  catalog.domainIds.map((id) => ({
    id,
    label: catalog.domainLabel(id),
    providers: catalog.providersFor(id),
    instances: catalog.instancesFor(id),
  })),
)

function draftFor(domain) {
  if (!drafts[domain]) drafts[domain] = { providerType: '', label: '' }
  const draft = drafts[domain]
  if (!draft.providerType) draft.providerType = catalog.providersFor(domain)[0]?.id || ''
  return draft
}

function openSettings(domain, instanceId) {
  modal.domain = domain
  modal.instanceId = instanceId
  modal.open = true
}

async function createInstance(domain) {
  const draft = draftFor(domain)
  if (!draft.providerType) return
  busyKey.value = `create:${domain}`
  error.value = ''
  try {
    const result = await catalog.createInstance(domain, {
      providerType: draft.providerType,
      label: draft.label.trim() || undefined,
    })
    creatingFor.value = ''
    draft.label = ''
    openSettings(domain, result.instance_id)
  } catch (err) {
    error.value = apiErrorText(err, 'Could not create provider instance')
  } finally {
    busyKey.value = ''
  }
}

function beginRename(instance) {
  editing[instance.instance_id] = instance.label
}

async function saveRename(domain, instance) {
  const label = editing[instance.instance_id]?.trim()
  if (!label) return
  busyKey.value = `rename:${domain}:${instance.instance_id}`
  error.value = ''
  try {
    await catalog.renameInstance(domain, instance.instance_id, label)
    delete editing[instance.instance_id]
  } catch (err) {
    error.value = apiErrorText(err, 'Could not rename provider instance')
  } finally {
    busyKey.value = ''
  }
}

async function removeInstance(domain, instance) {
  if (!window.confirm(`Delete “${instance.label}”? Nodes that reference it will need another provider.`)) return
  busyKey.value = `delete:${domain}:${instance.instance_id}`
  error.value = ''
  try {
    await catalog.deleteInstance(domain, instance.instance_id)
  } catch (err) {
    error.value = apiErrorText(err, 'Could not delete provider instance')
  } finally {
    busyKey.value = ''
  }
}

onMounted(() => catalog.loadCatalog())
</script>

<template>
  <section class="settings-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">Settings</p>
        <h1>Provider instances</h1>
        <p>Connect accounts once, then choose the named instance on any provider-capable node.</p>
      </div>
      <button class="secondary" :disabled="catalog.loading" @click="catalog.refresh()">Refresh</button>
    </header>

    <p v-if="error || catalog.error" class="page-error">{{ error || catalog.error }}</p>
    <p v-if="catalog.loading && !catalog.loaded" class="empty">Loading providers…</p>

    <div v-else class="domain-list">
      <article v-for="domain in domains" :key="domain.id" class="domain-card">
        <div class="domain-heading">
          <div>
            <h2>{{ domain.label }}</h2>
            <p>{{ domain.instances.length }} configured instance{{ domain.instances.length === 1 ? '' : 's' }}</p>
          </div>
          <button class="primary" @click="creatingFor = creatingFor === domain.id ? '' : domain.id">
            Add instance
          </button>
        </div>

        <div v-if="creatingFor === domain.id" class="create-row">
          <label>
            Provider type
            <select v-model="draftFor(domain.id).providerType">
              <option v-for="provider in domain.providers" :key="provider.id" :value="provider.id">
                {{ provider.label }}
              </option>
            </select>
          </label>
          <label>
            Instance name
            <input v-model="draftFor(domain.id).label" placeholder="e.g. Client account" @keyup.enter="createInstance(domain.id)" />
          </label>
          <button class="primary" :disabled="busyKey === `create:${domain.id}`" @click="createInstance(domain.id)">
            {{ busyKey === `create:${domain.id}` ? 'Adding…' : 'Add and configure' }}
          </button>
          <button class="secondary" @click="creatingFor = ''">Cancel</button>
        </div>

        <ProviderConfigurator
          v-if="domain.instances.length"
          :domain="domain.id"
          label="Default instance"
          description="Used when a workflow or Channel does not choose an instance explicitly."
          variant="panel"
        />

        <div v-if="domain.instances.length" class="instance-list">
          <div v-for="instance in domain.instances" :key="instance.instance_id" class="instance-row">
            <div class="instance-identity">
              <template v-if="editing[instance.instance_id] !== undefined">
                <input v-model="editing[instance.instance_id]" aria-label="Instance name" @keyup.enter="saveRename(domain.id, instance)" />
              </template>
              <template v-else>
                <strong>{{ instance.label }}</strong>
                <span>{{ instance.provider_type }} · {{ instance.instance_id }}</span>
              </template>
            </div>
            <span v-if="instance.selected" class="default-badge">Default</span>
            <div class="row-actions">
              <template v-if="editing[instance.instance_id] !== undefined">
                <button class="secondary" @click="saveRename(domain.id, instance)">Save name</button>
                <button class="ghost" @click="delete editing[instance.instance_id]">Cancel</button>
              </template>
              <template v-else>
                <button class="secondary" @click="openSettings(domain.id, instance.instance_id)">Configure</button>
                <button class="ghost" @click="beginRename(instance)">Rename</button>
                <button class="danger" :disabled="busyKey.includes(instance.instance_id)" @click="removeInstance(domain.id, instance)">Delete</button>
              </template>
            </div>
          </div>
        </div>
        <p v-else class="empty">No instances configured yet.</p>
      </article>
    </div>

    <ProviderSettingsModal
      v-if="modal.open"
      :visible="modal.open"
      :domain="modal.domain"
      :provider-id="modal.instanceId"
      @close="modal.open = false"
      @saved="modal.open = false"
    >
      <template #form="{ formData, schema, errors: formErrors, domain, providerId }">
        <ProviderSettingsForm
          :model-value="formData"
          :schema="schema"
          :errors="formErrors"
          :domain="domain"
          :provider-id="providerId"
          @update:model-value="(value) => Object.assign(formData, value)"
        />
      </template>
    </ProviderSettingsModal>
  </section>
</template>

<style scoped>
.settings-page { max-width: 1040px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
.page-header, .domain-heading, .instance-row, .create-row { display: flex; align-items: center; gap: 1rem; }
.page-header, .domain-heading { justify-content: space-between; }
.page-header h1 { margin: .15rem 0 .4rem; font: 700 2rem/1.1 var(--font-display, system-ui); }
.page-header p, .domain-heading p { margin: 0; color: var(--text-secondary, #9ca3af); }
.eyebrow { color: var(--accent, #4ecdc4) !important; font-size: .75rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
.domain-list { display: grid; gap: 1rem; margin-top: 1.5rem; }
.domain-card { padding: 1.25rem; background: var(--bg-surface, #181c22); border: 1px solid var(--border, #343a43); border-radius: 12px; }
.domain-heading { padding-bottom: 1rem; }
.domain-heading h2 { margin: 0 0 .2rem; font-size: 1.15rem; }
.domain-heading p { font-size: .82rem; }
.create-row { flex-wrap: wrap; padding: 1rem; margin-bottom: 1rem; border-radius: 8px; background: var(--bg-elevated, #222832); }
.create-row label { display: grid; gap: .35rem; color: var(--text-secondary, #9ca3af); font-size: .75rem; }
input, select { min-width: 180px; padding: .6rem .7rem; color: var(--text, #e5e7eb); background: var(--bg-dark, #11151a); border: 1px solid var(--border, #3f4650); border-radius: 6px; }
.provider-configurator { padding: 1rem 0; border-top: 1px solid var(--border, #343a43); }
.instance-list { border-top: 1px solid var(--border, #343a43); }
.instance-row { min-height: 64px; border-bottom: 1px solid var(--border, #343a43); }
.instance-row:last-child { border-bottom: 0; }
.instance-identity { display: grid; gap: .2rem; flex: 1; min-width: 0; }
.instance-identity span { color: var(--text-secondary, #9ca3af); font-size: .75rem; }
.row-actions { display: flex; gap: .45rem; }
.default-badge { padding: .2rem .5rem; border-radius: 999px; color: var(--accent, #4ecdc4); background: color-mix(in srgb, var(--accent, #4ecdc4) 12%, transparent); font-size: .7rem; }
button { padding: .55rem .75rem; border-radius: 6px; cursor: pointer; }
button:disabled { opacity: .5; cursor: not-allowed; }
.primary { border: 0; color: #07100f; background: var(--accent, #4ecdc4); font-weight: 650; }
.secondary { color: var(--text, #e5e7eb); background: var(--bg-elevated, #252b34); border: 1px solid var(--border, #3f4650); }
.ghost { color: var(--text-secondary, #9ca3af); background: transparent; border: 1px solid transparent; }
.danger { color: #f87171; background: transparent; border: 1px solid rgba(248, 113, 113, .35); }
.page-error { padding: .75rem; color: #f87171; background: rgba(248, 113, 113, .08); border: 1px solid rgba(248, 113, 113, .25); border-radius: 8px; }
.empty { color: var(--text-secondary, #9ca3af); }
@media (max-width: 720px) { .instance-row { align-items: flex-start; flex-wrap: wrap; padding: .75rem 0; } .row-actions { width: 100%; } .create-row label, .create-row input, .create-row select { width: 100%; } }
</style>

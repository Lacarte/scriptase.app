<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { apiErrorText } from '@/shared/api/errors.js'
import { useUndoableAction } from '@/shared/composables/useUndoableAction.js'
import ProviderConfigurator from './components/ProviderConfigurator.vue'
import ProviderSettingsForm from './components/ProviderSettingsForm.vue'
import ProviderSettingsModal from './components/ProviderSettingsModal.vue'
import { useProviderCatalogStore } from './stores/providerCatalog.js'

defineOptions({ name: 'ProvidersSettingsPage' })

const catalog = useProviderCatalogStore()
const undoable = useUndoableAction()
const creatingFor = ref('')
const busyKey = ref('')
const error = ref('')
const modal = reactive({ open: false, domain: '', instanceId: '' })
const drafts = reactive({})
const editing = reactive({})
/**
 * Instance ids hidden by an open Undo window (step 0.3). Deleting an instance
 * orphans every node that names it, so it gets a five-second grace rather than
 * a dialog nobody reads.
 */
const pendingDelete = ref([])

const domains = computed(() =>
  catalog.domainIds.map((id) => ({
    id,
    label: catalog.domainLabel(id),
    providers: catalog.providersFor(id),
    instances: catalog
      .instancesFor(id)
      .filter((instance) => !pendingDelete.value.includes(instance.instance_id)),
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

function removeInstance(domain, instance) {
  error.value = ''
  pendingDelete.value = [...pendingDelete.value, instance.instance_id]
  const restore = () => {
    pendingDelete.value = pendingDelete.value.filter((id) => id !== instance.instance_id)
  }
  undoable.run({
    message: `Deleted “${instance.label}” — nodes that reference it will need another provider`,
    async commit() {
      await catalog.deleteInstance(domain, instance.instance_id)
      restore()
    },
    undo: restore,
    onError(err) {
      error.value = apiErrorText(err, 'Could not delete provider instance')
    },
  })
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
/**
 * Providers — Settings surface.
 *
 * A stack of domain panels on the prototype's raised surface: `--panel-grad`
 * over a 1px `--line` with the top hairline, so each card reads as lit from
 * above. The duotone accent appears on exactly two things here — the primary
 * action and the "Default" marker, which is the active selection. Everything
 * else is ink and the status ramp.
 */

.settings-page {
  max-width: 1040px;
  margin: 0 auto;
  padding: 28px 20px 64px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.page-header,
.domain-heading,
.instance-row,
.create-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-header,
.domain-heading {
  justify-content: space-between;
}

.page-header h1 {
  margin: 4px 0 6px;
  font-family: var(--display);
  font-size: 24px;
  font-weight: 600;
  line-height: 1.1;
  letter-spacing: -0.4px;
  color: var(--text);
}

.page-header p,
.domain-heading p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--muted);
}

/* Qualified so it beats `.page-header p` on its own, rather than with
   `!important` — the eyebrow is the one accent-tinted label on the page. */
.page-header .eyebrow {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: var(--accent);
}

.domain-list {
  display: grid;
  gap: 14px;
  margin-top: 22px;
}

/* The raised panel. */
.domain-card {
  padding: 18px;
  background: var(--panel-grad);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  transition: border-color 0.18s, box-shadow 0.18s;
}

.domain-card:hover {
  border-color: var(--line-2);
}

.domain-heading {
  padding-bottom: 16px;
}

.domain-heading h2 {
  margin: 0 0 3px;
  font-family: var(--display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: var(--text);
}

.domain-heading p {
  font-size: 12px;
}

/* The create form is a recessed well cut into the panel. */
.create-row {
  flex-wrap: wrap;
  align-items: flex-end;
  padding: 14px;
  margin-bottom: 16px;
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
}

.create-row label {
  display: grid;
  gap: 8px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: var(--muted);
}

input,
select {
  min-width: 180px;
  padding: 9px 11px;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  font-family: var(--body);
  font-size: 13px;
  transition: border-color 0.16s, box-shadow 0.16s;
}

select {
  cursor: pointer;
}

input::placeholder {
  color: var(--faint);
}

input:focus,
select:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.provider-configurator {
  padding: 16px 0;
  border-top: 1px solid var(--line-soft);
}

.instance-list {
  border-top: 1px solid var(--line-soft);
}

.instance-row {
  min-height: 60px;
  border-bottom: 1px solid var(--line-soft);
}

.instance-row:last-child {
  border-bottom: 0;
}

.instance-identity {
  display: grid;
  gap: 3px;
  flex: 1;
  min-width: 0;
}

.instance-identity strong {
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
  color: var(--text);
}

/* The provider type and instance id are an identity readout, not prose. */
.instance-identity span {
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.3px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.default-badge {
  flex: none;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  padding: 3px 9px;
  border-radius: 20px;
  color: var(--accent);
  background: var(--accent-dim);
  box-shadow: inset 0 0 0 1px var(--accent-line);
}

.row-actions {
  display: flex;
  flex: none;
  gap: 6px;
}

button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 13px;
  border-radius: var(--r-s);
  font-family: var(--body);
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.16s, border-color 0.16s, color 0.14s,
    box-shadow 0.16s, filter 0.16s, transform 0.12s var(--ease-spring);
}

button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  filter: none;
}

.primary {
  border: 1px solid transparent;
  color: var(--text);
  background: var(--accent-grad);
  font-weight: 600;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast);
}

.primary:hover:not(:disabled) {
  filter: brightness(1.07) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
}

.secondary {
  color: var(--text);
  background: var(--panel-grad);
  border: 1px solid var(--line);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
}

.secondary:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  transform: translateY(-1px);
}

.ghost {
  color: var(--text-2);
  background: transparent;
  border: 1px solid transparent;
}

.ghost:hover:not(:disabled) {
  background: var(--panel-2);
  color: var(--text);
}

.danger {
  color: var(--fail);
  background: transparent;
  border: 1px solid var(--fail-line);
}

.danger:hover:not(:disabled) {
  background: var(--fail-dim);
  border-color: var(--fail-line-2);
}

.page-error {
  margin-top: 16px;
  padding: 11px 13px;
  border-radius: var(--r-s);
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--fail-text);
  background: var(--fail-dim);
  border: 1px solid var(--fail-line);
}

.empty {
  font-size: 12.5px;
  color: var(--muted);
}

@media (max-width: 720px) {
  .instance-row {
    align-items: flex-start;
    flex-wrap: wrap;
    padding: 12px 0;
  }

  .row-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  /* Three buttons plus a heading will not share a 375px line (step 0.3). */
  .page-header,
  .domain-heading {
    flex-wrap: wrap;
    gap: 12px;
  }

  .create-row label,
  .create-row input,
  .create-row select {
    width: 100%;
    min-width: 0;
  }
}
</style>

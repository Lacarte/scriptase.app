<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiErrorText } from '@/shared/api/errors.js'
import ProviderSettingsForm from './components/ProviderSettingsForm.vue'
import ProviderSettingsModal from './components/ProviderSettingsModal.vue'
import ProviderSimulationConsole from './components/ProviderSimulationConsole.vue'
import { useProviderCatalogStore } from './stores/providerCatalog.js'

defineOptions({ name: 'ProvidersSettingsPage' })

const catalog = useProviderCatalogStore()
const selectedKey = ref('')
const testing = ref(false)
const error = ref('')
const creatingFor = ref('')
const createDraft = reactive({ providerType: '', label: '' })
const modal = reactive({ open: false, domain: '', instanceId: '' })

const providers = computed(() => catalog.domainIds.flatMap((domain) => {
  const instances = catalog.instancesFor(domain)
  const rows = instances.length
    ? instances
    : catalog.providersFor(domain).map((type) => ({
        instance_id: type.id,
        provider_type: type.id,
        label: type.label,
        availability: type.availability,
        selected: catalog.selectedId(domain) === type.id,
      }))
  return rows.map((instance) => {
    const type = catalog.resolveProvider(domain, instance.provider_type) || {}
    return {
      ...instance,
      domain,
      key: `${domain}/${instance.instance_id}`,
      capability: catalog.domainLabel(domain),
      name: instance.label || type.label || instance.instance_id,
      typeName: type.label || instance.provider_type,
      kind: type.kind || 'local',
      description: type.description || 'Provider integration for this production capability.',
      capabilities: Object.entries(type.capabilities || {}).filter(([, value]) => value).map(([key]) => key),
      health: catalog.healthFor(domain, instance.instance_id),
    }
  })
}))

const selected = computed(() => providers.value.find((provider) => provider.key === selectedKey.value) || providers.value[0] || null)
const connectedCount = computed(() => providers.value.filter((provider) => provider.availability === 'available').length)
const status = computed(() => {
  if (selected.value?.health?.status) return selected.value.health.status === 'ok' ? 'connected' : 'error'
  return selected.value?.availability === 'available' ? 'connected' : 'disconnected'
})
const kindLabel = computed(() => ({ cloud: 'API key', extension: 'Extension', webhook: 'n8n', local: 'Local' }[selected.value?.kind] || selected.value?.kind))

watch(providers, (items) => {
  if (!items.some((item) => item.key === selectedKey.value)) selectedKey.value = items[0]?.key || ''
}, { immediate: true })

function openSettings() {
  if (!selected.value) return
  modal.domain = selected.value.domain
  modal.instanceId = selected.value.instance_id
  modal.open = true
}

async function testConnection() {
  if (!selected.value) return
  testing.value = true
  error.value = ''
  try {
    await catalog.checkHealth(selected.value.domain, selected.value.instance_id)
  } catch (err) {
    error.value = apiErrorText(err, 'Could not test connection')
  } finally {
    testing.value = false
  }
}

function beginCreate(domain) {
  creatingFor.value = domain
  createDraft.providerType = catalog.providersFor(domain)[0]?.id || ''
  createDraft.label = ''
}

async function createInstance() {
  if (!creatingFor.value || !createDraft.providerType) return
  error.value = ''
  try {
    const result = await catalog.createInstance(creatingFor.value, {
      providerType: createDraft.providerType,
      label: createDraft.label.trim() || undefined,
    })
    selectedKey.value = `${creatingFor.value}/${result.instance_id}`
    creatingFor.value = ''
    openSettings()
  } catch (err) {
    error.value = apiErrorText(err, 'Could not create provider instance')
  }
}

onMounted(() => catalog.loadCatalog())
</script>

<template>
  <section class="providers-page">
    <aside class="provider-rail">
      <header>
        <h1>Providers</h1>
        <p>One provider per production capability. Configure, test, and inspect each integration.</p>
      </header>
      <div v-if="catalog.loading && !catalog.loaded" class="rail-empty">Loading providers…</div>
      <nav v-else class="provider-list" aria-label="Provider integrations">
        <button
          v-for="provider in providers"
          :key="provider.key"
          class="provider-item"
          :class="{ selected: selected?.key === provider.key }"
          :aria-current="selected?.key === provider.key ? 'true' : undefined"
          @click="selectedKey = provider.key"
        >
          <span class="provider-mark">{{ provider.capability.slice(0, 1) }}</span>
          <span class="provider-copy">
            <small>{{ provider.capability }}</small>
            <strong>{{ provider.name }} <em>{{ ({ cloud: 'API', extension: 'EXT', webhook: 'N8N', local: 'LOCAL' })[provider.kind] }}</em></strong>
          </span>
          <span class="status-dot" :class="provider.availability === 'available' ? 'connected' : 'disconnected'"></span>
        </button>
      </nav>
      <footer><span class="status-dot connected"></span>{{ connectedCount }} of {{ providers.length }} available</footer>
    </aside>

    <main v-if="selected" class="provider-detail">
      <header class="provider-hero">
        <span class="hero-mark">{{ selected.capability.slice(0, 1) }}</span>
        <div class="hero-copy">
          <small>{{ selected.capability }}</small>
          <h2>{{ selected.name }} <span class="status-dot" :class="status"></span></h2>
          <p>{{ selected.description }}</p>
        </div>
        <div class="hero-status">
          <span class="status-badge" :class="status"><span class="status-dot" :class="status"></span>{{ status }}</span>
          <small>{{ kindLabel }} transport · {{ selected.typeName }}</small>
        </div>
      </header>

      <div class="detail-body">
        <p v-if="error || catalog.error" class="page-error" role="alert">{{ error || catalog.error }}</p>

        <section class="capability-link">
          <span class="link-mark">→</span>
          <div><strong>Powers {{ selected.capability }}</strong><p>Capability is metadata; execution remains owned by the workflow.</p></div>
          <span class="capability-pill">{{ selected.domain }}</span>
        </section>

        <section class="detail-section">
          <div class="section-heading">
            <div><h3>Connection & configuration</h3><p>Credentials are write-only. Stored secret values are never returned to this page.</p></div>
            <div class="section-actions">
              <button class="secondary" :disabled="testing" @click="testConnection">{{ testing ? 'Testing…' : 'Test connection' }}</button>
              <button class="primary" @click="openSettings">Configure</button>
            </div>
          </div>
          <div v-if="selected.health" class="health-result" :class="status">
            <span class="status-dot" :class="status"></span>
            {{ selected.health.message || (status === 'connected' ? 'Connection test passed' : 'Connection test failed') }}
            <span v-if="selected.health.latency_ms">· {{ selected.health.latency_ms }}ms</span>
          </div>
          <div class="capability-tags">
            <span v-for="capability in selected.capabilities" :key="capability">{{ capability.replaceAll('_', ' ') }}</span>
          </div>
        </section>

        <ProviderSimulationConsole
          :key="selected.key"
          :domain="selected.domain"
          :instance-id="selected.instance_id"
          :provider-name="selected.name"
        />

        <section class="instance-tools">
          <span>Need another named {{ selected.capability }} account?</span>
          <button class="ghost" @click="beginCreate(selected.domain)">Add instance</button>
          <div v-if="creatingFor === selected.domain" class="create-form">
            <select v-model="createDraft.providerType" aria-label="Provider type">
              <option v-for="type in catalog.providersFor(selected.domain)" :key="type.id" :value="type.id">{{ type.label }}</option>
            </select>
            <input v-model="createDraft.label" aria-label="Instance name" placeholder="Instance name" @keyup.enter="createInstance" />
            <button class="primary" @click="createInstance">Add and configure</button>
            <button class="ghost" @click="creatingFor = ''">Cancel</button>
          </div>
        </section>
      </div>
    </main>

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
          :model-value="formData" :schema="schema" :errors="formErrors"
          :domain="domain" :provider-id="providerId"
          @update:model-value="(value) => Object.assign(formData, value)"
        />
      </template>
    </ProviderSettingsModal>
  </section>
</template>

<style scoped>
.providers-page { height: 100%; min-height: 0; display: grid; grid-template-columns: 300px minmax(0, 1fr); color: var(--text); font: 13px var(--body); }
.provider-rail { min-height: 0; display: flex; flex-direction: column; background: linear-gradient(180deg, var(--bg-2), var(--bg)); border-right: 1px solid var(--line); }
.provider-rail header { padding: 18px 20px 15px; border-bottom: 1px solid var(--line-soft); }
h1 { margin: 0; font: 600 15px var(--display); }
.provider-rail header p { margin: 8px 0 0; color: var(--muted); font-size: 12px; line-height: 1.45; }
.provider-list { flex: 1; min-height: 0; overflow-y: auto; display: grid; align-content: start; gap: 7px; padding: 10px; }
.provider-item { width: 100%; display: flex; align-items: center; gap: 12px; padding: 12px; color: var(--text); text-align: left; background: var(--panel-grad); border: 1px solid var(--line); border-radius: var(--r-s); box-shadow: var(--hairline-top); cursor: pointer; transition: .16s var(--ease-spring); }
.provider-item:hover { transform: translateY(-1px); border-color: var(--line-2); }
.provider-item.selected { background: var(--accent-dim); border-color: var(--accent-line-2); box-shadow: var(--hairline-top), var(--glow); }
.provider-mark, .hero-mark { display: grid; place-items: center; flex: none; color: var(--accent); background: var(--accent-dim); box-shadow: inset 0 0 0 1px var(--accent-line); font: 600 15px var(--display); }
.provider-mark { width: 36px; height: 36px; border-radius: 9px; }
.provider-copy { min-width: 0; flex: 1; display: grid; gap: 3px; }
.provider-copy small, .hero-copy small { color: var(--muted); font: 9.5px var(--mono); letter-spacing: .5px; text-transform: uppercase; }
.provider-copy strong { overflow: hidden; font-size: 13.5px; text-overflow: ellipsis; white-space: nowrap; }
.provider-copy em { padding: 1px 5px; color: var(--text-2); background: var(--bg-2); border-radius: 4px; font: 500 8.5px var(--mono); }
.status-dot { width: 8px; height: 8px; display: inline-block; flex: none; border-radius: 50%; background: var(--faint); }
.status-dot.connected { background: var(--ok); box-shadow: 0 0 8px var(--ok); }.status-dot.error { background: var(--fail); }.status-dot.disconnected { background: var(--faint); }
.provider-rail footer { display: flex; align-items: center; gap: 8px; padding: 11px 18px; color: var(--muted); border-top: 1px solid var(--line-soft); font: 10.5px var(--mono); }
.rail-empty { padding: 20px; color: var(--muted); }
.provider-detail { min-width: 0; overflow-y: auto; }
.provider-hero { position: relative; display: flex; align-items: center; gap: 18px; padding: 26px 32px 22px; overflow: hidden; border-bottom: 1px solid var(--line-soft); }
.provider-hero::before { content: ''; position: absolute; inset: 0; pointer-events: none; opacity: .08; background: radial-gradient(420px 200px at 12% -30%, var(--accent), transparent 70%); }
.hero-mark { width: 62px; height: 62px; border-radius: 15px; font-size: 24px; }
.hero-copy { z-index: 1; flex: 1; min-width: 0; }
.hero-copy h2 { display: flex; align-items: center; gap: 11px; margin: 4px 0 7px; font: 600 24px var(--display); letter-spacing: -.5px; }
.hero-copy p, .section-heading p, .capability-link p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
.hero-status { z-index: 1; display: grid; justify-items: end; gap: 11px; color: var(--muted); font: 10.5px var(--mono); }
.status-badge { display: inline-flex; align-items: center; gap: 7px; padding: 5px 11px; border-radius: 20px; text-transform: uppercase; font: 600 10.5px var(--mono); }
.status-badge.connected { color: var(--ok); background: var(--ok-dim); }.status-badge.error { color: var(--fail); background: var(--fail-dim); }.status-badge.disconnected { color: var(--muted); background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line); }
.detail-body { max-width: 900px; display: grid; gap: 24px; padding: 24px 32px 50px; }
.capability-link { display: flex; align-items: center; gap: 12px; padding: 14px 16px; background: var(--panel-grad); border: 1px solid var(--line); border-radius: var(--r); box-shadow: var(--hairline-top); }
.link-mark { width: 34px; height: 34px; display: grid; place-items: center; color: var(--text-2); background: var(--raise); border-radius: 9px; }.capability-link div { flex: 1; }.capability-link strong { font-size: 12.5px; }
.capability-pill { padding: 4px 10px; color: var(--accent); background: var(--accent-dim); border-radius: 20px; font: 10px var(--mono); text-transform: uppercase; }
.detail-section { display: grid; gap: 14px; }.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; }.section-heading h3 { margin: 0 0 5px; font: 600 13px var(--display); }.section-actions { display: flex; gap: 8px; }
button { padding: 8px 13px; border-radius: var(--r-s); font: 500 12.5px var(--body); cursor: pointer; }.primary { color: var(--text); background: var(--accent-grad); border: 1px solid transparent; font-weight: 600; }.secondary { color: var(--text); background: var(--panel-grad); border: 1px solid var(--line); box-shadow: var(--hairline-top); }.ghost { color: var(--text-2); background: transparent; border: 1px solid transparent; }
.health-result { display: flex; align-items: center; gap: 8px; padding: 10px 12px; color: var(--text-2); background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: var(--r-s); font: 11px var(--mono); }.health-result.error { color: var(--fail-text); border-color: var(--fail-line); }
.capability-tags { display: flex; flex-wrap: wrap; gap: 6px; }.capability-tags span { padding: 3px 7px; color: var(--muted); background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 4px; font: 9px var(--mono); text-transform: uppercase; }
.instance-tools { display: flex; align-items: center; gap: 8px; padding-top: 18px; color: var(--muted); border-top: 1px solid var(--line-soft); font-size: 12px; }.create-form { width: 100%; display: flex; gap: 8px; flex-wrap: wrap; }.create-form input, .create-form select { min-width: 160px; padding: 8px 10px; color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s); }
.page-error { padding: 11px 13px; color: var(--fail-text); background: var(--fail-dim); border: 1px solid var(--fail-line); border-radius: var(--r-s); }
@media (max-width: 820px) { .providers-page { display: block; overflow-y: auto; }.provider-rail { min-height: auto; border-right: 0; border-bottom: 1px solid var(--line); }.provider-list { display: flex; overflow-x: auto; }.provider-item { min-width: 230px; }.provider-rail footer { display: none; }.provider-detail { overflow: visible; }.provider-hero, .section-heading, .instance-tools { align-items: flex-start; flex-wrap: wrap; }.hero-status { width: 100%; justify-items: start; }.detail-body { padding: 20px; }.section-actions { width: 100%; }.section-actions button { flex: 1; } }
</style>

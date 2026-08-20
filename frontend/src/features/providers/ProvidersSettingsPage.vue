<script setup>
/**
 * The prototype's Providers screen (step 6.5): the `pv-rail` capability list
 * beside a `pv-detail` pane that opens with a hero carrying the connection
 * state, then the activity strip, the capability chips, the simulation console
 * and a sticky `pv-foot` of actions.
 *
 * Nothing about a provider is written down here. The prototype hardcodes a
 * name, tagline, colour, icon, status and activity counters per provider; all
 * of that comes from `GET /api/providers` instead, and the two things the
 * catalog has no field for — the plate colour and its glyph — are *derived*
 * from ids the catalog does own, the way step 6.4 derives a channel avatar.
 * A new provider therefore still renders without a Vue edit (§26).
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiErrorText } from '@/shared/api/errors.js'
import ProviderSettingsForm from './components/ProviderSettingsForm.vue'
import ProviderSettingsModal from './components/ProviderSettingsModal.vue'
import ProviderSimulationConsole from './components/ProviderSimulationConsole.vue'
import { useProviderCatalogStore } from './stores/providerCatalog.js'

defineOptions({ name: 'ProvidersSettingsPage' })

/**
 * The prototype's five provider accents. Which domains exist is the backend's
 * to say; what colour one is drawn in is not, so the palette is indexed by the
 * domain's place in the sorted domain list rather than by a table of domain
 * names — a table would need an edit every time a domain is added.
 *
 * Position and not a hash of the id, which is where this differs from step
 * 6.4: there are 81 channels against 8 colours, but only a handful of domains
 * against 5, and a hash into a palette that small lands two capabilities on
 * the same colour more often than not. `domainIds` is sorted, so a given
 * catalog always produces the same assignment.
 */
// One vivid accent per capability. Seven distinct hues so no two rows in the
// shipped catalog share a plate colour (the washed grey the prototype ended on
// read as "disabled" beside the others). Indexed by the domain's sorted
// position so a given catalog is always coloured the same way.
const PROVIDER_COLORS = ['#3fb68b', '#5b8cff', '#b06be6', '#e0a44a', '#f0616d', '#4ea1ff', '#e084c4']

/**
 * A capability icon per domain, so the plate says what the row *does* rather
 * than repeating a domain initial (Script/Scene/Story all began with "S", both
 * visual domains with "V"). Presentation-only and derived from the domain id —
 * the catalog carries no icon field, exactly as it carries no colour — so a new
 * domain still renders (it falls back to `default`) without a backend edit.
 * Paths are 24×24, stroked, matching the SVGs used elsewhere in the app.
 */
const DOMAIN_ICONS = {
  script: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M9 13h6 M9 17h6',
  scene_director: 'M2 7h20 M2 7v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7 M7 3v4 M17 3v4 M2 12h20',
  tts: 'M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z M19 10v1a7 7 0 0 1-14 0v-1 M12 18v4',
  image: 'M3 3h18a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z M8.5 9a1.5 1.5 0 1 0 0 3 M21 15l-5-5L5 21',
  video: 'M23 7l-7 5 7 5V7z M14 5H3a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2z',
  viral: 'M12 20v-6 M6 20v-4 M18 20V8 M3 20h18',
  default: 'M4 4h16v16H4z',
}
function iconPathFor(domain) {
  return DOMAIN_ICONS[domain] || DOMAIN_ICONS.default
}

/**
 * Transport copy for the manifest's `kind` vocabulary — the same four values
 * `scriptase/providers/simulation.py` maps. An unrecognized kind falls back to
 * its own name rather than disappearing.
 */
const KINDS = {
  cloud: { label: 'API key', hint: 'Authenticated by a stored key' },
  extension: { label: 'Extension', hint: 'Browser extension over the automation socket' },
  webhook: { label: 'n8n', hint: 'Runs as an n8n workflow via webhook' },
  local: { label: 'Local', hint: 'Runs in-process, needs no credential' },
}

/**
 * The real service behind a provider type, shown after the capability name so
 * "Voice Generator" reads as "Voice Generator · Inworld". Derived from the type
 * id (presentation only, no catalog field); an unmapped id is title-cased so a
 * new provider still names its service without an edit here. n8n/webhook rows
 * already carry the service in their transport badge, so they get no duplicate.
 */
const SERVICE_NAMES = {
  inworld: 'Inworld',
  gemini_ws: 'Gemini',
  gemini: 'Gemini',
  grok_automa: 'Grok',
  deterministic: 'Built-in',
  random_template: 'Templates',
}
function serviceNameFor(type, kind) {
  if (kind === 'webhook') return ''
  const id = String(type || '')
  if (!id || id === 'n8n') return ''
  return SERVICE_NAMES[id] || id.replace(/[_-]+/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase())
}

const STATUS_LABELS = {
  connected: 'Connected',
  disconnected: 'Disconnected',
  error: 'Error',
  connecting: 'Connecting',
}

const catalog = useProviderCatalogStore()

function accentOf(domain) {
  const index = catalog.domainIds.indexOf(domain)
  return PROVIDER_COLORS[(index < 0 ? 0 : index) % PROVIDER_COLORS.length]
}

function plateStyle(domain) {
  const accent = accentOf(domain)
  // A tinted plate with a faint top light and a hairline of the accent, so the
  // capability icon reads clearly and each row keeps its own colour identity.
  return {
    background: `linear-gradient(145deg, ${accent}33, ${accent}14)`,
    color: accent,
    boxShadow: `inset 0 0 0 1px ${accent}40`,
  }
}

const selectedKey = ref('')
/** The instance whose health probe is in flight — the `st-connecting` row. */
const probing = ref('')
const error = ref('')
const creatingFor = ref('')
const createDraft = reactive({ providerType: '', label: '' })
const modal = reactive({ open: false, domain: '', instanceId: '' })
const simConsole = ref(null)

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
    const capability = catalog.domainLabel(domain)
    return {
      ...instance,
      domain,
      key: `${domain}/${instance.instance_id}`,
      availability: instance.availability || 'needs_configuration',
      capability,
      // The prototype's per-provider icon has no catalog field. The capability's
      // own initial needs none and stays stable as the catalog changes.
      glyph: capability.slice(0, 1).toUpperCase(),
      name: instance.label || type.label || instance.instance_id,
      typeName: type.label || instance.provider_type,
      service: serviceNameFor(instance.provider_type, type.kind),
      version: type.version || '',
      kind: type.kind || 'local',
      kindLabel: KINDS[type.kind]?.label || type.kind || 'Local',
      description: type.description || 'Provider integration for this production capability.',
      capabilities: catalog.grantedCapabilitiesOf(domain, instance.instance_id),
      health: catalog.healthFor(domain, instance.instance_id),
    }
  })
}))

/**
 * Filter the rail by transport (Extension / n8n / Cloud / Local). `all` is the
 * resting state. Only kinds actually present in the catalog get a chip, so the
 * bar never offers an empty filter, and each chip carries its live count.
 */
const kindFilter = ref('all')
const kindFilters = computed(() => {
  const counts = new Map()
  for (const provider of providers.value) {
    counts.set(provider.kind, (counts.get(provider.kind) || 0) + 1)
  }
  const order = ['extension', 'webhook', 'cloud', 'local']
  const present = [...counts.keys()].sort(
    (a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99),
  )
  return [
    { id: 'all', label: 'All', count: providers.value.length },
    ...present.map((kind) => ({
      id: kind,
      label: KINDS[kind]?.label || kind,
      count: counts.get(kind),
    })),
  ]
})
const filteredProviders = computed(() =>
  kindFilter.value === 'all'
    ? providers.value
    : providers.value.filter((p) => p.kind === kindFilter.value),
)

const selected = computed(() =>
  filteredProviders.value.find((p) => p.key === selectedKey.value)
  || providers.value.find((p) => p.key === selectedKey.value)
  || filteredProviders.value[0]
  || providers.value[0]
  || null,
)
const availableCount = computed(
  () => filteredProviders.value.filter((p) => p.availability === 'available').length,
)

/**
 * Two axes, kept apart the way the store keeps them (§21.5): a probe result
 * when one has been asked for, otherwise the availability that shipped with the
 * catalog. Nothing here triggers I/O to decide which dot to draw.
 */
function statusOf(provider) {
  if (probing.value === provider.key) return 'connecting'
  if (provider.health?.status) return provider.health.status === 'ok' ? 'connected' : 'error'
  return provider.availability === 'available' ? 'connected' : 'disconnected'
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

const status = computed(() => (selected.value ? statusOf(selected.value) : 'disconnected'))
const kindHint = computed(() => KINDS[selected.value?.kind]?.hint || 'Provider transport')

const probeResult = computed(() => {
  if (!selected.value) return null
  if (probing.value === selected.value.key) return { tone: 'run', text: 'Testing the stored configuration…' }
  const health = selected.value.health
  if (!health) return null
  const latency = health.latency_ms == null ? '' : ` · ${Math.round(health.latency_ms)}ms`
  const fallback = health.status === 'ok' ? 'Connection test passed' : 'Connection test failed'
  return {
    tone: health.status === 'ok' ? 'ok' : 'err',
    text: `${health.message || fallback}${latency}`,
  }
})

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
  if (!selected.value || probing.value) return
  probing.value = selected.value.key
  error.value = ''
  try {
    await catalog.checkHealth(selected.value.domain, selected.value.instance_id)
  } catch (err) {
    error.value = apiErrorText(err, 'Could not test connection')
  } finally {
    probing.value = ''
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
  <section class="pvview" aria-label="Providers">
    <aside class="pv-rail">
      <div class="pv-rail-head">
        <h2>Providers</h2>
        <div class="pv-rail-sub">
          One provider per production capability. Capability is metadata — a
          provider never owns a stage.
        </div>
      </div>

      <div v-if="!catalog.loading || catalog.loaded" class="pv-filters" role="group" aria-label="Filter by connection type">
        <button
          v-for="f in kindFilters"
          :key="f.id"
          type="button"
          class="pv-fchip"
          :class="{ on: kindFilter === f.id }"
          :aria-pressed="kindFilter === f.id"
          @click="kindFilter = f.id"
        >
          {{ f.label }}<span class="pv-fcount">{{ f.count }}</span>
        </button>
      </div>

      <p v-if="catalog.loading && !catalog.loaded" class="rail-state">Loading providers…</p>
      <nav v-else class="pv-list" aria-label="Provider integrations">
        <button
          v-for="provider in filteredProviders"
          :key="provider.key"
          type="button"
          class="pv-litem"
          :class="[`sig-${statusOf(provider)}`, { sel: selected?.key === provider.key, off: provider.availability === 'unavailable' }]"
          :aria-current="selected?.key === provider.key ? 'true' : undefined"
          @click="selectedKey = provider.key"
        >
          <span class="pv-spine" aria-hidden="true"></span>
          <span class="pv-ic" :style="plateStyle(provider.domain)" aria-hidden="true">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path :d="iconPathFor(provider.domain)" /></svg>
          </span>
          <span class="pl">
            <span class="cap">{{ provider.capability }}</span>
            <span class="pn">
              <span class="pn-name">{{ provider.name }}</span>
              <span v-if="provider.service" class="pn-svc">{{ provider.service }}</span>
              <span class="kind">{{ provider.kindLabel }}</span>
            </span>
          </span>
          <span class="pv-litem-status" :title="statusLabel(statusOf(provider))">
            <span class="pv-status-dot" :class="`st-${statusOf(provider)}`"></span>
          </span>
        </button>
        <p v-if="!providers.length" class="rail-state">No providers discovered.</p>
        <p v-else-if="!filteredProviders.length" class="rail-state">
          No {{ (kindFilters.find((f) => f.id === kindFilter) || {}).label }} providers.
          <button type="button" class="pv-flink" @click="kindFilter = 'all'">Show all</button>
        </p>
      </nav>

      <div class="pv-rail-foot">
        <span class="pv-status-dot st-connected"></span>
        {{ availableCount }} of {{ providers.length }} available
      </div>
    </aside>

    <main v-if="selected" class="pv-detail">
      <header class="pv-hero" :style="{ '--pv-color': accentOf(selected.domain) }">
        <span class="pv-hero-ic" :style="plateStyle(selected.domain)" aria-hidden="true">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path :d="iconPathFor(selected.domain)" /></svg>
        </span>
        <div class="pv-hero-main">
          <div class="pv-hero-cap">{{ selected.capability }}</div>
          <h1 class="pv-hero-name">
            {{ selected.name }}
            <span class="pv-status-dot" :class="`st-${status}`" :title="statusLabel(status)"></span>
          </h1>
          <p class="pv-hero-tag">{{ selected.description }}</p>
        </div>
        <div class="pv-hero-side">
          <span class="pv-badge" :class="status">
            <span class="pv-status-dot" :class="`st-${status}`"></span>{{ statusLabel(status) }}
          </span>
          <span class="mono kind-hint">{{ kindHint }}</span>
        </div>
      </header>

      <div class="pv-body">
        <p v-if="error || catalog.error" class="banner error" role="alert">{{ error || catalog.error }}</p>

        <div class="pv-link">
          <span class="lic" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          </span>
          <div class="lt">
            <div class="t">Powers the {{ selected.capability }} capability</div>
            <div class="d">Capability is metadata — the workflow, not this provider, owns the stage that uses it.</div>
          </div>
          <span class="stage-pill">{{ selected.domain }}</span>
        </div>

        <section class="pv-section">
          <h3>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 3v18h18" /><path d="M7 14l3-3 3 3 5-5" /></svg>
            Activity
          </h3>
          <!-- The prototype's counters are invented telemetry. These four cells
               are the catalog's own answers about this binding. -->
          <div class="pv-meta">
            <div class="cell">
              <div class="n">{{ selected.availability.replaceAll('_', ' ') }}</div>
              <div class="l">Availability</div>
            </div>
            <div class="cell">
              <div class="n">{{ selected.version || '—' }}</div>
              <div class="l">{{ selected.typeName }}</div>
            </div>
            <div class="cell">
              <div class="n">{{ selected.capabilities.length }}</div>
              <div class="l">Capabilities</div>
            </div>
            <div class="cell">
              <div class="n">{{ selected.health?.latency_ms == null ? '—' : `${Math.round(selected.health.latency_ms)}ms` }}</div>
              <div class="l">Last probe</div>
            </div>
          </div>
        </section>

        <section class="pv-section">
          <h3>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8M4.6 9a1.6 1.6 0 0 0-.3-1.8M9 4.6a1.6 1.6 0 0 0 1.8-.3M15 19.4a1.6 1.6 0 0 0-1.8.3" /></svg>
            Configuration
          </h3>
          <div class="desc">
            {{ kindHint }}. Settings are edited in a dialog, so this pane never
            holds a credential field.
          </div>
          <!-- The prototype's `pv-static` carries a fact that is always true of
               the row it sits in. Here that is the storage guarantee itself. -->
          <div class="pv-static">
            <span class="sd"></span>
            Secrets are stored write-only — no stored value is ever returned to this page.
          </div>
          <div v-if="selected.capabilities.length" class="pv-caps">
            <span v-for="capability in selected.capabilities" :key="capability" class="kind">
              {{ capability.replaceAll('_', ' ') }}
            </span>
          </div>
        </section>

        <div class="pv-test-out" :class="probeResult ? `show ${probeResult.tone}` : ''">
          {{ probeResult?.text }}
        </div>

        <section class="pv-section">
          <h3>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3" /><circle cx="12" cy="12" r="3" /></svg>
            Simulation
          </h3>
          <div class="desc">
            Send a safe dummy request and inspect the transport round-trip. No
            configured endpoint is contacted.
          </div>
          <ProviderSimulationConsole
            ref="simConsole"
            :key="selected.key"
            :domain="selected.domain"
            :instance-id="selected.instance_id"
            :provider-name="selected.name"
          />
        </section>

        <section class="pv-section instance-tools">
          <h3>Instances</h3>
          <div class="desc">
            A second named binding of the same provider type holds its own
            settings and its own availability.
          </div>
          <button type="button" class="btn sm ghost" @click="beginCreate(selected.domain)">
            Add instance
          </button>
          <div v-if="creatingFor === selected.domain" class="pv-cfg create-form">
            <div class="pv-field">
              <label for="pv-new-type">Provider type</label>
              <select id="pv-new-type" v-model="createDraft.providerType" class="pv-select">
                <option v-for="type in catalog.providersFor(selected.domain)" :key="type.id" :value="type.id">
                  {{ type.label }}
                </option>
              </select>
            </div>
            <div class="pv-field">
              <label for="pv-new-label">Instance name</label>
              <input
                id="pv-new-label"
                v-model="createDraft.label"
                class="pv-input mono"
                placeholder="Instance name"
                @keyup.enter="createInstance"
              />
            </div>
            <div class="create-actions">
              <button type="button" class="btn primary sm" @click="createInstance">Add and configure</button>
              <button type="button" class="btn sm ghost" @click="creatingFor = ''">Cancel</button>
            </div>
          </div>
        </section>
      </div>

      <footer class="pv-foot">
        <div class="spacer"></div>
        <button
          type="button"
          class="btn sm simulate-button"
          :disabled="simConsole?.running"
          @click="simConsole?.simulate()"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3" /></svg>
          Simulate request
        </button>
        <button type="button" class="btn sm" :disabled="Boolean(probing)" @click="testConnection">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>
          {{ probing ? 'Testing…' : 'Test connection' }}
        </button>
        <button type="button" class="btn primary sm" @click="openSettings">Configure</button>
      </footer>
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
/* ── The prototype's `.body.pvview` ───────────────────────────────────── */
.pvview {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  overflow: hidden;
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
}

.pv-rail {
  border-right: 1px solid var(--line);
  background: linear-gradient(180deg, var(--bg-2), var(--bg));
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.pv-rail-head { padding: 18px 20px 15px; border-bottom: 1px solid var(--line-soft); }
.pv-rail-head h2 { margin: 0; font-family: var(--display); font-size: 15px; font-weight: 600; }
.pv-rail-sub { color: var(--muted); font-size: 12px; margin-top: 8px; line-height: 1.45; }

/* Transport filter — a quiet chip row above the list, one chip per kind the
   catalog actually has, each with its live count. */
.pv-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 11px 14px 12px;
  border-bottom: 1px solid var(--line-soft);
}
.pv-fchip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 999px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: .3px;
  text-transform: uppercase;
  font-weight: 500;
  cursor: pointer;
  transition: color .14s, border-color .14s, background .14s;
}
.pv-fchip:hover { color: var(--text-2); border-color: var(--line-2); }
.pv-fchip.on {
  color: var(--text);
  border-color: var(--accent-line-2);
  background: var(--accent-wash);
}
.pv-fchip:focus-visible { outline: 2px solid var(--accent-line-2); outline-offset: 1px; }
.pv-fcount {
  font-size: 9.5px;
  color: var(--faint);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line-soft);
  padding: 0 5px;
  border-radius: 999px;
  min-width: 16px;
  text-align: center;
}
.pv-fchip.on .pv-fcount { color: var(--text-2); }
.pv-flink {
  border: 0;
  background: none;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  padding: 0 4px;
  text-decoration: underline;
}

.pv-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

/* A real button, with none of a button's chrome — the row is the surface.
   Signature: a left status spine turns the list into a patch bay you scan for
   signal, and the plate carries the capability's own colour so no two rows
   read alike. */
.pv-litem {
  position: relative;
  border: 1px solid var(--line);
  background: var(--panel-grad);
  border-radius: var(--r-s);
  padding: 13px 14px 13px 20px;
  cursor: pointer;
  transition: border-color .16s, background .16s, transform .16s, box-shadow .16s;
  flex: none;
  display: flex;
  align-items: center;
  gap: 13px;
  width: 100%;
  text-align: left;
  color: inherit;
  font: inherit;
  box-shadow: var(--hairline-top);
  overflow: hidden;
}

.pv-litem:hover {
  border-color: var(--line-2);
  background: var(--panel-grad2);
  transform: translateY(-1px);
  box-shadow: var(--hairline-top), 0 8px 18px -12px rgba(0, 0, 0, .7);
}
.pv-litem.sel {
  border-color: var(--accent-line-2);
  background: var(--accent-fill-2);
  box-shadow: var(--hairline-top), var(--accent-cast-md);
}
.pv-litem.off { opacity: .5; }
.pv-litem:focus-visible { outline: 2px solid var(--accent-line-2); outline-offset: 1px; }

/* The status spine: the one bold move. Colour = health, read down the left
   edge; the whole point of the console is which capabilities are live. */
.pv-spine {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--faint);
  border-radius: 0 2px 2px 0;
  transition: background .16s, box-shadow .16s;
}
.sig-connected .pv-spine { background: var(--ok); box-shadow: 0 0 10px -1px var(--ok-line); }
.sig-error .pv-spine { background: var(--fail); box-shadow: 0 0 10px -1px var(--fail-line); }
.sig-connecting .pv-spine { background: var(--run); animation: pv-blink 1s infinite; }
.sig-disconnected .pv-spine { background: var(--faint); }

.pv-ic {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  flex: none;
  display: grid;
  place-items: center;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .08);
  font-family: var(--display);
  font-size: 15px;
  font-weight: 700;
  transition: transform .16s;
}
.pv-litem:hover .pv-ic { transform: scale(1.04); }

.pv-litem .pl { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.pv-litem .cap {
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--muted);
}
.pv-litem .pn { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pv-litem .pn-name {
  font-family: var(--display);
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: -.15px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pv-litem.sel .pn-name { color: #fff; }
/* The real service behind the capability — quiet, set apart from the bold name
   by a hairline dot so "Voice Generator · Inworld" reads as one unit. */
.pv-litem .pn-svc {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--muted);
  white-space: nowrap;
  flex: none;
}
.pv-litem .pn-svc::before {
  content: "·";
  margin-right: 6px;
  color: var(--faint);
}

/* One chip shape, on the rail row's transport and on a capability alike. */
.pv-litem .pn .kind,
.pv-caps .kind {
  font-family: var(--mono);
  font-size: 8.5px;
  letter-spacing: .4px;
  text-transform: uppercase;
  color: var(--text-2);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line-soft);
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
  flex: none;
  white-space: nowrap;
}

.pv-caps { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }

.pv-status-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; display: inline-block; }
.st-connected { background: var(--ok); box-shadow: 0 0 0 3px var(--ok-dim); }
.st-disconnected { background: var(--faint); }
.st-error { background: var(--fail); box-shadow: 0 0 0 3px var(--fail-dim); }
.st-connecting { background: var(--run); box-shadow: 0 0 0 3px var(--run-dim); animation: pv-blink 1s infinite; }

/* On the row, the spine is the loud status signal, so the dot stays quiet — a
   small confirmation, no halo. */
.pv-litem-status { flex: none; display: grid; place-items: center; }
.pv-litem-status .pv-status-dot { width: 7px; height: 7px; box-shadow: none; }

@keyframes pv-blink { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }

@media (prefers-reduced-motion: reduce) {
  .st-connecting { animation: none; }
}

.pv-rail-foot {
  padding: 11px 18px;
  border-top: 1px solid var(--line-soft);
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 8px;
}

.rail-state { padding: 28px 14px; margin: 0; text-align: center; color: var(--muted); font-size: 12.5px; }

/* ── Detail ───────────────────────────────────────────────────────────── */
.pv-detail { min-width: 0; overflow-y: auto; display: flex; flex-direction: column; }

.pv-hero {
  padding: 26px 32px 22px;
  border-bottom: 1px solid var(--line-soft);
  display: flex;
  align-items: center;
  gap: 18px;
  position: relative;
  overflow: hidden;
  flex: none;
}

/* The wash is tinted by the row's own derived accent, not by --accent. */
.pv-hero::before {
  content: "";
  position: absolute;
  inset: 0;
  opacity: .09;
  background: radial-gradient(420px 200px at 12% -30%, var(--pv-color, var(--accent)), transparent 70%);
  pointer-events: none;
}

.pv-hero-ic {
  width: 62px;
  height: 62px;
  border-radius: 15px;
  flex: none;
  display: grid;
  place-items: center;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .1), 0 10px 24px -10px rgba(0, 0, 0, .6);
  z-index: 1;
  font-family: var(--display);
  font-size: 24px;
  font-weight: 600;
}

.pv-hero-main { flex: 1; min-width: 0; z-index: 1; }
.pv-hero-cap { font-family: var(--mono); font-size: 10.5px; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); }
.pv-hero-name { margin: 4px 0 0; font-family: var(--display); font-weight: 600; font-size: 24px; letter-spacing: -.5px; display: flex; align-items: center; gap: 11px; }
.pv-hero-tag { margin: 7px 0 0; font-size: 12.5px; color: var(--text-2); line-height: 1.5; }
.pv-hero-side { z-index: 1; display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
.kind-hint { font-size: 10.5px; color: var(--muted); text-align: right; }

.pv-badge {
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: .4px;
  text-transform: uppercase;
  padding: 5px 11px;
  border-radius: 20px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-weight: 600;
  white-space: nowrap;
}

.pv-badge.connected { color: var(--ok); background: var(--ok-dim); box-shadow: inset 0 0 0 1px var(--ok-line); }
.pv-badge.disconnected { color: var(--muted); background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line); }
.pv-badge.error { color: var(--fail); background: var(--fail-dim); box-shadow: inset 0 0 0 1px var(--fail-line); }
.pv-badge.connecting { color: var(--run); background: var(--run-dim); box-shadow: inset 0 0 0 1px var(--run-line); }

.pv-body { padding: 24px 32px 40px; display: flex; flex-direction: column; gap: 24px; max-width: 900px; flex: 1; }
.pv-section h3 { margin: 0 0 4px; font-family: var(--display); font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 9px; }
.pv-section h3 svg { color: var(--muted); flex: none; }
.pv-section .desc { color: var(--muted); font-size: 12px; margin-bottom: 16px; line-height: 1.5; }

/* ── Activity strip ───────────────────────────────────────────────────── */
.pv-meta { display: flex; gap: 0; border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; }
.pv-meta .cell { flex: 1; min-width: 0; padding: 14px 16px; border-right: 1px solid var(--line-soft); background: var(--panel); }
.pv-meta .cell:last-child { border-right: none; }
.pv-meta .cell .n { font-family: var(--display); font-size: 17px; font-weight: 600; letter-spacing: -.3px; text-transform: capitalize; overflow-wrap: anywhere; }
.pv-meta .cell .l { font-family: var(--mono); font-size: 9.5px; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); margin-top: 4px; overflow-wrap: anywhere; }

/* ── Config fields (the create-instance form is this page's only one) ─── */
.pv-cfg { display: flex; flex-direction: column; gap: 14px; }
.pv-field { display: flex; flex-direction: column; gap: 8px; }
.pv-field > label { font-family: var(--mono); font-size: 10px; letter-spacing: .8px; text-transform: uppercase; color: var(--muted); }

.pv-input,
.pv-select {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  color: var(--text);
  font-size: 13px;
  padding: 9px 11px;
  font-family: var(--body);
  width: 100%;
}

.pv-input.mono { font-family: var(--mono); font-size: 12px; }

.pv-select {
  cursor: pointer;
  appearance: none;
  padding-right: 32px;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%237c8698' stroke-width='2'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
}

.pv-input:focus,
.pv-select:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.pv-static {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  background: var(--bg-2);
  font-size: 13px;
  color: var(--text-2);
}

.pv-static .sd { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); flex: none; }

/* ── Pipeline link callout ────────────────────────────────────────────── */
.pv-link {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: linear-gradient(180deg, var(--panel), var(--bg-2));
  padding: 14px 16px;
}

.pv-link .lic { width: 34px; height: 34px; border-radius: 9px; flex: none; display: grid; place-items: center; background: var(--raise); box-shadow: inset 0 0 0 1px var(--line-soft); color: var(--text-2); }
.pv-link .lt { flex: 1; min-width: 0; }
.pv-link .lt .t { font-size: 12.5px; font-weight: 600; }
.pv-link .lt .d { font-size: 11.5px; color: var(--muted); margin-top: 2px; line-height: 1.45; }
.pv-link .stage-pill { font-family: var(--mono); font-size: 10px; letter-spacing: .3px; text-transform: uppercase; color: var(--accent); background: var(--accent-dim); box-shadow: inset 0 0 0 1px var(--accent-line); padding: 4px 10px; border-radius: 20px; flex: none; }

/* ── Probe readout ────────────────────────────────────────────────────── */
.pv-test-out { font-family: var(--mono); font-size: 11.5px; display: none; align-items: center; gap: 8px; }
.pv-test-out.show { display: flex; }
.pv-test-out.ok { color: var(--ok); }
.pv-test-out.err { color: var(--fail); }
.pv-test-out.run { color: var(--run); }

/* ── Sticky action footer ─────────────────────────────────────────────── */
.pv-foot {
  padding: 14px 32px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg-2);
  display: flex;
  align-items: center;
  gap: 10px;
  position: sticky;
  bottom: 0;
  flex: none;
}

.pv-foot .spacer { flex: 1; }
/* The prototype's `.pv-enable` toggle is not ported: a provider is discovered
   or excluded (§21.4), and there is no enable flag for a switch to write. */

.instance-tools .btn { align-self: flex-start; }
.create-form { margin-top: 14px; }
.create-actions { display: flex; gap: 8px; flex-wrap: wrap; }

.banner.error {
  margin: 0;
  padding: 11px 13px;
  color: var(--fail-text);
  background: var(--fail-dim);
  border: 1px solid var(--fail-line);
  border-radius: var(--r-s);
}

@media (max-width: 1000px) {
  .pv-meta { flex-wrap: wrap; }
  .pv-meta .cell { flex: 1 1 40%; }
  .pv-hero { flex-wrap: wrap; }
}

/* The prototype hides the rail below 820px. Here it is the only way to reach
   a provider, so it stacks above the detail instead. */
@media (max-width: 820px) {
  .pvview { display: block; overflow-y: auto; }
  .pv-rail { min-height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
  .pv-list { flex-direction: row; overflow-x: auto; }
  .pv-litem { min-width: 240px; }
  .pv-detail { overflow: visible; }
  .pv-body { padding: 20px; }
  .pv-hero { padding: 20px; }
  .pv-hero-side { width: 100%; align-items: flex-start; }
  .kind-hint { text-align: left; }
  .pv-foot { padding: 14px 20px; position: static; flex-wrap: wrap; }
  .pv-foot .spacer { display: none; }
  .pv-foot .btn { flex: 1; }
}
</style>

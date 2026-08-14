<script setup>
import { ref, computed, watch } from 'vue'
import { apiErrorText } from '@/shared/api/errors.js'
import { withoutSecrets } from '@/shared/schema/providerSettings.js'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'
import { availabilityInfo, healthInfo, toneColor } from '../availability.js'

const props = defineProps({
  domain: { type: String, required: true },
  providerId: { type: String, required: true },
  visible: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'saved'])

// The schema, the label, the capabilities, the links, and the health vocabulary
// all come from the catalog — this modal knows nothing about any provider.
const catalog = useProviderCatalogStore()

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const formData = ref({})
const schema = ref(null)
const manifest = ref(null)
const errors = ref([])
const loadError = ref('')
const testResult = ref(null)
const originalData = ref({})

const providerName = computed(() => manifest.value?.label || props.providerId)
const blockingIssues = computed(() => errors.value.filter((e) => e.severity === 'error'))
const isValid = computed(() => blockingIssues.value.length === 0)
const isDirty = computed(
  () => JSON.stringify(formData.value) !== JSON.stringify(originalData.value),
)

/**
 * Declared capabilities as badges (§20.4 / step 6.1).
 * Prefer the catalog (vocabulary-filtered). Fall back to the settings
 * payload's manifest when the catalog has not loaded this domain yet —
 * still drop keys the domain vocabulary rejects when one is present.
 */
const capabilities = computed(() => {
  if (props.domain && props.providerId) {
    const fromCatalog = catalog.grantedCapabilitiesOf(props.domain, props.providerId)
    if (fromCatalog.length) return fromCatalog
  }
  const raw = Object.entries(manifest.value?.capabilities || {})
    .filter(([, enabled]) => enabled === true)
    .map(([name]) => name)
  const vocab = props.domain ? catalog.vocabularyOf(props.domain) : []
  const vocabSet = vocab.length ? new Set(vocab) : null
  return raw
    .filter((name) => !vocabSet || vocabSet.has(name))
    .sort()
})

const availability = computed(() => availabilityInfo(manifest.value?.availability))
const links = computed(() =>
  [
    { label: 'Documentation', url: manifest.value?.docs_url },
    { label: 'Open provider', url: manifest.value?.open_url },
  ].filter((link) => Boolean(link.url)),
)

async function loadProviderData() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await catalog.getProviderSettings(props.domain, props.providerId)
    schema.value = data.schema
    manifest.value = data.manifest
    originalData.value = { ...data.settings }
    // An unsaved draft from an earlier visit wins over the stored values, so
    // switching providers to compare two configurations loses neither. Secrets
    // are never part of a draft (§22.6), so they always come from the server.
    const draft = catalog.draftFor(props.domain, props.providerId)
    formData.value = { ...data.settings, ...(draft || {}) }
    errors.value = []
    testResult.value = null
  } catch (e) {
    loadError.value = apiErrorText(e, `Failed to load ${providerName.value} settings`)
  } finally {
    loading.value = false
  }
}

/**
 * Remember the non-secret edits so this provider's draft survives a switch.
 * The provider is passed in: by the time the watcher runs, the props already
 * name the provider being switched *to*.
 */
function rememberDraft(domain, providerId) {
  if (!isDirty.value) {
    catalog.clearDraft(domain, providerId)
    return
  }
  catalog.setDraft(domain, providerId, withoutSecrets(formData.value, schema.value))
}

async function validateForm() {
  try {
    const result = await catalog.validateProviderSettings(
      props.domain, props.providerId, formData.value,
    )
    errors.value = result.issues || []
    return result.valid
  } catch (e) {
    errors.value = [{
      field: 'root',
      severity: 'error',
      message: apiErrorText(e, `Could not validate ${providerName.value} settings`),
    }]
    return false
  }
}

async function handleSave() {
  const valid = await validateForm()
  if (!valid) return

  saving.value = true
  try {
    await catalog.saveProviderSettings(props.domain, props.providerId, formData.value)
    catalog.clearDraft(props.domain, props.providerId)
    emit('saved', { domain: props.domain, providerId: props.providerId })
    emit('close')
  } catch (e) {
    errors.value = [{
      field: 'root',
      severity: 'error',
      message: apiErrorText(e, `Failed to save ${providerName.value} settings`),
    }]
  } finally {
    saving.value = false
  }
}

/** Probe the candidate settings without saving them (§21.5). */
async function handleTest() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await catalog.testProvider(
      props.domain, props.providerId, formData.value,
    )
  } catch (e) {
    testResult.value = {
      status: 'fail',
      message: apiErrorText(e, `${providerName.value} could not be reached`),
    }
  } finally {
    testing.value = false
  }
}

function handleReset() {
  formData.value = { ...originalData.value }
  catalog.clearDraft(props.domain, props.providerId)
  errors.value = []
  testResult.value = null
}

function handleCancel() {
  rememberDraft(props.domain, props.providerId)
  emit('close')
}

// `immediate` matters: the modal is created with `visible` already true (the
// page guards it with `v-if`), so a change-only watcher would never fire and
// the form would render against a null schema.
watch(
  () => [props.visible, props.providerId, props.domain],
  ([visible], previous) => {
    // Leaving a provider keeps its draft; arriving at one restores it.
    if (previous?.[0] && (!visible || previous[1] !== props.providerId)) {
      rememberDraft(previous[2], previous[1])
    }
    if (visible) loadProviderData()
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-overlay" @click.self="handleCancel">
      <div class="modal-content">
        <div class="modal-header">
          <div class="header-main">
            <h3>Configure {{ providerName }}</h3>
            <span
              class="availability-pill"
              :style="{ color: toneColor(availability.tone) }"
            >{{ availability.label }}</span>
          </div>
          <button class="close-btn" @click="handleCancel">&times;</button>
        </div>

        <div class="modal-body">
          <div v-if="loading" class="loading-state">Loading…</div>

          <template v-else>
            <p v-if="manifest?.description" class="provider-description">
              {{ manifest.description }}
            </p>

            <div v-if="capabilities.length" class="capability-badges">
              <span v-for="name in capabilities" :key="name" class="badge">{{ name }}</span>
            </div>

            <p v-if="links.length" class="provider-links">
              <a
                v-for="link in links"
                :key="link.url"
                :href="link.url"
                target="_blank"
                rel="noopener noreferrer"
              >{{ link.label }}</a>
            </p>

            <div v-if="loadError" class="validation-banner error">
              <span>⚠️</span>
              <span>{{ loadError }}</span>
            </div>

            <div v-else-if="blockingIssues.length" class="validation-banner error">
              <span>⚠️</span>
              <span>{{ providerName }} needs configuration before it can be used.</span>
            </div>

            <div
              v-if="testResult"
              class="test-result"
              :style="{ borderColor: toneColor(healthInfo(testResult.status).tone) }"
            >
              <span
                class="status-dot"
                :style="{ background: toneColor(healthInfo(testResult.status).tone) }"
              ></span>
              <span>
                {{ providerName }}:
                {{ testResult.message || healthInfo(testResult.status).label }}
              </span>
              <span v-if="testResult.latency_ms">({{ testResult.latency_ms }}ms)</span>
            </div>

            <slot
              name="form"
              :formData="formData"
              :schema="schema"
              :errors="errors"
              :domain="domain"
              :providerId="providerId"
              :updateField="(key, val) => (formData[key] = val)"
            />
          </template>
        </div>

        <div class="modal-footer">
          <button
            class="btn btn-secondary"
            :disabled="saving || testing || !isDirty"
            @click="handleReset"
          >
            Reset
          </button>
          <button class="btn btn-secondary" :disabled="saving || testing" @click="handleTest">
            {{ testing ? 'Testing…' : 'Test connection' }}
          </button>
          <button class="btn btn-secondary" @click="handleCancel">Cancel</button>
          <button class="btn btn-primary" :disabled="saving || !isValid" @click="handleSave">
            {{ saving ? 'Saving…' : 'Save' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.modal-content {
  background: var(--bg-surface, #1f1f23);
  border: 1px solid var(--border, #3f3f46);
  border-radius: 12px;
  width: 90%;
  max-width: 520px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border, #3f3f46);
}

.header-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
  color: var(--text, #e5e5e5);
}

.availability-pill {
  font-size: 12px;
}

.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  color: var(--text-secondary, #9ca3af);
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.close-btn:hover {
  color: var(--text, #e5e5e5);
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.provider-description {
  font-size: 13px;
  color: var(--text-secondary, #9ca3af);
  margin: 0 0 12px;
}

.capability-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.badge {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--bg-elevated, #2a2a2f);
  border: 1px solid var(--border, #3f3f46);
  color: var(--text-secondary, #9ca3af);
}

.provider-links {
  display: flex;
  gap: 14px;
  margin: 0 0 16px;
  font-size: 12px;
}

.provider-links a {
  color: var(--accent, #4ECDC4);
}

.modal-footer {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border, #3f3f46);
  justify-content: flex-end;
}

.loading-state {
  text-align: center;
  padding: 40px;
  color: var(--text-secondary, #9ca3af);
}

.validation-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 14px;
}

.validation-banner.error {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.test-result {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 14px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.btn {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  border: none;
  transition: opacity 0.15s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--accent, #4ECDC4);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-secondary {
  background: var(--bg-elevated, #2a2a2f);
  color: var(--text, #e5e5e5);
  border: 1px solid var(--border, #3f3f46);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--bg-surface-hover, #3a3a3f);
}
</style>

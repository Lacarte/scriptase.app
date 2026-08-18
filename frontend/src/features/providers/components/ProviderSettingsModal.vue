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
/**
 * The provider settings dialog.
 *
 * A lifted panel over a blurred wash: `--panel-grad2` on `--line` at the large
 * radius, with the layered ambient shadow plus a long cast so the dialog sits
 * clearly above the page. The footer is a recessed shelf (`--bg-2` under a
 * `--line-soft` hairline) that anchors the actions.
 *
 * The button rules are qualified with `.modal-footer` on purpose: this
 * template uses `.btn .btn-secondary` / `.btn .btn-primary`, and the global
 * `.btn` in styles/shared.css is the base layer. Qualifying puts these
 * overrides above it regardless of stylesheet injection order.
 *
 * `.availability-pill`, `.test-result`'s border and `.status-dot` take their
 * colour from an inline binding (`toneColor()` in ../availability.js); the
 * rules here own their geometry and typography only.
 */

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(4, 6, 9, 0.68);
  -webkit-backdrop-filter: blur(4px) saturate(1.1);
  backdrop-filter: blur(4px) saturate(1.1);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.modal-content {
  width: 90%;
  max-width: 520px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--panel-grad2);
  border: 1px solid var(--line);
  border-radius: var(--r-l);
  box-shadow: var(--shadow), 0 40px 80px -30px rgba(0, 0, 0, 0.85);
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--line-soft);
}

.header-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.modal-header h3 {
  margin: 0;
  font-family: var(--display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: var(--text);
}

.availability-pill {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  white-space: nowrap;
}

.close-btn {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  padding: 0;
  border: none;
  border-radius: var(--r-s);
  background: none;
  font-size: 22px;
  line-height: 1;
  color: var(--muted);
  cursor: pointer;
  transition: color 0.14s, background 0.14s;
}

.close-btn:hover {
  color: var(--text);
  background: var(--panel-2);
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.provider-description {
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--muted);
  margin: 0 0 14px;
}

.capability-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

/* Capability is metadata, so it is the neutral kind tag — never the accent.
   The global `.badge` is the base layer; this narrows it. */
.capability-badges .badge {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 4px;
  color: var(--text-2);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line-soft);
}

.provider-links {
  display: flex;
  gap: 14px;
  margin: 0 0 16px;
  font-size: 12px;
}

.provider-links a {
  color: var(--accent);
  transition: color 0.14s;
}

.provider-links a:hover {
  color: var(--accent-2);
  text-decoration: underline;
}

.modal-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 14px 20px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg-2);
}

.loading-state {
  text-align: center;
  padding: 40px;
  font-family: var(--mono);
  font-size: 11.5px;
  letter-spacing: 0.4px;
  color: var(--muted);
}

.validation-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 13px;
  border-radius: var(--r-s);
  margin-bottom: 16px;
  font-size: 12.5px;
  line-height: 1.55;
  background: var(--bg-2);
  border: 1px solid var(--line);
  color: var(--text-2);
}

.validation-banner.error {
  background: var(--fail-dim);
  border-color: var(--fail-line);
  color: var(--fail-text);
}

/* The probe readout. Its border colour arrives inline from the health tone. */
.test-result {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 13px;
  border-radius: var(--r-s);
  margin-bottom: 16px;
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.5;
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  color: var(--text-2);
}

.status-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
  background: var(--faint);
}

.modal-footer .btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel-grad);
  color: var(--text);
  font-family: var(--body);
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.16s, border-color 0.16s, color 0.14s,
    box-shadow 0.16s, filter 0.16s, transform 0.12s var(--ease-spring);
}

.modal-footer .btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  filter: none;
}

.modal-footer .btn-secondary:hover:not(:disabled) {
  background: var(--panel-grad2);
  border-color: var(--line-2);
  transform: translateY(-1px);
}

.modal-footer .btn-primary {
  background: var(--accent-grad);
  border-color: transparent;
  color: var(--text);
  font-weight: 600;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast);
}

.modal-footer .btn-primary:hover:not(:disabled) {
  filter: brightness(1.07) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), var(--accent-cast-lg);
}
</style>

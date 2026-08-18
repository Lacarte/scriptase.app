<script setup>
import { computed, ref } from 'vue'
import { apiErrorText } from '@/shared/api/errors.js'
import { useProviderCatalogStore } from '../stores/providerCatalog.js'

defineOptions({ name: 'ProviderSimulationConsole' })

const props = defineProps({
  domain: { type: String, required: true },
  instanceId: { type: String, required: true },
  providerName: { type: String, required: true },
})

const catalog = useProviderCatalogStore()
const running = ref(false)
const result = ref(null)
const error = ref('')
const prettyRequest = computed(() => JSON.stringify(result.value?.request || {}, null, 2))
const prettyResponse = computed(() => JSON.stringify(result.value?.response || {}, null, 2))

async function simulate() {
  running.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await catalog.simulateProvider(props.domain, props.instanceId)
  } catch (err) {
    error.value = apiErrorText(err, `Could not simulate ${props.providerName}`)
  } finally {
    running.value = false
  }
}
</script>

<template>
  <section class="simulation-section" aria-labelledby="simulation-title">
    <div class="section-heading">
      <div>
        <h3 id="simulation-title">Simulation</h3>
        <p>Send a safe dummy request and inspect the transport round-trip. No configured endpoint is contacted.</p>
      </div>
      <button class="secondary simulate-button" :disabled="running" @click="simulate">
        {{ running ? 'Simulating…' : 'Simulate request' }}
      </button>
    </div>

    <p v-if="error" class="console-error" role="alert">{{ error }}</p>
    <div v-else-if="result" class="console" aria-live="polite">
      <header class="console-header">
        <strong>{{ providerName }}</strong>
        <span class="status">Complete</span>
        <code>{{ result.transport }}</code>
        <span class="elapsed">{{ result.elapsed_ms }}ms · dummy</span>
      </header>
      <div class="round-trip">
        <div class="payload">
          <span class="payload-label">↑ Request · {{ result.operation }}</span>
          <pre>{{ prettyRequest }}</pre>
        </div>
        <div class="payload">
          <span class="payload-label">↓ Response</span>
          <pre>{{ prettyResponse }}</pre>
        </div>
      </div>
      <ol class="steps">
        <li v-for="step in result.steps" :key="step"><span></span>{{ step }}</li>
      </ol>
    </div>
    <div v-else class="console-empty">The simulated request and response will appear here.</div>
  </section>
</template>

<style scoped>
.simulation-section { display: grid; gap: 14px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; }
h3 { margin: 0 0 5px; font-family: var(--display); font-size: 13px; }
p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
button { padding: 8px 13px; border-radius: var(--r-s); font: 500 12.5px var(--body); cursor: pointer; }
button:disabled { opacity: .45; cursor: default; }
.secondary { color: var(--text); background: var(--panel-grad); border: 1px solid var(--line); box-shadow: var(--hairline-top); }
.secondary:hover:not(:disabled) { border-color: var(--line-2); }
.console, .console-empty { overflow: hidden; background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r); }
.console-empty { padding: 24px; color: var(--faint); font: 11px var(--mono); text-align: center; }
.console-header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--line-soft); }
.console-header strong { font-size: 12.5px; }
.console-header code, .elapsed { color: var(--muted); font: 10px var(--mono); }
.console-header code { margin-left: auto; }
.status { padding: 3px 8px; color: var(--ok); background: var(--ok-dim); border-radius: 5px; font: 600 9.5px var(--mono); text-transform: uppercase; }
.round-trip { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--line-soft); }
.payload { min-width: 0; padding: 13px 14px; background: var(--bg); }
.payload-label { color: var(--muted); font: 9.5px var(--mono); letter-spacing: .6px; text-transform: uppercase; }
pre { margin: 9px 0 0; color: var(--text-2); font: 11px/1.55 var(--mono); white-space: pre-wrap; word-break: break-word; }
.steps { display: grid; gap: 7px; margin: 0; padding: 11px 14px; border-top: 1px solid var(--line-soft); list-style: none; }
.steps li { display: flex; align-items: center; gap: 9px; color: var(--text-2); font: 10.5px var(--mono); }
.steps span { width: 6px; height: 6px; flex: none; border-radius: 50%; background: var(--ok); }
.console-error { padding: 11px 13px; color: var(--fail-text); background: var(--fail-dim); border: 1px solid var(--fail-line); border-radius: var(--r-s); }
@media (max-width: 680px) { .round-trip { grid-template-columns: 1fr; } .section-heading, .console-header { align-items: flex-start; flex-wrap: wrap; } .console-header code { width: 100%; margin: 0; } }
</style>

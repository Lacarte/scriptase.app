<script setup>
/**
 * The prototype's `pv-sim` console (step 6.5): a dummy request beside the
 * response it produced, the transport steps under both, and the artifact the
 * round-trip claims to have received.
 *
 * What it contacts is a platform-owned fixture that accepts no settings and
 * constructs no transport (`scriptase/providers/simulation.py`), so there is
 * no configured endpoint in reach and no stored secret in scope. The request
 * body stays `{}` for that reason — sending the draft settings would quietly
 * turn an explanation of the round-trip into a live one.
 *
 * The button lives in the detail pane's `pv-foot`, where the prototype puts
 * it, so `simulate` and `running` are exposed rather than wired to markup here.
 */
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

/**
 * Strings (and the `:` that makes one a key) then numbers. Strings are matched
 * first and consumed whole, so digits inside one are never re-read as a number.
 */
const JSON_TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g

/**
 * The prototype colours its JSON by rewriting the text and assigning it to
 * `innerHTML`. Tokens are emitted as data instead and rendered as elements:
 * `v-html` over a response body is the one thing this console must not do.
 */
function tokenize(value) {
  const text = JSON.stringify(value ?? {}, null, 2)
  const tokens = []
  let cursor = 0
  let match
  JSON_TOKEN.lastIndex = 0
  while ((match = JSON_TOKEN.exec(text)) !== null) {
    if (match.index > cursor) tokens.push({ text: text.slice(cursor, match.index), cls: '' })
    if (match[1] !== undefined) {
      tokens.push({ text: match[1], cls: match[2] ? 'k' : 's' })
      if (match[2]) tokens.push({ text: match[2], cls: '' })
    } else {
      tokens.push({ text: match[3], cls: 'n' })
    }
    cursor = match.index + match[0].length
  }
  if (cursor < text.length) tokens.push({ text: text.slice(cursor), cls: '' })
  return tokens
}

const requestTokens = computed(() => tokenize(result.value?.request))
const responseTokens = computed(() => tokenize(result.value?.response))
const steps = computed(() => result.value?.steps || [])

/**
 * The prototype's artifact card, filled from the fixture rather than invented:
 * `artifact` is the managed relative reference the response carries, and the
 * detail line is whatever scalars came back beside it.
 */
const artifact = computed(() => {
  const response = result.value?.response
  if (!response?.artifact) return null
  const detail = Object.entries(response)
    .filter(([key, value]) => !['artifact', 'status', 'request_id'].includes(key) && value !== null && typeof value !== 'object')
    .map(([key, value]) => `${key.replaceAll('_', ' ')} ${value}`)
    .join(' · ')
  return { name: response.artifact, detail: detail || result.value.operation }
})

async function simulate() {
  if (running.value) return
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

defineExpose({ simulate, running })
</script>

<template>
  <div class="pv-sim-host">
    <div class="pv-sim" :class="{ show: running || result || error }" aria-live="polite">
      <div class="pv-sim-head">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3" /></svg>
        <span class="st">{{ running ? `Simulating ${providerName}` : `Simulated ${providerName}` }}</span>
        <span v-if="running" class="badge2 run">Running</span>
        <span v-else-if="error" class="badge2 err">Failed</span>
        <span v-else class="badge2 ok">200 OK</span>
        <span class="sp"></span>
        <span class="mono transport">{{ result?.transport || '—' }}</span>
        <span v-if="result" class="ms">{{ result.elapsed_ms }}ms</span>
      </div>

      <p v-if="error" class="sim-error" role="alert">{{ error }}</p>

      <template v-else>
        <div class="pv-sim-body">
          <div class="pv-sim-col">
            <div class="cl"><span class="arrow">▲</span> Request · {{ result ? result.operation : 'dummy' }}</div>
            <pre v-if="running"><span class="muted">waiting…</span></pre>
            <pre v-else><span v-for="(token, i) in requestTokens" :key="i" :class="token.cls">{{ token.text }}</span></pre>
          </div>
          <div class="pv-sim-col">
            <div class="cl"><span class="arrow">▼</span> Response</div>
            <pre v-if="running"><span class="muted">waiting…</span></pre>
            <pre v-else><span v-for="(token, i) in responseTokens" :key="i" :class="token.cls">{{ token.text }}</span></pre>
          </div>
        </div>

        <div v-if="steps.length" class="pv-sim-steps">
          <div v-for="(step, i) in steps" :key="i" class="pv-sim-step done">
            <span class="dot"></span> {{ step }}
          </div>
          <div v-if="artifact" class="pv-sim-artifact">
            <span class="av">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M21 15V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9" />
                <path d="M3 15l4-4 4 4M17 17l2 2 4-4" />
              </svg>
            </span>
            <span class="txt">
              <span class="t">{{ artifact.name }}</span>
              <span class="d">{{ artifact.detail }}</span>
            </span>
            <span class="badge2 ok received">received</span>
          </div>
        </div>
      </template>
    </div>

    <div v-if="!running && !result && !error" class="pv-sim-empty">
      The simulated request and response will appear here.
    </div>
  </div>
</template>

<style scoped>
.pv-sim {
  display: none;
  margin-top: 4px;
  border: 1px solid var(--line);
  border-radius: var(--r);
  overflow: hidden;
  background: var(--bg-2);
}

.pv-sim.show { display: block; }

.pv-sim-head { display: flex; align-items: center; gap: 9px; padding: 10px 14px; border-bottom: 1px solid var(--line-soft); }
.pv-sim-head svg { color: var(--run); flex: none; }
.pv-sim-head .st { font-family: var(--display); font-weight: 600; font-size: 12.5px; }
.pv-sim-head .badge2 { font-family: var(--mono); font-size: 9.5px; letter-spacing: .4px; text-transform: uppercase; padding: 3px 8px; border-radius: 5px; flex: none; }
.pv-sim-head .badge2.run { color: var(--run); background: var(--run-dim); }
.pv-sim-head .badge2.ok { color: var(--ok); background: var(--ok-dim); }
.pv-sim-head .badge2.err { color: var(--fail); background: var(--fail-dim); }
.pv-sim-head .sp { flex: 1; }
.pv-sim-head .transport { font-size: 10px; color: var(--muted); overflow-wrap: anywhere; }
.pv-sim-head .ms { font-family: var(--mono); font-size: 11px; color: var(--muted); flex: none; }

/* A 1px gap over the rule colour is the divider between the two panes. */
.pv-sim-body { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--line-soft); }
.pv-sim-col { background: var(--bg); padding: 12px 14px; min-width: 0; }
.pv-sim-col .cl { font-family: var(--mono); font-size: 9.5px; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); margin-bottom: 9px; display: flex; align-items: center; gap: 7px; }
.pv-sim-col .cl .arrow { color: var(--accent); }
.pv-sim-col pre { margin: 0; font-family: var(--mono); font-size: 11px; line-height: 1.55; color: var(--text-2); white-space: pre-wrap; word-break: break-word; overflow-x: auto; }
.pv-sim-col pre .k { color: var(--sched); }
.pv-sim-col pre .s { color: var(--ok); }
.pv-sim-col pre .n { color: var(--warn); }
.pv-sim-col pre .muted { color: var(--faint); }

.pv-sim-steps { padding: 11px 14px; border-top: 1px solid var(--line-soft); display: flex; flex-direction: column; gap: 6px; }
.pv-sim-step { display: flex; align-items: center; gap: 9px; font-family: var(--mono); font-size: 10.5px; color: var(--muted); }
.pv-sim-step .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--faint); flex: none; }
.pv-sim-step.done { color: var(--text-2); }
.pv-sim-step.done .dot { background: var(--ok); }
/* The prototype's `.pv-sim-step.active` is not ported: it paces a fabricated
   multi-second animation over steps it already knows. One real round trip
   either returned or it did not, and pretending otherwise would put a
   progress indicator in front of an answer already on screen. */

.pv-sim-artifact { margin-top: 10px; display: flex; align-items: center; gap: 11px; padding: 10px 12px; border-radius: var(--r-s); background: var(--panel); box-shadow: inset 0 0 0 1px var(--line-soft); }
.pv-sim-artifact .av { width: 40px; height: 40px; border-radius: 7px; flex: none; display: grid; place-items: center; background: var(--accent-ic); color: var(--text); }
.pv-sim-artifact .txt { min-width: 0; flex: 1; }
.pv-sim-artifact .txt .t { display: block; font-size: 12.5px; font-weight: 600; overflow-wrap: anywhere; }
.pv-sim-artifact .txt .d { display: block; font-family: var(--mono); font-size: 10px; color: var(--muted); margin-top: 2px; }
.pv-sim-artifact .received { flex: none; font-family: var(--mono); font-size: 9.5px; letter-spacing: .4px; text-transform: uppercase; padding: 3px 8px; border-radius: 5px; color: var(--ok); background: var(--ok-dim); }

.sim-error { margin: 0; padding: 13px 14px; color: var(--fail-text); background: var(--bg); font-size: 12.5px; line-height: 1.5; }

/* The prototype has no resting state — its console is `display:none` until a
   simulation runs. Ours says so, rather than leaving a gap in the page. */
.pv-sim-empty { padding: 24px; color: var(--faint); font: 11px var(--mono); text-align: center; background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r); }

@media (max-width: 760px) {
  .pv-sim-body { grid-template-columns: 1fr; }
  .pv-sim-head { flex-wrap: wrap; }
  .pv-sim-head .transport { width: 100%; }
}
</style>

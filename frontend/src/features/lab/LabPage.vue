<script setup>
/**
 * Prompt Lab — a framework for prompt/config tuning labs.
 *
 * Each lab is self-describing (name, purpose, how-to, what it measures) and
 * declares its variant knobs; this page renders any lab from that metadata. The
 * prompt *engine* stays in tested code — a variant only parameterizes its
 * inputs — and every run is scored so a change is measurable, not blind.
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiGet, apiPost, apiPut, apiDelete } from '@/shared/api.js'

defineOptions({ name: 'LabPage' })

const SUBTABS = [
  { id: 'test', label: 'Test' },
  { id: 'variants', label: 'Variants' },
  { id: 'performance', label: 'Performance' },
  { id: 'inspector', label: 'Inspector' },
]
const subtab = ref('test')
const error = ref('')          // generic string errors (catalog loads, variants)
const runError = ref(null)     // structured error from a failed Run test
const collapsed = ref(false)   // the whole lab is one collapsible block

// A plain-language hint per failure code, so a failed run explains itself.
const RUN_HINTS = {
  CHANNEL_NOT_FOUND: 'The selected channel no longer exists. Pick another, or run with no channel.',
  WEBHOOK_UNSAFE: 'The story webhook URL is blocked by the safety check. Verify N8N_STORY_WEBHOOK_URL in your .env.',
  WEBHOOK_ERROR: 'The n8n workflow ran but reported a failure — often the upstream model provider (e.g. OpenRouter out of credit). The message above is what the webhook returned.',
  GENERATION_FAILED: 'The provider webhook could not be reached or rejected the request. Is n8n running and the URL correct?',
  EMPTY_RESULT: 'The provider replied but returned no script text. Check the n8n workflow output field.',
  UNKNOWN_LAB: 'This lab is not registered on the backend. Reload the page.',
}
function runErrorHint(code) {
  return RUN_HINTS[code] || 'Check that the provider webhook is reachable and try again.'
}

// ── Lab framework: which lab is active + its self-description ────────────────
const labs = ref([])
const labId = ref('script_prompt')
const lab = computed(() => labs.value.find((l) => l.id === labId.value) || null)

// ── Catalog: channels + providers (per the active lab's provider domain) ────
const channels = ref([])
const providers = ref([])
const variants = ref([])

async function loadLabs() {
  try {
    const data = await apiGet('/lab/labs')
    labs.value = data.labs || []
    if (labs.value.length && !labs.value.find((l) => l.id === labId.value)) {
      labId.value = labs.value[0].id
    }
  } catch (exc) { error.value = exc.message || 'Could not load labs' }
}

async function loadCatalog() {
  try {
    const domain = lab.value?.provider_domain || 'script'
    const [ch, pv, vs] = await Promise.all([
      apiGet('/channels', { limit: 500 }).catch(() => ({ channels: [] })),
      apiGet('/providers').catch(() => ({ domains: {} })),
      apiGet('/lab/variants', { lab: labId.value }).catch(() => ({ variants: [] })),
    ])
    channels.value = ch.channels || []
    const dom = (pv.domains && pv.domains[domain] && pv.domains[domain].providers) || []
    providers.value = dom.map((p) => ({ id: p.id, label: p.label }))
    if (providers.value.length && !providers.value.find((p) => p.id === run.provider_id)) {
      run.provider_id = providers.value[0].id
    }
    variants.value = vs.variants || []
  } catch (exc) { error.value = exc.message || 'Could not load the lab catalog' }
}

watch(labId, async () => { await loadCatalog(); await loadRuns() })

// ── Test: run + score ───────────────────────────────────────────────────────
const run = reactive({ channel_id: '', provider_id: '', variant_id: 'builtin', idea: '' })
const running = ref(false)
const results = ref([])
const compareA = ref(0)
const compareB = ref(1)

async function runExperiment() {
  running.value = true
  runError.value = null
  try {
    const data = await apiPost('/lab/run', {
      lab_id: labId.value,
      channel_id: run.channel_id || null,
      provider_id: run.provider_id,
      variant_id: run.variant_id,
      overrides: run.idea ? { idea: run.idea } : {},
    })
    if (!data || !data.run) throw new Error('The server returned an empty response.')
    results.value.unshift(data.run)
    results.value = results.value.slice(0, 6)
    await loadRuns()
  } catch (exc) {
    // exc is an ApiError (has .code/.status) or a plain Error. Surface both the
    // real reason from the server and a tailored hint — never a bare "502".
    const code = exc?.code || 'RUN_FAILED'
    runError.value = {
      code,
      message: exc?.message || 'The run failed.',
      hint: runErrorHint(code),
      status: exc?.status || null,
    }
  } finally { running.value = false }
}
function dismissRunError() { runError.value = null }
const bandClass = (band) => `band-${band}`
// The LLM judge's 0-1 score for one dimension of a run, or null if absent.
function llmDim(run, dimId) {
  const dims = run?.llm_score?.dimensions
  if (!dims) return null
  const d = dims.find((x) => x.id === dimId)
  return d ? d.score : null
}

// ── Variants: dynamic form from the lab's variant_fields ────────────────────
const editing = ref(null)
function blankVariant() {
  const v = { id: null, name: '', description: '' }
  for (const f of lab.value?.variant_fields || []) v[f.key] = f.default ?? (f.type === 'list' ? [] : '')
  return v
}
function cloneVariant(src) {
  const v = { id: null, name: `${src.name} (copy)`, description: src.description || '' }
  for (const f of lab.value?.variant_fields || []) v[f.key] = Array.isArray(src[f.key]) ? [...src[f.key]] : src[f.key]
  return v
}
function editVariant(v) { editing.value = v.builtin ? cloneVariant(v) : { ...v } }

// List fields (angle_pool, extra_directives) edit as one-per-line text. Plain
// getter + input handler so there's no computed created in the template.
function listAsText(key) {
  return (editing.value?.[key] || []).join('\n')
}
function setListFromText(key, val) {
  if (editing.value) editing.value[key] = val.split('\n').map((s) => s.trim()).filter(Boolean)
}

async function saveVariant() {
  error.value = ''
  const v = editing.value
  try {
    const body = { ...v, lab_id: labId.value }
    if (v.id) await apiPut(`/lab/variants/${v.id}`, body)
    else await apiPost('/lab/variants', body)
    editing.value = null
    await loadCatalog()
  } catch (exc) { error.value = exc.message || 'Could not save the variant' }
}
async function removeVariant(id) {
  error.value = ''
  try { await apiDelete(`/lab/variants/${id}`, { lab: labId.value }); await loadCatalog() }
  catch (exc) { error.value = exc.message || 'Could not delete the variant' }
}

// ── Performance ─────────────────────────────────────────────────────────────
const leaderboard = ref([])
async function loadRuns() {
  try { leaderboard.value = (await apiGet('/lab/runs', { lab: labId.value, limit: 100 })).leaderboard || [] }
  catch { /* non-fatal */ }
}

// ── Inspector (recent generated scripts + their prompt) ─────────────────────
const recent = ref([])
const selectedId = ref('')
const selected = computed(() => recent.value.find((r) => r.project_id === selectedId.value) || null)
async function loadRecent() {
  try {
    const data = await apiGet('/lab/prompts', { limit: 40 })
    recent.value = data.prompts || []
    if (recent.value.length && !selectedId.value) selectedId.value = recent.value[0].project_id
  } catch { /* non-fatal */ }
}
function copy(text) { if (navigator?.clipboard) navigator.clipboard.writeText(text || '') }

onMounted(async () => {
  await loadLabs()
  await loadCatalog()
  await Promise.all([loadRuns(), loadRecent()])
})
</script>

<template>
  <div class="lab">
    <!-- The whole lab is ONE collapsible block: header toggles the body. -->
    <section class="lab-block" :class="{ 'is-collapsed': collapsed }">
    <header class="lab-head">
      <button type="button" class="lab-collapse" :aria-expanded="String(!collapsed)"
        :title="collapsed ? 'Expand this lab' : 'Collapse this lab'" @click="collapsed = !collapsed">
        <svg class="chev" :class="{ closed: collapsed }" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div class="lab-title-row">
          <h1>{{ lab?.name || 'Lab' }}</h1>
          <span class="block-chip">1 lab</span>
        </div>
      </button>
      <select v-if="labs.length > 1" v-model="labId" class="lab-switch" @click.stop>
        <option v-for="l in labs" :key="l.id" :value="l.id">{{ l.name }}</option>
      </select>
    </header>

    <div v-show="!collapsed" class="lab-inner">
      <p class="sub">{{ lab?.description }}</p>

      <details class="lab-about" v-if="lab">
        <summary>What is this? · How to use it · What it measures</summary>
        <div class="about-grid">
          <div><span class="about-h">What it's for</span><p>{{ lab.purpose }}</p></div>
          <div><span class="about-h">How to use it</span><p>{{ lab.how_to }}</p></div>
          <div><span class="about-h">What it measures</span><p>{{ lab.measures }}</p></div>
        </div>
      </details>

      <nav class="lab-tabs" role="tablist" aria-label="Lab sections">
        <button v-for="t in SUBTABS" :key="t.id" type="button" class="lab-tab"
          :class="{ on: subtab === t.id }" role="tab" :aria-selected="String(subtab === t.id)"
          @click="subtab = t.id">{{ t.label }}</button>
      </nav>

    <p v-if="error" class="lab-error">{{ error }}</p>

    <!-- ── TEST ─────────────────────────────────────────────────────────── -->
    <section v-if="subtab === 'test'" class="lab-body split">
      <aside class="lab-form">
        <div class="list-head"><span>Run a variant</span></div>
        <label class="f">Channel
          <select v-model="run.channel_id">
            <option value="">— no channel (manual) —</option>
            <option v-for="c in channels" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <label class="f">Provider
          <select v-model="run.provider_id">
            <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
        </label>
        <label class="f">Variant
          <select v-model="run.variant_id">
            <option v-for="v in variants" :key="v.id" :value="v.id">{{ v.name }}</option>
          </select>
        </label>
        <label class="f">Idea (optional)
          <textarea v-model="run.idea" rows="2" placeholder="what the story is about"></textarea>
        </label>
        <button type="button" class="btn primary" :disabled="running" @click="runExperiment">
          {{ running ? 'Generating & scoring…' : 'Run test' }}
        </button>
        <p class="hint">Generates a real result and scores it — so you see the impact immediately. Run again to compare.</p>
      </aside>

      <div class="lab-detail">
        <!-- Any failure from Run test is shown here, with the real reason + a hint. -->
        <div v-if="runError" class="run-error" role="alert">
          <div class="re-head">
            <span class="re-badge">Run failed</span>
            <code class="re-code">{{ runError.code }}<template v-if="runError.status"> · {{ runError.status }}</template></code>
            <button type="button" class="re-x" title="Dismiss" @click="dismissRunError">✕</button>
          </div>
          <p class="re-msg">{{ runError.message }}</p>
          <p class="re-hint">{{ runError.hint }}</p>
          <button type="button" class="btn sm" :disabled="running" @click="runExperiment">Retry</button>
        </div>
        <p v-if="!results.length && !runError" class="empty">Run a test to see the result and its score.</p>
        <template v-if="results.length">
          <div v-if="results.length > 1" class="compare-bar">
            <span>Compare</span>
            <select v-model.number="compareA"><option v-for="(r, i) in results" :key="i" :value="i">{{ i + 1 }}. {{ r.variant.name }} · {{ r.score.score }}</option></select>
            <span>vs</span>
            <select v-model.number="compareB"><option v-for="(r, i) in results" :key="i" :value="i">{{ i + 1 }}. {{ r.variant.name }} · {{ r.score.score }}</option></select>
          </div>
          <div class="runs" :class="{ dual: results.length > 1 }">
            <article v-for="idx in (results.length > 1 ? [compareA, compareB] : [0])" :key="idx" class="run-card">
              <div class="run-top">
                <div class="score-pair">
                  <div class="score-col">
                    <span class="score-badge" :class="bandClass(results[idx].score.band)">{{ results[idx].score.score }}</span>
                    <span class="score-tag">Structural</span>
                  </div>
                  <div class="score-col" v-if="results[idx].llm_score">
                    <span class="score-badge" :class="bandClass(results[idx].llm_score.band)">{{ results[idx].llm_score.score }}</span>
                    <span class="score-tag">LLM judge</span>
                  </div>
                  <div class="score-col" v-else-if="results[idx].llm_error">
                    <span class="score-badge score-na" title="LLM judge unavailable">—</span>
                    <span class="score-tag">LLM judge</span>
                  </div>
                </div>
                <div class="run-meta">
                  <div class="rm-variant">{{ results[idx].variant.name }}</div>
                  <div class="rm-sub">{{ results[idx].score.band }} · {{ results[idx].word_count }}w · {{ results[idx].provider_id }}</div>
                </div>
              </div>

              <!-- LLM's one-line verdict, or why it's missing. -->
              <p v-if="results[idx].llm_score && results[idx].llm_score.summary" class="llm-summary">
                <span class="llm-quote">“{{ results[idx].llm_score.summary }}”</span>
              </p>
              <p v-else-if="results[idx].llm_error" class="llm-missing">
                LLM second opinion unavailable — {{ results[idx].llm_error }}
              </p>

              <!-- Per-dimension: structural bar, plus the LLM's dot when present. -->
              <div class="dims">
                <div v-for="d in results[idx].score.dimensions" :key="d.id" class="dim">
                  <span class="dim-name">{{ d.id.replaceAll('_', ' ') }}</span>
                  <span class="dim-bar">
                    <i :style="{ width: Math.min(100, d.points * 3) + '%' }"></i>
                    <b v-if="llmDim(results[idx], d.id) !== null" class="dim-llm"
                       :style="{ left: Math.min(100, llmDim(results[idx], d.id) * 100) + '%' }"
                       :title="'LLM: ' + Math.round(llmDim(results[idx], d.id) * 100) + '%'"></b>
                  </span>
                  <span class="dim-pts">{{ d.points }}</span>
                </div>
              </div>
              <p v-if="results[idx].llm_score" class="dim-legend"><i class="lg-bar"></i> structural <b class="lg-dot"></b> LLM</p>

              <pre class="raw script">{{ results[idx].story_text }}</pre>
            </article>
          </div>
        </template>
      </div>
    </section>

    <!-- ── VARIANTS (dynamic form) ──────────────────────────────────────── -->
    <section v-else-if="subtab === 'variants'" class="lab-body split">
      <aside class="lab-list">
        <div class="list-head"><span>Variants</span><button type="button" class="btn xs" @click="editing = blankVariant()">+ New</button></div>
        <button v-for="v in variants" :key="v.id" type="button" class="list-item"
          :class="{ on: editing && editing.id === v.id }" @click="editVariant(v)">
          <span class="li-title">{{ v.name }}<span v-if="v.builtin" class="soon-chip">control · clone</span></span>
          <span class="li-meta">{{ v.description || 'no description' }}</span>
        </button>
      </aside>

      <div class="lab-detail">
        <p v-if="!editing" class="empty">Select a variant to edit, or clone the built-in control (its real defaults are pre-filled) to start a new one.</p>
        <template v-else>
          <div class="list-head"><span>{{ editing.id ? 'Edit variant' : 'New variant' }}</span></div>
          <label class="f">Name<input v-model="editing.name" placeholder="e.g. Question hooks, tighter" /></label>
          <label class="f">Description<input v-model="editing.description" placeholder="what this variant tries" /></label>

          <label v-for="fld in (lab?.variant_fields || [])" :key="fld.key" class="f">
            {{ fld.label }} <span v-if="fld.help" class="fn">— {{ fld.help }}</span>
            <textarea v-if="fld.type === 'list'" :value="listAsText(fld.key)" rows="4" @input="setListFromText(fld.key, $event.target.value)"></textarea>
            <select v-else-if="fld.type === 'select'" v-model="editing[fld.key]">
              <option v-for="o in fld.options" :key="o" :value="o">{{ o || 'default' }}</option>
            </select>
            <input v-else-if="fld.type === 'number'" v-model.number="editing[fld.key]" type="number"
              :min="fld.min" :max="fld.max" :step="fld.step" />
            <input v-else v-model="editing[fld.key]" type="text" />
          </label>

          <div class="btn-row">
            <button type="button" class="btn primary sm" @click="saveVariant">{{ editing.id ? 'Save' : 'Create' }}</button>
            <button v-if="editing.id" type="button" class="btn danger sm" @click="removeVariant(editing.id)">Delete</button>
            <button type="button" class="btn ghost sm" @click="editing = null">Cancel</button>
          </div>
        </template>
      </div>
    </section>

    <!-- ── PERFORMANCE ──────────────────────────────────────────────────── -->
    <section v-else-if="subtab === 'performance'" class="lab-body">
      <div class="lab-detail">
        <div class="list-head"><span>Variant leaderboard — average score</span><button type="button" class="btn xs" @click="loadRuns">↻ Refresh</button></div>
        <p v-if="!leaderboard.length" class="empty">Run some tests to build a leaderboard.</p>
        <table v-else class="board">
          <thead><tr><th>Variant</th><th>Runs</th><th>Avg score</th></tr></thead>
          <tbody><tr v-for="row in leaderboard" :key="row.variant_id"><td>{{ row.name }}</td><td>{{ row.runs }}</td><td><b>{{ row.avg_score }}</b></td></tr></tbody>
        </table>
        <p class="hint">Ranked by the offline scorer today. Real view/retention data plugs in here later.</p>
      </div>
    </section>

    <!-- ── INSPECTOR ────────────────────────────────────────────────────── -->
    <section v-else class="lab-body split">
      <aside class="lab-list">
        <div class="list-head"><span>Recent scripts</span><button type="button" class="btn xs" @click="loadRecent">↻</button></div>
        <p v-if="!recent.length" class="empty">No scripts with saved prompts yet.</p>
        <button v-for="r in recent" :key="r.project_id" type="button" class="list-item" :class="{ on: selectedId === r.project_id }" @click="selectedId = r.project_id">
          <span class="li-title">{{ r.concept_family || r.story_category || r.project_id }}</span>
          <span class="li-meta">{{ r.story_category }} · {{ r.word_count }}w</span>
        </button>
      </aside>
      <div class="lab-detail">
        <p v-if="!selected" class="empty">Select a script to inspect its prompt.</p>
        <template v-else>
          <h3 class="block-h">User prompt — decomposed</h3>
          <div class="parts">
            <div v-for="(p, i) in selected.prompt.decomposed" :key="i" class="part">
              <span class="part-label">{{ p.label }}</span><p class="part-text">{{ p.text }}</p>
            </div>
          </div>
          <div class="raw-row"><h3 class="block-h">System prompt</h3><button type="button" class="btn xs" @click="copy(selected.prompt.system_prompt)">Copy</button></div>
          <pre class="raw">{{ selected.prompt.system_prompt }}</pre>
          <div class="raw-row"><h3 class="block-h">Script</h3></div>
          <pre class="raw script">{{ selected.story_text }}</pre>
        </template>
      </div>
    </section>
    </div><!-- /.lab-inner -->
    </section><!-- /.lab-block -->
  </div>
</template>

<style scoped>
.lab { padding: 22px 26px; max-width: 1200px; margin: 0 auto; }

/* The lab is one bordered card; header collapses the body so it reads as a unit. */
.lab-block { border: 1px solid var(--line); border-radius: var(--r-m, 12px); background: var(--panel-grad); box-shadow: var(--hairline-top); overflow: hidden; }
.lab-block.is-collapsed { background: var(--panel); }

.lab-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; }
.lab-block:not(.is-collapsed) .lab-head { border-bottom: 1px solid var(--line-soft); }
.lab-collapse { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; border: 0; background: none; color: inherit; font: inherit; cursor: pointer; padding: 0; text-align: left; }
.chev { color: var(--muted); transition: transform .15s ease; flex: none; }
.chev.closed { transform: rotate(-90deg); }
.lab-collapse:hover .chev { color: var(--accent); }
.lab-title-row { display: flex; align-items: center; gap: 10px; min-width: 0; }
.lab-head h1 { margin: 0; font-family: var(--display); font-size: 20px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.block-chip { font-family: var(--mono); font-size: 9px; letter-spacing: .5px; text-transform: uppercase; color: var(--accent); background: var(--accent-wash); box-shadow: inset 0 0 0 1px var(--accent-line-2, var(--line-soft)); padding: 2px 7px; border-radius: 999px; flex: none; }
.lab-switch { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s); color: var(--text); padding: 6px 8px; font-size: 12px; flex: none; }

.lab-inner { padding: 4px 16px 16px; }
.lab-inner .sub { margin: 8px 0 0; color: var(--muted); font-size: 13px; }

.lab-about { margin-top: 12px; border: 1px solid var(--line-soft); border-radius: var(--r-s); background: var(--bg-2); }
.lab-about summary { cursor: pointer; padding: 9px 12px; font-size: 12px; color: var(--text-2); font-family: var(--mono); }
.about-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; padding: 4px 14px 14px; }
.about-h { font-family: var(--mono); font-size: 9px; letter-spacing: .5px; text-transform: uppercase; color: var(--accent); }
.about-grid p { margin: 5px 0 0; font-size: 12px; color: var(--muted); line-height: 1.55; }

.lab-tabs { display: flex; gap: 6px; margin-top: 16px; border-bottom: 1px solid var(--line-soft); }
.lab-tab { border: 0; background: none; color: var(--muted); font: inherit; font-size: 13px; padding: 9px 12px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.lab-tab:hover { color: var(--text-2); }
.lab-tab.on { color: var(--text); border-bottom-color: var(--accent); }
.lab-error { color: var(--fail-text); background: var(--fail-dim); border: 1px solid var(--fail-line); border-radius: var(--r-s); padding: 8px 12px; margin: 14px 0 0; font-size: 13px; }

.lab-body { margin-top: 18px; }
.split { display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }
.lab-list, .lab-form { border: 1px solid var(--line); background: var(--panel-grad); border-radius: var(--r-s); padding: 8px; box-shadow: var(--hairline-top); position: sticky; top: 14px; }
.list-head { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px 10px; color: var(--muted); font-family: var(--mono); font-size: 10px; letter-spacing: .5px; text-transform: uppercase; }
.list-item { display: flex; flex-direction: column; gap: 3px; width: 100%; text-align: left; border: 0; background: transparent; color: var(--text); font: inherit; cursor: pointer; padding: 9px 10px; border-radius: var(--r-s); }
.list-item:hover { background: var(--raise); }
.list-item.on { background: var(--accent-wash); }
.li-title { font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
.li-meta { font-family: var(--mono); font-size: 10px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.lab-detail { border: 1px solid var(--line); background: var(--panel-grad); border-radius: var(--r-s); padding: 16px 18px; box-shadow: var(--hairline-top); min-height: 300px; }
.empty { color: var(--muted); font-size: 13px; padding: 24px 4px; text-align: center; }

.f { display: flex; flex-direction: column; gap: 5px; padding: 6px 8px; font-size: 11px; color: var(--muted); font-family: var(--mono); text-transform: uppercase; letter-spacing: .3px; }
.f .fn { text-transform: none; letter-spacing: 0; color: var(--faint); font-size: 10px; }
.f input, .f textarea, .f select { font-family: var(--display); font-size: 13px; text-transform: none; letter-spacing: 0; color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s); padding: 7px 9px; }
.f input:focus, .f textarea:focus, .f select:focus { outline: none; border-color: var(--accent-line-2); }
.lab-form .btn.primary { width: calc(100% - 16px); margin: 8px; }
.hint { color: var(--muted); font-size: 11px; padding: 0 10px 8px; line-height: 1.5; }
.btn-row { display: flex; gap: 8px; padding: 8px; }
.soon-chip { font-family: var(--mono); font-size: 8px; letter-spacing: .4px; text-transform: uppercase; color: var(--faint); background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line-soft); padding: 1px 5px; border-radius: 999px; }

.run-error { border: 1px solid var(--fail-line); background: var(--fail-dim); border-radius: var(--r-s); padding: 12px 14px; margin-bottom: 16px; }
.re-head { display: flex; align-items: center; gap: 8px; }
.re-badge { font-family: var(--mono); font-size: 9px; letter-spacing: .5px; text-transform: uppercase; color: var(--fail-text); background: var(--fail-line); padding: 2px 7px; border-radius: 999px; }
.re-code { font-family: var(--mono); font-size: 10px; color: var(--fail-text); opacity: .85; }
.re-x { margin-left: auto; border: 0; background: none; color: var(--fail-text); cursor: pointer; font-size: 12px; opacity: .7; padding: 2px 4px; }
.re-x:hover { opacity: 1; }
.re-msg { margin: 8px 0 4px; font-size: 13px; color: var(--fail-text); font-weight: 600; }
.re-hint { margin: 0 0 10px; font-size: 12px; color: var(--muted); line-height: 1.5; }

.compare-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; color: var(--muted); font-family: var(--mono); font-size: 11px; }
.compare-bar select { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s); color: var(--text); padding: 4px 6px; font-size: 11px; }
.runs.dual { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.run-card { border: 1px solid var(--line-soft); border-radius: var(--r-s); padding: 12px; background: var(--bg-2); }
.run-top { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.score-pair { display: flex; gap: 10px; flex: none; }
.score-col { display: flex; flex-direction: column; align-items: center; gap: 3px; }
.score-tag { font-family: var(--mono); font-size: 8px; letter-spacing: .4px; text-transform: uppercase; color: var(--muted); }
.score-badge { width: 46px; height: 46px; border-radius: 12px; display: grid; place-items: center; font-family: var(--display); font-weight: 700; font-size: 18px; flex: none; }
.score-na { background: var(--bg-2); color: var(--faint); box-shadow: inset 0 0 0 1px var(--line-soft); }
.llm-summary { margin: 0 0 10px; }
.llm-quote { font-size: 12px; color: var(--text-2); font-style: italic; line-height: 1.5; }
.llm-missing { margin: 0 0 10px; font-size: 11px; color: var(--warn); }
.dim-legend { margin: 0 0 12px; font-family: var(--mono); font-size: 9px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.lg-bar { display: inline-block; width: 14px; height: 4px; border-radius: 2px; background: var(--accent-grad); }
.lg-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--text); margin-left: 6px; }
.band-strong { background: rgba(53,192,138,.18); color: var(--ok); box-shadow: inset 0 0 0 1px var(--ok-line); }
.band-solid { background: rgba(88,166,255,.18); color: var(--run); box-shadow: inset 0 0 0 1px var(--run-line); }
.band-weak { background: rgba(240,173,75,.18); color: var(--warn); box-shadow: inset 0 0 0 1px var(--warn-line); }
.band-poor { background: rgba(255,95,110,.18); color: var(--fail); box-shadow: inset 0 0 0 1px var(--fail-line); }
.rm-variant { font-family: var(--display); font-weight: 600; font-size: 14px; }
.rm-sub { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.dims { display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px; }
.dim { display: grid; grid-template-columns: 90px 1fr 34px; align-items: center; gap: 8px; font-size: 11px; }
.dim-name { font-family: var(--mono); color: var(--muted); text-transform: capitalize; }
.dim-bar { position: relative; height: 6px; background: var(--line-soft); border-radius: 999px; }
.dim-bar i { display: block; height: 100%; background: var(--accent-grad); border-radius: 999px; }
/* The LLM judge's score for this dimension, as a dot over the structural bar. */
.dim-llm { position: absolute; top: 50%; width: 8px; height: 8px; border-radius: 50%; background: var(--text); box-shadow: 0 0 0 2px var(--bg-2); transform: translate(-50%, -50%); }
.dim-pts { text-align: right; font-family: var(--mono); color: var(--text-2); }

.block-h { font-size: 12px; font-weight: 600; color: var(--text-2); margin: 14px 0 8px; text-transform: uppercase; letter-spacing: .4px; }
.parts { display: flex; flex-direction: column; gap: 8px; }
.part { border: 1px solid var(--line-soft); border-radius: var(--r-s); padding: 9px 11px; background: var(--bg-2); }
.part-label { font-family: var(--mono); font-size: 9px; letter-spacing: .5px; text-transform: uppercase; color: var(--accent); }
.part-text { margin: 4px 0 0; font-size: 12.5px; color: var(--text-2); line-height: 1.5; white-space: pre-wrap; }
.raw-row { display: flex; justify-content: space-between; align-items: center; }
.raw { margin: 8px 0 0; padding: 12px; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: var(--r-s); font-family: var(--mono); font-size: 11.5px; color: var(--text-2); white-space: pre-wrap; overflow: auto; line-height: 1.55; max-height: 340px; }
.raw.script { color: var(--text); }

.board { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
.board th { text-align: left; color: var(--muted); font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: .4px; padding: 8px 10px; border-bottom: 1px solid var(--line-soft); }
.board td { padding: 9px 10px; border-bottom: 1px solid var(--line-soft); }
.board td b { color: var(--accent); }

@media (max-width: 860px) { .split { grid-template-columns: 1fr; } .runs.dual { grid-template-columns: 1fr; } }
</style>
